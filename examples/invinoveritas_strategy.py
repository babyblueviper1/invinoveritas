"""
InvinoveritasStrategy — Freqtrade strategy plugin
Uses invinoveritas /decision endpoint to validate trades before entry.

The bot runs its normal technical analysis. Before it enters a position,
it calls invinoveritas and asks: "Should I enter this trade right now?"
If confidence is too low or risk is too high, it skips the trade.

Setup:
  1. pip install requests lndgrpc  (or pyln-client for CLN)
  2. Set environment variables:
       API_BASE   — https://api.babyblueviper.com
       LND_DIR    — /root/.lnd  (or CLN_RPC_PATH for CLN)
  3. Drop this file in your freqtrade/user_data/strategies/ folder
  4. Run: freqtrade trade --strategy InvinoveritasStrategy

Tune these thresholds to your risk appetite:
  MIN_CONFIDENCE   — minimum confidence score to allow entry (0.0–1.0)
  MAX_RISK         — maximum risk level to allow entry (low / medium / high)
  SATS_BUDGET      — max sats to spend per session (circuit breaker)
"""

import os
import json
import logging
import requests
from functools import lru_cache
from datetime import datetime
from freqtrade.strategy import IStrategy, informative
from pandas import DataFrame
import talib.abstract as ta

logger = logging.getLogger(__name__)

# ─── tunable thresholds ───────────────────────────────────────
MIN_CONFIDENCE = 0.60       # skip trade if confidence below this
MAX_RISK = "medium"         # skip trade if risk_level is "high"
SATS_BUDGET = 10_000        # circuit breaker: stop calling after this many sats spent
# ─────────────────────────────────────────────────────────────

API_BASE = os.getenv("API_BASE", "https://api.babyblueviper.com").rstrip("/")
LND_DIR = os.getenv("LND_DIR")
CLN_RPC_PATH = os.getenv("CLN_RPC_PATH")

RISK_RANK = {"low": 0, "medium": 1, "high": 2}
MAX_RISK_RANK = RISK_RANK.get(MAX_RISK, 1)

try:
    from lndgrpc import LNDClient
except ImportError:
    LNDClient = None

try:
    from pyln.client import LightningRpc
except ImportError:
    LightningRpc = None


# ─── lightning + L402 helpers ─────────────────────────────────

def _pay_invoice(bolt11: str) -> str:
    if LND_DIR and LNDClient:
        lnd = LNDClient(LND_DIR)
        resp = lnd.send_payment_sync(payment_request=bolt11)
        return resp.payment_preimage.hex()
    if CLN_RPC_PATH and LightningRpc:
        rpc = LightningRpc(CLN_RPC_PATH)
        return rpc.pay(bolt11).get("payment_preimage")
    raise RuntimeError("No Lightning node configured. Set LND_DIR or CLN_RPC_PATH.")


def _call_decision(goal: str, context: str, question: str) -> dict:
    """Full L402 flow — returns the decision result dict."""
    payload = {"goal": goal, "context": context, "question": question}
    url = f"{API_BASE}/decision"

    resp = requests.post(url, json=payload, timeout=15)
    if resp.status_code == 200:
        return resp.json().get("result", {})

    if resp.status_code != 402:
        resp.raise_for_status()

    www_auth = resp.headers.get("WWW-Authenticate", "")
    token = www_auth.split('token="')[1].split('"')[0]
    bolt11 = www_auth.split('invoice="')[1].split('"')[0]

    preimage = _pay_invoice(bolt11)

    retry = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"L402 {token}:{preimage}"},
        timeout=30,
    )
    retry.raise_for_status()
    return retry.json().get("result", {})


def _get_price_sats() -> int:
    try:
        r = requests.get(f"{API_BASE}/price/decision", timeout=5)
        return r.json().get("price_sats", 1000)
    except Exception:
        return 1000


# ─── strategy ─────────────────────────────────────────────────

