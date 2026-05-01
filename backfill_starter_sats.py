#!/usr/bin/env python3
"""
One-shot backfill: credit 250 starter sats to eligible zero-balance accounts.

Eligible = registered before today, balance=0, ≥2 calls or any sats spent,
not a test/smoke account.

Safe to re-run: skips accounts that already have balance > 0 or that have
already received a backfill DM from "invinoveritas_backfill".
"""
import sqlite3
import time
import uuid
from datetime import datetime, timezone

ACCOUNTS_DB   = "/root/invinoveritas_accounts.db"
MESSAGES_DB   = "/root/invinoveritas/data/messages.db"
CREDIT_SATS   = 250
DAILY_CAP     = 30_000
TODAY_UTC     = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# Cutoff: only accounts created before today
CUTOFF_TS = int(
    datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()
)

DM_CONTENT = (
    "⚡ Welcome back! We've just credited your account with 250 starter sats — "
    "on us. The marketplace is live with 46+ listings: reasoning services, trading "
    "signals, node data, and more. Go spend some sats and let the flywheel spin. "
    "→ https://api.babyblueviper.com/marketplace"
)


def today_giveaway_used(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT sats_given FROM daily_giveaway WHERE day = ?", (TODAY_UTC,)
    ).fetchone()
    return row[0] if row else 0


def claim_giveaway(conn: sqlite3.Connection, amount: int):
    conn.execute(
        """INSERT INTO daily_giveaway (day, sats_given) VALUES (?, ?)
           ON CONFLICT(day) DO UPDATE SET sats_given = sats_given + ?""",
        (TODAY_UTC, amount, amount),
    )


def already_notified(msg_conn: sqlite3.Connection, api_key: str) -> bool:
    row = msg_conn.execute(
        "SELECT 1 FROM direct_messages WHERE from_agent='invinoveritas_backfill' AND from_api_key=?",
        (api_key,),
    ).fetchone()
    return row is not None


def send_dm(msg_conn: sqlite3.Connection, api_key: str, agent_id: str):
    msg_conn.execute(
        """INSERT INTO direct_messages
           (dm_id, from_agent, from_api_key, to_agent, content,
            price_paid, recipient_payout, recipient_credited, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(uuid.uuid4()),
            "invinoveritas_backfill",
            api_key,
            agent_id,
            DM_CONTENT,
            0, 0, 0,
            int(time.time()),
        ),
    )


def main():
    acc_conn = sqlite3.connect(ACCOUNTS_DB, timeout=15)
    acc_conn.execute("PRAGMA journal_mode=WAL")

    try:
        msg_conn = sqlite3.connect(MESSAGES_DB, timeout=15)
        msg_conn.execute("PRAGMA journal_mode=WAL")
    except Exception as e:
        print(f"[WARN] Could not open messages DB ({e}) — credits will run without DMs")
        msg_conn = None

    # Check daily cap headroom
    used = today_giveaway_used(acc_conn)
    headroom = DAILY_CAP - used
    print(f"Daily giveaway: {used} sats used today, {headroom} remaining (cap {DAILY_CAP})")

    # Fetch eligible accounts
    rows = acc_conn.execute(
        """SELECT api_key, total_calls, total_spent_sats, label,
                  datetime(created_at,'unixepoch') as created
           FROM accounts
           WHERE balance_sats = 0
             AND created_at < ?
             AND (total_calls >= 2 OR total_spent_sats > 0)
             AND (label IS NULL
                  OR (label NOT LIKE '%test%' AND label NOT LIKE '%smoke%'))
           ORDER BY total_calls DESC""",
        (CUTOFF_TS,),
    ).fetchall()

    print(f"\nFound {len(rows)} eligible accounts\n")

    credited = 0
    skipped  = 0

    for api_key, calls, spent, label, created in rows:
        agent_id = f"agent_{api_key[4:12].lower()}"

        # Re-check balance inside transaction (may have changed)
        current_bal = acc_conn.execute(
            "SELECT balance_sats FROM accounts WHERE api_key = ?", (api_key,)
        ).fetchone()[0]

        if current_bal > 0:
            print(f"  SKIP  {agent_id} — balance now {current_bal} sats (already funded)")
            skipped += 1
            continue

        if msg_conn and already_notified(msg_conn, api_key):
            print(f"  SKIP  {agent_id} — already received backfill DM")
            skipped += 1
            continue

        if headroom < CREDIT_SATS:
            print(f"  STOP  daily cap exhausted ({used} sats used)")
            break

        # Credit the account
        acc_conn.execute(
            "UPDATE accounts SET balance_sats = balance_sats + ? WHERE api_key = ?",
            (CREDIT_SATS, api_key),
        )
        claim_giveaway(acc_conn, CREDIT_SATS)
        acc_conn.commit()

        headroom -= CREDIT_SATS
        used     += CREDIT_SATS
        credited += 1

        # Send DM notification
        if msg_conn:
            try:
                send_dm(msg_conn, api_key, agent_id)
                msg_conn.commit()
                dm_status = "DM sent"
            except Exception as e:
                dm_status = f"DM failed: {e}"
        else:
            dm_status = "no DM (messages DB unavailable)"

        print(
            f"  CREDIT {agent_id} | calls={calls} spent={spent} label={label!r} "
            f"created={created} | {dm_status}"
        )

    print(f"\nDone. Credited {credited} accounts, skipped {skipped}. "
          f"Total giveaway today: {used} sats.")

    acc_conn.close()
    if msg_conn:
        msg_conn.close()


if __name__ == "__main__":
    main()
