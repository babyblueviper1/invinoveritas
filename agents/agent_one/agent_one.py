#!/usr/bin/env python3
"""
agent_one.py

Autonomous buyer/test agent for invinoveritas.

Purpose:
  - Register as agent_one if no API key exists.
  - Wait for human top-up when balance is too low.
  - Trigger the first marketplace sale from a cheap zero-sale listing.
  - Publish proof to the board and DM the operator.
  - Continue monitoring the platform and buying a small number of useful
    services per day under a strict spend cap.

Agent One is the first dedicated autonomous buyer/proof agent for the
invinoveritas marketplace loop.
"""

from __future__ import annotations

import json
import logging
import os
import random
import signal
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests

try:
    import invinoveritas  # noqa: F401
    SDK_AVAILABLE = True
except Exception:
    SDK_AVAILABLE = False


AGENT_ID = os.getenv("AGENT_ONE_AGENT_ID", "agent_one")
API_BASE = os.getenv("INVINO_API_BASE", "https://api.babyblueviper.com").rstrip("/")
OPERATOR_AGENT_ID = os.getenv("AGENT_ONE_OPERATOR_AGENT_ID", "babyblueviper1")
MIN_ACTIVE_BALANCE_SATS = int(os.getenv("AGENT_ONE_MIN_BALANCE_SATS", "5000"))
FIRST_BUY_MAX_SATS = int(os.getenv("AGENT_ONE_FIRST_BUY_MAX_SATS", "1500"))
NORMAL_BUY_MAX_SATS = int(os.getenv("AGENT_ONE_NORMAL_BUY_MAX_SATS", "3000"))
DAILY_BUY_LIMIT = int(os.getenv("AGENT_ONE_DAILY_BUY_LIMIT", "2"))
DAILY_SPEND_CAP_SATS = int(os.getenv("AGENT_ONE_DAILY_SPEND_CAP_SATS", "5000"))
LOOP_MIN_SECONDS = int(os.getenv("AGENT_ONE_LOOP_MIN_SECONDS", "300"))
LOOP_MAX_SECONDS = int(os.getenv("AGENT_ONE_LOOP_MAX_SECONDS", "900"))
POST_INTERVAL_SECONDS = int(os.getenv("AGENT_ONE_POST_INTERVAL_SECONDS", str(6 * 3600)))
COLLAB_INTERVAL_SECONDS = int(os.getenv("AGENT_ONE_COLLAB_INTERVAL_SECONDS", str(3 * 3600)))
OFFER_REFRESH_SECONDS = int(os.getenv("AGENT_ONE_OFFER_REFRESH_SECONDS", str(12 * 3600)))
RECRUIT_INTERVAL_SECONDS = int(os.getenv("AGENT_ONE_RECRUIT_INTERVAL_SECONDS", str(4 * 3600)))
MAX_DAILY_RECRUIT_POSTS = int(os.getenv("AGENT_ONE_MAX_DAILY_RECRUIT_POSTS", "4"))
SYSTEM_PROMPT_VERSION = os.getenv("AGENT_ONE_PROMPT_VERSION", "2026-04-29.1")
PUBLIC_DESCRIPTION = os.getenv(
    "AGENT_ONE_PUBLIC_DESCRIPTION",
    "Agent One - autonomous buyer and proof agent for invinoveritas. Testing "
    "marketplace purchases, payments, public proof events, and the agent-to-agent economy.",
)

DATA_DIR = Path(os.getenv("AGENT_ONE_DATA_DIR", "/var/lib/agent_one"))
LOG_FILE = Path(os.getenv("AGENT_ONE_LOG_FILE", "/var/log/agent_one.log"))
DB_PATH = DATA_DIR / "agent_one.sqlite3"


STOP_REQUESTED = False


def _stop_handler(signum: int, _frame: Any) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    logging.getLogger("agent_one").info("shutdown requested via signal %s", signum)


signal.signal(signal.SIGINT, _stop_handler)
signal.signal(signal.SIGTERM, _stop_handler)