class InvinoveritasStrategy(IStrategy):
    """
    Standard EMA crossover strategy with an invinoveritas confidence gate.

    Normal signal flow:
      - EMA 9 crosses above EMA 21  → candidate long entry
      - RSI < 70                    → not overbought

    Before confirming entry, calls invinoveritas /decision:
      - confidence >= MIN_CONFIDENCE  → proceed
      - risk_level <= MAX_RISK        → proceed
      - otherwise                     → skip this candle

    This adds an AI second opinion to every trade without replacing
    the underlying technical signal.
    """

    INTERFACE_VERSION = 3
    timeframe = "1h"
    stoploss = -0.05
    trailing_stop = True
    trailing_stop_positive = 0.02

    # track sats spent this session
    _sats_spent: int = 0
    _decisions_made: int = 0
    _decisions_skipped: int = 0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema9"] = ta.EMA(dataframe, timeperiod=9)
        dataframe["ema21"] = ta.EMA(dataframe, timeperiod=21)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["volume_mean"] = dataframe["volume"].rolling(20).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["ema9"] > dataframe["ema21"]) &
                (dataframe["ema9"].shift(1) <= dataframe["ema21"].shift(1)) &
                (dataframe["rsi"] < 70) &
                (dataframe["volume"] > dataframe["volume_mean"])
            ),
            "enter_long"
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["ema9"] < dataframe["ema21"]) &
                (dataframe["ema9"].shift(1) >= dataframe["ema21"].shift(1))
            ),
            "exit_long"
        ] = 1
        return dataframe

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: str | None,
        **kwargs,
    ) -> bool:
        """
        Called by Freqtrade before every entry order is placed.
        This is where we call invinoveritas.
        """

        # Circuit breaker — stop spending if budget exhausted
        if self._sats_spent >= SATS_BUDGET:
            logger.warning(
                f"invinoveritas: sats budget exhausted ({self._sats_spent} sats spent). "
                f"Allowing trade without AI check."
            )
            return True

        price_sats = _get_price_sats()

        goal = "Maximize risk-adjusted returns on crypto trades"
        context = (
            f"Trading pair: {pair}. "
            f"Current price: {rate:.4f} USDT. "
            f"Entry signal: EMA9 crossed above EMA21 with RSI below 70 and above-average volume. "
            f"Strategy stoploss: {self.stoploss * 100:.1f}%. "
            f"Session stats: {self._decisions_made} trades approved, "
            f"{self._decisions_skipped} trades skipped, "
            f"{self._sats_spent} sats spent."
        )
        question = (
            f"Should I enter a long position on {pair} right now, "
            f"given the current market conditions and this technical signal?"
        )

        try:
            logger.info(f"invinoveritas: consulting decision engine for {pair} (~{price_sats} sats)...")
            result = _call_decision(goal, context, question)

            confidence = float(result.get("confidence", 0))
            risk_level = result.get("risk_level", "high").lower()
            decision = result.get("decision", "")
            reasoning = result.get("reasoning", "")
            risk_rank = RISK_RANK.get(risk_level, 2)

            self._sats_spent += price_sats

            logger.info(
                f"invinoveritas [{pair}]: "
                f"decision='{decision}' | "
                f"confidence={confidence:.2f} | "
                f"risk={risk_level} | "
                f"reasoning='{reasoning}'"
            )

            # Apply thresholds
            if confidence < MIN_CONFIDENCE:
                logger.info(
                    f"invinoveritas: SKIP {pair} — "
                    f"confidence {confidence:.2f} below threshold {MIN_CONFIDENCE}"
                )
                self._decisions_skipped += 1
                return False

            if risk_rank > MAX_RISK_RANK:
                logger.info(
                    f"invinoveritas: SKIP {pair} — "
                    f"risk_level '{risk_level}' exceeds max '{MAX_RISK}'"
                )
                self._decisions_skipped += 1
                return False

            logger.info(f"invinoveritas: APPROVE {pair} — confidence {confidence:.2f}, risk {risk_level}")
            self._decisions_made += 1
            return True

        except Exception as e:
            # If invinoveritas is unreachable, fail open (allow the trade)
            # Change to `return False` if you prefer fail closed
            logger.error(f"invinoveritas: decision engine error for {pair}: {e}. Allowing trade.")
            return True