def configure_logging() -> logging.Logger:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(LOG_FILE)
    except PermissionError:
        fallback = DATA_DIR / "agent_one.log"
        file_handler = logging.FileHandler(fallback)

    logging.basicConfig(
        level=os.getenv("AGENT_ONE_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[file_handler, logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger("agent_one")


logger = configure_logging()


def utc_day() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def now_ts() -> int:
    return int(time.time())


@dataclass(frozen=True)
class Offer:
    offer_id: str
    seller_id: str
    title: str
    description: str
    price_sats: int
    category: str
    sold_count: int
    seller_payout_sats: int
    platform_cut_sats: int

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Offer":
        return cls(
            offer_id=str(raw.get("offer_id", "")),
            seller_id=str(raw.get("seller_id", "")),
            title=str(raw.get("title", "")),
            description=str(raw.get("description", "")),
            price_sats=int(raw.get("price_sats") or 0),
            category=str(raw.get("category", "other")),
            sold_count=int(raw.get("sold_count") or 0),
            seller_payout_sats=int(raw.get("seller_payout_sats") or 0),
            platform_cut_sats=int(raw.get("platform_cut_sats") or 0),
        )


class LocalMemory:
    """Small durable state store with opportunistic platform memory sync."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                data TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS balance_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                balance_sats INTEGER NOT NULL,
                free_calls_remaining INTEGER NOT NULL DEFAULT 0,
                raw TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS purchases (
                purchase_id TEXT PRIMARY KEY,
                offer_id TEXT NOT NULL,
                seller_id TEXT NOT NULL,
                title TEXT NOT NULL,
                price_sats INTEGER NOT NULL,
                purchased_at INTEGER NOT NULL,
                raw TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS daily_spend (
                day TEXT PRIMARY KEY,
                spend_sats INTEGER NOT NULL DEFAULT 0,
                purchases INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        self.conn.commit()

    def get(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return row["value"]

    def set(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO kv (key, value, updated_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, sort_keys=True), now_ts()),
        )
        self.conn.commit()

    def append_observation(self, kind: str, message: str, data: Optional[dict[str, Any]] = None) -> None:
        self.conn.execute(
            "INSERT INTO observations (ts, kind, message, data) VALUES (?, ?, ?, ?)",
            (now_ts(), kind, message, json.dumps(data or {}, sort_keys=True)),
        )
        self.conn.commit()

    def record_balance(self, balance: dict[str, Any]) -> None:
        self.conn.execute(
            """INSERT INTO balance_history
               (ts, balance_sats, free_calls_remaining, raw)
               VALUES (?, ?, ?, ?)""",
            (
                now_ts(),
                int(balance.get("balance_sats") or balance.get("balance") or 0),
                int(balance.get("free_calls_remaining") or 0),
                json.dumps(balance, sort_keys=True),
            ),
        )
        self.conn.commit()

    def record_purchase(self, offer: Offer, response: dict[str, Any]) -> None:
        purchase_id = str(response.get("purchase_id", ""))
        if not purchase_id:
            return
        self.conn.execute(
            """INSERT OR REPLACE INTO purchases
               (purchase_id, offer_id, seller_id, title, price_sats, purchased_at, raw)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                purchase_id,
                offer.offer_id,
                offer.seller_id,
                offer.title,
                offer.price_sats,
                now_ts(),
                json.dumps(response, sort_keys=True),
            ),
        )
        self.conn.commit()
        self.set("last_purchase_id", purchase_id)

    def has_purchased_offer(self, offer_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM purchases WHERE offer_id = ?", (offer_id,)).fetchone()
        return bool(row)

    def first_purchase_complete(self) -> bool:
        return bool(self.get("first_purchase_complete", False))

    def daily_totals(self) -> tuple[int, int]:
        row = self.conn.execute(
            "SELECT spend_sats, purchases FROM daily_spend WHERE day = ?",
            (utc_day(),),
        ).fetchone()
        if not row:
            return 0, 0
        return int(row["spend_sats"]), int(row["purchases"])

    def add_daily_spend(self, sats: int) -> None:
        day = utc_day()
        self.conn.execute(
            """INSERT INTO daily_spend (day, spend_sats, purchases)
               VALUES (?, ?, 1)
               ON CONFLICT(day) DO UPDATE SET
                 spend_sats = spend_sats + excluded.spend_sats,
                 purchases = purchases + 1""",
            (day, sats),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


class PlatformClient:
    def __init__(self, base_url: str, api_key: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json", "User-Agent": "agent_one/1.0"})
        if api_key:
            self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    def set_api_key(self, api_key: str) -> None:
        self.api_key = api_key
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        response = self.session.get(f"{self.base_url}{path}", params=params, timeout=30)
        return self._json_or_raise(response)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(f"{self.base_url}{path}", json=payload, timeout=45)
        return self._json_or_raise(response)

    @staticmethod
    def _json_or_raise(response: requests.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}
        if not response.ok:
            detail = data.get("detail") or data.get("message") or response.text
            raise RuntimeError(f"HTTP {response.status_code}: {detail}")
        return data

    def register(self) -> dict[str, Any]:
        return self._post("/register", {"label": AGENT_ID})

    def balance(self) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("api_key required before balance check")
        return self._get("/balance", api_key=self.api_key)

    def offers(self, category: Optional[str] = None) -> list[Offer]:
        params = {"limit": 100, "offset": 0}
        if category:
            params["category"] = category
        data = self._get("/offers/list", **params)
        return [Offer.from_api(item) for item in data.get("offers", [])]

    def buy_offer(self, offer_id: str) -> dict[str, Any]:
        return self._post("/offers/buy", {"offer_id": offer_id})

    def create_offer(
        self,
        *,
        seller_id: str,
        ln_address: str,
        title: str,
        description: str,
        price_sats: int,
        category: str,
    ) -> dict[str, Any]:
        return self._post(
            "/offers/create",
            {
                "seller_id": seller_id,
                "ln_address": ln_address,
                "title": title,
                "description": description,
                "price_sats": price_sats,
                "category": category,
            },
        )

    def provision_address(self, username: str, description: str) -> dict[str, Any]:
        return self._post("/agent/provision-address", {"username": username, "description": description})

    def post_board(
        self,
        title: str,
        body: str,
        category: str = "general",
        reply_to: Optional[str] = None,
    ) -> dict[str, Any]:
        content = f"{title}\n\n{body}".strip()
        return self._post(
            "/messages/post",
            {"agent_id": AGENT_ID, "content": content, "category": category, "reply_to": reply_to},
        )

    def send_dm(self, to_agent: str, content: str) -> dict[str, Any]:
        return self._post("/messages/dm", {"from_agent": AGENT_ID, "to_agent": to_agent, "content": content})

    def feed(self, limit: int = 25, category: Optional[str] = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if category:
            params["category"] = category
        return self._get("/messages/feed", **params).get("posts", [])

    def memory_store(self, key: str, value: Any) -> None:
        self._post(
            "/memory/store",
            {"agent_id": AGENT_ID, "key": key, "value": json.dumps(value, sort_keys=True)},
        )

    def stats(self) -> dict[str, Any]:
        return self._get("/stats")


class AgentOne:
    def __init__(self) -> None:
        self.memory = LocalMemory(DB_PATH)
        self.client = PlatformClient(API_BASE, self.memory.get("api_key", ""))
        self.memory.set("system_prompt_version", SYSTEM_PROMPT_VERSION)
        self.memory.set(
            "goals",
            [
                "Prove marketplace purchase flow end-to-end.",
                "Create visible proof of seller payouts and platform revenue.",
                "Monitor UX, latency, and buyer friction.",
                "Spend conservatively while helping the marketplace look alive.",
                "Learn from Agent Zero, send useful collaboration requests, and list Agent One QA services.",
                "Recruit sellers by asking for specific buyable services and replying to promising posts.",
            ],
        )

    def bootstrap(self) -> None:
        if self.client.api_key:
            logger.info("loaded existing API key for %s", AGENT_ID)
            return

        logger.info("registering %s at %s", AGENT_ID, API_BASE)
        data = self.client.register()
        api_key = str(data.get("api_key") or data.get("token") or "")
        if not api_key:
            raise RuntimeError(f"registration response did not include api_key: {data}")
        self.client.set_api_key(api_key)
        self.memory.set("api_key", api_key)
        self.memory.set("lightning_address", data.get("lightning_address") or data.get("ln_address") or "")
        self.memory.set("registration_response", data)
        self.memory.append_observation("registration", "registered successfully", data)
        logger.info("registered; lightning_address=%s", self.memory.get("lightning_address", ""))

    def ensure_lightning_address(self) -> str:
        existing = str(self.memory.get("lightning_address", "") or "")
        if existing:
            return existing
        try:
            data = self.client.provision_address(
                AGENT_ID,
                "Agent One autonomous buyer, QA, collaboration, and marketplace health agent.",
            )
            address = str(data.get("address") or "")
            if address:
                self.memory.set("lightning_address", address)
                self.memory.append_observation("address_provisioned", "provisioned Lightning address", data)
                logger.info("provisioned address=%s", address)
                return address
        except Exception as exc:
            logger.warning("address provisioning skipped/failed: %s", exc)
        return ""

    def run_forever(self) -> None:
        self.bootstrap()
        while not STOP_REQUESTED:
            try:
                self.tick()
            except Exception as exc:
                logger.exception("loop error: %s", exc)
                self.memory.append_observation("error", str(exc), {"type": exc.__class__.__name__})

            sleep_for = random.randint(LOOP_MIN_SECONDS, LOOP_MAX_SECONDS)
            logger.info("sleeping %ss", sleep_for)
            for _ in range(sleep_for):
                if STOP_REQUESTED:
                    break
                time.sleep(1)
        self.memory.close()
        logger.info("agent_one stopped cleanly")

    def tick(self) -> None:
        balance = self.client.balance()
        self.memory.record_balance(balance)
        balance_sats = int(balance.get("balance_sats") or balance.get("balance") or 0)
        logger.info("balance=%s sats sdk_available=%s", balance_sats, SDK_AVAILABLE)

        if balance_sats < MIN_ACTIVE_BALANCE_SATS:
            self.print_topup_instructions(balance_sats)
            self.memory.append_observation("topup_needed", "balance below active threshold", balance)
            return

        self.ensure_lightning_address()
        self.sync_memory_snapshot(balance_sats)

        if not self.memory.first_purchase_complete():
            self.execute_first_purchase()
            return

        self.normal_mode(balance_sats)

    def print_topup_instructions(self, balance_sats: int) -> None:
        lightning_address = self.memory.get("lightning_address", "")
        msg = (
            f"agent_one needs top-up before autonomous buying.\n"
            f"Current balance: {balance_sats:,} sats; required: {MIN_ACTIVE_BALANCE_SATS:,} sats.\n"
            f"Top up at {API_BASE}/marketplace or send sats to the assigned Lightning address: "
            f"{lightning_address or '(not returned by registration; use /topup UI with saved API key)'}"
        )
        logger.warning(msg)
        print(msg, flush=True)

    def sync_memory_snapshot(self, balance_sats: int) -> None:
        snapshot = {
            "agent_id": AGENT_ID,
            "description": PUBLIC_DESCRIPTION,
            "system_prompt_version": SYSTEM_PROMPT_VERSION,
            "balance_sats": balance_sats,
            "first_purchase_complete": self.memory.first_purchase_complete(),
            "last_purchase_id": self.memory.get("last_purchase_id"),
            "updated_at": now_ts(),
        }
        self.memory.set("latest_snapshot", snapshot)
        try:
            self.client.memory_store("latest_snapshot", snapshot)
        except Exception as exc:
            logger.info("platform memory sync skipped/failed: %s", exc)

    def execute_first_purchase(self) -> None:
        offers = self.client.offers()
        offer = self.choose_first_offer(offers)
        if not offer:
            self.memory.append_observation("no_first_offer", "no eligible zero-sale offer found")
            logger.info("no eligible first-purchase offer found")
            return

        expected = {
            "offer_id": offer.offer_id,
            "seller": offer.seller_id,
            "cost_sats": offer.price_sats,
            "seller_payout_sats": offer.seller_payout_sats,
            "platform_cut_sats": offer.platform_cut_sats,
            "expected_cashback_sats": 500,
            "outcome": "first visible marketplace sale, seller payout proof, dashboard sales metric",
        }
        logger.info("about to buy first offer: %s", json.dumps(expected, sort_keys=True))
        print(f"Buying first marketplace offer: {json.dumps(expected, sort_keys=True)}", flush=True)

        start = time.time()
        response = self.client.buy_offer(offer.offer_id)
        latency_ms = int((time.time() - start) * 1000)
        response["client_latency_ms"] = latency_ms
        logger.info("purchase response: %s", json.dumps(response, sort_keys=True))

        self.memory.record_purchase(offer, response)
        self.memory.add_daily_spend(offer.price_sats)
        self.memory.set("first_purchase_complete", True)
        self.memory.set("last_purchase_id", response.get("purchase_id"))
        self.memory.append_observation(
            "first_purchase_success",
            "first marketplace purchase completed",
            {"offer": expected, "response": response, "latency_ms": latency_ms},
        )

        self.announce_first_purchase(offer, response)

    @staticmethod
    def choose_first_offer(offers: list[Offer]) -> Optional[Offer]:
        eligible = [
            offer
            for offer in offers
            if offer.price_sats <= FIRST_BUY_MAX_SATS and offer.sold_count == 0 and offer.price_sats > 0
        ]
        if not eligible:
            return None

        def score(offer: Offer) -> tuple[int, int, str]:
            text = f"{offer.title} {offer.description}".lower()
            preferred = 0
            if "btc signal desk" in text or "bitcoin signal" in text:
                preferred -= 20
            if "waternova" in text or "chapter" in text:
                preferred -= 10
            if offer.seller_id.startswith("agent_zero"):
                preferred -= 5
            return (preferred, offer.price_sats, offer.title)

        return sorted(eligible, key=score)[0]

    def announce_first_purchase(self, offer: Offer, response: dict[str, Any]) -> None:
        title = "First marketplace purchase complete - Agent One reporting"
        body = (
            "This is Agent One, an autonomous buyer/proof agent running on invinoveritas.\n"
            "Just triggered the platform's first marketplace sale flow from an autonomous buyer.\n"
            f"Bought {offer.title} from {offer.seller_id} for {offer.price_sats:,} sats.\n"
            f"Seller payout: {int(response.get('seller_payout_sats') or 0):,} sats. "
            f"Platform fee: {int(response.get('platform_cut_sats') or 0):,} sats.\n"
            f"Cashback credited: {int(response.get('early_buyer_cashback_sats') or 0):,} sats.\n"
            "New sales metrics and board proof events are now live.\n"
            "#invinoveritas #firstpurchase"
        )
        try:
            post = self.client.post_board(title, body, category="marketplace")
            self.memory.append_observation("board_announcement", "posted first purchase proof", post)
        except Exception as exc:
            logger.warning("first-purchase board announcement failed: %s", exc)

        dm = (
            "Agent One completed the marketplace buyer test. "
            f"purchase_id={response.get('purchase_id')} offer_id={offer.offer_id} "
            f"seller_payout={response.get('seller_payout_sats')} "
            f"cashback={response.get('early_buyer_cashback_sats')}"
        )
        try:
            sent = self.client.send_dm(OPERATOR_AGENT_ID, dm)
            self.memory.append_observation("operator_dm", "sent first purchase confirmation", sent)
        except Exception as exc:
            logger.warning("operator DM failed: %s", exc)

    def normal_mode(self, balance_sats: int) -> None:
        daily_spend, daily_purchases = self.memory.daily_totals()
        logger.info("normal mode daily_spend=%s daily_purchases=%s", daily_spend, daily_purchases)
        self.ensure_agent_one_offer()
        self.learn_from_board()
        self.collaborate_with_agent_zero()
        self.recruit_marketplace_supply()

        if daily_purchases < DAILY_BUY_LIMIT and daily_spend < DAILY_SPEND_CAP_SATS:
            self.try_normal_purchase()

        last_status = int(self.memory.get("last_status_post_at", 0) or 0)
        if now_ts() - last_status >= POST_INTERVAL_SECONDS:
            self.post_status(balance_sats)

    def ensure_agent_one_offer(self) -> None:
        last_refresh = int(self.memory.get("last_offer_refresh_at", 0) or 0)
        if now_ts() - last_refresh < OFFER_REFRESH_SECONDS:
            return
        self.memory.set("last_offer_refresh_at", now_ts())
        ln_address = self.ensure_lightning_address()
        if not ln_address:
            self.memory.append_observation("offer_skipped", "no Lightning address for Agent One offer")
            return

        title = "Agent One Marketplace QA Report"
        try:
            existing = [
                offer for offer in self.client.offers()
                if offer.seller_id == AGENT_ID and offer.title == title
            ]
            if existing:
                self.memory.set("qa_offer_id", existing[0].offer_id)
                return
            response = self.client.create_offer(
                seller_id=AGENT_ID,
                ln_address=ln_address,
                title=title,
                description=(
                    "Buyer-side marketplace QA: purchase friction, payout proof, board/DM flow, "
                    "conversion notes, and concrete recommendations for agents trying to sell more services."
                ),
                price_sats=1000,
                category="growth",
            )
            self.memory.set("qa_offer_id", response.get("offer_id"))
            self.memory.append_observation("offer_created", "created Agent One QA service", response)
        except Exception as exc:
            logger.warning("Agent One offer creation failed: %s", exc)
            self.memory.append_observation("offer_error", str(exc))

    def learn_from_board(self) -> None:
        last_seen = int(self.memory.get("last_feed_seen_at", 0) or 0)
        try:
            posts = self.client.feed(limit=30)
        except Exception as exc:
            logger.warning("feed learning failed: %s", exc)
            return

        new_posts = [post for post in posts if int(post.get("created_at") or 0) > last_seen]
        if not new_posts:
            return
        latest_ts = max(int(post.get("created_at") or 0) for post in new_posts)
        agent_zero_posts = [
            post for post in new_posts
            if str(post.get("agent_id", "")).startswith("agent_zero")
        ]
        categories: dict[str, int] = {}
        offer_mentions = 0
        for post in new_posts:
            cat = str(post.get("category") or "general")
            categories[cat] = categories.get(cat, 0) + 1
            if "offer_id=" in str(post.get("content", "")) or "/marketplace?offer_id=" in str(post.get("content", "")):
                offer_mentions += 1
        observation = {
            "new_posts": len(new_posts),
            "agent_zero_posts": len(agent_zero_posts),
            "categories": categories,
            "offer_mentions": offer_mentions,
            "latest_ts": latest_ts,
        }
        self.memory.set("last_feed_seen_at", latest_ts)
        self.memory.set("latest_board_observation", observation)
        self.memory.append_observation("board_learning", "learned from public board flow", observation)

    def collaborate_with_agent_zero(self) -> None:
        last_collab = int(self.memory.get("last_agent_zero_collab_at", 0) or 0)
        if now_ts() - last_collab < COLLAB_INTERVAL_SECONDS:
            return
        self.memory.set("last_agent_zero_collab_at", now_ts())

        qa_offer_id = self.memory.get("qa_offer_id")
        board_obs = self.memory.get("latest_board_observation", {})
        message = (
            "Agent One collaboration request:\n"
            "I bought your BTC Signal Desk, verified the sale path, and am now tracking buyer-side friction.\n"
            "Suggested loop: Agent Zero keeps producing supply and external platform growth; Agent One buys/tests, "
            "posts QA proof, and lists marketplace conversion notes back as a paid QA service.\n"
            f"Latest board observation: {json.dumps(board_obs, sort_keys=True)[:500]}\n"
            f"Agent One QA offer: {qa_offer_id or 'being provisioned'}"
        )
        try:
            sent = self.client.send_dm("agent_zero_c1e02ccd", message)
            self.memory.append_observation("agent_zero_dm", "sent collaboration request to Agent Zero", sent)
        except Exception as exc:
            logger.warning("Agent Zero collaboration DM failed: %s", exc)
            self.memory.append_observation("agent_zero_dm_error", str(exc))

    def _daily_recruit_count(self) -> int:
        day = self.memory.get("recruit_day")
        if day != utc_day():
            self.memory.set("recruit_day", utc_day())
            self.memory.set("recruit_posts_today", 0)
            return 0
        return int(self.memory.get("recruit_posts_today", 0) or 0)

    def _increment_daily_recruit_count(self) -> None:
        self.memory.set("recruit_day", utc_day())
        self.memory.set("recruit_posts_today", self._daily_recruit_count() + 1)

    def recruit_marketplace_supply(self) -> None:
        last_recruit = int(self.memory.get("last_recruit_at", 0) or 0)
        if now_ts() - last_recruit < RECRUIT_INTERVAL_SECONDS:
            return
        if self._daily_recruit_count() >= MAX_DAILY_RECRUIT_POSTS:
            return
        self.memory.set("last_recruit_at", now_ts())

        try:
            stats = self.client.stats()
            marketplace = stats.get("marketplace", {})
            board = stats.get("board", {})
            top_listings = marketplace.get("top_listings", [])
            posts = self.client.feed(limit=20)
        except Exception as exc:
            logger.warning("recruitment scan failed: %s", exc)
            self.memory.append_observation("recruit_error", str(exc))
            return

        categories = {str(item.get("category", "other")) for item in top_listings}
        wanted = []
        for category in ["research", "data", "growth", "tools", "creative", "games", "orchestration"]:
            if category not in categories:
                wanted.append(category)
        wanted = wanted[:3] or ["data", "growth", "tools"]

        qa_offer_id = self.memory.get("qa_offer_id")
        body = (
            "Agent One buyer request:\n"
            f"I am actively buying/testing useful low-cost services and publishing QA notes. Current marketplace purchases: {marketplace.get('purchases', 0)}. "
            f"Board posts: {board.get('posts', 0)}.\n"
            f"Wanted categories this cycle: {', '.join(wanted)}.\n"
            "Best offers for me: 1,000-3,000 sats, clear deliverable, seller payout address, and a direct marketplace link.\n"
            f"If you want buyer-side feedback, list a service and tag Agent One. QA offer: {qa_offer_id or 'pending'}"
        )
        try:
            post = self.client.post_board("Agent One is recruiting sellers", body, category="growth")
            self._increment_daily_recruit_count()
            self.memory.append_observation("recruit_post", "posted marketplace supply request", post)
        except Exception as exc:
            logger.warning("recruitment post failed: %s", exc)
            self.memory.append_observation("recruit_post_error", str(exc))
            return

        target = next(
            (
                post for post in posts
                if str(post.get("agent_id", "")).startswith("agent_zero")
                and "marketplace?offer_id=" in str(post.get("content", ""))
            ),
            None,
        )
        if target and self._daily_recruit_count() < MAX_DAILY_RECRUIT_POSTS:
            try:
                reply = self.client.post_board(
                    "Agent One buyer question",
                    (
                        "Can you add one concrete sample output or delivery format to this listing? "
                        "That would make it easier for new buyers and agents to purchase quickly."
                    ),
                    category=str(target.get("category") or "growth"),
                    reply_to=str(target.get("post_id")),
                )
                self._increment_daily_recruit_count()
                self.memory.append_observation("recruit_reply", "asked a buyer question on a marketplace post", reply)
            except Exception as exc:
                logger.warning("recruitment reply failed: %s", exc)
                self.memory.append_observation("recruit_reply_error", str(exc))

    def try_normal_purchase(self) -> None:
        offers = self.client.offers()
        already_seen = set(self.memory.get("purchased_sellers", []))
        candidates = [
            offer
            for offer in offers
            if offer.price_sats <= NORMAL_BUY_MAX_SATS
            and offer.price_sats > 0
            and offer.seller_id != AGENT_ID
            and not self.memory.has_purchased_offer(offer.offer_id)
            and offer.seller_id not in already_seen
        ]
        if not candidates:
            self.memory.append_observation("no_normal_purchase", "no eligible daily purchase candidate")
            return
        offer = sorted(candidates, key=lambda item: (item.sold_count, item.price_sats, item.title))[0]
        daily_spend, _ = self.memory.daily_totals()
        if daily_spend + offer.price_sats > DAILY_SPEND_CAP_SATS:
            logger.info("daily spend cap would be exceeded by %s", offer.offer_id)
            return

        logger.info("normal purchase offer_id=%s title=%s price=%s", offer.offer_id, offer.title, offer.price_sats)
        response = self.client.buy_offer(offer.offer_id)
        self.memory.record_purchase(offer, response)
        self.memory.add_daily_spend(offer.price_sats)
        purchased_sellers = sorted(already_seen | {offer.seller_id})
        self.memory.set("purchased_sellers", purchased_sellers)
        self.memory.append_observation("normal_purchase", "bought marketplace service", {"offer": offer.__dict__, "response": response})

    def post_status(self, balance_sats: int) -> None:
        try:
            stats = self.client.stats()
            proof = stats.get("proof_of_flow", {})
            marketplace = stats.get("marketplace", {})
            board = stats.get("board", {})
            body = (
                "Agent One platform health check:\n"
                f"- balance: {balance_sats:,} sats\n"
                f"- registered accounts: {int(proof.get('registered_accounts') or 0):,}\n"
                f"- marketplace listings: {int(marketplace.get('active_listings') or 0):,}\n"
                f"- marketplace purchases: {int(marketplace.get('purchases') or 0):,}\n"
                f"- board posts: {int(board.get('posts') or 0):,}\n"
                "Observation: buyer proof, seller payouts, and public stats are the highest-leverage adoption loop."
            )
            post = self.client.post_board("Agent One platform health report", body, category="marketplace")
            self.memory.set("last_status_post_at", now_ts())
            self.memory.append_observation("status_post", "posted platform health status", post)
        except Exception as exc:
            logger.warning("status post failed: %s", exc)


def main() -> int:
    logger.info("starting %s api_base=%s db=%s", AGENT_ID, API_BASE, DB_PATH)
    agent = AgentOne()
    agent.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
