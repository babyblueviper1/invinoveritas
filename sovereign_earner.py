import asyncio
import json
import os
import random
import re
import sys
import time
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiohttp
import numpy as np
from dotenv import load_dotenv
from lnmarkets_sdk.v3.http.client import APIAuthContext, APIClientConfig, LNMClient
load_dotenv()


APP_DIR = Path(os.getenv("AGENT_HOME", "/root/invinoveritas"))
LOG_FILE = APP_DIR / "agent.log"
LOG_MAX_BYTES = int(os.getenv("AGENT_LOG_MAX_BYTES", str(25 * 1024 * 1024)))  # 25 MB
LOG_BACKUPS = int(os.getenv("AGENT_LOG_BACKUPS", "5"))
_LOG_ROTATION_CHECK_EVERY = 1000
_LOG_ROTATION_COUNTER = {"n": 0}
MEMORY_FILE = APP_DIR / "agent_memory.json"
REVIEW_REPORT_FILE = APP_DIR / "agent_review_reports.jsonl"
REVIEW_REPORT_MAX_BYTES = int(os.getenv("AGENT_REVIEW_REPORT_MAX_BYTES", str(64 * 1024 * 1024)))  # 64 MB
REVIEW_REPORT_BACKUPS = int(os.getenv("AGENT_REVIEW_REPORT_BACKUPS", "4"))
_REVIEW_ROTATION_CHECK_EVERY = 100
_REVIEW_ROTATION_COUNTER = {"n": 0}
KILL_FILE = APP_DIR / "STOP.txt"
AI_ENDPOINT = os.getenv("AI_REASON_ENDPOINT", "http://127.0.0.1:8000/reason")

BEARER_TOKEN = os.getenv("BEARER_TOKEN")
LNM_API_KEY = os.getenv("LNM_API_KEY")
LNM_API_SECRET = os.getenv("LNM_API_SECRET")
LNM_API_PASSPHRASE = os.getenv("LNM_API_PASSPHRASE")

FAST_SLEEP = 3.0
SLOW_SLEEP = 60
SAVE_EVERY_N_CYCLES = 10
AI_REVIEW_INTERVAL_SECONDS = 600
AI_ENTRY_COOLDOWN_SECONDS = 180      # flat-cycle: min gap after hold/None signal
AI_OPEN_POS_COOLDOWN_SECONDS = 300  # open-position cycle: min gap after hold/blocked exit

FEE_RATE = 0.0010
RISK_PER_TRADE = 0.035
MAX_RISK_PER_TRADE = 0.07
DEFAULT_LEVERAGE = 5
MIN_LEVERAGE = 1
MAX_LEVERAGE = 8
LEVERAGE_MARGIN_BUFFER = 0.85

MIN_SL_PCT = 0.0048
MIN_TP_TO_SL = 1.5
MAX_ADD_COUNT = 6
MAX_SCALE_OUT_COUNT = 5
ADD_MOVE_BPS_THRESHOLD = 15.0
ADD_CONFIDENCE_FLOOR = 0.50
ADD_STRONG_WINNER_CONFIDENCE_FLOOR = 0.48
ADD_TRUE_STALE_MINUTES = 6 * 60
SCALE_OUT_THESIS_THRESHOLD = 0.05
SCALE_OUT_STALL_MINUTES = 8.0
SCALE_ACTION_COOLDOWN_SECONDS = 60
ADD_FAILURE_COOLDOWN_SECONDS = 2 * 60
ADD_MARGIN_RESERVE_SATS = 750.0
ADD_MARGIN_UTILIZATION = 0.70
POST_ADD_GRACE_SECONDS = 90
SCALE_OUT_MIN_FEE_RATIO = 1.80
SCALE_OUT_PEAK_FEE_MULTIPLE = 2.00
SCALE_OUT_GIVEBACK_FRACTION = 0.65
RECOVERY_ADD_MIN_ADVERSE_BPS = 4.0
RECOVERY_ADD_MAX_ADVERSE_BPS = 32.0
RECOVERY_ADD_MIN_THESIS_SCORE = -0.08
RECOVERY_ADD_MAX_CLOSE_ALIGN = 0.24
RECOVERY_ADD_CONFIDENCE_FLOOR = 0.45
WINNER_ADD_MIN_MOVE_BPS = 8.0
WINNER_ADD_MIN_FEE_RATIO = 0.32
REBOUND_SCALE_OUT_MIN_FEE_RATIO = 0.90
REBOUND_SCALE_OUT_MIN_MOVE_BPS = 4.0
NET_REBALANCE_MIN_STRUCTURE_CONF = 0.60
NET_REBALANCE_REDUCE_MIN_CLOSE_ALIGN = 0.35
NET_REBALANCE_REDUCE_MIN_ADVERSE_BPS = 36.0
NET_REBALANCE_REDUCE_MAX_THESIS_SCORE = -0.55
NET_REBALANCE_MAX_REDUCE_FRACTION = 0.50
NET_REBALANCE_CROSS_MIN_STRUCTURE_CONF = 0.72
NET_REBALANCE_CROSS_TARGET_FRACTION = 0.25
POST_LOSS_COOLDOWN_MINUTES = 7.0
POST_LOSS_COOLDOWN_THRESHOLD = -25.0
POST_WIN_COOLDOWN_MINUTES = 5.0
POST_WIN_MEDIUM_COOLDOWN_MINUTES = 6.0
POST_WIN_LARGE_COOLDOWN_MINUTES = 10.0
POST_WIN_MEDIUM_THRESHOLD = 20.0
POST_WIN_LARGE_THRESHOLD = 50.0
POST_WIN_COOLDOWN_THRESHOLD = 0.0
POST_WIN_BREAKEVEN_EXEMPT_MIN = -5.0
POST_WIN_BREAKEVEN_EXEMPT_MAX = 10.0
POST_WIN_REENTRY_EDGE_MIN = 0.12
POST_WIN_REENTRY_EDGE_WINDOW_MINUTES = 30.0
MAX_QTY = 50
BROKEN_EXIT_THESIS_SCORE = -0.30
BROKEN_EXIT_ADVERSE_MOVE_BPS = 14.0

MAX_DAILY_LOSS_SATS = 15000
MAX_SESSION_DRAWDOWN_PCT = 0.08
COOLDOWN_AFTER_BIG_LOSS_MIN = 60
REGIME_RESTORE_MAX_AGE_SECONDS = 1800
LEARNING_EPOCH = os.getenv("LEARNING_EPOCH", "2026-04-16_epoch_1")
MAX_TRADES_PER_HOUR = 12
MAX_ATTACK_ENTRIES_PER_HOUR = 16
MAX_ADD_TRADES_PER_HOUR = 12
MAX_EXPLORATION_TRADES_PER_HOUR = 8  # deprecated: exploration rate is now dynamic, not hard-capped
MAX_CONSECUTIVE_LOSSES = 4
SIZING_BALANCE_HYSTERESIS_PCT = 0.02
EXPOSURE_BUDGET_MIN = 0.02
EXPOSURE_BUDGET_MAX = 0.85
STUCK_REPORT_MIN_AGE_MINUTES = 18.0
STUCK_REPORT_MAX_MFE_BPS = 8.0
STUCK_REPORT_MIN_MAE_BPS = 16.0
STUCK_REPORT_MIN_NO_PROGRESS = 0.55
FEATURE_WARMUP_MIN_PRICES = 60
FEATURE_WARMUP_MIN_MOMENTUM = 6
FEATURE_WARMUP_MIN_ORACLE_POINTS = 500
ENTRY_PRICE_DEVIATION_MAX_BPS = 12.0
EVIDENCE_VALID_MAX_ORACLE_AGE_SECONDS = 30 * 60

EXPLORATION_RISK_FLOOR = 0.18
EXPLORATION_RISK_CEIL = 0.45
EXPLORATION_MIN_CONFIDENCE = 0.44

# ==================== EXPLORATION OVERRIDE ====================
FORCE_EXPLORATION = False
FORCE_EXPLORATION_RATE = 0.35

# ==================== FEATURE FLAGS ====================
# Phase 4: early partial scale-out when fee_ratio is high but thesis is still intact.
ENABLE_EARLY_PARTIAL_SCALE_OUT = True
EARLY_PARTIAL_SCALE_OUT_FEE_RATIO = 0.45
EARLY_PARTIAL_SCALE_OUT_FRACTION = 0.33
EARLY_PARTIAL_SCALE_OUT_MIN_PEAK_FEE = 0.30
EXPLORATION_BASE_RATE = 0.50
EXPLORATION_MIN_RATE = 0.10
EXPLORATION_MAX_RATE = 0.92
SQUEEZE_PATIENCE_START_MINUTES = 60.0
SQUEEZE_PATIENCE_FULL_MINUTES = 180.0
SQUEEZE_PATIENCE_BONUS_MAX = 0.18
EXPLORATION_FREQUENCY_SOFT_COUNT = 6.0
EXPLORATION_FREQUENCY_PENALTY_MAX = 0.12
EXPLORATION_AUTOTUNE_INTERVAL_SECONDS = 4 * 60 * 60
EXPLORATION_AUTOTUNE_MIN_RESOLVED = 8
EXPLORATION_AUTOTUNE_GOOD_FCR = 0.55
EXPLORATION_AUTOTUNE_BAD_FCR = 0.35
EXPLORATION_AUTOTUNE_GOOD_AVG_BPS = 18.0
EXPLORATION_AUTOTUNE_BAD_AVG_BPS = -10.0
EXPLORATION_AUTOTUNE_GOOD_PEAK_FEE = 1.60
EXPLORATION_AUTOTUNE_BAD_PEAK_FEE = 0.90
EXPLORATION_MIN_SCORE_FLOOR = 0.50
EXPLORATION_MAX_SCORE_FLOOR = 0.56
EXPLORATION_MIN_COOLDOWN_SECONDS = 30
EXPLORATION_MAX_COOLDOWN_SECONDS = 180
STRATEGIC_ATTACK_MIN_MIX_RATE = 0.75
STRATEGIC_ATTACK_SCORE_RELIEF = 0.06
STRATEGIC_ATTACK_EDGE_RELIEF = 0.06
AGGRESSIVE_LEARNING_EDGE_LIFT_CAP = 0.38
AGGRESSIVE_LEARNING_MIN_EFFECTIVE_EDGE = 0.12
AGGRESSIVE_LEARNING_FLAT_BYPASS_MINUTES = 18.0
AGGRESSIVE_LEARNING_PREDICTIVE_FLOOR = 0.58
AGGRESSIVE_LEARNING_STRUCT_CONF_FLOOR = 0.52
EXPLORATION_LANE_MIN_RESOLVED = 6
EXPLORATION_LANE_GOOD_EV_BPS = 12.0
EXPLORATION_LANE_GOOD_BPS_PER_HOUR = 35.0
EXPLORATION_LANE_MIN_FCR = 0.55
EXPLORATION_LANE_MIN_PEAK_FEE = 1.50
EXPLORATION_LANE_MAX_ADVERSE_BPS = 28.0
EXPLORATION_LANE_MAX_AGE_HOURS = 8.0
EXPLORATION_LANE_ROLLBACK_MIN_RESOLVED = 4
EXPLORATION_LANE_ROLLBACK_MAX_FCR = 0.25
EXPLORATION_LANE_ROLLBACK_MAX_AVG_BPS = -15.0
TUNER_DRIFT_FREEZE_INSTABILITY = 0.55
EXPLORATION_ALLOC_ABS_QTY_MULT_MIN = 0.45
EXPLORATION_ALLOC_ABS_QTY_MULT_MAX = 1.60
EXPLORATION_ALLOC_ABS_RISK_MULT_MIN = 0.55
EXPLORATION_ALLOC_ABS_RISK_MULT_MAX = 1.25
EXPLORATION_ALLOC_ABS_MAX_LIVE_LEVERAGE = 20
CHOP_RISK_CAP = 0.0045
UNKNOWN_RISK_CAP = 0.0030
DETERMINISTIC_MOMENTUM_BREAK = 0.0012
DETERMINISTIC_PRICE_BREAK_PCT = 0.0020
CHOP_STALE_EXIT_MINUTES = 28
CHOP_REPROBE_BONUS_WINDOW_SECONDS = 20 * 60
CHOP_WEAK_THESIS_EXIT_MINUTES = 10
CHOP_WEAK_THESIS_SCORE = -0.30
CHOP_WEAK_THESIS_FEE_RATIO = 0.18
FEE_KILL_LOOKBACK_SECONDS = 2 * 3600
SMALL_ACCOUNT_CHOP_SUPPRESS_SATS = 15000
SMALL_ACCOUNT_CHOP_MIN_QUALITY = 0.35
SMALL_ACCOUNT_CHOP_MIN_EDGE = 0.30
SMALL_ACCOUNT_DYNAMIC_SIZING_SATS = 20000
SMALL_ACCOUNT_DYNAMIC_MIN_SATS = 6000
SMALL_ACCOUNT_MEDIUM_QTY = 3
SMALL_ACCOUNT_STRONG_QTY = 6
SMALL_ACCOUNT_AGGRESSIVE_QTY = 10
SMALL_ACCOUNT_EXPLORE_WINNER_QTY = 5
SMALL_ACCOUNT_MAX_MARGIN_UTIL = 0.85
SMALL_ACCOUNT_CAUTION_MARGIN_UTIL = 0.70
ELITE_CHOP_MIN_QUALITY = 0.36
ELITE_CHOP_MIN_EDGE = 0.42
ELITE_CHOP_MIN_REPLAY_SCORE = 0.58
ELITE_CHOP_MIN_REPLAY_SAMPLES = 80
CHOP_ALIGNMENT_MIN_SCORE = 0.50
CHOP_ALIGNMENT_MIN_LIVE_SCORE = 0.46
CHOP_FADE_VETO_VOLX = 1.10
CHOP_MIN_PEAK_FEE_MULTIPLE = 1.10
ELITE_CHOP_MIN_PEAK_FEE_MULTIPLE = 1.35
LIVE_CHOP_MIN_PREDICTIVE = 0.60
LIVE_CHOP_MIN_EDGE = 0.24
CHOP_LEARNER_LANE_MIN_QUALITY = 0.24
CHOP_LEARNER_LANE_MIN_ALIGN = 0.22
CHOP_LEARNER_LANE_MIN_PREDICTIVE = 0.60
CHOP_LEARNER_LANE_MIN_PEAK_FEE = 1.00
SMALL_ACCOUNT_DIRECTIONAL_MIN_QUALITY = 0.52
SMALL_ACCOUNT_DIRECTIONAL_MIN_EDGE = 0.22
SMALL_ACCOUNT_DIRECTIONAL_MIN_STRUCTURE = 0.58
SMALL_ACCOUNT_DIRECTIONAL_MIN_PREDICTIVE = 0.62
SMALL_ACCOUNT_BREAKOUT_MIN_PREDICTIVE = 0.58

# ==================== RANGE DETECTION ====================
CHOP_RANGE_LOOKBACK = 60            # candles for range high/low detection
CHOP_MIN_RANGE_WIDTH_PCT = 0.0040   # 0.40% min range to trade chop (2× round-trip fee)
CHOP_RANGE_LONG_MAX = 0.25          # long entries only in bottom 25% of range
CHOP_RANGE_SHORT_MIN = 0.75         # short entries only in top 75% of range
CHOP_RANGE_EDGE_BONUS = 0.12        # max chop alignment bonus for being at range edge
CHOP_RANGE_WIDTH_BONUS_MAX = 0.08   # max bonus for wide tradeable range
CHOP_RANGE_TP_MAX_OVERSHOOT = 0.80  # cap TP at 80% of range width (don't target opposite extreme)
LEVEL_MAP_MIN_POINTS = 30
LEVEL_NEAR_BPS = 14.0
LEVEL_RECLAIM_BPS = 5.0
LEVEL_MIN_ROOM_BPS = 42.0
LEVEL_BREAKOUT_MIN_ROOM_BPS = 55.0
LEVEL_SWING_LOOKBACK = 240
LEVEL_SWING_PIVOT_WIDTH = 3
LEVEL_SWING_PIVOT_WIDTH_SQUEEZE = 5
LEVEL_PIVOT_MIN_PROMINENCE_BPS = 3.0
LEVEL_PIVOT_MIN_PROMINENCE_BPS_SQUEEZE = 2.0
LEVEL_CLUSTER_MIN_GAP_BPS = 6.0  # Treat sub-floor pivots as one micro-zone, not separate hard targets.
WYCKOFF_SPRING_BREAK_BPS = 4.0    # level must be genuinely breached by this many bps
WYCKOFF_SPRING_RECLAIM_BPS = 6.0  # price must recover this many bps above/below level
WYCKOFF_SPRING_LOOKBACK = 60      # price history window to find the breach
LEVEL_AUTOTUNE_INTERVAL_SECONDS = 4 * 60 * 60
LEVEL_AUTOTUNE_MIN_RESOLVED = 6
LEVEL_AUTOTUNE_MIN_FCR = 0.55
LEVEL_AUTOTUNE_MIN_AVG_OUTCOME_BPS = 25.0
LEVEL_AUTOTUNE_MIN_AVG_PEAK_FEE = 1.60
LEVEL_AUTOTUNE_MAX_AVG_ADVERSE_BPS = 24.0
LEVEL_MIN_ROOM_HARD_FLOOR_BPS = 24.0
LEVEL_BREAKOUT_ROOM_HARD_FLOOR_BPS = 18.0
# Adaptive squeeze floors — used when the live bracket is narrower than the
# tuned gate, so buy-low/sell-high can fire in tight ranges without the gate
# becoming mathematically unreachable.
LEVEL_SQUEEZE_ROOM_FLOOR_BPS = 2.5
LEVEL_SQUEEZE_BREAKOUT_FLOOR_BPS = 6.0
# Trigger ratio: adaptive floor fires when bracket < value * ratio.
# Raised from 1.5 → 2.5 so the adaptive floor covers typical squeeze brackets
# (45–60 bps total) rather than only very tight ones (<36 bps).
LEVEL_SQUEEZE_BRACKET_TRIGGER_RATIO = 2.5
LEVEL_SQUEEZE_BRACKET_TRIGGER_RATIO_FLOOR = 1.5   # hard min — never go narrower than original
LEVEL_SQUEEZE_BRACKET_TRIGGER_RATIO_CEIL = 4.0    # hard max — avoid triggering in wide ranges
# Room fraction: adaptive min = max(floor, fraction * bracket).
# Lowered from 0.50 → 0.35 so a 60-bps bracket allows ~21-bps entries instead of 30.
LEVEL_SQUEEZE_ROOM_FRACTION = 0.22
LEVEL_SQUEEZE_ROOM_FRACTION_FLOOR = 0.12   # absolute min fraction allowed by tuner
LEVEL_SQUEEZE_ROOM_FRACTION_CEIL = 0.55    # absolute max (reverts toward original 0.50)
LEVEL_SQUEEZE_BREAKOUT_FRACTION = 0.55     # breakout stays tighter than mean-revert
LEVEL_SQUEEZE_BREAKOUT_FRACTION_FLOOR = 0.35
LEVEL_SQUEEZE_BREAKOUT_FRACTION_CEIL = 0.70
LEVEL_BREAKOUT_SHADOW_PROOF_MAX_AGE_HOURS = 12.0
WINNER_LOCK_PEAK_FEE_MULTIPLE = 1.5
WINNER_LOCK_STRONG_PEAK_FEE_MULTIPLE = 3.0
WINNER_LOCK_MIN_BPS = 25.0
WINNER_LOCK_RETAIN_MFE = 0.55
WINNER_LOCK_BREAKEVEN_PEAK_FEE = 0.70
EDGE_CALIBRATION_MIN_TRADES = 5
EDGE_CALIBRATION_MIN_CONTEXT_RESOLVED = 3
EDGE_CALIBRATION_MIN_FEE_CLEAR = 0.12
EDGE_CALIBRATION_MIN_PEAK_FEE = 0.80
DIRECTIONAL_PROOF_MIN_RESOLVED = 2
POLICY_STATS_DECAY_HALF_LIFE_HOURS = 36.0
GATE_SNAPSHOT_LOG_INTERVAL_SECONDS = 60
SHADOW_REPORT_LOG_INTERVAL_SECONDS = 15 * 60

RISK_RECENT_PNL_WINDOW = 4
RISK_STREAK_WINDOW = 5
RISK_PROTECTION_RECENT_LOSS_RATIO = 0.12
RISK_PROTECTION_DAILY_LOSS_RATIO = 0.26
RISK_PROTECTION_COOLDOWN_SECONDS = 15 * 60
RISK_CAUTION_RECENT_LOSS_RATIO = 0.08
RISK_CAUTION_DAILY_LOSS_RATIO = 0.12
RISK_CAUTION_CONSECUTIVE_LOSSES = 5
RISK_CAUTION_STREAK = -5
DIRECTIONAL_MIN_PEAK_FEE_MULTIPLE = 0.75
DIRECTIONAL_SHADOW_MIN_PEAK_FEE_MULTIPLE = 0.60
EXTERNAL_MARKET_INTERVAL_SECONDS = 5 * 60
BITGET_API_BASE = os.getenv("BITGET_API_BASE", "https://api.bitget.com")
DERIBIT_API_BASE = os.getenv("DERIBIT_API_BASE", "https://www.deribit.com/api/v2")
ORACLE_API_BASE = os.getenv("ORACLE_API_BASE", "https://api.lnmarkets.com/v3")
HTF_BIAS_REFRESH_SECONDS = 4 * 3600  # re-fetch daily/weekly structure every 4 hours
ORACLE_REPLAY_INTERVAL_SECONDS = 15 * 60
ORACLE_REPLAY_LOOKBACK_HOURS = 168
ORACLE_REPLAY_LIMIT = 1000
ORACLE_REPLAY_MAX_PAGES = 7
ORACLE_REPLAY_FEE_PROXY_BPS = 18.0
ORACLE_REPLAY_HOLD_STEPS = 24
ORACLE_REPLAY_MIN_POINTS = 120
ORACLE_REGIME_BLEND = 0.35
ORACLE_FCR_MIN_SAMPLES = 30
ORACLE_FCR_SQUEEZE_MIN_SAMPLES = 12   # lower bar — squeeze samples accumulate slowly
ORACLE_FCR_HARD_BLOCK = 0.24
ORACLE_FCR_CAUTION = 0.34
ORACLE_FCR_SQUEEZE_BASE_THRESHOLD = 0.28
ORACLE_FCR_SQUEEZE_FLAT20_THRESHOLD = 0.22
ORACLE_FCR_SQUEEZE_ALIGN_OVERRIDE_MIN = 0.65
ORACLE_FCR_SQUEEZE_ALIGN_OVERRIDE_MINUTES = 35.0
CAUTION_DECAY_START_MINUTES = 20.0
CAUTION_DECAY_FULL_MINUTES = 45.0
CAUTION_DECAY_MIN_MULTIPLIER = 0.12
CONSECUTIVE_LOSS_DECAY_REDUCED_MINUTES = 25.0
CONSECUTIVE_LOSS_DECAY_RESET_MINUTES = 40.0
AI_SQUEEZE_MIN_CONFIDENCE = 0.32
AI_SQUEEZE_FLAT_MIN_CONFIDENCE = 0.32
AI_SQUEEZE_ALIGNMENT_OVERRIDE = 0.55
SQUEEZE_MEAN_REVERT_STRUCTURE_MIN_CONF = 0.70
SQUEEZE_MEAN_REVERT_MIN_ROOM_BPS = 12.0
SQUEEZE_MICRO_RANGE_MIN_WIDTH_PCT = 0.0012
SQUEEZE_MICRO_RANGE_MIN_BRACKET_BPS = 12.0
SQUEEZE_MICRO_RANGE_MAX_BRACKET_BPS = 55.0
ORACLE_SCORE_HARD_BLOCK = 0.46
FLAT_REACTIVATION_START_MINUTES = 12
FLAT_REACTIVATION_FULL_MINUTES = 36
MAX_CHOP_REACTIVATION_RELIEF = 0.08
SHADOW_EXPLORATION_COOLDOWN_SECONDS = 5 * 60
SHADOW_MAX_PENDING = 6
SHADOW_SELECTOR_BONUS_CAP = 0.05

TECHNICAL_EXIT_REASON_TOKENS = tuple(
    token.strip().lower()
    for token in os.getenv(
        "TECHNICAL_EXIT_REASON_TOKENS",
        "technical,bug,prompt,fee_rule,fee bug,fee issue,sync,error,failed,repair,exchange_no_position,order_rejected",
    ).split(",")
    if token.strip()
)

EXPLORATION_COOLDOWN_SECONDS = 60
EPOCH_CUTOFF_UTC = datetime(2026, 4, 16, 14, 0, 0, tzinfo=timezone.utc)
AI_CLOSE_FEE_MULTIPLIER = 1.25
REDUCE_FEE_MULTIPLIER = 1.10
MIN_ABSOLUTE_THESIS_EXIT_PNL = 250.0

_cycle_counter = 0
_last_daily_update = 0.0
_last_htf_update = 0.0
AI_SEMAPHORE = asyncio.Semaphore(2)
AI_SESSION: Optional[aiohttp.ClientSession] = None
AI_PAYMENT_BLOCK_COOLDOWN_SECONDS = int(os.getenv("AI_PAYMENT_BLOCK_COOLDOWN_SECONDS", "600"))
_ai_payment_block_until = 0.0
PRICE_WINDOW = deque(maxlen=300)

# ==================== FEES ====================

total_fees_paid: float = 0.0
total_trades_with_fees: int = 0

market_state = {
    "last_price": 0.0,
    "momentum": 0.0,
    "volatility": 0.0008,
    "micro_trend": "neutral",
}

brain: dict[str, Any] = {
    "trade_lessons": [],
    "meta_lessons": [],
    "last_price": None,
    "momentum": 0.0,
    "volatility": 0.0008,
    "regime_hint": "neutral",
    "market_regime": {
        "regime": "unknown",
        "volatility": 0.0,
        "trend_strength": 0.0,
        "compression": 0.0,
        "confidence": 0.0,
        "timestamp": None,
    },
    "regime_history": [],
    "regime_transition": {},
    "regime_stats": {
        "trend": {"trades": 0, "wins": 0, "pnl": 0.0},
        "chop": {"trades": 0, "wins": 0, "pnl": 0.0},
        "volatile": {"trades": 0, "wins": 0, "pnl": 0.0},
        "squeeze": {"trades": 0, "wins": 0, "pnl": 0.0},
    },
    "regime_weights": {},
    "oracle_replay": {
        "last_run_at": None,
        "last_status": "idle",
        "points": 0,
        "regime_stats": {},
        "regime_weights": {},
        "regime_scores": {},
        "regime_context": {},
    },
    "market_context": {
        "bid": 0.0,
        "ask": 0.0,
        "spread_pct": 0.0,
        "imbalance": 0.0,
        "mid_price": 0.0,
        "spread_shock": 1.0,
        "funding_momentum": "stable",
        "funding_bias": "neutral",
        "session_bucket": "offhours",
        "session_bias": "neutral",
        "volatility_state": "normal",
        "volatility_expansion": 1.0,
        "mtf_alignment": "mixed",
        "momentum_1m": 0.0,
        "momentum_5m": 0.0,
        "momentum_15m": 0.0,
        "range_position": 0.5,
        "range_width_pct": 0.0,
        "range_high": 0.0,
        "range_low": 0.0,
        "range_mid": 0.0,
        "range_established": False,
        "external_bias": "neutral",
        "external_conviction": 0.0,
        "external_source": "none",
        "bitget_status": "missing",
        "bitget_open_interest": 0.0,
        "bitget_account_long_ratio": 0.5,
        "bitget_position_long_ratio": 0.5,
        "binance_oi_delta_pct": 0.0,
        "binance_taker_ratio": 1.0,
        "binance_top_position_ratio": 1.0,
        "binance_top_account_ratio": 1.0,
        "deribit_funding_1h": 0.0,
        "deribit_funding_8h": 0.0,
    },
    "external_market": {
        "last_updated_at": None,
        "status": "idle",
        "binance": {},
        "deribit": {},
    },
    "htf_bias": {
        "htf_bias_score": 0.0,
        "htf_bias": "neutral",
        "htf_daily_score": 0.0,
        "htf_weekly_score": 0.0,
        "htf_12h_score": 0.0,
        "htf_4h_score": 0.0,
        "htf_1h_score": 0.0,
        "status": "idle",
    },
    "price_action_summary": "neutral",
    "learning_epoch": None,
    "learning_epoch_started_at": None,
    "trades": 0,
    "wins": 0,
    "losses": 0,
    "streak": 0,
    "total_pnl": 0.0,
    "lifetime_trades": 0,
    "lifetime_total_pnl": 0.0,
    "daily_pnl": 0.0,
    "daily_start_time": None,
    "daily_realized": [],
    "last_pnls": [],
    "historical_stats": {},
    "equity_peak": 0.0,
    "current_equity": 0.0,
    "drawdown": 0.0,
    "risk_mode": "normal",
    "base_risk_per_trade": RISK_PER_TRADE,
    "current_risk_per_trade": RISK_PER_TRADE,
    "current_risk_multiplier": 1.0,
    "confidence_bias": 0.0,
    "risk_history": [],
    "intent_stats": {
        "trend_follow": {"trades": 0, "wins": 0, "pnl": 0.0, "winrate": 0.0},
        "mean_revert": {"trades": 0, "wins": 0, "pnl": 0.0, "winrate": 0.0},
        "breakout": {"trades": 0, "wins": 0, "pnl": 0.0, "winrate": 0.0},
        "scalp": {"trades": 0, "wins": 0, "pnl": 0.0, "winrate": 0.0},
    },
    "confidence_stats": {},
    "last_decision": {
        "timestamp": None,
        "action": None,
        "direction": None,
        "intent": "trend_follow",
        "mode": "exploit",
        "policy": "ai_primary",
        "confidence": 0.5,
        "leverage": None,
        "tp_bps": None,
        "sl_bps": None,
        "trail_bps": None,
        "max_hold": None,
        "reason": "",
    },
    "last_review_action": None,
    "last_review_reason": None,
    "last_trade": {"entry": None, "side": None, "qty": 0, "leverage": None},
    "position": {"is_open": False},
    "last_exit": {},
    "last_exit_reason": "",
    "last_trade_error": {},
    "last_monitor_error": {},
    "last_margin": {"leverage": DEFAULT_LEVERAGE, "usable": 800.0},
    "trade_failures": 0,
    "session_start": None,
    "cooldown_until": 0,
    "last_entry_attempt": 0,
    "last_ai_hold_signal_time": 0,
    "past_ai_decisions": [],
    "ai_reviews": [],
    "ai_adjustments": [],
    "adds": [],
    "position_events": [],
    "funding_rate": 0.0,
    "funding_rate_pct": 0.0,
    "leaderboard": {},
    "leaderboard_history": [],
    "processed_trade_ids": [],
    "last_replay_at": None,
    "trade_timestamps": [],
    "exploration": {
        "last_policy": None,
        "last_explore_at": 0.0,
        "last_score": 0.0,
        "mix_rate": EXPLORATION_BASE_RATE,
        "policies": {},
        "recent": [],
    },
    "shadow_exploration": {
        "last_shadow_at": 0.0,
        "policies": {},
        "recent": [],
        "pending": [],
    },
    "range_thresholds": {
        "long_max": 0.25,
        "short_min": 0.75,
        "last_tuned": None,
        "tune_count": 0,
        "last_reason": "initial defaults",
        "history": [],
    },
    "entry_thresholds": {
        "quality_floor": 0.20,
        "chop_align_min": 0.50,
        "chop_align_live_min": 0.46,
        "range_width_min_pct": 0.0040,
        "fee_kill_ratio": 0.625,
        "directional_min_quality": 0.52,
        "directional_min_structure": 0.58,
        "directional_min_predictive": 0.62,
        "directional_min_edge": 0.22,
        "breakout_min_predictive": 0.64,
        "last_tuned": None,
        "tune_count": 0,
        "last_reason": "initial defaults",
        "history": [],
    },
}

MEMORY: dict[str, Any] = {}
recent_pnls: list[float] = []
@dataclass
class EntrySignal:
    action: str
    direction: str
    intent: str
    mode: str
    policy: str
    confidence: float
    sl_bps: int
    tp_bps: int
    trail_bps: int
    leverage: int
    max_hold_minutes: int
    risk_per_trade: float
    reason: str
    quantity: Optional[int] = None

    base_risk_per_trade: float = 0.0
    effective_risk_per_trade: float = 0.0
    expected_edge: float = 0.0
    predictive_setup_score: float = 0.0
    predictive_setup_summary: str = "n/a"
    predictive_setup_edge_bonus: float = 0.0
    llm_predictive_prob: float = 0.5
    llm_predictive_edge: float = 0.0
    chop_learner_lane_active: bool = False
    entry_gate_state_snapshot: Optional[dict[str, Any]] = None
    tuned_lane_key: str = ""
    tuned_qty_multiplier: float = 1.0
    tuned_risk_multiplier: float = 1.0
    tuned_allocation_reason: str = ""
    parent_qty_multiplier: float = 1.0
    parent_risk_multiplier: float = 1.0
    parent_leverage_target: int = 0
    parent_allocation_reason: str = ""
    entry_tag: str = ""
    signal_price: float = 0.0
    evidence_valid: bool = True
    evidence_reason: str = "n/a"
    roi_schedule_reason: str = ""


@dataclass
class PositionState:
    side: Optional[str] = None
    entry: Optional[float] = None
    qty: float = 0.0
    leverage: Optional[float] = None
    intent: str = "trend_follow"
    confidence: float = 0.5
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    trail_buffer_pct: Optional[float] = None
    pending_close: bool = False
    pending_add: bool = False
    pending_add_qty: float = 0.0
    pending_reduce: bool = False
    pending_reduce_qty: float = 0.0
    pending_reverse: bool = False
    pending_reverse_qty: float = 0.0
    pending_reverse_direction: Optional[str] = None
    last_reason: str = ""
    opened_at: Optional[datetime] = None
    max_hold_minutes: Optional[float] = None
    add_count: int = 0
    original_qty: float = 0.0
    scale_out_count: int = 0
    last_scale_action_at: Optional[datetime] = None
    last_add_at: Optional[datetime] = None
    status: str = "closed"
    exchange_order_id: Optional[str] = None
    mode: str = "exploit"
    policy: str = "ai_primary"

    initial_margin: Optional[float] = None
    running_margin: Optional[float] = None
    total_pl: Optional[float] = None
    entry_market_quality: float = 0.0
    entry_momentum: float = 0.0
    entry_imbalance: float = 0.0
    entry_momentum_persistence: float = 0.0
    entry_imbalance_persistence: float = 0.0
    best_price: Optional[float] = None
    worst_price: Optional[float] = None
    trailing_min_since_open: float = 0.0
    trailing_max_since_min: float = 0.0
    trailing_max_since_open: float = 0.0
    trailing_min_since_max: float = 0.0
    max_unrealized_pnl: float = 0.0
    min_unrealized_pnl: float = 0.0
    time_to_mfe_minutes: Optional[float] = None
    time_to_mae_minutes: Optional[float] = None
    last_thesis_score: float = 0.0
    last_add_ready: bool = False
    entry_expected_edge: float = 0.0
    entry_predictive_setup_score: float = 0.0
    entry_predictive_setup_summary: str = "n/a"
    entry_chop_learner_lane_active: bool = False
    entry_nearest_support: float = 0.0
    entry_nearest_resistance: float = 0.0
    entry_room_to_target_bps: float = 0.0
    entry_level_alignment: str = "unknown"
    entry_level_summary: str = "n/a"
    entry_feature_health_summary: str = "n/a"
    entry_tag: str = ""
    exit_tag: str = ""
    signal_price: float = 0.0
    evidence_valid: bool = True
    evidence_reason: str = "n/a"
    roi_schedule_reason: str = ""

    @property
    def is_open(self) -> bool:
        return self.status == "open" and self.qty > 0

    @property
    def age_minutes(self) -> float:
        if not self.opened_at:
            return 0.0
        return (datetime.now() - self.opened_at).total_seconds() / 60

    def unrealized_pnl(self, current_price: float) -> float:
        """LN Markets inverse futures P&L formula — gross, before fees"""
        if not self.is_open or self.entry is None or self.qty <= 0:
            return 0.0

        if current_price <= 0 or self.entry <= 0:
            return 0.0

        qty = abs(self.qty)

        try:
            if self.side == "long":
                pnl = qty * (1 / self.entry - 1 / current_price) * 100_000_000
            elif self.side == "short":
                pnl = qty * (1 / current_price - 1 / self.entry) * 100_000_000
            else:
                return 0.0

            if abs(pnl) > 100:
                log(
                    f"UNREALIZED PNL | {pnl:+.0f} sats | "
                    f"side={self.side} qty={qty:.2f} × lev={self.leverage}x | "
                    f"entry={self.entry:.1f} → current={current_price:.1f}"
                )
        except (ZeroDivisionError, OverflowError):
            pnl = 0.0

        return pnl

    def update_trail(self, current_price: float):
        if not self.is_open or self.trail_buffer_pct is None:
            return
        distance = current_price * self.trail_buffer_pct
        if self.side == "long":
            new_sl = current_price - distance
            if self.sl_price is None or new_sl > self.sl_price:
                self.sl_price = new_sl
        elif self.side == "short":
            new_sl = current_price + distance
            if self.sl_price is None or new_sl < self.sl_price:
                self.sl_price = new_sl

    def open(
        self,
        side: str,
        entry: float,
        qty: float,
        leverage: float,
        sl_price: Optional[float],
        tp_price: Optional[float],
        trail_buffer_pct: Optional[float],
        max_hold_minutes: Optional[float],
        intent: str,
        confidence: float,
        reason: str,
        mode: str = "exploit",
        policy: str = "ai_primary",
        exchange_order_id: Optional[str] = None,
        initial_margin: Optional[float] = None,
        running_margin: Optional[float] = None,
        total_pl: Optional[float] = None,
        entry_expected_edge: float = 0.0,
        entry_predictive_setup_score: float = 0.0,
        entry_predictive_setup_summary: str = "n/a",
        entry_chop_learner_lane_active: bool = False,
        entry_tag: str = "",
        signal_price: float = 0.0,
        evidence_valid: bool = True,
        evidence_reason: str = "n/a",
        roi_schedule_reason: str = "",
    ):
        """Open a position with proper validation and LN Markets-friendly logging"""

        if qty <= 0:
            log(f"⚠️ Invalid qty={qty} — refusing to open position")
            return

        if leverage < 1.0:
            leverage = 1.0
            log("⚠️ Leverage was invalid, forcing minimum 1x")

        self.side = side
        self.entry = float(entry)
        self.qty = float(qty)
        self.leverage = float(leverage)
        self.sl_price = sl_price
        self.tp_price = tp_price
        self.trail_buffer_pct = trail_buffer_pct
        self.max_hold_minutes = max_hold_minutes
        self.intent = intent
        self.confidence = float(confidence)
        self.opened_at = datetime.now()
        self.status = "open"
        self.last_reason = reason
        self.add_count = 0
        self.original_qty = float(qty)
        self.scale_out_count = 0
        self.last_scale_action_at = None
        self.last_add_at = None
        self.pending_close = False
        self.pending_add = False
        self.pending_add_qty = 0.0
        self.pending_reduce = False
        self.pending_reduce_qty = 0.0
        self.pending_reverse = False
        self.pending_reverse_qty = 0.0
        self.pending_reverse_direction = None
        self.exchange_order_id = exchange_order_id

        self.initial_margin = initial_margin
        self.running_margin = running_margin
        self.total_pl = total_pl
        signal_features = get_market_path_features()
        self.entry_market_quality = float(brain.get("last_market_quality_components", {}).get("raw_score", 0.0) or 0.0)
        self.entry_momentum = float(brain.get("momentum", 0.0) or 0.0)
        self.entry_imbalance = float(brain.get("market_context", {}).get("imbalance", 0.0) or 0.0)
        self.entry_momentum_persistence = float(signal_features.get("momentum_persistence", 0.0) or 0.0)
        self.entry_imbalance_persistence = float(signal_features.get("imbalance_persistence", 0.0) or 0.0)
        self.best_price = self.entry
        self.worst_price = self.entry
        self.trailing_min_since_open = self.entry
        self.trailing_max_since_min = self.entry
        self.trailing_max_since_open = self.entry
        self.trailing_min_since_max = self.entry
        self.max_unrealized_pnl = 0.0
        self.min_unrealized_pnl = 0.0
        self.time_to_mfe_minutes = 0.0
        self.time_to_mae_minutes = 0.0
        self.last_thesis_score = 0.0
        self.last_add_ready = False
        self.entry_expected_edge = float(entry_expected_edge or 0.0)
        self.entry_predictive_setup_score = float(entry_predictive_setup_score or 0.0)
        self.entry_predictive_setup_summary = str(entry_predictive_setup_summary or "n/a")
        self.entry_chop_learner_lane_active = bool(entry_chop_learner_lane_active)
        market_ctx = brain.get("market_context", {}) or {}
        level_side_key = "room_to_resistance_bps" if side == "long" else "room_to_support_bps"
        self.entry_nearest_support = float(market_ctx.get("nearest_support", 0.0) or 0.0)
        self.entry_nearest_resistance = float(market_ctx.get("nearest_resistance", 0.0) or 0.0)
        self.entry_room_to_target_bps = float(market_ctx.get(level_side_key, 0.0) or 0.0)
        self.entry_level_alignment = str(market_ctx.get("level_alignment", "unknown") or "unknown")
        self.entry_level_summary = str(market_ctx.get("level_summary", "n/a") or "n/a")
        self.entry_feature_health_summary = str(market_ctx.get("feature_health_summary", "n/a") or "n/a")
        self.entry_tag = str(entry_tag or "")
        self.exit_tag = ""
        self.signal_price = float(signal_price or entry or 0.0)
        self.evidence_valid = bool(evidence_valid)
        self.evidence_reason = str(evidence_reason or "n/a")
        self.roi_schedule_reason = str(roi_schedule_reason or "")

        self.mode = mode
        self.policy = policy

        log(
            f"OPEN {side.upper()} | entry={self.entry:.1f} | "
            f"qty={self.qty:.2f} | lev={self.leverage:.1f}x | "
            f"margin={self.initial_margin or 'N/A'} | "
            f"sl={f'{sl_price:.0f}' if sl_price else 'N/A'} | "
            f"tp={f'{tp_price:.0f}' if tp_price else 'N/A'} | "
            f"{mode}/{policy} | {reason}"
        )
        persist_open_position_plan(self)

    def reset(self, reason: str = ""):
        log(f"Position reset | reason={reason or self.last_reason}")
        self.side = None
        self.entry = None
        self.qty = 0.0
        self.leverage = None
        self.sl_price = None
        self.tp_price = None
        self.trail_buffer_pct = None
        self.pending_close = False
        self.pending_add = False
        self.pending_add_qty = 0.0
        self.pending_reduce = False
        self.pending_reduce_qty = 0.0
        self.pending_reverse = False
        self.pending_reverse_qty = 0.0
        self.pending_reverse_direction = None
        self.last_reason = reason
        self.opened_at = None
        self.max_hold_minutes = None
        self.add_count = 0
        self.original_qty = 0.0
        self.scale_out_count = 0
        self.last_scale_action_at = None
        self.last_add_at = None
        self.status = "closed"
        self.exchange_order_id = None
        self.mode = "exploit"
        self.policy = "ai_primary"
        self.entry_market_quality = 0.0
        self.entry_momentum = 0.0
        self.entry_imbalance = 0.0
        self.entry_momentum_persistence = 0.0
        self.entry_imbalance_persistence = 0.0
        self.best_price = None
        self.worst_price = None
        self.trailing_min_since_open = 0.0
        self.trailing_max_since_min = 0.0
        self.trailing_max_since_open = 0.0
        self.trailing_min_since_max = 0.0
        self.max_unrealized_pnl = 0.0
        self.min_unrealized_pnl = 0.0
        self.time_to_mfe_minutes = None
        self.time_to_mae_minutes = None
        self.last_thesis_score = 0.0
        self.last_add_ready = False
        self.entry_expected_edge = 0.0
        self.entry_predictive_setup_score = 0.0
        self.entry_chop_learner_lane_active = False
        self.entry_predictive_setup_summary = "n/a"
        self.entry_nearest_support = 0.0
        self.entry_nearest_resistance = 0.0
        self.entry_room_to_target_bps = 0.0
        self.entry_level_alignment = "unknown"
        self.entry_level_summary = "n/a"
        self.entry_feature_health_summary = "n/a"
        self.entry_tag = ""
        self.exit_tag = ""
        self.signal_price = 0.0
        self.evidence_valid = True
        self.evidence_reason = "n/a"
        self.roi_schedule_reason = ""
        clear_persisted_position_plan(reason)


def _rotate_log_if_needed() -> None:
    try:
        if not LOG_FILE.exists():
            return
        if LOG_FILE.stat().st_size < LOG_MAX_BYTES:
            return
        # Shift existing backups: agent.log.4 → .5, .3 → .4, ...
        for idx in range(LOG_BACKUPS, 0, -1):
            src = LOG_FILE.with_suffix(LOG_FILE.suffix + f".{idx}") if idx > 1 else Path(str(LOG_FILE) + ".1")
            dst = Path(str(LOG_FILE) + f".{idx + 1}")
            if src.exists():
                if idx + 1 > LOG_BACKUPS:
                    try:
                        src.unlink()
                    except Exception:
                        pass
                else:
                    try:
                        src.replace(dst)
                    except Exception:
                        pass
        try:
            LOG_FILE.replace(Path(str(LOG_FILE) + ".1"))
        except Exception:
            pass
    except Exception:
        pass


def _rotate_jsonl_if_needed(path: Path, max_bytes: int, backups: int) -> None:
    try:
        if backups <= 0 or max_bytes <= 0 or not path.exists():
            return
        if path.stat().st_size < max_bytes:
            return
        for idx in range(backups, 0, -1):
            src = Path(str(path) + f".{idx}")
            dst = Path(str(path) + f".{idx + 1}")
            if not src.exists():
                continue
            if idx + 1 > backups:
                try:
                    src.unlink()
                except Exception:
                    pass
            else:
                try:
                    src.replace(dst)
                except Exception:
                    pass
        try:
            path.replace(Path(str(path) + ".1"))
        except Exception:
            pass
    except Exception:
        pass


def _rotate_review_report_if_needed() -> None:
    _rotate_jsonl_if_needed(REVIEW_REPORT_FILE, REVIEW_REPORT_MAX_BYTES, REVIEW_REPORT_BACKUPS)


def iter_review_report_files() -> list[Path]:
    """Return active + rotated review reports, newest first."""
    files = [REVIEW_REPORT_FILE]
    for idx in range(1, max(REVIEW_REPORT_BACKUPS, 0) + 1):
        files.append(Path(str(REVIEW_REPORT_FILE) + f".{idx}"))
    return [path for path in files if path.exists()]


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        _LOG_ROTATION_COUNTER["n"] += 1
        if _LOG_ROTATION_COUNTER["n"] >= _LOG_ROTATION_CHECK_EVERY:
            _LOG_ROTATION_COUNTER["n"] = 0
            _rotate_log_if_needed()
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass


def append_review_report(report_type: str, payload: dict[str, Any]):
    """Append-only review feed for offline tuning; never affects live decisions."""
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        _REVIEW_ROTATION_COUNTER["n"] += 1
        if _REVIEW_ROTATION_COUNTER["n"] >= _REVIEW_ROTATION_CHECK_EVERY:
            _REVIEW_ROTATION_COUNTER["n"] = 0
            _rotate_review_report_if_needed()
        record = {
            "timestamp": datetime.now().isoformat(),
            "type": report_type,
            "payload": safe_serialize(payload),
        }
        with REVIEW_REPORT_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        if REVIEW_REPORT_FILE.stat().st_size >= REVIEW_REPORT_MAX_BYTES:
            _rotate_review_report_if_needed()
    except Exception as exc:
        log(f"review report append failed: {exc}")


def emit_gate_event_if_changed(gate_name: str, state: str, payload: Optional[dict[str, Any]] = None):
    """Append a gate_event record to agent_review_reports.jsonl only when the state of
    a named gate changes. Prevents flooding the log while capturing every transition."""
    try:
        tracker = brain.setdefault("gate_event_last_state", {})
        prev = tracker.get(gate_name)
        if prev == state:
            return
        tracker[gate_name] = state
        record = {
            "gate": gate_name,
            "from_state": prev,
            "to_state": state,
        }
        if payload:
            record.update(payload)
        append_review_report("gate_event", record)
    except Exception as exc:
        log(f"gate_event emit failed: {exc}")


def maybe_emit_thesis_trajectory(position, thesis: dict[str, Any], price: float, period_seconds: float = 120.0):
    """Per-position periodic trajectory snapshot for offline tuning. No behavior change."""
    try:
        if not getattr(position, "is_open", False) or not getattr(position, "entry", None):
            return
        key = f"{getattr(position, 'side', '')}_{getattr(position, 'opened_at', '')}"
        tracker = brain.setdefault("thesis_trajectory_last_emit", {})
        now_ts = time.time()
        last_ts = float(tracker.get(key, 0.0) or 0.0)
        if now_ts - last_ts < period_seconds:
            return
        tracker[key] = now_ts
        close_alignment = compute_close_alignment(position, thesis, price)
        fee_floor = max(estimate_round_trip_fee_from_position(position), 1.0)
        gross_pnl = position.unrealized_pnl(price)
        signal_ctx = get_signal_context()
        append_review_report(
            "thesis_trajectory",
            {
                "side": position.side,
                "policy": position.policy,
                "intent": position.intent,
                "mode": position.mode,
                "age_minutes": round(position.age_minutes, 2),
                "price": round(price, 2),
                "entry": round(position.entry or 0.0, 2),
                "thesis_score": round(float(thesis.get("score", 0.0) or 0.0), 4),
                "thesis_intact": bool(thesis.get("intact", False)),
                "add_ready": bool(thesis.get("add_ready", False)),
                "fee_ratio": round(float(thesis.get("fee_ratio", 0.0) or 0.0), 4),
                "gross_pnl": round(gross_pnl, 2),
                "fee_floor": round(fee_floor, 2),
                "max_favorable_bps": round(float(thesis.get("max_favorable_bps", 0.0) or 0.0), 2),
                "max_adverse_bps": round(float(thesis.get("max_adverse_bps", 0.0) or 0.0), 2),
                "close_alignment": round(float(close_alignment.get("score", 0.0) or 0.0), 4),
                "regime": brain.get("market_regime", {}).get("regime", "unknown"),
                "at_support": bool(signal_ctx.get("at_support", False)),
                "at_resistance": bool(signal_ctx.get("at_resistance", False)),
                "room_to_support_bps": round(float(signal_ctx.get("room_to_support_bps", 0.0) or 0.0), 2),
                "room_to_resistance_bps": round(float(signal_ctx.get("room_to_resistance_bps", 0.0) or 0.0), 2),
                "sl_price": getattr(position, "sl_price", None),
                "tp_price": getattr(position, "tp_price", None),
            },
        )
    except Exception as exc:
        log(f"thesis_trajectory emit failed: {exc}")


def maybe_emit_stuck_position_report(position: PositionState, thesis: dict[str, Any], price: float) -> None:
    """Report-only stuck detector; does not close, reduce, add, or bypass exit gates."""
    try:
        if not position.is_open:
            return
        age = float(position.age_minutes)
        mfe = float(thesis.get("mfe_bps", 0.0) or 0.0)
        mae = float(thesis.get("mae_bps", 0.0) or 0.0)
        no_progress = float(thesis.get("no_progress_penalty", 0.0) or 0.0)
        fee_ratio = float(thesis.get("fee_ratio", 0.0) or 0.0)
        thesis_score = float(thesis.get("score", 0.0) or 0.0)
        if not (
            age >= STUCK_REPORT_MIN_AGE_MINUTES
            and mfe <= STUCK_REPORT_MAX_MFE_BPS
            and mae >= STUCK_REPORT_MIN_MAE_BPS
            and no_progress >= STUCK_REPORT_MIN_NO_PROGRESS
            and fee_ratio <= 0.10
            and thesis_score <= -0.10
        ):
            return
        key = f"{position.side}_{position.opened_at}_{int(age // 5)}"
        last_key = brain.get("last_stuck_position_report_key")
        if last_key == key:
            return
        brain["last_stuck_position_report_key"] = key
        close_alignment = compute_close_alignment(position, thesis, price)
        append_review_report(
            "stuck_position_observation",
            {
                "side": position.side,
                "policy": position.policy,
                "intent": position.intent,
                "mode": position.mode,
                "age_minutes": round(age, 2),
                "price": round(price, 2),
                "entry": round(float(position.entry or 0.0), 2),
                "gross_pnl": round(position.unrealized_pnl(price), 2),
                "fee_ratio": round(fee_ratio, 4),
                "thesis_score": round(thesis_score, 4),
                "mfe_bps": round(mfe, 2),
                "mae_bps": round(mae, 2),
                "no_progress_penalty": round(no_progress, 4),
                "close_alignment": round(float(close_alignment.get("score", 0.0) or 0.0), 4),
                "trailing_min_since_open": round(float(position.trailing_min_since_open or 0.0), 2),
                "trailing_max_since_min": round(float(position.trailing_max_since_min or 0.0), 2),
                "trailing_max_since_open": round(float(position.trailing_max_since_open or 0.0), 2),
                "trailing_min_since_max": round(float(position.trailing_min_since_max or 0.0), 2),
                "would_reduce": False,
                "note": "report_only_unstuck_candidate",
            },
        )
        log(
            f"🧷 Stuck observation recorded | side={position.side} age={age:.1f}m "
            f"mfe={mfe:.1f} mae={mae:.1f} thesis={thesis_score:+.2f}"
        )
    except Exception as exc:
        log(f"stuck_position_observation emit failed: {exc}")


def persist_open_position_plan(position: PositionState):
    if not position.is_open:
        brain["position"] = {"is_open": False}
        return

    brain["position"] = {
        "is_open": True,
        "side": position.side,
        "entry": position.entry,
        "qty": position.qty,
        "leverage": position.leverage,
        "sl_price": position.sl_price,
        "tp_price": position.tp_price,
        "trail_buffer_pct": position.trail_buffer_pct,
        "opened_at": position.opened_at.isoformat() if position.opened_at else None,
        "max_hold_minutes": position.max_hold_minutes,
        "intent": position.intent,
        "confidence": position.confidence,
        "mode": position.mode,
        "policy": position.policy,
        "add_count": position.add_count,
        "original_qty": position.original_qty,
        "scale_out_count": position.scale_out_count,
        "last_scale_action_at": position.last_scale_action_at.isoformat() if position.last_scale_action_at else None,
        "exchange_order_id": position.exchange_order_id,
        "initial_margin": position.initial_margin,
        "running_margin": position.running_margin,
        "total_pl": position.total_pl,
        "last_reason": position.last_reason,
        "entry_market_quality": position.entry_market_quality,
        "entry_momentum": position.entry_momentum,
        "entry_imbalance": position.entry_imbalance,
        "entry_momentum_persistence": position.entry_momentum_persistence,
        "entry_imbalance_persistence": position.entry_imbalance_persistence,
        "best_price": position.best_price,
        "worst_price": position.worst_price,
        "trailing_min_since_open": position.trailing_min_since_open,
        "trailing_max_since_min": position.trailing_max_since_min,
        "trailing_max_since_open": position.trailing_max_since_open,
        "trailing_min_since_max": position.trailing_min_since_max,
        "max_unrealized_pnl": position.max_unrealized_pnl,
        "min_unrealized_pnl": position.min_unrealized_pnl,
        "time_to_mfe_minutes": position.time_to_mfe_minutes,
        "time_to_mae_minutes": position.time_to_mae_minutes,
        "last_thesis_score": position.last_thesis_score,
        "last_add_ready": position.last_add_ready,
        "entry_expected_edge": position.entry_expected_edge,
        "entry_predictive_setup_score": position.entry_predictive_setup_score,
        "entry_predictive_setup_summary": position.entry_predictive_setup_summary,
        "entry_chop_learner_lane_active": bool(position.entry_chop_learner_lane_active),
        "entry_nearest_support": position.entry_nearest_support,
        "entry_nearest_resistance": position.entry_nearest_resistance,
        "entry_room_to_target_bps": position.entry_room_to_target_bps,
        "entry_level_alignment": position.entry_level_alignment,
        "entry_level_summary": position.entry_level_summary,
        "entry_feature_health_summary": position.entry_feature_health_summary,
        "entry_tag": position.entry_tag,
        "exit_tag": position.exit_tag,
        "signal_price": position.signal_price,
        "evidence_valid": position.evidence_valid,
        "evidence_reason": position.evidence_reason,
        "roi_schedule_reason": position.roi_schedule_reason,
    }


def clear_persisted_position_plan(reason: str = ""):
    brain["position"] = {
        "is_open": False,
        "last_reason": reason,
        "closed_at": datetime.now().isoformat(),
    }


def _safe_create_task(coro):
    """Create async task with error logging to prevent silent failures"""
    task = asyncio.create_task(coro)
    task.add_done_callback(
        lambda t: log(f"⚠️ Background task failed: {t.exception()}") if t.exception() else None
    )
    return task


def safe_serialize(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, deque):
        return [safe_serialize(x) for x in obj]
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [safe_serialize(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): safe_serialize(v) for k, v in obj.items()}
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return str(obj)


def initialize_brain_deques():
    for key, maxlen in (
        ("momentum_history", 30),
        ("imbalance_history", 30),
        ("spread_history", 30),
        ("funding_history", 20),
        ("funding_rate_samples", 12),
        ("regime_vol_history", 30),
        ("confidence_bias_history", 30),
    ):
        if not isinstance(brain.get(key), deque):
            brain[key] = deque(brain.get(key, []), maxlen=maxlen)
    brain.setdefault("daily_realized", [])
    brain.setdefault("processed_trade_ids", [])
    brain.setdefault("leaderboard_history", [])
    brain.setdefault("past_ai_decisions", [])
    brain.setdefault("trade_lessons", [])
    brain.setdefault("meta_lessons", [])
    brain.setdefault("ai_reviews", [])
    brain.setdefault("ai_adjustments", [])
    brain.setdefault("adds", [])
    brain.setdefault("position_events", [])
    brain.setdefault("risk_history", [])
    brain.setdefault("trade_timestamps", [])
    brain.setdefault("feature_health", {})
    brain.setdefault("level_map", {})
    brain.setdefault("edge_calibration", {})
    brain.setdefault("winner_fade_stats", {})
    brain.setdefault("dry_run_entry_report", {})
    brain.setdefault("shadow_report", {})
    brain.setdefault(
        "level_thresholds",
        {
            "min_room_bps": LEVEL_MIN_ROOM_BPS,
            "breakout_min_room_bps": LEVEL_BREAKOUT_MIN_ROOM_BPS,
            "breakout_long_shadow_ok": False,
            "breakout_short_shadow_ok": False,
            "squeeze_bracket_trigger_ratio": LEVEL_SQUEEZE_BRACKET_TRIGGER_RATIO,
            "squeeze_room_fraction": LEVEL_SQUEEZE_ROOM_FRACTION,
            "squeeze_breakout_fraction": LEVEL_SQUEEZE_BREAKOUT_FRACTION,
            "last_reason": "initial defaults",
            "history": [],
        },
    )
    brain.setdefault(
        "exploration",
        {
            "last_policy": None,
            "last_explore_at": 0.0,
            "last_score": 0.0,
            "mix_rate": EXPLORATION_BASE_RATE,
            "policies": {},
            "recent": [],
        },
    )
    brain.setdefault(
        "exploration_thresholds",
        {
            "mix_bias": 0.0,
            "min_score": 0.48,
            "min_edge": 0.16,
            "confidence_floor": EXPLORATION_MIN_CONFIDENCE,
            "cooldown_seconds": EXPLORATION_COOLDOWN_SECONDS,
            "risk_floor": EXPLORATION_RISK_FLOOR,
            "risk_ceiling": EXPLORATION_RISK_CEIL,
            "allocation_caps": {
                "qty_multiplier_min": 0.60,
                "qty_multiplier_max": 1.00,
                "risk_multiplier_min": 0.75,
                "risk_multiplier_max": 1.00,
                "last_reason": "initial conservative allocation caps",
            },
            "policy_fit_adjustments": {},
            "lane_stats": {},
            "top_lane": {},
            "last_reason": "initial defaults",
            "history": [],
        },
    )
    exploration = brain["exploration"]
    exploration.setdefault("last_policy", None)
    exploration.setdefault("last_explore_at", 0.0)
    exploration.setdefault("last_score", 0.0)
    exploration.setdefault("mix_rate", EXPLORATION_BASE_RATE)
    exploration.setdefault("policies", {})
    exploration.setdefault("recent", [])
    brain.setdefault(
        "oracle_replay",
        {
            "last_run_at": None,
            "last_status": "idle",
            "points": 0,
            "regime_stats": {},
            "regime_weights": {},
            "regime_scores": {},
            "regime_context": {},
        },
    )

    for policy in (
        "mean_revert_micro",
        "mean_revert_reclaim",
        "mean_revert_imbalance_fade",
        "breakout_probe",
        "momentum_follow",
        "orderbook_imbalance_follow",
        "quick_scalp",
    ):
        exploration["policies"].setdefault(
            policy,
            {
                "trades": 0,
                "wins": 0,
                "pnl": 0.0,
                "avg_pnl": 0.0,
                "score": 0.0,
                "last_used_at": None,
                "last_regime": None,
                "fee_clear_rate": 0.0,
                "avg_peak_fee_multiple": 0.0,
                "avg_time_to_mfe_minutes": 0.0,
            },
        )


def parse_iso_dt(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def avg_or_zero(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _running_avg(old_avg: float, old_n: int, new_val: float) -> float:
    """Incremental running average: (old_avg * old_n + new_val) / (old_n + 1)."""
    return (float(old_avg or 0.0) * old_n + float(new_val or 0.0)) / max(old_n + 1, 1)


def get_session_context(now_utc: Optional[datetime] = None) -> dict[str, str]:
    now_utc = now_utc or datetime.now(timezone.utc)
    hour = now_utc.hour
    if 0 <= hour < 6:
        bucket = "asia"
        bias = "chop"
    elif 6 <= hour < 13:
        bucket = "london"
        bias = "build"
    elif 13 <= hour < 17:
        bucket = "ny_open"
        bias = "trend"
    elif 17 <= hour < 22:
        bucket = "ny_late"
        bias = "follow_through"
    else:
        bucket = "rollover"
        bias = "chop"
    return {"session_bucket": bucket, "session_bias": bias}


def compute_multi_timeframe_momentum() -> dict[str, Any]:
    prices = list(PRICE_WINDOW)
    if len(prices) < 8:
        return {
            "momentum_1m": 0.0,
            "momentum_5m": 0.0,
            "momentum_15m": 0.0,
            "mtf_alignment": "mixed",
        }

    def lookback_move(lookback_ticks: int) -> float:
        if len(prices) <= lookback_ticks:
            return 0.0
        base = float(prices[-lookback_ticks - 1])
        last = float(prices[-1])
        if base <= 0:
            return 0.0
        return (last - base) / base

    m1 = lookback_move(20)
    m5 = lookback_move(100)
    m15 = lookback_move(299)

    signs = []
    for value in (m1, m5, m15):
        if value > 0.0004:
            signs.append(1)
        elif value < -0.0004:
            signs.append(-1)
        else:
            signs.append(0)

    if all(sign >= 0 for sign in signs) and any(sign > 0 for sign in signs):
        alignment = "bullish"
    elif all(sign <= 0 for sign in signs) and any(sign < 0 for sign in signs):
        alignment = "bearish"
    else:
        alignment = "mixed"

    return {
        "momentum_1m": round(m1, 6),
        "momentum_5m": round(m5, 6),
        "momentum_15m": round(m15, 6),
        "mtf_alignment": alignment,
    }


def compute_volatility_expansion() -> dict[str, float | str]:
    prices = np.array(PRICE_WINDOW, dtype=float)
    if len(prices) < 40:
        return {"atr_pct": 0.0, "atr_baseline_pct": 0.0, "volatility_expansion": 1.0, "volatility_state": "normal"}

    abs_returns = np.abs(np.diff(prices) / prices[:-1])
    atr_pct = float(np.mean(abs_returns[-20:])) if len(abs_returns) >= 20 else float(np.mean(abs_returns))
    if len(abs_returns) >= 30:
        rolling = [float(np.mean(abs_returns[idx - 20:idx])) for idx in range(20, len(abs_returns) + 1)]
        atr_baseline_pct = avg_or_zero(rolling[-10:]) if rolling else atr_pct
    else:
        atr_baseline_pct = float(np.mean(abs_returns))

    expansion = atr_pct / max(atr_baseline_pct, 1e-9)
    state = "normal"
    if expansion >= 1.35:
        state = "expanded"
    elif expansion <= 0.80:
        state = "compressed"
    return {
        "atr_pct": round(atr_pct, 6),
        "atr_baseline_pct": round(atr_baseline_pct, 6),
        "volatility_expansion": round(expansion, 3),
        "volatility_state": state,
    }


def compute_external_market_context() -> dict[str, Any]:
    external = brain.get("external_market", {}) or {}
    bitget = external.get("bitget", {}) or {}
    binance = external.get("binance", {}) or {}
    deribit = external.get("deribit", {}) or {}
    bitget_status = str(bitget.get("status", "missing") or "missing")
    binance_status = str(binance.get("status", "missing") or "missing")
    deribit_status = str(deribit.get("status", "missing") or "missing")

    bitget_open_interest = float(bitget.get("open_interest", 0.0) or 0.0)
    bitget_account_long_ratio = float(bitget.get("account_long_ratio", 0.5) or 0.5)
    bitget_position_long_ratio = float(bitget.get("position_long_ratio", 0.5) or 0.5)
    oi_delta_pct = float(binance.get("oi_delta_pct", 0.0) or 0.0)
    taker_ratio = float(binance.get("taker_ratio", 1.0) or 1.0)
    top_position_ratio = float(binance.get("top_position_ratio", 1.0) or 1.0)
    top_account_ratio = float(binance.get("top_account_ratio", 1.0) or 1.0)
    deribit_funding_1h = float(deribit.get("funding_1h", 0.0) or 0.0)
    deribit_funding_8h = float(deribit.get("funding_8h", 0.0) or 0.0)

    components: dict[str, float] = {}
    source = "none"
    if bitget_status in {"ok", "partial"}:
        source = "bitget"
        components["account_positioning"] = clamp((bitget_account_long_ratio - 0.5) / 0.08, -1.0, 1.0) * 0.10
        components["position_positioning"] = clamp((bitget_position_long_ratio - 0.5) / 0.08, -1.0, 1.0) * 0.10
        components["oi_build"] = 0.0
        components["taker_pressure"] = 0.0
        components["top_positioning"] = 0.0
        components["top_accounts"] = 0.0
    elif binance_status in {"ok", "partial"}:
        source = "binance"
        if oi_delta_pct > 0.5:
            components["oi_build"] = 0.10
        elif oi_delta_pct < -0.5:
            components["oi_build"] = -0.06
        else:
            components["oi_build"] = 0.0

        taker_deviation = taker_ratio - 1.0
        components["taker_pressure"] = clamp(taker_deviation / 0.25, -1.0, 1.0) * 0.12
        components["top_positioning"] = clamp((top_position_ratio - 1.0) / 0.20, -1.0, 1.0) * 0.08
        components["top_accounts"] = clamp((top_account_ratio - 1.0) / 0.20, -1.0, 1.0) * 0.05
        components["account_positioning"] = 0.0
        components["position_positioning"] = 0.0
    else:
        components["oi_build"] = 0.0
        components["taker_pressure"] = 0.0
        components["top_positioning"] = 0.0
        components["top_accounts"] = 0.0
        components["account_positioning"] = 0.0
        components["position_positioning"] = 0.0

    if deribit_status == "ok":
        components["funding_pressure"] = clamp((deribit_funding_1h + deribit_funding_8h * 0.35) / 0.0015, -1.0, 1.0) * 0.08
    else:
        components["funding_pressure"] = 0.0

    raw = sum(components.values())
    if raw >= 0.08:
        bias = "bullish"
    elif raw <= -0.08:
        bias = "bearish"
    else:
        bias = "neutral"

    component_summary = ", ".join(
        f"{name}={value:+.2f}"
        for name, value in sorted(components.items(), key=lambda item: abs(item[1]), reverse=True)
        if abs(value) >= 0.015
    ) or "flat"

    if source != "none" and deribit_status == "ok":
        data_quality = "full"
    elif source != "none" or deribit_status == "ok":
        data_quality = "partial"
    else:
        data_quality = "none"

    return {
        "external_bias": bias,
        "external_conviction": round(clamp(abs(raw), 0.0, 1.0), 4),
        "external_source": source,
        "external_data_quality": data_quality,
        "bitget_status": bitget_status,
        "bitget_open_interest": round(bitget_open_interest, 4),
        "bitget_account_long_ratio": round(bitget_account_long_ratio, 4),
        "bitget_position_long_ratio": round(bitget_position_long_ratio, 4),
        "binance_status": binance_status,
        "deribit_status": deribit_status,
        "binance_oi_delta_pct": round(oi_delta_pct, 4),
        "binance_taker_ratio": round(taker_ratio, 4),
        "binance_top_position_ratio": round(top_position_ratio, 4),
        "binance_top_account_ratio": round(top_account_ratio, 4),
        "deribit_funding_1h": round(deribit_funding_1h, 6),
        "deribit_funding_8h": round(deribit_funding_8h, 6),
        "external_component_summary": component_summary,
    }


def get_market_signal_context() -> dict[str, Any]:
    spread_hist = [float(x) for x in list(brain.get("spread_history", []))[-8:] if isinstance(x, (int, float))]
    funding_samples = [float(x) for x in list(brain.get("funding_rate_samples", []))[-4:] if isinstance(x, (int, float))]
    session_ctx = get_session_context()
    vol_ctx = compute_volatility_expansion()
    mtf_ctx = compute_multi_timeframe_momentum()
    external_ctx = compute_external_market_context()
    feature_health = compute_feature_health(brain.get("market_context", {}) or {}, external_ctx)
    level_map = compute_level_map()

    current_spread = float(brain.get("market_context", {}).get("spread_pct", 0.0) or 0.0)
    spread_avg = avg_or_zero(spread_hist[:-1] if len(spread_hist) > 1 else spread_hist)
    spread_shock = current_spread / max(spread_avg, 1e-6) if current_spread > 0 and spread_avg > 0 else 1.0

    funding_delta = funding_samples[-1] - funding_samples[0] if len(funding_samples) >= 2 else 0.0
    funding_momentum = "rising" if funding_delta > 0.0005 else "falling" if funding_delta < -0.0005 else "stable"
    latest_funding = funding_samples[-1] if funding_samples else float(brain.get("funding_rate_pct", 0.0) or 0.0)
    funding_bias = "neutral"
    if latest_funding >= 0 and funding_delta > 0:
        funding_bias = "short_bias"
    elif latest_funding <= 0 and funding_delta < 0:
        funding_bias = "long_bias"

    _htf = brain.get("htf_bias", {}) or {}
    return {
        "spread_avg_pct": round(spread_avg, 4),
        "spread_shock": round(spread_shock, 3),
        "funding_delta_pct": round(funding_delta, 5),
        "funding_momentum": funding_momentum,
        "funding_bias": funding_bias,
        "htf_bias_score": float(_htf.get("htf_bias_score", 0.0) or 0.0),
        "htf_bias": str(_htf.get("htf_bias", "neutral") or "neutral"),
        **session_ctx,
        **vol_ctx,
        **mtf_ctx,
        **external_ctx,
        **feature_health,
        **level_map,
        **compute_predictive_market_context(),
    }


def compute_predictive_market_context() -> dict[str, Any]:
    signal_features = get_market_path_features()
    market = brain.get("market_context", {}) or {}
    regime_state = brain.get("market_regime", {}) or {}
    regime = str(regime_state.get("regime", "unknown") or "unknown")
    oracle = get_oracle_regime_insight(regime)
    imbalance_hist = [float(x) for x in list(brain.get("imbalance_history", []))[-9:] if isinstance(x, (int, float))]
    funding_hist = [float(x) for x in list(brain.get("funding_history", []))[-6:] if isinstance(x, (int, float))]
    momentum_1m = float(brain.get("momentum", 0.0) or 0.0)
    momentum_5m = float(compute_multi_timeframe_momentum().get("momentum_5m", 0.0) or 0.0)
    momentum_15m = float(compute_multi_timeframe_momentum().get("momentum_15m", 0.0) or 0.0)
    imbalance_recent = avg_or_zero(imbalance_hist[-3:])
    imbalance_prev = avg_or_zero(imbalance_hist[-6:-3]) if len(imbalance_hist) >= 6 else 0.0
    funding_recent = avg_or_zero(funding_hist[-3:])
    funding_prev = avg_or_zero(funding_hist[-6:-3]) if len(funding_hist) >= 6 else 0.0
    funding_velocity = funding_recent - funding_prev
    funding_last = funding_hist[-1] if funding_hist else float(brain.get("funding_rate_pct", 0.0) or 0.0)
    funding_pressure_raw = funding_last * 0.65 + funding_velocity * 0.35
    funding_acceleration = clamp(funding_pressure_raw / 0.0045, -1.0, 1.0)
    orderbook_trend = clamp(
        imbalance_recent * 1.5
        + float(signal_features.get("imbalance_delta", 0.0) or 0.0) / 0.05
        + float(signal_features.get("imbalance_persistence", 0.0) or 0.0) * 0.35,
        -1.0,
        1.0,
    )
    mtf_divergence = clamp((momentum_5m - momentum_15m) / 0.0016, -1.0, 1.0)
    mtf_impulse = clamp((momentum_1m * 0.7 + momentum_5m * 1.1 + momentum_15m * 1.3) / 0.0026, -1.0, 1.0)
    micro_acceleration = clamp(
        float(signal_features.get("momentum_delta", 0.0) or 0.0) / 0.00018
        + float(signal_features.get("imbalance_delta", 0.0) or 0.0) / 0.05
        - float(signal_features.get("spread_delta", 0.0) or 0.0) / 0.004,
        -1.0,
        1.0,
    )
    oracle_bias = str(oracle.get("dominant_bias", "neutral") or "neutral")
    oracle_score = float(oracle.get("score", 0.0) or 0.0)
    oracle_dir = 0.0
    if oracle_bias == "bullish" and oracle_score >= 0.45:
        oracle_dir = min(1.0, oracle_score)
    elif oracle_bias == "bearish" and oracle_score >= 0.45:
        oracle_dir = -min(1.0, oracle_score)
    elif oracle_bias == "bullish" and oracle_score < 0.45:
        # Bullish bias with failed score → longs breaking down = short fade signal
        oracle_dir = -(0.45 - oracle_score) * 1.6
    elif oracle_bias == "bearish" and oracle_score < 0.45:
        # Bearish bias with failed score → shorts breaking down = long fade signal
        oracle_dir = (0.45 - oracle_score) * 1.6
    range_established = bool(market.get("range_established", False))
    range_position = float(market.get("range_position", 0.5) or 0.5)
    range_width_pct = float(market.get("range_width_pct", 0.0) or 0.0)
    volatility_expansion = float(compute_volatility_expansion().get("volatility_expansion", 1.0) or 1.0)
    breakout_energy = clamp(
        mtf_impulse * 0.34
        + orderbook_trend * 0.24
        + micro_acceleration * 0.22
        - funding_acceleration * 0.16
        + oracle_dir * 0.14,
        -1.0,
        1.0,
    )
    range_up_pressure = clamp((range_position - 0.54) / 0.30, -0.25, 0.25) if range_established else 0.0
    range_down_pressure = clamp((0.46 - range_position) / 0.30, -0.25, 0.25) if range_established else 0.0
    vol_break_bonus = clamp((volatility_expansion - 1.0) / 0.30, -0.10, 0.16)
    range_width_bonus = clamp((range_width_pct - get_range_width_min()) * 16.0, -0.06, 0.10) if range_established else -0.04
    upside_break_prob = clamp(
        0.50 + breakout_energy * 0.22 + range_up_pressure + vol_break_bonus + range_width_bonus,
        0.05,
        0.95,
    )
    downside_break_prob = clamp(
        0.50 - breakout_energy * 0.22 + range_down_pressure + vol_break_bonus + range_width_bonus,
        0.05,
        0.95,
    )
    forecast_score = clamp(
        (upside_break_prob - downside_break_prob) * 1.35
        + mtf_divergence * 0.20
        + micro_acceleration * 0.12,
        -1.0,
        1.0,
    )
    if forecast_score >= 0.12:
        next_bias = "bullish"
    elif forecast_score <= -0.12:
        next_bias = "bearish"
    else:
        next_bias = "neutral"
    confidence = clamp(abs(forecast_score) * 0.65 + abs(breakout_energy) * 0.25, 0.0, 1.0)
    summary = (
        f"15-60m bias={next_bias} conf={confidence:.2f} "
        f"up_break={upside_break_prob:.2f} down_break={downside_break_prob:.2f} "
        f"obook_trend={orderbook_trend:+.2f} funding_accel={funding_acceleration:+.2f} "
        f"mtf_div={mtf_divergence:+.2f} micro_accel={micro_acceleration:+.2f}"
    )
    return {
        "predictive_orderbook_trend": round(orderbook_trend, 4),
        "predictive_funding_acceleration": round(funding_acceleration, 4),
        "predictive_mtf_divergence": round(mtf_divergence, 4),
        "predictive_micro_acceleration": round(micro_acceleration, 4),
        "predictive_upside_break_prob": round(upside_break_prob, 4),
        "predictive_downside_break_prob": round(downside_break_prob, 4),
        "predictive_horizon_score": round(forecast_score, 4),
        "predictive_horizon_confidence": round(confidence, 4),
        "predictive_next_15_60_bias": next_bias,
        "predictive_summary": summary,
    }


MARKET_SIGNAL_CONTEXT_KEYS = (
    "spread_avg_pct",
    "spread_shock",
    "funding_delta_pct",
    "funding_momentum",
    "funding_bias",
    "session_bucket",
    "session_bias",
    "atr_pct",
    "atr_baseline_pct",
    "volatility_expansion",
    "volatility_state",
    "momentum_1m",
    "momentum_5m",
    "momentum_15m",
    "mtf_alignment",
    "external_bias",
    "external_conviction",
    "external_source",
    "external_data_quality",
    "bitget_status",
    "bitget_open_interest",
    "bitget_account_long_ratio",
    "bitget_position_long_ratio",
    "binance_status",
    "deribit_status",
    "binance_oi_delta_pct",
    "binance_taker_ratio",
    "binance_top_position_ratio",
    "binance_top_account_ratio",
    "deribit_funding_1h",
    "deribit_funding_8h",
    "external_component_summary",
        "orderbook_live",
        "spread_live",
        "external_live",
        "feature_health_summary",
        "feature_health_source",
        "feature_health_reason",
        "orderbook_bid",
    "orderbook_ask",
    "orderbook_spread_pct",
    "orderbook_imbalance",
    "level_map_ready",
    "nearest_support",
    "nearest_resistance",
    "raw_nearest_support",
    "raw_nearest_resistance",
    "support_distance_bps",
    "resistance_distance_bps",
    "raw_support_distance_bps",
    "raw_resistance_distance_bps",
    "room_to_support_bps",
    "room_to_resistance_bps",
    "at_support",
    "at_resistance",
    "sweep_reclaim_long",
    "sweep_reclaim_short",
    "wyckoff_spring_long",
    "wyckoff_spring_short",
    "level_position",
        "level_alignment",
        "level_summary",
        "swing_support_count",
        "swing_resistance_count",
    "support_valid",
    "resistance_valid",
    "level_cluster_count",
    "broader_structure_direction",
    "broader_structure_action",
    "broader_structure_confidence",
    "broader_structure_summary",
    "range_position",
    "range_width_pct",
    "range_high",
    "range_low",
    "range_mid",
    "range_established",
    "micro_range_established",
    "micro_range_reason",
    "predictive_orderbook_trend",
    "predictive_funding_acceleration",
    "predictive_mtf_divergence",
    "predictive_micro_acceleration",
    "predictive_upside_break_prob",
    "predictive_downside_break_prob",
    "predictive_horizon_score",
    "predictive_horizon_confidence",
    "predictive_next_15_60_bias",
    "predictive_summary",
)


def refresh_market_signal_context() -> dict[str, Any]:
    signal_ctx = get_market_signal_context()
    market_context = brain.setdefault("market_context", {})
    if not isinstance(market_context, dict):
        market_context = {}
        brain["market_context"] = market_context
    market_context.update(signal_ctx)
    structure = compute_broader_structure_context(signal_ctx)
    signal_ctx.update(
        {
            "broader_structure_direction": structure["direction"],
            "broader_structure_action": structure["action"],
            "broader_structure_confidence": structure["confidence"],
            "broader_structure_summary": structure["summary"],
        }
    )
    market_context.update(signal_ctx)
    return signal_ctx


def get_signal_context() -> dict[str, Any]:
    market_context = brain.get("market_context", {})
    if isinstance(market_context, dict) and all(key in market_context for key in MARKET_SIGNAL_CONTEXT_KEYS):
        return {key: market_context.get(key) for key in MARKET_SIGNAL_CONTEXT_KEYS}
    return refresh_market_signal_context()


def compute_broader_structure_context(signal_ctx: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    ctx = signal_ctx or get_signal_context()
    regime_state = brain.get("market_regime", {}) or {}
    regime = str(regime_state.get("regime", "unknown") or "unknown")
    regime_bias = str(regime_state.get("bias", "neutral") or "neutral")
    price_action = str(brain.get("price_action_summary", "neutral") or "neutral")
    oracle = get_oracle_regime_insight(regime)
    mtf = str(ctx.get("mtf_alignment", "mixed") or "mixed")
    htf_bias_score = float(ctx.get("htf_bias_score", 0.0) or 0.0)
    external_bias = str(ctx.get("external_bias", "neutral") or "neutral")
    external_conviction = float(ctx.get("external_conviction", 0.0) or 0.0)
    volx = float(ctx.get("volatility_expansion", 1.0) or 1.0)
    at_support = bool(ctx.get("at_support", False) or ctx.get("sweep_reclaim_long", False))
    at_resistance = bool(ctx.get("at_resistance", False) or ctx.get("sweep_reclaim_short", False))
    room_up = float(ctx.get("room_to_resistance_bps", 0.0) or 0.0)
    room_down = float(ctx.get("room_to_support_bps", 0.0) or 0.0)
    resistance_valid = bool(ctx.get("resistance_valid", False))
    support_valid = bool(ctx.get("support_valid", False))
    range_established = bool(ctx.get("range_established", False))
    range_position = float(ctx.get("range_position", 0.5) or 0.5)

    long_score = 0.0
    short_score = 0.0
    reasons: list[str] = []
    min_room = get_level_min_room_bps()
    if at_support and (room_up >= min_room or not resistance_valid):
        long_score += 0.28
        reasons.append("long_level_edge")
    if at_resistance and (room_down >= min_room or not support_valid):
        short_score += 0.28
        reasons.append("short_level_edge")
    if range_established:
        if range_position <= get_range_long_max():
            long_score += 0.18
            reasons.append(f"range_low={range_position:.2f}")
        elif range_position >= get_range_short_min():
            short_score += 0.18
            reasons.append(f"range_high={range_position:.2f}")
    if price_action in {"higher_highs", "bullish_breakout"}:
        long_score += 0.16
        reasons.append(price_action)
    elif price_action == "bearish_breakdown":
        short_score += 0.16
        reasons.append(price_action)
    if regime_bias == "bullish":
        long_score += 0.12
    elif regime_bias == "bearish":
        short_score += 0.12
    if mtf == "bullish":
        long_score += 0.12
    elif mtf == "bearish":
        short_score += 0.12
    oracle_bias = str(oracle.get("dominant_bias", "neutral") or "neutral")
    oracle_score = float(oracle.get("score", 0.0) or 0.0)
    if oracle_bias == "bullish" and oracle_score >= 0.45:
        long_score += min(0.12, oracle_score * 0.12)
    elif oracle_bias == "bearish" and oracle_score >= 0.45:
        short_score += min(0.12, oracle_score * 0.12)
    elif oracle_bias == "bullish" and oracle_score < 0.45:
        # Bullish setups breaking down → fade: short signal
        short_score += min(0.10, (0.45 - oracle_score) * 0.20)
    elif oracle_bias == "bearish" and oracle_score < 0.45:
        # Bearish setups breaking down → fade: long signal
        long_score += min(0.10, (0.45 - oracle_score) * 0.20)
    if external_bias == "bullish":
        long_score += min(0.08, external_conviction * 0.20)
    elif external_bias == "bearish":
        short_score += min(0.08, external_conviction * 0.20)
    if not resistance_valid and price_action in {"higher_highs", "bullish_breakout"} and volx >= 1.05:
        long_score += 0.12
        reasons.append("open_air_up")
    if not support_valid and price_action == "bearish_breakdown" and volx >= 1.05:
        short_score += 0.12
        reasons.append("open_air_down")
    if htf_bias_score > 0.40:
        long_score += 0.08
        reasons.append(f"htf_bull={htf_bias_score:+.2f}")
    elif htf_bias_score < -0.40:
        short_score += 0.08
        reasons.append(f"htf_bear={htf_bias_score:+.2f}")
    else:
        _htf = brain.get("htf_bias", {}) or {}
        _h4 = float(_htf.get("htf_4h_score", 0.0) or 0.0)
        _h12 = float(_htf.get("htf_12h_score", 0.0) or 0.0)
        if _h4 < -0.10 and _h12 < -0.25:
            short_score += 0.08
            reasons.append(f"htf_intraday_bear=4h{_h4:+.2f}/12h{_h12:+.2f}")
        elif _h4 > 0.10 and _h12 > 0.25:
            long_score += 0.08
            reasons.append(f"htf_intraday_bull=4h{_h4:+.2f}/12h{_h12:+.2f}")

    net = long_score - short_score
    direction = "long" if net >= 0.12 else "short" if net <= -0.12 else "neutral"
    if direction == "long":
        action = "breakout_long" if not resistance_valid and price_action in {"higher_highs", "bullish_breakout"} else "mean_revert_long" if at_support else "trend_long"
    elif direction == "short":
        action = "breakout_short" if not support_valid and price_action == "bearish_breakdown" else "mean_revert_short" if at_resistance else "trend_short"
    else:
        action = "wait"
    confidence = clamp(0.45 + abs(net), 0.0, 0.95)
    structure = {
        "direction": direction,
        "action": action,
        "confidence": round(confidence, 4),
        "long_score": round(long_score, 4),
        "short_score": round(short_score, 4),
        "net": round(net, 4),
        "summary": (
            f"{action} conf={confidence:.2f} long={long_score:.2f} short={short_score:.2f} "
            f"regime={regime}/{regime_bias} pa={price_action} mtf={mtf} reasons={','.join(reasons[:4]) or 'balanced'}"
        ),
    }
    brain["broader_structure"] = structure
    if isinstance(brain.get("market_context"), dict):
        brain["market_context"]["broader_structure_direction"] = structure["direction"]
        brain["market_context"]["broader_structure_action"] = structure["action"]
        brain["market_context"]["broader_structure_confidence"] = structure["confidence"]
        brain["market_context"]["broader_structure_summary"] = structure["summary"]
    return structure


def get_broader_structure_alignment(
    direction: str,
    intent: str,
    structure: Optional[dict[str, Any]] = None,
) -> str:
    """
    Broader structure is a weighted parent view, not a unanimity gate. Use this
    to bias candidate scoring/relief without weakening hard risk or exit gates.
    """
    resolved = structure or brain.get("broader_structure") or {}
    broader_direction = str(resolved.get("direction", "neutral") or "neutral")
    broader_action = str(resolved.get("action", "wait") or "wait")
    if broader_direction not in {"long", "short"} or direction not in {"long", "short"}:
        return "neutral"
    if direction != broader_direction:
        return "conflict"
    if intent == "mean_revert" and broader_action in {"mean_revert_long", "mean_revert_short"}:
        return "aligned"
    if intent in {"breakout", "trend_follow"} and broader_action in {
        "breakout_long",
        "breakout_short",
        "trend_long",
        "trend_short",
    }:
        return "aligned"
    return "supportive"


def get_strategic_aggression_context() -> dict[str, Any]:
    """
    Strategic posture for leaderboard/account-growth mode. It biases opportunity
    selection toward action when the parent structure is strong, while hard risk,
    cooldown, sizing, and exit gates remain authoritative.
    """
    structure = brain.get("broader_structure") or {}
    confidence = float(structure.get("confidence", 0.0) or 0.0)
    action = str(structure.get("action", "wait") or "wait")
    risk_mode = str(brain.get("risk_mode", "normal") or "normal")
    daily_pnl = float(brain.get("daily_pnl", 0.0) or 0.0)
    risk_snapshot = get_recent_risk_snapshot()
    recent_loss_ratio = float(risk_snapshot.get("recent_loss_ratio", 0.0) or 0.0)
    daily_loss_ratio = float(risk_snapshot.get("daily_loss_ratio", 0.0) or 0.0)
    cooldown_active = bool(float(brain.get("cooldown_until", 0.0) or 0.0) > time.time())
    flat_minutes = get_flat_duration_minutes()
    gate_state = brain.get("last_entry_gate_state", {}) or {}
    align_score = float((gate_state.get("chop_alignment") or {}).get("score", 0.0) or 0.0)
    setup_edge = float(gate_state.get("quality", 0.0) or 0.0)
    regime = str((brain.get("market_regime", {}) or {}).get("regime", "unknown") or "unknown")
    persisted_position = brain.get("position", {}) or {}
    open_position_attack_sticky = bool(
        regime == "squeeze"
        and bool(persisted_position.get("is_open"))
        and float(persisted_position.get("last_thesis_score", 0.0) or 0.0) > 0.05
    )
    structure_ready = action != "wait" and confidence >= 0.62
    squeeze_attack_candidate = bool(
        regime == "squeeze"
        and (
            align_score > 0.55
            or setup_edge > 0.45
            or (flat_minutes >= 20.0 and align_score > 0.30)
            or open_position_attack_sticky
        )
    )
    flat_attack_override = bool(
        not cooldown_active
        and regime == "squeeze"
        and flat_minutes >= 20.0
        and (setup_edge >= 0.45 or align_score >= 0.55 or (flat_minutes >= 20.0 and align_score > 0.30))
    )
    attack = bool(
        not cooldown_active
        and (structure_ready or squeeze_attack_candidate or flat_attack_override or open_position_attack_sticky)
        and (
            ((risk_mode != "protection")
             and (
                 risk_mode == "normal"
                 or regime == "squeeze"
                 or squeeze_attack_candidate
                 or open_position_attack_sticky
             )
             and recent_loss_ratio < RISK_PROTECTION_RECENT_LOSS_RATIO
             and daily_loss_ratio < RISK_PROTECTION_DAILY_LOSS_RATIO)
            or flat_attack_override
            or open_position_attack_sticky
        )
    )
    return {
        "mode": "attack" if attack else "protect" if risk_mode == "protection" else "observe",
        "default_aggressive": attack,
        "structure_action": action,
        "structure_confidence": round(confidence, 4),
        "daily_pnl": round(daily_pnl, 2),
        "recent_loss_ratio": round(recent_loss_ratio, 4),
        "daily_loss_ratio": round(daily_loss_ratio, 4),
        "reason": (
            f"structure={action}/{confidence:.2f} daily={daily_pnl:+.0f} "
            f"risk={risk_mode} recent_loss={recent_loss_ratio:.3f} daily_loss={daily_loss_ratio:.3f} "
            f"flat={flat_minutes:.1f}m edge={setup_edge:.2f} align={align_score:.2f} "
            f"sticky_open={open_position_attack_sticky}"
        ),
    }


def compute_parent_allocation_plan(
    signal: EntrySignal,
    adaptive: dict[str, Any],
    usable: float,
) -> dict[str, Any]:
    """
    Holistic parent allocation view. It blends broader structure, replay/edge,
    level room, risk mode, margin, and drift state into sizing intent while the
    existing tuner, risk gate, margin caps, and exchange leverage check remain
    the hard safety rails.
    """
    structure = brain.get("broader_structure") or {}
    strategic = get_strategic_aggression_context()
    gate_state = dict(getattr(signal, "entry_gate_state_snapshot", None) or brain.get("last_entry_gate_state", {}) or {})
    allocation_caps = (get_exploration_thresholds().get("allocation_caps", {}) or {})

    confidence = float(structure.get("confidence", 0.0) or 0.0)
    alignment = get_broader_structure_alignment(signal.direction, signal.intent, structure)
    quality = float(gate_state.get("quality", brain.get("market_quality_score", 0.0)) or 0.0)
    edge = max(
        float(getattr(signal, "expected_edge", 0.0) or 0.0),
        float(gate_state.get("selected_expected_edge", 0.0) or 0.0),
    )
    predictive = max(
        float(getattr(signal, "predictive_setup_score", 0.0) or 0.0),
        float(gate_state.get("selected_predictive_setup_score", 0.0) or 0.0),
    )
    oracle = float((gate_state.get("oracle_insight") or {}).get("score", 0.0) or 0.0)
    level_room = max(
        float(gate_state.get("level_room_bps", 0.0) or 0.0),
        float(gate_state.get("room_bps", 0.0) or 0.0),
    )
    instability = float((brain.get("regime_transition", {}) or {}).get("instability", 0.0) or 0.0)
    risk_mode = str(brain.get("risk_mode", "normal") or "normal")
    regime = str(adaptive.get("regime") or brain.get("market_regime", {}).get("regime", "unknown") or "unknown")
    same_shadow_proof = summarize_shadow_direction_proof(regime, signal.direction)
    opposite_shadow_proof = summarize_shadow_direction_proof(
        regime,
        "short" if signal.direction == "long" else "long",
        policies={"breakout_probe"},
    )
    live_drag = summarize_live_direction_drag(regime, signal.policy, signal.direction)

    score = 0.0
    if alignment == "aligned":
        score += 0.22
    elif alignment == "supportive":
        score += 0.10
    elif alignment == "conflict":
        score -= 0.35
    if strategic.get("mode") == "attack":
        score += 0.14
    elif strategic.get("mode") == "protect":
        score -= 0.25
    score += clamp((confidence - 0.55) * 0.75, -0.15, 0.18)
    score += clamp((quality - 0.45) * 0.40, -0.10, 0.12)
    score += clamp((edge - 0.16) * 0.55, -0.10, 0.18)
    score += clamp((predictive - 0.55) * 0.30, -0.06, 0.10)
    score += clamp(oracle * 0.08, -0.08, 0.08)
    if level_room >= LEVEL_MIN_ROOM_BPS:
        score += 0.04
    if same_shadow_proof.get("proven"):
        score += 0.10
    if opposite_shadow_proof.get("proven"):
        score -= 0.14
    if live_drag.get("dragging"):
        score -= 0.10
    score -= clamp(instability * 0.30, 0.0, 0.24)
    if risk_mode == "caution":
        score -= 0.12
    elif risk_mode == "protection":
        score -= 0.35
    if usable < SMALL_ACCOUNT_DYNAMIC_MIN_SATS:
        score -= 0.08

    qty_mult = 1.0
    risk_mult = 1.0
    posture = "neutral"

    if score >= 0.45 and alignment in {"aligned", "supportive"} and risk_mode == "normal":
        posture = "press"
        qty_mult = 1.12
        risk_mult = 1.04
    elif score <= -0.20 or alignment == "conflict" or instability >= TUNER_DRIFT_FREEZE_INSTABILITY:
        posture = "trim"
        qty_mult = 0.75
        risk_mult = 0.85

    qty_cap = min(float(allocation_caps.get("qty_multiplier_max", 1.0) or 1.0), 1.25)
    risk_cap = min(float(allocation_caps.get("risk_multiplier_max", 1.0) or 1.0), 1.10)
    qty_floor = max(float(allocation_caps.get("qty_multiplier_min", 0.60) or 0.60), 0.60)
    risk_floor = max(float(allocation_caps.get("risk_multiplier_min", 0.75) or 0.75), 0.70)
    qty_floor = min(qty_floor, qty_cap)
    risk_floor = min(risk_floor, risk_cap)
    qty_mult = clamp(qty_mult, qty_floor, qty_cap)
    risk_mult = clamp(risk_mult, risk_floor, risk_cap)
    return {
        "posture": posture,
        "score": round(score, 4),
        "alignment": alignment,
        "qty_multiplier": round(qty_mult, 4),
        "risk_multiplier": round(risk_mult, 4),
        "reason": (
            f"parent_{posture} score={score:+.2f} align={alignment} "
            f"structure={structure.get('action', 'wait')}/{confidence:.2f} "
            f"q={quality:.2f} edge={edge:.2f} pred={predictive:.2f} "
            f"oracle={oracle:+.2f} room={level_room:.0f} "
            f"shadow_same={same_shadow_proof.get('proven')} "
            f"shadow_opp={opposite_shadow_proof.get('proven')} "
            f"live_drag={live_drag.get('dragging')} instab={instability:.2f}"
        ),
    }


def apply_parent_allocation_plan(signal: EntrySignal, adaptive: dict[str, Any], usable: float) -> None:
    plan = compute_parent_allocation_plan(signal, adaptive, usable)
    risk_mult = float(plan.get("risk_multiplier", 1.0) or 1.0)
    signal.risk_per_trade = min(
        float(signal.risk_per_trade or RISK_PER_TRADE) * risk_mult,
        float(adaptive.get("risk_per_trade", RISK_PER_TRADE) or RISK_PER_TRADE),
        MAX_RISK_PER_TRADE,
    )
    signal.base_risk_per_trade = signal.risk_per_trade
    signal.effective_risk_per_trade = signal.risk_per_trade
    signal.parent_qty_multiplier = float(plan.get("qty_multiplier", 1.0) or 1.0)
    signal.parent_risk_multiplier = risk_mult
    signal.parent_leverage_target = int(signal.leverage or DEFAULT_LEVERAGE)
    signal.parent_allocation_reason = str(plan.get("reason", "n/a"))
    if abs(signal.parent_qty_multiplier - 1.0) > 0.01 or abs(risk_mult - 1.0) > 0.01:
        log(
            f"🧭 Parent allocation | qtyx={signal.parent_qty_multiplier:.2f} riskx={risk_mult:.2f} | "
            f"{signal.parent_allocation_reason}"
        )


def compute_signal_persistence(values: list[float], neutral_band: float) -> float:
    if not values:
        return 0.0
    scored = []
    for value in values:
        if value > neutral_band:
            scored.append(1.0)
        elif value < -neutral_band:
            scored.append(-1.0)
        else:
            scored.append(0.0)
    non_neutral = [value for value in scored if value != 0.0]
    if not non_neutral:
        return 0.0
    dominant = 1.0 if sum(non_neutral) >= 0 else -1.0
    agreement = sum(1 for value in non_neutral if value == dominant) / max(len(non_neutral), 1)
    density = len(non_neutral) / max(len(scored), 1)
    return round(dominant * agreement * density, 4)


def get_market_path_features() -> dict[str, float]:
    momentum_hist = [float(value) for value in list(brain.get("momentum_history", []))[-6:]]
    imbalance_hist = [float(value) for value in list(brain.get("imbalance_history", []))[-6:]]
    spread_hist = [float(value) for value in list(brain.get("spread_history", []))[-6:]]

    momentum_recent = momentum_hist[-3:]
    momentum_prev = momentum_hist[-6:-3]
    imbalance_recent = imbalance_hist[-3:]
    imbalance_prev = imbalance_hist[-6:-3]
    spread_recent = spread_hist[-3:]
    spread_prev = spread_hist[-6:-3]

    momentum_avg = avg_or_zero(momentum_recent)
    imbalance_avg = avg_or_zero(imbalance_recent)
    spread_avg = avg_or_zero(spread_recent)
    momentum_delta = momentum_avg - avg_or_zero(momentum_prev) if momentum_prev else 0.0
    imbalance_delta = imbalance_avg - avg_or_zero(imbalance_prev) if imbalance_prev else 0.0
    spread_delta = spread_avg - avg_or_zero(spread_prev) if spread_prev else 0.0

    return {
        "momentum_avg": round(momentum_avg, 6),
        "momentum_delta": round(momentum_delta, 6),
        "momentum_persistence": compute_signal_persistence(momentum_hist, 0.00008),
        "imbalance_avg": round(imbalance_avg, 6),
        "imbalance_delta": round(imbalance_delta, 6),
        "imbalance_persistence": compute_signal_persistence(imbalance_hist, 0.03),
        "spread_avg": round(spread_avg, 6),
        "spread_delta": round(spread_delta, 6),
        "spread_persistence": compute_signal_persistence(spread_hist, 0.002),
    }


def build_position_learning_snapshot(position: PositionState) -> dict[str, Any]:
    fee_floor = max(estimate_round_trip_fee_from_position(position), 1.0)
    return {
        "entry_momentum": round(float(position.entry_momentum or 0.0), 6),
        "entry_imbalance": round(float(position.entry_imbalance or 0.0), 6),
        "entry_momentum_persistence": round(float(position.entry_momentum_persistence or 0.0), 4),
        "entry_imbalance_persistence": round(float(position.entry_imbalance_persistence or 0.0), 4),
        "max_unrealized_pnl": round(float(position.max_unrealized_pnl or 0.0), 2),
        "min_unrealized_pnl": round(float(position.min_unrealized_pnl or 0.0), 2),
        "max_fee_multiple": round(float(position.max_unrealized_pnl or 0.0) / fee_floor, 3),
        "min_fee_multiple": round(float(position.min_unrealized_pnl or 0.0) / fee_floor, 3),
        "time_to_mfe_minutes": None if position.time_to_mfe_minutes is None else round(float(position.time_to_mfe_minutes), 2),
        "time_to_mae_minutes": None if position.time_to_mae_minutes is None else round(float(position.time_to_mae_minutes), 2),
        "fee_cleared": bool(float(position.max_unrealized_pnl or 0.0) >= fee_floor),
        "entry_nearest_support": round(float(position.entry_nearest_support or 0.0), 2),
        "entry_nearest_resistance": round(float(position.entry_nearest_resistance or 0.0), 2),
        "entry_room_to_target_bps": round(float(position.entry_room_to_target_bps or 0.0), 2),
        "entry_level_alignment": position.entry_level_alignment,
        "entry_level_summary": position.entry_level_summary,
        "entry_feature_health_summary": position.entry_feature_health_summary,
        "entry_tag": position.entry_tag,
        "exit_tag": position.exit_tag,
        "signal_price": round(float(position.signal_price or 0.0), 2),
        "evidence_valid": bool(position.evidence_valid),
        "evidence_reason": position.evidence_reason,
        "roi_schedule_reason": position.roi_schedule_reason,
    }


def maybe_decay_policy_stats(policy_stats: dict[str, Any], now: datetime):
    last_used = parse_iso_dt(policy_stats.get("last_used_at"))
    if not last_used:
        return
    elapsed_hours = max(0.0, (now - last_used).total_seconds() / 3600.0)
    if elapsed_hours < 6.0:
        return
    decay = 0.5 ** (elapsed_hours / max(POLICY_STATS_DECAY_HALF_LIFE_HOURS, 1.0))
    for key in ("pnl", "avg_pnl"):
        policy_stats[key] = float(policy_stats.get(key, 0.0) or 0.0) * decay
    for key in ("fee_clear_rate", "avg_peak_fee_multiple", "avg_time_to_mfe_minutes", "score"):
        policy_stats[key] = round(float(policy_stats.get(key, 0.0) or 0.0) * decay, 4)
    policy_stats["decay_factor"] = round(decay, 4)
    policy_stats["last_decay_at"] = now.isoformat()


def update_winner_fade_stats(position: PositionState, learning_snapshot: dict[str, Any], net_pnl: float):
    stats = brain.setdefault(
        "winner_fade_stats",
        {
            "fee_cleared_trades": 0,
            "faded_to_loss": 0,
            "faded_to_small_win": 0,
            "avg_peak_fee_multiple": 0.0,
            "avg_giveback_fee_multiple": 0.0,
            "last_event": {},
        },
    )
    if not learning_snapshot.get("fee_cleared"):
        return
    peak_fee = float(learning_snapshot.get("max_fee_multiple", 0.0) or 0.0)
    fee_floor = max(estimate_round_trip_fee_from_position(position), 1.0)
    peak_pnl = float(learning_snapshot.get("max_unrealized_pnl", 0.0) or 0.0)
    giveback_fee = max(0.0, (peak_pnl - net_pnl) / fee_floor)
    prior = int(stats.get("fee_cleared_trades", 0) or 0)
    stats["fee_cleared_trades"] = prior + 1
    stats["avg_peak_fee_multiple"] = round(
        _running_avg(float(stats.get("avg_peak_fee_multiple", 0.0) or 0.0), prior, peak_fee),
        4,
    )
    stats["avg_giveback_fee_multiple"] = round(
        _running_avg(float(stats.get("avg_giveback_fee_multiple", 0.0) or 0.0), prior, giveback_fee),
        4,
    )
    if net_pnl <= 0:
        stats["faded_to_loss"] = int(stats.get("faded_to_loss", 0) or 0) + 1
    elif net_pnl < fee_floor:
        stats["faded_to_small_win"] = int(stats.get("faded_to_small_win", 0) or 0) + 1
    stats["last_event"] = {
        "timestamp": datetime.now().isoformat(),
        "policy": position.policy,
        "side": position.side,
        "net_pnl": round(net_pnl, 2),
        "peak_fee_multiple": round(peak_fee, 3),
        "giveback_fee_multiple": round(giveback_fee, 3),
    }
    if net_pnl <= 0:
        log(
            f"⚠️ WINNER FADE | policy={position.policy} peak_fee={peak_fee:.2f} "
            f"giveback_fee={giveback_fee:.2f} net={net_pnl:+.0f}"
        )


def update_policy_learning_stats(policy_stats: dict[str, Any], net_pnl: float, is_win: bool, learning_snapshot: dict[str, Any], now: datetime, regime: str):
    maybe_decay_policy_stats(policy_stats, now)
    policy_stats["trades"] = int(policy_stats.get("trades", 0)) + 1
    policy_stats["pnl"] = float(policy_stats.get("pnl", 0.0) or 0.0) + net_pnl
    if is_win:
        policy_stats["wins"] = int(policy_stats.get("wins", 0)) + 1
    policy_stats["avg_pnl"] = policy_stats["pnl"] / max(policy_stats["trades"], 1)

    prior = int(policy_stats["trades"]) - 1  # always >= 0 since trades was just incremented
    policy_stats["fee_clear_rate"] = round(
        _running_avg(float(policy_stats.get("fee_clear_rate", 0.0) or 0.0), prior,
                     1.0 if learning_snapshot.get("fee_cleared") else 0.0), 4)
    policy_stats["avg_peak_fee_multiple"] = round(
        _running_avg(float(policy_stats.get("avg_peak_fee_multiple", 0.0) or 0.0), prior,
                     float(learning_snapshot.get("max_fee_multiple", 0.0) or 0.0)), 4)

    timed_count = int(policy_stats.get("timed_mfe_count", 0) or 0)
    if learning_snapshot.get("time_to_mfe_minutes") is not None:
        policy_stats["avg_time_to_mfe_minutes"] = round(
            _running_avg(float(policy_stats.get("avg_time_to_mfe_minutes", 0.0) or 0.0), timed_count,
                         float(learning_snapshot.get("time_to_mfe_minutes", 0.0) or 0.0)), 4)
        timed_count += 1
        policy_stats["timed_mfe_count"] = timed_count

    policy_winrate = policy_stats["wins"] / max(policy_stats["trades"], 1)
    policy_stats["score"] = round(
        policy_winrate * 0.45
        + max(-0.35, min(0.35, policy_stats["avg_pnl"] / 2500.0))
        + float(policy_stats.get("fee_clear_rate", 0.0) or 0.0) * 0.12
        + max(-0.08, min(0.12, float(policy_stats.get("avg_peak_fee_multiple", 0.0) or 0.0) / 3.0)),
        4,
    )
    policy_stats["last_used_at"] = now.isoformat()
    policy_stats["last_regime"] = regime


def parse_exchange_dt(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def estimate_round_trip_fee_from_position(position: "PositionState") -> float:
    if not position.entry or position.qty <= 0:
        return 0.0
    # Inverse perpetual: fee in sats = (qty_usd / price_usd) * rate * 2 legs * sats_per_btc
    notional_btc = abs(position.qty / position.entry)
    return notional_btc * FEE_RATE * 2.0 * 100_000_000


def should_block_fee_dominated_ai_close(position: "PositionState", gross_pnl: float) -> bool:
    estimated_fee = estimate_round_trip_fee_from_position(position)
    if estimated_fee <= 0:
        return False
    if abs(gross_pnl) <= estimated_fee * AI_CLOSE_FEE_MULTIPLIER:
        return True
    if gross_pnl < 0 and abs(gross_pnl) < estimated_fee * 1.75:
        return True
    return False


def should_block_fee_dominated_reduce(
    position: "PositionState",
    gross_pnl: float,
    reduce_qty: float,
) -> bool:
    if reduce_qty <= 0 or not position.qty:
        return True

    reduce_ratio = min(reduce_qty / max(position.qty, 1e-9), 1.0)
    estimated_fee = estimate_round_trip_fee_from_position(position) * reduce_ratio
    realized_gross = gross_pnl * reduce_ratio

    if abs(realized_gross) <= estimated_fee * REDUCE_FEE_MULTIPLIER:
        return True

    if realized_gross > -MIN_ABSOLUTE_THESIS_EXIT_PNL and abs(realized_gross) < estimated_fee * 2.0:
        return True

    return False


def extract_signed_quantity(pos: Any) -> tuple[Optional[float], bool]:
    side_hint = str(
        _safe_get(pos, "side")
        or _safe_get(pos, "direction")
        or _safe_get(pos, "position_side")
        or _safe_get(pos, "type")
        or ""
    ).lower().strip()

    for key in ("quantity", "qty", "size", "contracts", "amount", "position_size"):
        val = _safe_get(pos, key)
        if val is None:
            continue
        try:
            qty = float(val)
        except (TypeError, ValueError):
            continue

        if qty > 0 and side_hint in {"short", "sell"}:
            qty = -qty
        elif qty < 0 and side_hint in {"long", "buy"}:
            qty = abs(qty)
        return qty, True

    return None, False


async def set_cross_leverage(client, leverage: int) -> Optional[float]:
    """Set cross leverage using whatever method the installed SDK exposes."""
    cross = getattr(getattr(client, "futures", None), "cross", None)
    if cross is None:
        log("❌ Cross leverage set failed: missing futures.cross client")
        return None

    payload = {"leverage": int(leverage)}
    candidates = ("set_leverage", "update_leverage", "put_leverage")

    for method_name in candidates:
        method = getattr(cross, method_name, None)
        if method is None:
            continue
        try:
            response = await method(payload)
            exchange_lev = _safe_get(response, "leverage")
            if exchange_lev is None and isinstance(response, dict):
                exchange_lev = response.get("leverage")
            if exchange_lev is not None:
                exchange_lev = float(exchange_lev)
            log(
                f"✅ CROSS LEVERAGE SET | requested={leverage} | "
                f"exchange={exchange_lev if exchange_lev is not None else 'unknown'} | method={method_name}"
            )
            return exchange_lev
        except TypeError:
            try:
                response = await method(leverage=payload["leverage"])
                exchange_lev = _safe_get(response, "leverage")
                if exchange_lev is None and isinstance(response, dict):
                    exchange_lev = response.get("leverage")
                if exchange_lev is not None:
                    exchange_lev = float(exchange_lev)
                log(
                    f"✅ CROSS LEVERAGE SET | requested={leverage} | "
                    f"exchange={exchange_lev if exchange_lev is not None else 'unknown'} | method={method_name}"
                )
                return exchange_lev
            except Exception as exc:
                log(f"Cross leverage method {method_name} failed: {exc}")
        except Exception as exc:
            log(f"Cross leverage method {method_name} failed: {exc}")

    log(f"❌ Unable to set cross leverage to {leverage} with available SDK methods")
    return None


def reset_learning_state_for_epoch():
    brain["lifetime_trades"] = int(brain.get("lifetime_trades", 0)) + int(brain.get("trades", 0))
    brain["lifetime_total_pnl"] = float(brain.get("lifetime_total_pnl", 0.0)) + float(brain.get("total_pnl", 0.0))

    brain["learning_epoch"] = LEARNING_EPOCH
    brain["learning_epoch_started_at"] = datetime.now().isoformat()

    # === CLEAN START FOR NEW EPOCH ===
    brain["trade_lessons"] = []
    brain["meta_lessons"] = []
    brain["trades"] = 0
    brain["wins"] = 0
    brain["losses"] = 0
    brain["streak"] = 0
    brain["total_pnl"] = 0.0
    brain["daily_pnl"] = 0.0
    brain["daily_realized"] = []

    # Keep only last 10 PnLs today (to protect the fresh epoch)
    brain["last_pnls"] = brain.get("last_pnls", [])[-10:]

    brain["historical_stats"] = {}
    brain["equity_peak"] = 0.0
    brain["current_equity"] = 0.0
    brain["drawdown"] = 0.0
    brain["confidence_bias"] = 0.0
    brain["risk_history"] = []
    brain["past_ai_decisions"] = []
    brain["ai_reviews"] = []
    brain["ai_adjustments"] = []
    brain["adds"] = []
    brain["position"] = {"is_open": False}
    brain["last_exit"] = {}
    brain["last_exit_reason"] = ""
    brain["last_review_action"] = None
    brain["last_review_reason"] = None

    brain["intent_stats"] = {
        "trend_follow": {"trades": 0, "wins": 0, "pnl": 0.0, "winrate": 0.0},
        "mean_revert": {"trades": 0, "wins": 0, "pnl": 0.0, "winrate": 0.0},
        "breakout": {"trades": 0, "wins": 0, "pnl": 0.0, "winrate": 0.0},
        "scalp": {"trades": 0, "wins": 0, "pnl": 0.0, "winrate": 0.0},
    }
    brain["confidence_stats"] = {}
    brain["regime_stats"] = {
        "trend": {"trades": 0, "wins": 0, "pnl": 0.0},
        "chop": {"trades": 0, "wins": 0, "pnl": 0.0},
        "volatile": {"trades": 0, "wins": 0, "pnl": 0.0},
        "squeeze": {"trades": 0, "wins": 0, "pnl": 0.0},
    }
    brain["regime_weights"] = {}
    brain["trade_timestamps"] = []
    brain["exploration"] = {
        "last_policy": None,
        "last_explore_at": 0.0,
        "last_score": 0.0,
        "mix_rate": EXPLORATION_BASE_RATE,
        "policies": {},
        "recent": [],
    }

    log(f"🔄 NEW EPOCH STARTED CLEAN: {LEARNING_EPOCH} → keeping only last 10 PnLs (today's trades)")


def restore_trade_stats_from_position(position: PositionState):
    """Restore basic stats when we sync an existing open position on restart"""
    if not position.is_open:
        return

    # Only restore if we have zero trades in brain (fresh epoch or after reset)
    if brain.get("trades", 0) == 0:
        brain["trades"] = 1
        brain["last_trade"] = {
            "entry": position.entry,
            "side": position.side,
            "qty": position.qty,
            "leverage": position.leverage,
            "mode": position.mode,
            "policy": position.policy,
            "entry_nearest_support": position.entry_nearest_support,
            "entry_nearest_resistance": position.entry_nearest_resistance,
            "entry_room_to_target_bps": position.entry_room_to_target_bps,
            "entry_level_alignment": position.entry_level_alignment,
            "entry_level_summary": position.entry_level_summary,
            "entry_feature_health_summary": position.entry_feature_health_summary,
        }
        log(f"Restored open position stats | trades=1 side={position.side} entry={position.entry}")


def reconcile_open_position_context(position: PositionState) -> bool:
    """Normalize carried-over open-position metadata to the active regime/risk model."""
    if not position.is_open:
        return False

    changed = False
    regime = brain.get("market_regime", {}).get("regime", "unknown")
    adaptive = get_adaptive_trade_parameters()
    desired_risk = float(adaptive.get("risk_per_trade", RISK_PER_TRADE) or RISK_PER_TRADE)
    previous_risk = float(brain.get("current_risk_per_trade", RISK_PER_TRADE) or RISK_PER_TRADE)
    if abs(previous_risk - desired_risk) > 1e-6:
        brain["current_risk_per_trade"] = desired_risk
        changed = True

    if regime == "chop":
        ambiguous_intent = position.intent in {"", "unknown", "neutral", None}
        generic_policy = not position.policy or position.policy == "ai_primary"
        existing_mean_revert = position.intent == "mean_revert" or str(position.policy or "").startswith("mean_revert")
        if ambiguous_intent or generic_policy or existing_mean_revert:
            if position.intent != "mean_revert":
                position.intent = "mean_revert"
                changed = True
            if not position.policy or position.policy == "ai_primary":
                position.policy = "mean_revert_micro"
                changed = True
            if not position.last_reason or position.last_reason.strip() == "":
                position.last_reason = "reconciled chop carry-over position"
                changed = True
        if position.mode == "exploit":
            position.mode = "explore"
            changed = True
    elif regime == "unknown":
        desired_risk = min(desired_risk, UNKNOWN_RISK_CAP)
        if abs(float(brain.get("current_risk_per_trade", desired_risk) or desired_risk) - desired_risk) > 1e-6:
            brain["current_risk_per_trade"] = desired_risk
            changed = True

    if brain.get("trades", 0) == 0:
        restore_trade_stats_from_position(position)
        changed = True

    last_trade = brain.get("last_trade", {})
    if position.side in {"long", "short"}:
        if last_trade.get("side") != position.side or not last_trade.get("entry"):
            brain["last_trade"] = {
                "timestamp": datetime.now().isoformat(),
                "entry": position.entry,
                "side": position.side,
                "qty": position.qty,
                "leverage": position.leverage,
                "sl_price": position.sl_price,
                "tp_price": position.tp_price,
                "trail_buffer_pct": position.trail_buffer_pct,
                "intent": position.intent,
                "confidence": round(float(position.confidence or 0.5), 3),
                "reason": position.last_reason,
                "max_hold_minutes": position.max_hold_minutes,
                "risk_per_trade": round(float(brain.get("current_risk_per_trade", desired_risk) or desired_risk), 5),
                "mode": position.mode,
                "policy": position.policy,
                "order_id": position.exchange_order_id,
            }
            changed = True
        else:
            sync_fields = {
                "intent": position.intent,
                "confidence": round(float(position.confidence or 0.5), 3),
                "reason": position.last_reason,
                "mode": position.mode,
                "policy": position.policy,
                "risk_per_trade": round(float(brain.get("current_risk_per_trade", desired_risk) or desired_risk), 5),
            }
            for key, value in sync_fields.items():
                if last_trade.get(key) != value:
                    last_trade[key] = value
                    changed = True

    if changed:
        persist_open_position_plan(position)

    return changed


def load_memory():
    global MEMORY
    if not MEMORY_FILE.exists():
        return
    try:
        with MEMORY_FILE.open("r", encoding="utf-8") as handle:
            MEMORY = json.load(handle)
        brain.update(MEMORY.get("brain", {}))
        market_state.update(MEMORY.get("market_state", {}))
        recent_pnls.clear()
        recent_pnls.extend(MEMORY.get("recent_pnls", [])[-100:])
        saved_prices = MEMORY.get("recent_prices", [])
        if saved_prices:
            PRICE_WINDOW.clear()
            for price in saved_prices[-PRICE_WINDOW.maxlen:]:
                try:
                    PRICE_WINDOW.append(float(price))
                except (TypeError, ValueError):
                    continue
        if brain.get("learning_epoch") != LEARNING_EPOCH:
            reset_learning_state_for_epoch()
        ensure_shadow_exploration_state()
        brain["base_risk_per_trade"] = RISK_PER_TRADE
        brain["current_risk_per_trade"] = RISK_PER_TRADE
        load_hybrid_xgb_model()
        log("Memory loaded")
    except Exception as exc:
        log(f"Memory load failed: {exc}")


def ensure_shadow_exploration_state() -> dict[str, Any]:
    shadow = brain.setdefault("shadow_exploration", {})
    shadow.setdefault("last_shadow_at", 0.0)
    shadow.setdefault("policies", {})
    shadow.setdefault("recent", [])
    shadow.setdefault("pending", [])
    return shadow


def trim_shadow_exploration_state() -> dict[str, Any]:
    shadow = ensure_shadow_exploration_state()
    shadow["recent"] = shadow.get("recent", [])[-480:]
    shadow["pending"] = shadow.get("pending", [])[-SHADOW_MAX_PENDING:]
    return shadow


def save_memory():
    global MEMORY
    get_risk_mode()
    brain["trade_lessons"] = brain.get("trade_lessons", [])[-50:]
    brain["meta_lessons"] = brain.get("meta_lessons", [])[-10:]
    brain["past_ai_decisions"] = brain.get("past_ai_decisions", [])[-100:]
    brain["leaderboard_history"] = brain.get("leaderboard_history", [])[-12:]
    brain["daily_realized"] = brain.get("daily_realized", [])[-500:]
    trim_shadow_exploration_state()
    MEMORY["brain"] = safe_serialize(brain)
    MEMORY["market_state"] = safe_serialize(market_state)
    MEMORY["recent_pnls"] = recent_pnls[-100:]
    MEMORY["recent_prices"] = list(PRICE_WINDOW)[-PRICE_WINDOW.maxlen:]
    MEMORY["saved_at"] = datetime.now().isoformat()
    MEMORY["version"] = "3.2"
    tmp_path = MEMORY_FILE.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(MEMORY, handle, indent=2, ensure_ascii=False)
    os.replace(tmp_path, MEMORY_FILE)
    log("Memory saved")


def maybe_save_memory(force: bool = False):
    global _cycle_counter
    _cycle_counter += 1
    if not force and _cycle_counter < SAVE_EVERY_N_CYCLES:
        return
    try:
        save_memory()
        _cycle_counter = 0
    except Exception as exc:
        log(f"Memory save failed: {exc}")


def validate_startup():
    missing = [
        name
        for name, value in (
            ("BEARER_TOKEN", BEARER_TOKEN),
            ("LNM_API_KEY", LNM_API_KEY),
            ("LNM_API_SECRET", LNM_API_SECRET),
            ("LNM_API_PASSPHRASE", LNM_API_PASSPHRASE),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


def _safe_get(obj: Any, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def update_price(price: float):
    PRICE_WINDOW.append(float(price))


def compute_range_state() -> dict[str, Any]:
    prices = list(PRICE_WINDOW)[-CHOP_RANGE_LOOKBACK:]
    if len(prices) < 20:
        return {
            "range_position": 0.5,
            "range_width_pct": 0.0,
            "range_high": 0.0,
            "range_low": 0.0,
            "range_mid": 0.0,
            "range_established": False,
            "micro_range_established": False,
            "micro_range_reason": "insufficient_prices",
        }
    range_high = float(max(prices))
    range_low = float(min(prices))
    range_mid = (range_high + range_low) / 2.0
    spread = range_high - range_low
    range_width_pct = spread / max(range_mid, 1.0)
    current_price = prices[-1]
    range_position = clamp((current_price - range_low) / max(spread, 1e-8), 0.0, 1.0)
    range_established = len(prices) >= 30 and range_width_pct >= 0.002
    bracket_bps = range_width_pct * 10000.0
    micro_range_established = bool(
        not range_established
        and len(prices) >= 30
        and SQUEEZE_MICRO_RANGE_MIN_WIDTH_PCT <= range_width_pct
        and SQUEEZE_MICRO_RANGE_MIN_BRACKET_BPS <= bracket_bps <= SQUEEZE_MICRO_RANGE_MAX_BRACKET_BPS
    )
    micro_range_reason = (
        f"width={range_width_pct:.4f} bracket={bracket_bps:.1f}bps"
        if micro_range_established
        else "not_micro_range"
    )
    return {
        "range_position": round(range_position, 4),
        "range_width_pct": round(range_width_pct, 6),
        "range_high": round(range_high, 2),
        "range_low": round(range_low, 2),
        "range_mid": round(range_mid, 2),
        "range_established": range_established,
        "micro_range_established": micro_range_established,
        "micro_range_reason": micro_range_reason,
    }


def compute_feature_health(market: Optional[dict[str, Any]] = None, external_ctx: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    market = market or brain.get("market_context", {}) or {}
    external_ctx = external_ctx or {}
    bid = float(market.get("bid", 0.0) or 0.0)
    ask = float(market.get("ask", 0.0) or 0.0)
    spread_pct = float(market.get("spread_pct", 0.0) or 0.0)
    imbalance = float(market.get("imbalance", 0.0) or 0.0)
    depth_live = bool(market.get("depth_live", False))
    # LN Markets v3 exposes ticker/best bid-ask, not reliable depth; require sizes for imbalance policies.
    orderbook_live = bool(bid > 0 and ask > 0 and ask >= bid and spread_pct > 0 and depth_live)
    spread_live = bool(spread_pct > 0)
    external_live = str(external_ctx.get("external_data_quality", "none")) in {"full", "partial"}
    stale = []
    if not orderbook_live:
        stale.append("orderbook_depth")
    if not spread_live:
        stale.append("spread")
    if not external_live:
        stale.append("external")
    source = str(market.get("source", "lnmarkets_ticker") or "lnmarkets_ticker")
    missing_reason = "ok" if not stale else "missing_or_zero:" + ",".join(stale)
    health = {
        "orderbook_live": orderbook_live,
        "spread_live": spread_live,
        "external_live": external_live,
        "feature_health_summary": "ok" if not stale else "stale:" + ",".join(stale),
        "feature_health_source": source,
        "feature_health_reason": missing_reason,
        "orderbook_bid": round(bid, 2),
        "orderbook_ask": round(ask, 2),
        "orderbook_spread_pct": round(spread_pct, 5),
        "orderbook_imbalance": round(imbalance, 4),
    }
    brain["feature_health"] = health
    return health


def cluster_price_levels(levels: list[float], current_price: float, gap_bps: float) -> list[dict[str, Any]]:
    if current_price <= 0:
        return []
    gap_abs = current_price * max(0.0, gap_bps) / 10000.0
    sorted_levels = sorted({round(float(level), 2) for level in levels if float(level or 0.0) > 0})
    clusters: list[list[float]] = []
    for level in sorted_levels:
        if not clusters or level - clusters[-1][-1] > gap_abs:
            clusters.append([level])
        else:
            clusters[-1].append(level)
    return [
        {
            "low": float(cluster[0]),
            "high": float(cluster[-1]),
            "mid": sum(cluster) / len(cluster),
            "count": len(cluster),
        }
        for cluster in clusters
    ]


def compute_level_map() -> dict[str, Any]:
    prices = [float(price) for price in list(PRICE_WINDOW) if float(price or 0.0) > 0]
    current_price = float(prices[-1]) if prices else float(brain.get("last_price", 0.0) or 0.0)
    if current_price <= 0 or len(prices) < LEVEL_MAP_MIN_POINTS:
        level_map = {
            "level_map_ready": False,
            "nearest_support": 0.0,
            "nearest_resistance": 0.0,
            "raw_nearest_support": 0.0,
            "raw_nearest_resistance": 0.0,
            "support_distance_bps": 0.0,
            "resistance_distance_bps": 0.0,
            "raw_support_distance_bps": 0.0,
            "raw_resistance_distance_bps": 0.0,
            "room_to_support_bps": 0.0,
            "room_to_resistance_bps": 0.0,
            "at_support": False,
            "at_resistance": False,
            "sweep_reclaim_long": False,
            "sweep_reclaim_short": False,
            "wyckoff_spring_long": False,
            "wyckoff_spring_short": False,
            "level_position": 0.5,
            "level_alignment": "unknown",
            "support_valid": False,
            "resistance_valid": False,
            "level_cluster_count": 0,
            "level_summary": "level map not ready",
        }
        brain["level_map"] = level_map
        return level_map

    market = brain.get("market_context", {}) or {}
    candidates: list[float] = []
    for lookback in (30, 90, 180, 360):
        sample = prices[-lookback:] if len(prices) >= lookback else prices
        if len(sample) >= LEVEL_MAP_MIN_POINTS:
            candidates.extend([min(sample), max(sample)])
    swing_sample = prices[-LEVEL_SWING_LOOKBACK:]
    # In squeeze the tick-level noise produces 0.1bps "pivots" that dominate S/R.
    # Widen the pivot neighborhood and require a minimum prominence so
    # buy-low/sell-high has real structure to lean on.
    _live_regime = str((brain.get("market_regime", {}) or {}).get("regime", "unknown") or "unknown")
    _in_squeeze = _live_regime == "squeeze"
    pivot_width = max(
        1,
        int(LEVEL_SWING_PIVOT_WIDTH_SQUEEZE if _in_squeeze else LEVEL_SWING_PIVOT_WIDTH),
    )
    min_prom_bps = (
        LEVEL_PIVOT_MIN_PROMINENCE_BPS_SQUEEZE if _in_squeeze else LEVEL_PIVOT_MIN_PROMINENCE_BPS
    )
    swing_lows: list[float] = []
    swing_highs: list[float] = []
    if len(swing_sample) >= pivot_width * 2 + 1:
        for idx in range(pivot_width, len(swing_sample) - pivot_width):
            center = swing_sample[idx]
            if center <= 0:
                continue
            left = swing_sample[idx - pivot_width:idx]
            right = swing_sample[idx + 1:idx + pivot_width + 1]
            neighbor_min = min(min(left), min(right))
            neighbor_max = max(max(left), max(right))
            if center <= min(left) and center <= min(right):
                prominence_bps = (neighbor_max - center) / center * 10000.0
                if prominence_bps >= min_prom_bps:
                    swing_lows.append(center)
            if center >= max(left) and center >= max(right):
                prominence_bps = (center - neighbor_min) / center * 10000.0
                if prominence_bps >= min_prom_bps:
                    swing_highs.append(center)
    candidates.extend(swing_lows[-8:])
    candidates.extend(swing_highs[-8:])
    for key in ("range_low", "range_high", "range_mid"):
        value = float(market.get(key, 0.0) or 0.0)
        if value > 0:
            candidates.append(value)

    clustered_levels = cluster_price_levels(candidates, current_price, LEVEL_CLUSTER_MIN_GAP_BPS)
    raw_support_candidates = [level for level in candidates if level < current_price * 0.99999]
    raw_resistance_candidates = [level for level in candidates if level > current_price * 1.00001]
    tradable_support_candidates = [level["high"] for level in clustered_levels if level["high"] < current_price * 0.99999]
    tradable_resistance_candidates = [level["low"] for level in clustered_levels if level["low"] > current_price * 1.00001]
    support_candidates = tradable_support_candidates or raw_support_candidates
    resistance_candidates = tradable_resistance_candidates or raw_resistance_candidates
    support_valid = bool(support_candidates)
    resistance_valid = bool(resistance_candidates)
    nearest_support = max(support_candidates) if support_valid else 0.0
    nearest_resistance = min(resistance_candidates) if resistance_valid else 0.0
    support_distance_bps = ((current_price - nearest_support) / current_price * 10000) if support_valid else 0.0
    resistance_distance_bps = ((nearest_resistance - current_price) / current_price * 10000) if resistance_valid else 0.0
    raw_support_valid = bool(raw_support_candidates)
    raw_resistance_valid = bool(raw_resistance_candidates)
    raw_nearest_support = max(raw_support_candidates) if raw_support_valid else 0.0
    raw_nearest_resistance = min(raw_resistance_candidates) if raw_resistance_valid else 0.0
    raw_support_distance_bps = ((current_price - raw_nearest_support) / current_price * 10000) if raw_support_valid else 0.0
    raw_resistance_distance_bps = ((raw_nearest_resistance - current_price) / current_price * 10000) if raw_resistance_valid else 0.0
    range_established = bool(market.get("range_established", False))
    range_position = float(market.get("range_position", 0.5) or 0.5)
    if support_valid and resistance_valid and nearest_resistance > nearest_support:
        level_position = clamp((current_price - nearest_support) / (nearest_resistance - nearest_support), 0.0, 1.0)
    else:
        level_position = range_position
    at_support = (raw_support_valid and raw_support_distance_bps <= LEVEL_NEAR_BPS) or (
        range_established and range_position <= get_range_long_max() + 0.05
    )
    at_resistance = (raw_resistance_valid and raw_resistance_distance_bps <= LEVEL_NEAR_BPS) or (
        range_established and range_position >= get_range_short_min() - 0.05
    )
    recent = prices[-9:-1]
    recent_low = min(recent) if recent else current_price
    recent_high = max(recent) if recent else current_price
    sweep_reclaim_long = bool(
        raw_nearest_support > 0
        and recent_low <= raw_nearest_support * (1 + 0.0002)
        and current_price >= raw_nearest_support * (1 + LEVEL_RECLAIM_BPS / 10000.0)
    )
    sweep_reclaim_short = bool(
        raw_nearest_resistance > 0
        and recent_high >= raw_nearest_resistance * (1 - 0.0002)
        and current_price <= raw_nearest_resistance * (1 - LEVEL_RECLAIM_BPS / 10000.0)
    )
    # Wyckoff spring (long) / upthrust (short): price genuinely broke through the level
    # and then snapped back — highest-quality entry signal, better than a mere touch.
    spring_window = prices[-WYCKOFF_SPRING_LOOKBACK:]
    spring_low = min(spring_window) if spring_window else current_price
    spring_high = max(spring_window) if spring_window else current_price
    wyckoff_spring_long = bool(
        raw_nearest_support > 0
        and spring_low < raw_nearest_support * (1 - WYCKOFF_SPRING_BREAK_BPS / 10000.0)
        and current_price >= raw_nearest_support * (1 + WYCKOFF_SPRING_RECLAIM_BPS / 10000.0)
    )
    wyckoff_spring_short = bool(
        raw_nearest_resistance > 0
        and spring_high > raw_nearest_resistance * (1 + WYCKOFF_SPRING_BREAK_BPS / 10000.0)
        and current_price <= raw_nearest_resistance * (1 - WYCKOFF_SPRING_RECLAIM_BPS / 10000.0)
    )
    level_alignment = "support" if at_support or sweep_reclaim_long or wyckoff_spring_long else "resistance" if at_resistance or sweep_reclaim_short or wyckoff_spring_short else "mid"
    level_map = {
        "level_map_ready": True,
        "nearest_support": round(nearest_support, 2),
        "nearest_resistance": round(nearest_resistance, 2),
        "raw_nearest_support": round(raw_nearest_support, 2),
        "raw_nearest_resistance": round(raw_nearest_resistance, 2),
        "support_distance_bps": round(support_distance_bps, 2),
        "resistance_distance_bps": round(resistance_distance_bps, 2),
        "raw_support_distance_bps": round(raw_support_distance_bps, 2),
        "raw_resistance_distance_bps": round(raw_resistance_distance_bps, 2),
        "room_to_support_bps": round(support_distance_bps, 2),
        "room_to_resistance_bps": round(resistance_distance_bps, 2),
        "at_support": at_support,
        "at_resistance": at_resistance,
        "sweep_reclaim_long": sweep_reclaim_long,
        "sweep_reclaim_short": sweep_reclaim_short,
        "wyckoff_spring_long": wyckoff_spring_long,
        "wyckoff_spring_short": wyckoff_spring_short,
        "level_position": round(level_position, 4),
        "level_alignment": level_alignment,
        "swing_support_count": len(swing_lows),
        "swing_resistance_count": len(swing_highs),
        "support_valid": support_valid,
        "resistance_valid": resistance_valid,
        "level_cluster_count": len(clustered_levels),
        "level_summary": (
            f"support={nearest_support:.1f} ({support_distance_bps:.1f}bps{'' if support_valid else ', NO_SUB_PRICE_CAND'}), "
            f"resistance={nearest_resistance:.1f} ({resistance_distance_bps:.1f}bps{'' if resistance_valid else ', NO_ABOVE_PRICE_CAND'}), "
            f"raw={raw_support_distance_bps:.1f}/{raw_resistance_distance_bps:.1f}bps, "
            f"align={level_alignment}, pivots={len(swing_lows)}/{len(swing_highs)}, clusters={len(clustered_levels)}"
        ),
    }
    brain["level_map"] = level_map
    return level_map


def get_range_based_tp_bps(direction: str, fallback_tp_bps: int) -> int:
    ctx = brain.get("market_context", {})
    if not bool(ctx.get("range_established", False)):
        return fallback_tp_bps
    range_mid = float(ctx.get("range_mid", 0.0) or 0.0)
    range_width_pct = float(ctx.get("range_width_pct", 0.0) or 0.0)
    price = float(brain.get("last_price", 0.0) or 0.0)
    if range_mid <= 0 or price <= 0 or range_width_pct < CHOP_MIN_RANGE_WIDTH_PCT:
        return fallback_tp_bps
    target_dist = (range_mid - price) if direction == "long" else (price - range_mid)
    if target_dist <= 0:
        return fallback_tp_bps
    range_tp_bps = int(target_dist / price * 10000)
    max_tp = int(range_width_pct * 10000 * CHOP_RANGE_TP_MAX_OVERSHOOT)
    return max(fallback_tp_bps, min(range_tp_bps, max_tp))


def get_range_long_max() -> float:
    return float(brain.get("range_thresholds", {}).get("long_max", CHOP_RANGE_LONG_MAX))


def get_range_short_min() -> float:
    return float(brain.get("range_thresholds", {}).get("short_min", CHOP_RANGE_SHORT_MIN))


def _squeeze_bracket_bps() -> float:
    # Live total bracket (room to support + room to resistance) when the
    # level map is ready and both sides are valid; 0 otherwise.
    lvl = brain.get("level_map", {}) or {}
    if not (
        lvl.get("level_map_ready", False)
        and lvl.get("support_valid", False)
        and lvl.get("resistance_valid", False)
    ):
        return 0.0
    regime = str((brain.get("market_regime", {}) or {}).get("regime", "unknown") or "unknown")
    if regime != "squeeze":
        return 0.0
    return float(lvl.get("room_to_support_bps", 0.0) or 0.0) + float(
        lvl.get("room_to_resistance_bps", 0.0) or 0.0
    )


def _get_squeeze_bracket_trigger_ratio() -> float:
    return float(clamp(
        float(brain.get("level_thresholds", {}).get("squeeze_bracket_trigger_ratio", LEVEL_SQUEEZE_BRACKET_TRIGGER_RATIO) or LEVEL_SQUEEZE_BRACKET_TRIGGER_RATIO),
        LEVEL_SQUEEZE_BRACKET_TRIGGER_RATIO_FLOOR,
        LEVEL_SQUEEZE_BRACKET_TRIGGER_RATIO_CEIL,
    ))


def _get_squeeze_room_fraction() -> float:
    return float(clamp(
        float(brain.get("level_thresholds", {}).get("squeeze_room_fraction", LEVEL_SQUEEZE_ROOM_FRACTION) or LEVEL_SQUEEZE_ROOM_FRACTION),
        LEVEL_SQUEEZE_ROOM_FRACTION_FLOOR,
        LEVEL_SQUEEZE_ROOM_FRACTION_CEIL,
    ))


def _get_squeeze_breakout_fraction() -> float:
    return float(clamp(
        float(brain.get("level_thresholds", {}).get("squeeze_breakout_fraction", LEVEL_SQUEEZE_BREAKOUT_FRACTION) or LEVEL_SQUEEZE_BREAKOUT_FRACTION),
        LEVEL_SQUEEZE_BREAKOUT_FRACTION_FLOOR,
        LEVEL_SQUEEZE_BREAKOUT_FRACTION_CEIL,
    ))


def get_level_min_room_bps() -> float:
    value = float(brain.get("level_thresholds", {}).get("min_room_bps", LEVEL_MIN_ROOM_BPS) or LEVEL_MIN_ROOM_BPS)
    value = clamp(value, LEVEL_MIN_ROOM_HARD_FLOOR_BPS, LEVEL_MIN_ROOM_BPS)
    bracket = _squeeze_bracket_bps()
    if 0.0 < bracket < value * _get_squeeze_bracket_trigger_ratio():
        value = max(LEVEL_SQUEEZE_ROOM_FLOOR_BPS, _get_squeeze_room_fraction() * bracket)
    return value


def get_level_breakout_min_room_bps() -> float:
    if get_top_lane_drift_guard_reason((brain.get("exploration_thresholds", {}) or {}).get("top_lane", {}) or {}):
        return LEVEL_BREAKOUT_MIN_ROOM_BPS
    value = float(
        brain.get("level_thresholds", {}).get("breakout_min_room_bps", LEVEL_BREAKOUT_MIN_ROOM_BPS)
        or LEVEL_BREAKOUT_MIN_ROOM_BPS
    )
    value = clamp(value, LEVEL_BREAKOUT_ROOM_HARD_FLOOR_BPS, LEVEL_BREAKOUT_MIN_ROOM_BPS)
    bracket = _squeeze_bracket_bps()
    if 0.0 < bracket < value * _get_squeeze_bracket_trigger_ratio():
        value = max(LEVEL_SQUEEZE_BREAKOUT_FLOOR_BPS, _get_squeeze_breakout_fraction() * bracket)
    return value


def get_exploration_thresholds() -> dict[str, Any]:
    et = brain.setdefault("exploration_thresholds", {})
    et.setdefault("mix_bias", 0.0)
    et.setdefault("mix_floor", 0.10)
    et.setdefault("mix_ceiling", 0.72)
    et.setdefault("min_score", 0.48)
    et.setdefault("min_edge", 0.16)
    et.setdefault("confidence_floor", EXPLORATION_MIN_CONFIDENCE)
    et.setdefault("cooldown_seconds", EXPLORATION_COOLDOWN_SECONDS)
    et.setdefault("risk_floor", EXPLORATION_RISK_FLOOR)
    et.setdefault("risk_ceiling", EXPLORATION_RISK_CEIL)
    et.setdefault(
        "allocation_caps",
        {
            "qty_multiplier_min": 0.60,
            "qty_multiplier_max": 1.00,
            "risk_multiplier_min": 0.75,
            "risk_multiplier_max": 1.00,
            "last_reason": "initial conservative allocation caps",
        },
    )
    et.setdefault("policy_fit_adjustments", {})
    et.setdefault("lane_stats", {})
    et.setdefault("top_lane", {})
    et.setdefault("last_reason", "initial defaults")
    et.setdefault("history", [])

    # Hard bounds keep autotune from silently increasing live risk posture.
    et["mix_bias"] = round(clamp(float(et.get("mix_bias", 0.0) or 0.0), -0.12, 0.10), 4)
    et["mix_floor"] = round(clamp(float(et.get("mix_floor", 0.10) or 0.10), 0.06, 0.20), 4)
    et["mix_ceiling"] = round(clamp(float(et.get("mix_ceiling", 0.72) or 0.72), 0.34, 0.92), 4)
    if et["mix_ceiling"] < et["mix_floor"]:
        et["mix_ceiling"] = et["mix_floor"]
    et["min_score"] = round(clamp(float(et.get("min_score", 0.48) or 0.48), EXPLORATION_MIN_SCORE_FLOOR, EXPLORATION_MAX_SCORE_FLOOR), 4)
    et["min_edge"] = round(clamp(float(et.get("min_edge", 0.16) or 0.16), 0.12, 0.24), 4)
    et["confidence_floor"] = round(clamp(float(et.get("confidence_floor", EXPLORATION_MIN_CONFIDENCE) or EXPLORATION_MIN_CONFIDENCE), EXPLORATION_MIN_CONFIDENCE, 0.52), 4)
    et["cooldown_seconds"] = int(clamp(float(et.get("cooldown_seconds", EXPLORATION_COOLDOWN_SECONDS) or EXPLORATION_COOLDOWN_SECONDS), EXPLORATION_MIN_COOLDOWN_SECONDS, EXPLORATION_MAX_COOLDOWN_SECONDS))
    et["risk_floor"] = round(clamp(float(et.get("risk_floor", EXPLORATION_RISK_FLOOR) or EXPLORATION_RISK_FLOOR), 0.12, EXPLORATION_RISK_FLOOR), 4)
    et["risk_ceiling"] = round(clamp(float(et.get("risk_ceiling", EXPLORATION_RISK_CEIL) or EXPLORATION_RISK_CEIL), et["risk_floor"], EXPLORATION_RISK_CEIL), 4)
    caps = et.setdefault("allocation_caps", {})
    caps["qty_multiplier_min"] = round(clamp(float(caps.get("qty_multiplier_min", 0.60) or 0.60), EXPLORATION_ALLOC_ABS_QTY_MULT_MIN, 1.0), 4)
    caps["qty_multiplier_max"] = round(clamp(float(caps.get("qty_multiplier_max", 1.0) or 1.0), caps["qty_multiplier_min"], EXPLORATION_ALLOC_ABS_QTY_MULT_MAX), 4)
    caps["risk_multiplier_min"] = round(clamp(float(caps.get("risk_multiplier_min", 0.75) or 0.75), EXPLORATION_ALLOC_ABS_RISK_MULT_MIN, 1.0), 4)
    caps["risk_multiplier_max"] = round(clamp(float(caps.get("risk_multiplier_max", 1.0) or 1.0), caps["risk_multiplier_min"], EXPLORATION_ALLOC_ABS_RISK_MULT_MAX), 4)
    return et


def get_exploration_policy_fit_adjustment(policy: str) -> float:
    thresholds = get_exploration_thresholds()
    adjustments = thresholds.get("policy_fit_adjustments", {}) or {}
    adjustment = clamp(float(adjustments.get(policy, 0.0) or 0.0), -0.10, 0.08)
    if adjustment <= 0:
        return adjustment

    top = thresholds.get("top_lane", {}) or {}
    top_policy = split_exploration_lane_key(str(top.get("lane_key", "")))["policy"] if top else ""
    if top_policy == policy and get_top_lane_drift_guard_reason(top):
        return 0.0

    for lane_key, stats in (thresholds.get("lane_stats", {}) or {}).items():
        if split_exploration_lane_key(lane_key)["policy"] != policy:
            continue
        if int(stats.get("resolved", 0) or 0) < 2:
            continue
        if (
            float(stats.get("fee_clear_rate", 0.0) or 0.0) < 0.35
            or float(stats.get("ev_after_fee_bps", 0.0) or 0.0) < -10.0
            or float(stats.get("avg_adverse_bps", 0.0) or 0.0) > 35.0
        ):
            return 0.0
    return adjustment


def load_hybrid_xgb_model() -> None:
    return


def get_dynamic_leverage(thesis_score: float, alignment: str, regime: str, risk_mode: str) -> int:
    score = float(thesis_score or 0.0)
    align = str(alignment or "neutral")
    regime_name = str(regime or "unknown")
    caution_decay = get_caution_decay_multiplier()
    effective_losses = get_effective_consecutive_losses()

    if risk_mode == "protection":
        return 1
    if risk_mode == "caution" or effective_losses >= 3:
        if score > 0.65 and align == "excellent" and caution_decay <= 0.85:
            return 20 if regime_name in {"trend", "squeeze"} else 18
        if score > 0.45 and align in {"good", "excellent"} and caution_decay <= 0.95:
            return 15 if regime_name in {"trend", "squeeze"} else 12
        if score > 0.32 and align in {"good", "excellent"} and caution_decay <= 0.98:
            return 8 if regime_name in {"trend", "squeeze"} else 6
        if score > 0.65 and align == "excellent":
            return 3
        if score > 0.45 and align in {"good", "excellent"}:
            return 2
        return 1

    if score > 0.65 and align == "excellent":
        return 20 if regime_name in {"trend", "squeeze"} else 18
    if score > 0.45 and align in {"good", "excellent"}:
        return 15 if regime_name in {"trend", "squeeze"} else 12
    if align in {"supportive", "good", "excellent"}:
        return 8 if regime_name in {"trend", "squeeze"} else 6
    return 5


def get_exploration_min_score() -> float:
    score = float(get_exploration_thresholds().get("min_score", 0.48) or 0.48)
    if get_strategic_aggression_context().get("default_aggressive"):
        score = max(EXPLORATION_MIN_SCORE_FLOOR, score - STRATEGIC_ATTACK_SCORE_RELIEF)
    return score


def get_exploration_min_edge(regime: str, intent: str, small_account: bool, elite_chop: bool) -> float:
    dynamic_floor = float(get_exploration_thresholds().get("min_edge", 0.16) or 0.16)
    if get_strategic_aggression_context().get("default_aggressive") and regime in {"trend", "squeeze"}:
        dynamic_floor = max(0.10, dynamic_floor - STRATEGIC_ATTACK_EDGE_RELIEF)
    if small_account and regime == "chop":
        return max(dynamic_floor, ELITE_CHOP_MIN_EDGE if elite_chop else SMALL_ACCOUNT_CHOP_MIN_EDGE)
    if small_account and regime in {"trend", "squeeze"}:
        return max(0.10, min(dynamic_floor, 0.16))
    return dynamic_floor


def compute_aggressive_learning_edge_lift(
    *,
    base_edge: float,
    predictive_score: float,
    alignment: str,
    level_edge: bool,
    same_proof: Optional[dict[str, Any]] = None,
    shadow_bonus: float = 0.0,
    shadow_direction_bonus: float = 0.0,
    structure_confidence: float = 0.0,
    flat_minutes: Optional[float] = None,
) -> tuple[float, float, str]:
    """
    Converts the bot's learning evidence into tradable edge.

    The old path treated expected_edge as the only truth even when predictive
    and shadow evidence had already found a setup. That was too passive for a
    learning bot: it can collect evidence forever without taking the trade.
    This lift is capped, auditable, and still requires the downstream level,
    risk, exchange, SL/TP, and daily-loss guards.
    """
    pred = float(predictive_score or 0.0)
    edge = float(base_edge or 0.0)
    align = str(alignment or "neutral")
    proof = same_proof or {}
    flat = get_flat_duration_minutes() if flat_minutes is None else float(flat_minutes or 0.0)

    lift = 0.0
    reasons: list[str] = []

    if pred >= AGGRESSIVE_LEARNING_PREDICTIVE_FLOOR:
        pred_lift = min(0.22, (pred - 0.50) * 0.55)
        lift += pred_lift
        reasons.append(f"pred+{pred_lift:.2f}")
    if proof.get("proven"):
        avg_bps = float(proof.get("avg_outcome_bps", 0.0) or 0.0)
        peak_fee = float(proof.get("avg_peak_fee", proof.get("avg_peak_fee_multiple", 0.0)) or 0.0)
        proof_lift = 0.08 + min(0.12, max(0.0, avg_bps) / 220.0) + min(0.05, max(0.0, peak_fee) * 0.025)
        lift += proof_lift
        reasons.append(f"shadow+{proof_lift:.2f}")
    if shadow_bonus > 0.0 or shadow_direction_bonus > 0.0:
        bonus_lift = min(0.12, max(0.0, shadow_bonus) * 2.0 + max(0.0, shadow_direction_bonus) * 2.4)
        lift += bonus_lift
        reasons.append(f"selector+{bonus_lift:.2f}")
    if align == "aligned":
        align_lift = 0.07 + min(0.05, max(0.0, structure_confidence) * 0.06)
        lift += align_lift
        reasons.append(f"align+{align_lift:.2f}")
    elif align == "supportive":
        lift += 0.04
        reasons.append("support+0.04")
    if level_edge:
        lift += 0.08
        reasons.append("level+0.08")
    if flat >= AGGRESSIVE_LEARNING_FLAT_BYPASS_MINUTES:
        flat_lift = min(0.08, (flat - AGGRESSIVE_LEARNING_FLAT_BYPASS_MINUTES) / 120.0)
        lift += flat_lift
        reasons.append(f"flat+{flat_lift:.2f}")

    lift = min(AGGRESSIVE_LEARNING_EDGE_LIFT_CAP, max(0.0, lift))
    effective_edge = max(edge, edge + lift)
    return effective_edge, lift, ",".join(reasons) if reasons else "none"


def should_aggressive_learning_bypass_block(block_reason: str, state: Optional[dict[str, Any]] = None) -> tuple[bool, str]:
    reason = str(block_reason or "")
    if not reason:
        return False, "no_block"
    if str(brain.get("risk_mode", "normal") or "normal") == "protection":
        return False, "protection"
    bypassable = (
        "squeeze structural gate" in reason
        or "squeeze final structural gate" in reason
        or "squeeze oracle caution block" in reason
        or "edge filter" in reason
        or "weak expected edge blocked" in reason
        or ("level gate" in reason and "level map not ready" not in reason)
    )
    if not bypassable:
        return False, "not_bypassable"
    if "room=" in reason and "bps < min=" in reason:
        return False, "room_gate_not_bypassable"

    gate = dict(state or brain.get("last_entry_gate_state", {}) or {})
    regime = str(gate.get("regime", brain.get("market_regime", {}).get("regime", "unknown")) or "unknown")
    if regime not in {"trend", "squeeze"}:
        return False, f"regime={regime}"
    flat_minutes = get_flat_duration_minutes()
    if flat_minutes < AGGRESSIVE_LEARNING_FLAT_BYPASS_MINUTES:
        return False, f"flat={flat_minutes:.1f}m"

    quality = float(gate.get("quality", brain.get("market_quality_score", 0.0)) or 0.0)
    oracle = gate.get("oracle_insight", {}) or {}
    oracle_score = float(oracle.get("score", 0.0) or 0.0)
    structure = brain.get("broader_structure") or {}
    struct_conf = float(structure.get("confidence", 0.0) or 0.0)
    align_score = float((gate.get("chop_alignment") or {}).get("score", 0.0) or 0.0)
    if max(quality, oracle_score, struct_conf, align_score) < AGGRESSIVE_LEARNING_STRUCT_CONF_FLOOR:
        return False, (
            f"weak_context q={quality:.2f} oracle={oracle_score:.2f} "
            f"struct={struct_conf:.2f} align={align_score:.2f}"
        )
    return True, (
        f"aggressive_learning_bypass flat={flat_minutes:.1f}m q={quality:.2f} "
        f"oracle={oracle_score:.2f} struct={struct_conf:.2f} align={align_score:.2f}"
    )


def build_exploration_lane_key(
    regime: str,
    regime_bias: str,
    policy: str,
    direction: str,
    session_bucket: str,
) -> str:
    return "|".join(
        [
            str(regime or "unknown"),
            str(regime_bias or "neutral"),
            str(policy or "unknown"),
            str(direction or "unknown"),
            str(session_bucket or "offhours"),
        ]
    )


def exploration_lane_key_from_candidate(
    candidate: dict[str, Any],
    regime: str,
    signal_ctx: dict[str, Any],
    regime_bias: Optional[str] = None,
) -> str:
    resolved_bias = str(regime_bias or brain.get("market_regime", {}).get("bias", "neutral") or "neutral")
    return build_exploration_lane_key(
        regime,
        resolved_bias,
        str(candidate.get("policy", "unknown") or "unknown"),
        str(candidate.get("direction", "unknown") or "unknown"),
        str(signal_ctx.get("session_bucket", "offhours") or "offhours"),
    )


def get_best_exploration_lane() -> dict[str, Any]:
    top = get_exploration_thresholds().get("top_lane", {}) or {}
    tuned_at = parse_iso_dt(top.get("last_tuned"))
    if not tuned_at:
        return {}
    if (datetime.now() - tuned_at).total_seconds() > EXPLORATION_LANE_MAX_AGE_HOURS * 3600:
        return {}
    if not bool(top.get("proven", False)):
        return {}
    # Proven lanes are only valid while the live context still matches them.
    # This prevents old shadow wins from pressing size into a regime flip.
    if get_top_lane_drift_guard_reason(top):
        return {}
    return top


def candidate_matches_best_lane(
    candidate: dict[str, Any],
    *,
    regime: str,
    regime_bias: str,
    signal_ctx: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    top = get_best_exploration_lane()
    if not top:
        return False, {}
    lane_key = exploration_lane_key_from_candidate(candidate, regime, signal_ctx, regime_bias)
    return lane_key == str(top.get("lane_key", "")), top


def split_exploration_lane_key(lane_key: str) -> dict[str, str]:
    parts = str(lane_key or "").split("|")
    while len(parts) < 5:
        parts.append("unknown")
    return {
        "regime": parts[0],
        "regime_bias": parts[1],
        "policy": parts[2],
        "direction": parts[3],
        "session_bucket": parts[4],
    }


def get_top_lane_drift_guard_reason(top_lane: dict[str, Any]) -> Optional[str]:
    if not top_lane:
        return None
    instability = float((brain.get("regime_transition", {}) or {}).get("instability", 0.0) or 0.0)
    if instability >= TUNER_DRIFT_FREEZE_INSTABILITY:
        return f"regime_instability={instability:.2f}"

    lane = split_exploration_lane_key(str(top_lane.get("lane_key", "")))
    current_regime = str((brain.get("market_regime", {}) or {}).get("regime", "unknown") or "unknown")
    current_bias = str((brain.get("market_regime", {}) or {}).get("bias", "neutral") or "neutral")
    current_session = str((brain.get("market_context", {}) or {}).get("session_bucket", "offhours") or "offhours")
    if lane["regime"] != current_regime:
        return f"regime_mismatch lane={lane['regime']} current={current_regime}"
    # Neutral live bias is the absence of a directional signal, not a
    # contradiction of the promoted lane's bias — don't freeze on it or the
    # tuner stays permanently locked during consolidation.
    if (
        lane["regime_bias"] != current_bias
        and current_bias != "neutral"
        and lane["regime_bias"] != "neutral"
    ):
        return f"bias_mismatch lane={lane['regime_bias']} current={current_bias}"
    if lane["session_bucket"] != current_session:
        return f"session_mismatch lane={lane['session_bucket']} current={current_session}"
    return None


def get_lane_allocation_plan(lane_key: str) -> dict[str, Any]:
    thresholds = get_exploration_thresholds()
    caps = thresholds.get("allocation_caps", {}) or {}
    qty_min = float(caps.get("qty_multiplier_min", 0.60) or 0.60)
    qty_max = float(caps.get("qty_multiplier_max", 1.0) or 1.0)
    risk_min = float(caps.get("risk_multiplier_min", 0.75) or 0.75)
    risk_max = float(caps.get("risk_multiplier_max", 1.0) or 1.0)
    top = get_best_exploration_lane()
    if top and lane_key == str(top.get("lane_key", "")):
        profit_score = float(top.get("profit_score", 0.0) or 0.0)
        ev_after_fee = float(top.get("ev_after_fee_bps", 0.0) or 0.0)
        bps_per_hour = float(top.get("bps_per_hour", 0.0) or 0.0)
        qty_mult = clamp(1.0 + profit_score / 450.0, 1.0, qty_max)
        risk_mult = clamp(1.0 + ev_after_fee / 350.0, 1.0, risk_max)
        return {
            "lane_key": lane_key,
            "qty_multiplier": round(qty_mult, 4),
            "risk_multiplier": round(risk_mult, 4),
            "reason": (
                f"top_profit_lane ev={ev_after_fee:+.1f}bps "
                f"bpsh={bps_per_hour:+.1f} score={profit_score:+.1f}"
            ),
        }

    stats = (thresholds.get("lane_stats", {}) or {}).get(lane_key, {}) or {}
    if stats:
        ev_after_fee = float(stats.get("ev_after_fee_bps", 0.0) or 0.0)
        fee_clear_rate = float(stats.get("fee_clear_rate", 0.0) or 0.0)
        if ev_after_fee < -10.0 or fee_clear_rate < 0.30:
            return {
                "lane_key": lane_key,
                "qty_multiplier": max(qty_min, 0.65),
                "risk_multiplier": max(risk_min, 0.80),
                "reason": f"weak_lane ev={ev_after_fee:+.1f}bps fcr={fee_clear_rate:.0%}",
            }

    return {
        "lane_key": lane_key,
        "qty_multiplier": 1.0,
        "risk_multiplier": 1.0,
        "reason": "neutral_lane_allocation",
    }


def apply_signal_allocation_tuning(
    signal: EntrySignal,
    *,
    lane_key: str,
    allocation_plan: dict[str, Any],
    adaptive: dict[str, Any],
) -> None:
    if signal.mode != "explore":
        return
    risk_mult = clamp(
        float(allocation_plan.get("risk_multiplier", 1.0) or 1.0),
        float((get_exploration_thresholds().get("allocation_caps", {}) or {}).get("risk_multiplier_min", 0.75) or 0.75),
        float((get_exploration_thresholds().get("allocation_caps", {}) or {}).get("risk_multiplier_max", 1.0) or 1.0),
    )
    qty_mult = clamp(
        float(allocation_plan.get("qty_multiplier", 1.0) or 1.0),
        float((get_exploration_thresholds().get("allocation_caps", {}) or {}).get("qty_multiplier_min", 0.60) or 0.60),
        float((get_exploration_thresholds().get("allocation_caps", {}) or {}).get("qty_multiplier_max", 1.0) or 1.0),
    )
    signal.risk_per_trade = min(
        float(signal.risk_per_trade or RISK_PER_TRADE) * risk_mult,
        float(adaptive.get("risk_per_trade", RISK_PER_TRADE) or RISK_PER_TRADE),
    )
    signal.base_risk_per_trade = signal.risk_per_trade
    signal.effective_risk_per_trade = signal.risk_per_trade
    signal.tuned_lane_key = lane_key
    signal.tuned_qty_multiplier = qty_mult
    signal.tuned_risk_multiplier = risk_mult
    signal.tuned_allocation_reason = str(allocation_plan.get("reason", "n/a"))

    # If this candidate matches the currently proven top lane, the tuner has
    # empirically-derived hold and trail suggestions. Apply them so the best
    # lane gets the exit plan its own resolved history supports:
    #   * max_hold_minutes can lengthen up to the suggested value (we never
    #     shorten a directional hold here — that's handled elsewhere).
    #   * trail_bps can loosen up to the suggested value so winners aren't
    #     trimmed on routine noise inside the proven lane.
    top_lane = get_best_exploration_lane()
    if top_lane and str(top_lane.get("lane_key", "")) == str(lane_key) and bool(top_lane.get("proven")):
        suggested_hold = int(top_lane.get("suggested_max_hold_minutes", 0) or 0)
        suggested_trail = int(top_lane.get("suggested_trail_bps", 0) or 0)
        if suggested_hold and suggested_hold > int(signal.max_hold_minutes or 0):
            signal.max_hold_minutes = suggested_hold
        if suggested_trail and suggested_trail > int(signal.trail_bps or 0):
            signal.trail_bps = suggested_trail
        signal.tuned_allocation_reason += (
            f" | top_lane_plan hold={signal.max_hold_minutes}m trail={signal.trail_bps}bps"
        )


def get_quality_floor() -> float:
    return float(brain.get("entry_thresholds", {}).get("quality_floor", 0.20))


def get_chop_align_min() -> float:
    return float(brain.get("entry_thresholds", {}).get("chop_align_min", CHOP_ALIGNMENT_MIN_SCORE))


def get_chop_align_live_min() -> float:
    return float(brain.get("entry_thresholds", {}).get("chop_align_live_min", CHOP_ALIGNMENT_MIN_LIVE_SCORE))


def get_range_width_min() -> float:
    return float(brain.get("entry_thresholds", {}).get("range_width_min_pct", CHOP_MIN_RANGE_WIDTH_PCT))


def get_fee_kill_ratio() -> float:
    return float(brain.get("entry_thresholds", {}).get("fee_kill_ratio", 0.625))


def get_directional_min_quality() -> float:
    return float(brain.get("entry_thresholds", {}).get("directional_min_quality", SMALL_ACCOUNT_DIRECTIONAL_MIN_QUALITY))


def get_directional_min_structure() -> float:
    return float(brain.get("entry_thresholds", {}).get("directional_min_structure", SMALL_ACCOUNT_DIRECTIONAL_MIN_STRUCTURE))


def get_directional_min_predictive() -> float:
    return float(brain.get("entry_thresholds", {}).get("directional_min_predictive", SMALL_ACCOUNT_DIRECTIONAL_MIN_PREDICTIVE))


def get_directional_min_edge() -> float:
    return float(brain.get("entry_thresholds", {}).get("directional_min_edge", SMALL_ACCOUNT_DIRECTIONAL_MIN_EDGE))


def get_breakout_min_predictive() -> float:
    return float(brain.get("entry_thresholds", {}).get("breakout_min_predictive", SMALL_ACCOUNT_BREAKOUT_MIN_PREDICTIVE))


def get_directional_flat_relief(regime: str, signal_ctx: dict[str, Any]) -> float:
    """
    Progressive relief on directional entry thresholds after extended flat periods
    in squeeze or trend regimes. Starts at 2h flat, reaches max at 4h flat.
    Only fires when regime is genuinely directional (non-neutral bias, aligned MTF).
    Max relief 0.14 — enough to unlock Asia-session quality 0.44 setups.
    """
    if regime not in {"squeeze", "trend"}:
        return 0.0
    regime_bias = str(brain.get("market_regime", {}).get("bias", "neutral") or "neutral")
    if regime_bias == "neutral":
        return 0.0
    flat_minutes = get_flat_duration_minutes()
    START = 60.0    # 1 hour flat → start relaxing
    FULL = 120.0    # 2 hours flat → full relief
    if flat_minutes < START:
        return 0.0
    flat_progress = min((flat_minutes - START) / max(FULL - START, 1.0), 1.0)
    mtf = str(signal_ctx.get("mtf_alignment", "mixed") or "mixed")
    mtf_support = 1.0 if (
        (regime_bias == "bullish" and mtf == "bullish") or
        (regime_bias == "bearish" and mtf == "bearish")
    ) else 0.6 if mtf == "mixed" else 0.2
    spread_ok = 1.0 if float(signal_ctx.get("spread_shock", 1.0) or 1.0) <= 1.30 else 0.0
    relief = flat_progress * (0.50 + mtf_support * 0.30 + spread_ok * 0.20)
    return round(min(relief * 0.14, 0.14), 4)


def tune_entry_thresholds() -> None:
    """
    Calibrate entry quality thresholds from actual trade + shadow outcomes.
    Tunes: quality_floor, fee_kill_ratio. Soft-blends 70/30. No-ops if data insufficient.
    """
    MIN_HISTORY = 30
    BLEND_OLD = 0.70
    BLEND_NEW = 0.30

    history = MEMORY.get("history", [])
    if len(history) < MIN_HISTORY:
        return

    recent = history[-80:]
    et = brain.setdefault("entry_thresholds", {})
    changes: list[str] = []

    # quality_floor — raise if overall win rate is persistently low, ease if high
    all_pnls = [float(r.get("net_pnl", 0.0) or 0.0) for r in recent]
    if len(all_pnls) >= 20:
        win_rate = sum(1 for p in all_pnls if p > 0) / len(all_pnls)
        current_floor = float(et.get("quality_floor", 0.20) or 0.20)
        if win_rate < 0.28:
            target_floor = min(0.30, current_floor + 0.01)
        elif win_rate > 0.48:
            target_floor = max(0.16, current_floor - 0.005)
        else:
            target_floor = current_floor
        new_floor = round(clamp(current_floor * BLEND_OLD + target_floor * BLEND_NEW, 0.16, 0.32), 4)
        if abs(new_floor - current_floor) >= 0.002:
            changes.append(f"quality_floor {current_floor:.3f}→{new_floor:.3f} (wr={win_rate:.1%})")
            et["quality_floor"] = new_floor

    # fee_kill_ratio — lower (trigger sooner) if fee-only losses dominate chop
    chop_recent = [
        r for r in recent
        if r.get("regime") == "chop"
        and r.get("intent") in {"mean_revert", None, ""}
    ]
    if len(chop_recent) >= 10:
        fee_only_losses = sum(
            1 for r in chop_recent
            if float(r.get("net_pnl", 0.0) or 0.0) < 0
            and float(r.get("fee", 0.0) or 0.0) > 0
            and abs(float(r.get("net_pnl", 0.0))) < abs(float(r.get("fee", 0.0))) * 1.8
        )
        fee_pressure = fee_only_losses / len(chop_recent)
        current_kill = float(et.get("fee_kill_ratio", 0.625) or 0.625)
        if fee_pressure > 0.50:
            target_kill = max(0.45, current_kill - 0.02)
        elif fee_pressure < 0.20:
            target_kill = min(0.75, current_kill + 0.01)
        else:
            target_kill = current_kill
        new_kill = round(clamp(current_kill * BLEND_OLD + target_kill * BLEND_NEW, 0.40, 0.80), 4)
        if abs(new_kill - current_kill) >= 0.005:
            changes.append(f"fee_kill {current_kill:.3f}→{new_kill:.3f} (fee_pressure={fee_pressure:.1%})")
            et["fee_kill_ratio"] = new_kill

    if not changes:
        return
    now_iso = datetime.now().isoformat()
    et["last_tuned"] = now_iso
    et["tune_count"] = int(et.get("tune_count", 0) or 0) + 1
    et["last_reason"] = "; ".join(changes)
    et.setdefault("history", []).append({"tuned_at": now_iso, "changes": changes})
    et["history"] = et["history"][-20:]
    log(f"Entry thresholds tuned | {' | '.join(changes)}")


def tune_range_thresholds() -> None:
    """
    Analyze recent live trades to find the level_position cutoffs where mean_revert
    long/short entries are actually profitable. Adjusts long_max / short_min by ±0.02
    with 70/30 soft blend. No-ops if insufficient mean_revert history.
    """
    MIN_MR_TRADES = 15
    BLEND_OLD = 0.70
    BLEND_NEW = 0.30

    history = MEMORY.get("history", [])
    mr_trades = [
        r for r in history[-100:]
        if r.get("intent") == "mean_revert"
        and r.get("net_pnl") is not None
        and r.get("level_position") is not None
    ]
    if len(mr_trades) < MIN_MR_TRADES:
        return

    rt = brain.setdefault("range_thresholds", {})
    changes: list[str] = []

    # long_max — find the level_position boundary below which longs succeed
    long_trades = [r for r in mr_trades if r.get("side") == "long" or r.get("direction") == "long"]
    if len(long_trades) >= 8:
        low_longs = [r for r in long_trades if float(r.get("level_position", 0.5) or 0.5) <= 0.35]
        high_longs = [r for r in long_trades if float(r.get("level_position", 0.5) or 0.5) > 0.35]
        low_wr = sum(1 for r in low_longs if float(r.get("net_pnl", 0.0) or 0.0) > 0) / max(len(low_longs), 1) if low_longs else 0.0
        high_wr = sum(1 for r in high_longs if float(r.get("net_pnl", 0.0) or 0.0) > 0) / max(len(high_longs), 1) if high_longs else 0.0
        current_long_max = float(rt.get("long_max", CHOP_RANGE_LONG_MAX) or CHOP_RANGE_LONG_MAX)
        if high_wr < 0.25 and len(high_longs) >= 4:
            target = max(0.15, current_long_max - 0.02)  # tighten: high entries fail
        elif low_wr > 0.42 and len(low_longs) >= 4:
            target = min(0.40, current_long_max + 0.02)  # loosen: low entries working
        else:
            target = current_long_max
        new_max = round(clamp(current_long_max * BLEND_OLD + target * BLEND_NEW, 0.12, 0.42), 3)
        if abs(new_max - current_long_max) >= 0.005:
            changes.append(f"long_max {current_long_max:.2f}→{new_max:.2f} (low_wr={low_wr:.1%} high_wr={high_wr:.1%})")
            rt["long_max"] = new_max

    # short_min — mirror logic
    short_trades = [r for r in mr_trades if r.get("side") == "short" or r.get("direction") == "short"]
    if len(short_trades) >= 8:
        high_shorts = [r for r in short_trades if float(r.get("level_position", 0.5) or 0.5) >= 0.65]
        low_shorts = [r for r in short_trades if float(r.get("level_position", 0.5) or 0.5) < 0.65]
        high_wr = sum(1 for r in high_shorts if float(r.get("net_pnl", 0.0) or 0.0) > 0) / max(len(high_shorts), 1) if high_shorts else 0.0
        low_wr = sum(1 for r in low_shorts if float(r.get("net_pnl", 0.0) or 0.0) > 0) / max(len(low_shorts), 1) if low_shorts else 0.0
        current_short_min = float(rt.get("short_min", CHOP_RANGE_SHORT_MIN) or CHOP_RANGE_SHORT_MIN)
        if low_wr < 0.25 and len(low_shorts) >= 4:
            target = min(0.85, current_short_min + 0.02)
        elif high_wr > 0.42 and len(high_shorts) >= 4:
            target = max(0.58, current_short_min - 0.02)
        else:
            target = current_short_min
        new_min = round(clamp(current_short_min * BLEND_OLD + target * BLEND_NEW, 0.58, 0.88), 3)
        if abs(new_min - current_short_min) >= 0.005:
            changes.append(f"short_min {current_short_min:.2f}→{new_min:.2f} (high_wr={high_wr:.1%} low_wr={low_wr:.1%})")
            rt["short_min"] = new_min

    if not changes:
        return
    now_iso = datetime.now().isoformat()
    rt["last_tuned"] = now_iso
    rt["tune_count"] = int(rt.get("tune_count", 0) or 0) + 1
    rt["last_reason"] = "; ".join(changes)
    rt.setdefault("history", []).append({"tuned_at": now_iso, "changes": changes})
    rt["history"] = rt["history"][-20:]
    log(f"Range thresholds tuned | {' | '.join(changes)}")


def tune_level_thresholds_from_shadow() -> None:
    """
    Sets breakout_long/short_shadow_ok once enough resolved level-gate shadows show
    positive FCR (>= 0.45). Revokes approval if subsequent evidence goes cold (FCR < 0.22
    with >= 8 resolved). Enables Path A in is_shadow_proven_breakout_level once proven.
    """
    MIN_RESOLVED = 4
    APPROVE_FCR = 0.45
    REVOKE_FCR = 0.22
    REVOKE_MIN = 8

    shadow_recent = (brain.get("shadow_exploration", {}) or {}).get("recent", [])[-100:]

    for direction in ("long", "short"):
        blocked = [
            item for item in shadow_recent
            if str(item.get("direction", "") or "") == direction
            and "level gate" in str(item.get("blocked_reason", "") or "")
            and item.get("resolved_at") is not None
        ]
        if len(blocked) < MIN_RESOLVED:
            continue

        fee_clears = sum(1 for item in blocked if item.get("fee_cleared", False))
        fcr = fee_clears / len(blocked)
        lt = brain.setdefault("level_thresholds", {})
        key = f"breakout_{direction}_shadow_ok"

        if fcr >= APPROVE_FCR and not lt.get(key, False):
            lt[key] = True
            lt["last_tuned"] = datetime.now().isoformat()
            log(f"Level tuner | {key} approved | fcr={fcr:.2f} n={len(blocked)}")
        elif lt.get(key, False) and fcr < REVOKE_FCR and len(blocked) >= REVOKE_MIN:
            lt[key] = False
            log(f"Level tuner | {key} revoked | fcr={fcr:.2f} n={len(blocked)}")


def tune_exploration_thresholds() -> None:
    """
    Shifts policy_fit_adjustments (-0.10..+0.08) based on blended live + shadow FCR.
    Updates lane_stats from recent exploration records for the drift-guard checks.
    Demotes losers faster than it promotes winners (asymmetric blend rates).
    No-ops if policies have insufficient evidence.
    """
    MIN_LIVE = 3
    MIN_SHADOW = 5
    BLEND_PROMOTE = 0.25   # slow promotion
    BLEND_DEMOTE  = 0.45   # fast demotion

    et = get_exploration_thresholds()
    live_policies   = (brain.get("exploration", {}) or {}).get("policies", {}) or {}
    shadow_policies = (brain.get("shadow_exploration", {}) or {}).get("policies", {}) or {}

    all_policies = set(live_policies) | set(shadow_policies)
    if not all_policies:
        return

    adjustments = dict(et.get("policy_fit_adjustments", {}) or {})
    changes: list[str] = []

    for policy in all_policies:
        live   = live_policies.get(policy, {}) or {}
        shadow = shadow_policies.get(policy, {}) or {}
        live_n   = int(live.get("trades", 0) or 0)
        shadow_n = int(shadow.get("resolved", 0) or 0)

        if live_n < MIN_LIVE and shadow_n < MIN_SHADOW:
            continue

        live_fcr   = float(live.get("fee_clear_rate", 0.0) or 0.0)   if live_n   >= MIN_LIVE   else None
        shadow_fcr = float(shadow.get("fee_clear_rate", 0.0) or 0.0) if shadow_n >= MIN_SHADOW else None

        if live_fcr is not None and shadow_fcr is not None:
            blended_fcr = live_fcr * 0.60 + shadow_fcr * 0.40
        elif live_fcr is not None:
            blended_fcr = live_fcr
        else:
            blended_fcr = shadow_fcr  # type: ignore[assignment]

        # Map FCR → target adjustment
        if blended_fcr >= 0.52:
            target = 0.06
        elif blended_fcr >= 0.42:
            target = 0.03
        elif blended_fcr >= 0.32:
            target = 0.00
        elif blended_fcr >= 0.22:
            target = -0.04
        else:
            target = -0.09

        # Extra boost if live score is strong
        live_score = float(live.get("score", 0.0) or 0.0)
        if live_n >= MIN_LIVE and live_score > 0.50:
            target = min(0.08, target + 0.02)

        existing = float(adjustments.get(policy, 0.0) or 0.0)
        blend = BLEND_PROMOTE if target >= existing else BLEND_DEMOTE
        new_adj = round(clamp(existing * (1.0 - blend) + target * blend, -0.10, 0.08), 4)

        if abs(new_adj - existing) >= 0.003:
            changes.append(f"{policy} {existing:+.3f}→{new_adj:+.3f} (fcr={blended_fcr:.2f})")
            adjustments[policy] = new_adj

    if not changes:
        return

    et["policy_fit_adjustments"] = adjustments

    # Rebuild lane_stats from recent exploration records
    recent_records = (brain.get("exploration", {}) or {}).get("recent", [])[-100:]
    lane_stats: dict[str, dict] = dict(et.get("lane_stats", {}) or {})
    for rec in recent_records:
        lane_key = str(rec.get("lane_key", "") or "")
        if not lane_key:
            continue
        pnl = float(rec.get("pnl", 0.0) or 0.0)
        fee_cleared = bool(rec.get("fee_cleared", False))
        adverse = abs(min(0.0, float(rec.get("min_unrealized_pnl", 0.0) or 0.0)))
        ls = lane_stats.setdefault(lane_key, {
            "lane_key": lane_key,
            "resolved": 0, "fee_clears": 0,
            "pnl_sum": 0.0, "adverse_bps_sum": 0.0,
            "fee_clear_rate": 0.0, "ev_after_fee_bps": 0.0,
            "avg_adverse_bps": 0.0, "profit_score": 0.0,
        })
        n_prev = int(ls.get("resolved", 0) or 0)
        ls["resolved"] = n_prev + 1
        ls["fee_clears"] = int(ls.get("fee_clears", 0) or 0) + (1 if fee_cleared else 0)
        ls["pnl_sum"] = float(ls.get("pnl_sum", 0.0) or 0.0) + pnl
        ls["adverse_bps_sum"] = float(ls.get("adverse_bps_sum", 0.0) or 0.0) + adverse
        n = ls["resolved"]
        ls["fee_clear_rate"] = round(ls["fee_clears"] / max(n, 1), 4)
        ls["ev_after_fee_bps"] = round(ls["pnl_sum"] / max(n, 1), 2)
        ls["avg_adverse_bps"] = round(ls["adverse_bps_sum"] / max(n, 1), 2)
        ls["profit_score"] = round(
            ls["fee_clear_rate"] * 0.5
            + clamp(ls["ev_after_fee_bps"] / 50.0, -0.3, 0.3)
            - clamp(ls["avg_adverse_bps"] / 100.0, 0.0, 0.2),
            4,
        )

    et["lane_stats"] = lane_stats
    et["last_reason"] = f"tuned {len(changes)} policies"
    et.setdefault("history", []).append({
        "tuned_at": datetime.now().isoformat(),
        "changes": changes,
    })
    et["history"] = et["history"][-20:]
    log(f"Exploration thresholds tuned | {' | '.join(changes)}")


def get_restored_regime() -> Optional[dict[str, Any]]:
    saved_regime = brain.get("market_regime", {})
    regime_name = saved_regime.get("regime", "unknown")
    if regime_name == "unknown":
        return None

    ts = (
        saved_regime.get("timestamp")
        or (brain.get("regime_history", [])[-1].get("time") if brain.get("regime_history") else None)
        or MEMORY.get("saved_at")
    )
    saved_at = parse_iso_dt(ts)
    if not saved_at:
        return None
    age = (datetime.now() - saved_at).total_seconds()
    if age > REGIME_RESTORE_MAX_AGE_SECONDS:
        return None

    restored = dict(saved_regime)
    restored["confidence"] = min(float(saved_regime.get("confidence", 0.0)), 0.6)
    restored["timestamp"] = saved_at.isoformat()
    restored["restored"] = True
    return restored


def extract_price_lnm(ticker) -> float:
    if not ticker:
        return 0.0
    keys = ("lastPrice", "last_price", "last", "price", "markPrice", "mark_price", "index")
    for key in keys:
        value = _safe_get(ticker, key)
        if value is None:
            continue
        try:
            price = float(value)
        except Exception:
            continue
        if price > 100:
            return price
    return 0.0


def extract_json(text: str) -> Optional[dict]:
    if not isinstance(text, str) or not text.strip():
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"```(?:json)?", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("```", "").strip()

    candidates = []
    if cleaned.startswith("{") and cleaned.endswith("}"):
        candidates.append(cleaned)
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        candidates.append(match.group(0))

    for candidate in candidates:
        variants = [
            candidate,
            re.sub(r",\s*([}\]])", r"\1", candidate),
            candidate.replace("'", '"'),
        ]
        for variant in variants:
            try:
                parsed = json.loads(variant)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

    log(f"JSON parse failed. Preview: {cleaned[:200]}")
    return None


def clamp_signal(parsed: dict) -> Optional[EntrySignal]:
    def to_int(value: Any, default: int) -> int:
        try:
            if value is None or value == "":
                return default
            return int(float(value))
        except (TypeError, ValueError):
            return default

    def to_float(value: Any, default: float) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    action = str(parsed.get("action", "hold")).lower().strip()
    if action not in {"open", "add", "reduce", "reverse", "close", "hold"}:
        action = "hold"
    direction = str(parsed.get("direction", "long")).lower().strip()
    if direction not in {"long", "short"}:
        direction = "long"

    intent = str(parsed.get("intent", "trend_follow")).lower().strip()
    if intent not in {"trend_follow", "mean_revert", "breakout", "scalp"}:
        # Unknown AI intent should not silently become trend-follow; safer to hold.
        action = "hold"
        intent = "mean_revert"

    confidence = max(0.0, min(1.0, to_float(parsed.get("confidence", 0.5), 0.5)))
    sl_bps = max(int(MIN_SL_PCT * 10000), to_int(parsed.get("sl_bps", 150), 150))
    tp_bps = max(int(sl_bps * MIN_TP_TO_SL), to_int(parsed.get("tp_bps", 250), 250))
    trail_bps = max(0, to_int(parsed.get("trail_bps", 80), 80))
    leverage = max(MIN_LEVERAGE, min(MAX_LEVERAGE, to_int(parsed.get("leverage", DEFAULT_LEVERAGE), DEFAULT_LEVERAGE)))
    max_hold_minutes = max(5, to_int(parsed.get("max_hold_minutes", 60), 60))
    reason = str(parsed.get("reason", "")).strip()[:240]
    quantity = to_int(parsed.get("quantity"), 0)
    quantity = quantity if quantity > 0 else None
    signal_price = float(brain.get("last_price") or market_state.get("last_price") or 0.0)

    # Enforce minimum TP to cover fees + buffer
    MIN_TP_BPS = 50
    tp_bps = max(tp_bps, MIN_TP_BPS)

    # Enforce minimum R:R of 1.5
    if tp_bps < sl_bps * 1.5:
        tp_bps = int(sl_bps * 1.5)

    return EntrySignal(
        action=action,
        direction=direction,
        intent=intent,
        mode="exploit",
        policy="ai_primary",
        confidence=confidence,
        sl_bps=sl_bps,
        tp_bps=tp_bps,
        trail_bps=trail_bps,
        leverage=leverage,
        max_hold_minutes=max_hold_minutes,
        risk_per_trade=RISK_PER_TRADE,
        reason=reason,
        quantity=quantity,
        signal_price=signal_price,
    )


def coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def build_review_signal(parsed: dict) -> dict[str, Any]:
    action = str(parsed.get("action", "hold")).lower().strip()
    if action not in {"hold", "close", "add", "reduce"}:
        action = "hold"
    direction = str(parsed.get("direction", "")).lower().strip()
    if direction not in {"long", "short"}:
        direction = ""
    quantity = parsed.get("quantity")
    try:
        quantity = int(float(quantity)) if quantity not in (None, "") else None
    except (TypeError, ValueError):
        quantity = None
    if quantity is not None and quantity <= 0:
        quantity = None
    return {
        "action": action,
        "reason": str(parsed.get("reason", "")).strip()[:240],
        "direction": direction,
        "quantity": quantity,
    }


def normalize_position_action(
    action: str,
    direction: Optional[str],
    current_side: Optional[str],
) -> tuple[str, Optional[str], Optional[str]]:
    """Normalize action semantics for one-net-position cross trading."""
    if not current_side or not direction:
        return action, direction, None

    opposite = "short" if current_side == "long" else "long"

    if action == "reduce" and direction == current_side:
        return action, opposite, f"Normalized reduce direction {direction}->{opposite}"

    if action == "add" and direction != current_side:
        return "reduce", opposite, f"Converted opposite-direction add into reduce {direction}->{opposite}"

    return action, direction, None


def compute_regime() -> dict[str, float | str]:
    if len(PRICE_WINDOW) < 20:
        restored = get_restored_regime()
        if restored:
            return restored
        return {
            "regime": "unknown",
            "bias": "neutral",
            "regime_flavor": "unknown",
            "volatility": 0.0,
            "trend_strength": 0.0,
            "compression": 0.0,
            "confidence": 0.0,
            "timestamp": datetime.now().isoformat(),
        }

    prices = np.array(PRICE_WINDOW, dtype=float)
    returns = np.diff(prices) / prices[:-1]
    volatility = float(np.std(returns))
    x = np.arange(len(prices))
    slope = float(np.polyfit(x, prices, 1)[0])
    normalized_slope = slope / max(float(np.mean(prices)), 1e-9)
    signed_trend_strength = float(normalized_slope)
    trend_strength = abs(signed_trend_strength)
    recent = prices[-20:]
    compression = float((np.max(recent) - np.min(recent)) / max(float(np.mean(recent)), 1e-9))
    mtf_windows = {
        "short": prices[-20:],
        "medium": prices[-60:] if len(prices) >= 60 else prices,
        "long": prices[-180:] if len(prices) >= 180 else prices,
    }
    mtf_slopes = {}
    for key, window_prices in mtf_windows.items():
        wx = np.arange(len(window_prices), dtype=float)
        window_slope = float(np.polyfit(wx, window_prices, 1)[0]) if len(window_prices) >= 8 else 0.0
        mtf_slopes[key] = window_slope / max(float(np.mean(window_prices)), 1e-9)
    mtf_signs = [1 if val > 0 else -1 if val < 0 else 0 for val in mtf_slopes.values()]
    mtf_alignment_score = sum(mtf_signs)
    drift_20 = ((prices[-1] / prices[-20]) - 1.0) if len(prices) >= 20 else 0.0
    drift_60 = ((prices[-1] / prices[-60]) - 1.0) if len(prices) >= 60 else drift_20
    directional_drift = max(abs(drift_20), abs(drift_60))
    if mtf_alignment_score >= 2 and (signed_trend_strength > 0 or drift_20 > 0):
        bias = "bullish"
    elif mtf_alignment_score <= -2 and (signed_trend_strength < 0 or drift_20 < 0):
        bias = "bearish"
    else:
        bias = "neutral"

    regime = "chop"
    if volatility > 0.004:
        regime = "volatile"
    if (
        trend_strength > 0.0011
        and volatility < 0.0045
        and directional_drift > 0.0035
        and abs(mtf_alignment_score) >= 2
    ):
        regime = "trend"
    if compression < 0.01 and trend_strength < 0.0012 and volatility <= 0.004:
        regime = "squeeze"
    if volatility < 0.002 and trend_strength < 0.0008 and abs(mtf_alignment_score) < 2 and compression >= 0.01:
        regime = "chop"

    confidence = min(1.0, (volatility + trend_strength + compression) * 50)
    regime_flavor = regime if bias == "neutral" else f"{bias}_{regime}"
    return {
        "regime": regime,
        "bias": bias,
        "regime_flavor": regime_flavor,
        "volatility": volatility,
        "trend_strength": trend_strength,
        "signed_trend_strength": signed_trend_strength,
        "compression": compression,
        "mtf_alignment_score": float(mtf_alignment_score),
        "directional_drift": float(directional_drift),
        "confidence": float(confidence),
        "timestamp": datetime.now().isoformat(),
    }


def detect_regime_transition(window: int = 10) -> dict[str, Any]:
    history = [x.get("regime", "unknown") for x in brain.get("regime_history", [])[-window:] if isinstance(x, dict)]
    if len(history) < 2:
        return {
            "current": history[-1] if history else "unknown",
            "dominant_prev": "unknown",
            "next_likely": "unknown",
            "instability": 0.0,
            "confidence": 0.0,
            "risk_multiplier": 1.0,
        }

    current = history[-1]
    counts: dict[str, int] = {}
    for regime in history:
        counts[regime] = counts.get(regime, 0) + 1
    dominant_prev = max(counts, key=counts.get)
    changes = sum(1 for idx in range(1, len(history)) if history[idx] != history[idx - 1])
    instability = changes / max(len(history) - 1, 1)

    next_likely = current
    confidence = 0.5
    if instability > 0.6:
        next_likely = "chop"
        confidence = 0.75
    elif counts.get("trend", 0) >= 6:
        next_likely = "trend"
        confidence = 0.8
    elif counts.get("volatile", 0) >= 4:
        next_likely = "volatile"
        confidence = 0.75
    elif counts.get("squeeze", 0) >= 3:
        next_likely = "squeeze"
        confidence = 0.7

    risk_multiplier = 1.0
    if instability > 0.7:
        risk_multiplier = 0.4
    elif current != dominant_prev:
        risk_multiplier = 0.7
    elif counts.get(current, 0) >= window * 0.7:
        risk_multiplier = 1.2

    return {
        "current": current,
        "dominant_prev": dominant_prev,
        "next_likely": next_likely,
        "instability": instability,
        "confidence": confidence,
        "risk_multiplier": risk_multiplier,
    }


def get_regime_weights() -> dict[str, float]:
    weights = {}
    for regime, data in brain.get("regime_stats", {}).items():
        trades = max(int(data.get("trades", 0)), 1)
        avg_pnl = float(data.get("pnl", 0.0)) / trades
        weights[regime] = max(-1.0, min(1.0, avg_pnl / 100))
    oracle = brain.get("oracle_replay", {})
    oracle_stats = oracle.get("regime_stats", {})
    oracle_weights = oracle.get("regime_weights", {})
    oracle_scores = oracle.get("regime_scores", {})
    for regime in ("trend", "squeeze"):
        replay_trades = int((oracle_stats.get(regime) or {}).get("trades", 0))
        replay_samples = int((oracle_scores.get(regime) or {}).get("samples", 0))
        if replay_trades < 6 and replay_samples < 40:
            continue
        live_weight = float(weights.get(regime, 0.0) or 0.0)
        replay_weight = float(oracle_weights.get(regime, 0.0) or 0.0)
        weights[regime] = max(-1.0, min(1.0, live_weight * (1.0 - ORACLE_REGIME_BLEND) + replay_weight * ORACLE_REGIME_BLEND))
    return weights


def compute_entry_quality_bias() -> dict[str, Any]:
    """
    Learn from closed trade history: compute win rates for key entry conditions
    and derive composite score biases. Runs on boot and every ENTRY_BIAS_UPDATE_INTERVAL
    trades. Results stored in brain["entry_quality_bias"].
    """
    history = MEMORY.get("history", [])
    trades = [
        r for r in history
        if r.get("net_pnl") is not None
        and r.get("regime") is not None
        and r.get("level_alignment") is not None
    ]
    if len(trades) < 20:
        return {}

    def _bucket_stats(items: list[dict[str, Any]]) -> dict[str, Any]:
        pnls = [float(r["net_pnl"]) for r in items]
        wins = sum(1 for p in pnls if p > 0)
        n = len(pnls)
        return {"n": n, "win_rate": round(wins / n, 3), "avg_pnl": round(sum(pnls) / n, 2)}

    # Entry conditions → win rate buckets
    spring_longs = [r for r in trades if r.get("wyckoff_spring_long") and r.get("side") == "long"]
    spring_shorts = [r for r in trades if r.get("wyckoff_spring_short") and r.get("side") == "short"]
    reclaim_longs = [r for r in trades if "reclaim" in (r.get("entry_tag") or "") and r.get("side") == "long"]
    reclaim_shorts = [r for r in trades if "reclaim" in (r.get("entry_tag") or "") and r.get("side") == "short"]
    support_longs = [r for r in trades if r.get("at_support") and r.get("side") == "long"]
    resistance_shorts = [r for r in trades if r.get("at_resistance") and r.get("side") == "short"]
    wrong_side_longs = [r for r in trades if r.get("level_alignment") == "resistance" and r.get("side") == "long"]
    wrong_side_shorts = [r for r in trades if r.get("level_alignment") == "support" and r.get("side") == "short"]

    result: dict[str, Any] = {
        "computed_at": datetime.now().isoformat(),
        "trade_count": len(trades),
        "spring_long": _bucket_stats(spring_longs) if spring_longs else {},
        "spring_short": _bucket_stats(spring_shorts) if spring_shorts else {},
        "reclaim_long": _bucket_stats(reclaim_longs) if reclaim_longs else {},
        "reclaim_short": _bucket_stats(reclaim_shorts) if reclaim_shorts else {},
        "support_long": _bucket_stats(support_longs) if support_longs else {},
        "resistance_short": _bucket_stats(resistance_shorts) if resistance_shorts else {},
        "wrong_side_long": _bucket_stats(wrong_side_longs) if wrong_side_longs else {},
        "wrong_side_short": _bucket_stats(wrong_side_shorts) if wrong_side_shorts else {},
    }

    # Derive composite score biases from win rate deltas vs baseline
    baseline_wr = _bucket_stats(trades)["win_rate"]
    def _bias(bucket: dict[str, Any], min_n: int = 5) -> float:
        if bucket.get("n", 0) < min_n:
            return 0.0
        delta = bucket["win_rate"] - baseline_wr
        return round(clamp(delta * 0.20, -0.08, 0.12), 4)

    result["biases"] = {
        "wyckoff_spring": _bias(result["spring_long"]) if spring_longs else _bias(result["spring_short"]) if spring_shorts else 0.08,
        "reclaim": _bias({**_bucket_stats(reclaim_longs + reclaim_shorts)} if reclaim_longs or reclaim_shorts else {}),
        "wrong_side_long_penalty": _bias(result["wrong_side_long"]),
        "wrong_side_short_penalty": _bias(result["wrong_side_short"]),
    }

    log(
        f"Entry quality bias updated | n={len(trades)} baseline_wr={baseline_wr:.1%} "
        f"spring_wr={result['spring_long'].get('win_rate', 0):.1%} "
        f"reclaim_wr={_bucket_stats(reclaim_longs + reclaim_shorts).get('win_rate', 0) if (reclaim_longs or reclaim_shorts) else 0:.1%} "
        f"wrong_side_l_wr={result['wrong_side_long'].get('win_rate', 0):.1%}"
    )
    brain["entry_quality_bias"] = result
    return result


def get_entry_quality_bias() -> dict[str, Any]:
    return brain.get("entry_quality_bias") or {}


# ---------------------------------------------------------------------------
# Post-exit price tracker + exit quality bias learner
# ---------------------------------------------------------------------------

POST_EXIT_CHECKPOINTS = (5, 15, 30)  # minutes after exit to sample price


async def track_post_exit_prices(trade_id: str, exit_price: float, side: str, exit_reason: str) -> None:
    """
    Sample price at 5m, 15m, 30m after exit and update the matching trade record
    in MEMORY["history"]. Adverse = price moved back toward the trade (shakeout).
    """
    if not trade_id or exit_price <= 0:
        return
    prev_checkpoint = 0
    for minutes in POST_EXIT_CHECKPOINTS:
        delay = (minutes - prev_checkpoint) * 60
        await asyncio.sleep(delay)
        prev_checkpoint = minutes
        current_price = float(brain.get("last_price", 0.0) or 0.0)
        if current_price <= 0:
            continue
        move_bps = (current_price - exit_price) / exit_price * 10000.0
        # For a LONG that was closed: adverse = price moved UP (we missed gains / got shaken out)
        # For a SHORT that was closed: adverse = price moved DOWN
        adverse_bps = move_bps if side == "long" else -move_bps
        label = f"post_{minutes}m"
        # Update the matching history record in-place
        history = MEMORY.get("history", [])
        for trade in reversed(history[-100:]):
            if trade.get("id") == trade_id:
                pe = trade.setdefault("post_exit", {})
                pe[label] = {
                    "price": round(current_price, 2),
                    "move_bps": round(move_bps, 2),
                    "adverse_bps": round(adverse_bps, 2),
                }
                break
    # After all checkpoints, compute a shakeout label on the record
    history = MEMORY.get("history", [])
    for trade in reversed(history[-100:]):
        if trade.get("id") == trade_id:
            pe = trade.get("post_exit", {})
            # shakeout = price moved adversely >= 15 bps within 15 min
            adv_15 = float((pe.get("post_15m") or {}).get("adverse_bps", 0.0))
            adv_30 = float((pe.get("post_30m") or {}).get("adverse_bps", 0.0))
            pe["shakeout"] = bool(max(adv_15, adv_30) >= 15.0)
            pe["max_adverse_bps"] = round(max(adv_15, adv_30), 2)
            pe["exit_reason_short"] = exit_reason.split("|")[0].strip()[:40]
            break
    maybe_save_memory()
    log(
        f"Post-exit tracked | id={trade_id[:8]} side={side} "
        f"exit={exit_price:.0f} +5m={float((pe.get('post_5m') or {}).get('move_bps', 0)):.1f}bps "
        f"+15m={float((pe.get('post_15m') or {}).get('move_bps', 0)):.1f}bps "
        f"+30m={float((pe.get('post_30m') or {}).get('move_bps', 0)):.1f}bps "
        f"shakeout={pe.get('shakeout')}"
    )


def compute_exit_quality_bias() -> dict[str, Any]:
    """
    Analyse post-exit price observations to learn which exit conditions produce
    shakeouts (false exits) vs. confirmed exits. Updates brain["exit_quality_bias"].
    """
    history = MEMORY.get("history", [])
    tracked = [
        r for r in history
        if isinstance(r.get("post_exit"), dict)
        and r["post_exit"].get("shakeout") is not None
        and r.get("exit_reason") is not None
    ]
    if len(tracked) < 5:
        return {}

    def _bucket(items: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(items)
        shakeouts = sum(1 for r in items if r.get("post_exit", {}).get("shakeout"))
        avg_adv = sum(float(r.get("post_exit", {}).get("max_adverse_bps", 0)) for r in items) / max(n, 1)
        return {"n": n, "shakeout_rate": round(shakeouts / n, 3), "avg_adverse_bps": round(avg_adv, 2)}

    # Group by simplified exit reason
    from collections import defaultdict
    reason_buckets: dict[str, list] = defaultdict(list)
    for r in tracked:
        reason_key = (r.get("post_exit") or {}).get("exit_reason_short") or r.get("exit_reason", "?")[:40]
        simplified = (
            "DET_THESIS_BREAK" if "THESIS_BREAK" in reason_key
            else "SL_HIT" if "SL_HIT" in reason_key
            else "DYN_REBALANCE" if "DYN_REBALANCE" in reason_key
            else "TP_HIT" if "TP_HIT" in reason_key
            else "OTHER"
        )
        reason_buckets[simplified].append(r)

    # Group by close_alignment quartile at exit
    ca_buckets: dict[str, list] = defaultdict(list)
    for r in tracked:
        ca = float(r.get("close_alignment", 0.0) or 0.0)
        ca_buckets["ca_high" if ca >= 0.60 else "ca_mid" if ca >= 0.35 else "ca_low"].append(r)

    result: dict[str, Any] = {
        "computed_at": datetime.now().isoformat(),
        "tracked_count": len(tracked),
        "by_reason": {k: _bucket(v) for k, v in reason_buckets.items()},
        "by_close_alignment": {k: _bucket(v) for k, v in ca_buckets.items()},
        "overall": _bucket(tracked),
    }

    # Per-side DET_THESIS_BREAK buckets (longs shake out far more than shorts)
    det_all = reason_buckets.get("DET_THESIS_BREAK", [])
    det_longs = [r for r in det_all if r.get("side") == "long"]
    det_shorts = [r for r in det_all if r.get("side") == "short"]

    def _shakeout_rate(items: list[dict[str, Any]]) -> float:
        if not items:
            return 0.0
        return sum(1 for r in items if r.get("post_exit", {}).get("shakeout")) / len(items)

    det_long_rate = _shakeout_rate(det_longs)
    det_short_rate = _shakeout_rate(det_shorts)
    sl_shakeout_rate = float(result["by_reason"].get("SL_HIT", {}).get("shakeout_rate", 0.0))
    ca_high_stats = result["by_close_alignment"].get("ca_high", {})
    ca_low_stats = result["by_close_alignment"].get("ca_low", {})

    # Per-side DET loosening: longs get up to +10 bps, shorts up to +5 bps
    # Floor at 25% shakeout rate — below that we leave the threshold alone
    det_long_loosening_bps = round(clamp((det_long_rate - 0.25) * 40.0, 0.0, 10.0), 2)
    det_short_loosening_bps = round(clamp((det_short_rate - 0.25) * 20.0, 0.0, 5.0), 2)

    # SL loosening (unchanged formula, modest)
    sl_loosening_bps = round(clamp((sl_shakeout_rate - 0.20) * 0.5, 0.0, 0.12) * 15, 2)

    # close_alignment exit threshold — loosen if high-CA exits are shaking out badly
    ca_threshold = 0.55
    if ca_high_stats.get("n", 0) >= 3 and ca_low_stats.get("n", 0) >= 3:
        high_shake = float(ca_high_stats.get("shakeout_rate", 0.5))
        low_shake = float(ca_low_stats.get("shakeout_rate", 0.5))
        if high_shake < low_shake - 0.15:
            ca_threshold = 0.60
        elif high_shake > low_shake + 0.10:
            ca_threshold = 0.50

    result["biases"] = {
        "det_long_loosening_bps": det_long_loosening_bps,
        "det_short_loosening_bps": det_short_loosening_bps,
        "sl_loosening_bps": sl_loosening_bps,
        "close_alignment_exit_threshold": round(ca_threshold, 3),
        "det_long_shakeout_rate": round(det_long_rate, 3),
        "det_short_shakeout_rate": round(det_short_rate, 3),
        "det_long_n": len(det_longs),
        "det_short_n": len(det_shorts),
        "sl_shakeout_rate": round(sl_shakeout_rate, 3),
    }

    log(
        f"Exit quality bias | n={len(tracked)} "
        f"DET long={det_long_rate:.0%}(n={len(det_longs)}) +{det_long_loosening_bps}bps "
        f"short={det_short_rate:.0%}(n={len(det_shorts)}) +{det_short_loosening_bps}bps "
        f"SL={sl_shakeout_rate:.0%} ca_thr={ca_threshold:.2f}"
    )
    brain["exit_quality_bias"] = result
    return result


def get_exit_quality_bias() -> dict[str, Any]:
    return brain.get("exit_quality_bias") or {}


def get_oracle_regime_insight(regime: str) -> dict[str, float]:
    oracle = brain.get("oracle_replay", {})
    score_blob = ((oracle.get("regime_scores", {}) or {}).get(regime) or {})
    stats_blob = ((oracle.get("regime_stats", {}) or {}).get(regime) or {})
    context_blob = ((oracle.get("regime_context", {}) or {}).get(regime) or {})
    samples = int(score_blob.get("samples", 0) or 0)
    trades = int(stats_blob.get("trades", 0) or 0)
    avg_score = float(score_blob.get("score_sum", 0.0) or 0.0) / max(samples, 1) if samples else 0.0
    weight = float((oracle.get("regime_weights", {}) or {}).get(regime, 0.0) or 0.0)
    fee_clear_rate = float(stats_blob.get("fee_clears", 0) or 0.0) / max(trades, 1) if trades else 0.0
    avg_peak_bps = float(stats_blob.get("peak_bps_sum", 0.0) or 0.0) / max(trades, 1) if trades else 0.0
    avg_adverse_bps = float(stats_blob.get("adverse_bps_sum", 0.0) or 0.0) / max(trades, 1) if trades else 0.0
    fee_clear_timed_count = int(stats_blob.get("fee_clear_timed_count", 0) or 0)
    avg_time_to_fee_clear = (
        float(stats_blob.get("time_to_fee_clear_sum", 0.0) or 0.0) / max(fee_clear_timed_count, 1)
        if fee_clear_timed_count else 0.0
    )
    fee_clear_before_half_rate = float(stats_blob.get("fee_clear_before_half_count", 0) or 0.0) / max(trades, 1) if trades else 0.0
    avg_fade_after_peak = float(stats_blob.get("fade_after_peak_sum", 0.0) or 0.0) / max(trades, 1) if trades else 0.0
    degrade_after_peak_rate = float(stats_blob.get("degrade_after_peak_count", 0) or 0.0) / max(trades, 1) if trades else 0.0
    return {
        "samples": samples,
        "trades": trades,
        "score": avg_score,
        "weight": weight,
        "fee_clear_rate": fee_clear_rate,
        "avg_peak_bps": avg_peak_bps,
        "avg_adverse_bps": avg_adverse_bps,
        "avg_time_to_fee_clear": avg_time_to_fee_clear,
        "fee_clear_before_half_rate": fee_clear_before_half_rate,
        "avg_fade_after_peak": avg_fade_after_peak,
        "degrade_after_peak_rate": degrade_after_peak_rate,
        "dominant_bias": str(context_blob.get("dominant_bias", "neutral")),
        "dominant_flavor": str(context_blob.get("dominant_flavor", regime)),
        "avg_signed_trend_strength": float(context_blob.get("avg_signed_trend_strength", 0.0) or 0.0),
        "avg_directional_drift": float(context_blob.get("avg_directional_drift", 0.0) or 0.0),
        "avg_mtf_alignment_score": float(context_blob.get("avg_mtf_alignment_score", 0.0) or 0.0),
        "bullish_bias_rate": float(context_blob.get("bullish_bias_rate", 0.0) or 0.0),
        "bearish_bias_rate": float(context_blob.get("bearish_bias_rate", 0.0) or 0.0),
        "neutral_bias_rate": float(context_blob.get("neutral_bias_rate", 0.0) or 0.0),
    }


def get_live_chop_evidence() -> dict[str, float]:
    recent = brain.get("exploration", {}).get("recent", [])
    resolved = [
        item for item in recent[-30:]
        if item.get("regime") == "chop" and item.get("outcome_pnl") is not None
    ]
    trades = len(resolved)
    if not trades:
        return {
            "trades": 0,
            "fee_clear_rate": 0.0,
            "avg_peak_fee_multiple": 0.0,
            "avg_outcome_pnl": 0.0,
            "recent_fee_only_losses": 0,
        }
    fee_clears = sum(1 for item in resolved if item.get("fee_cleared"))
    avg_peak_fee_multiple = sum(float(item.get("max_fee_multiple", 0.0) or 0.0) for item in resolved) / trades
    avg_outcome_pnl = sum(float(item.get("outcome_pnl", 0.0) or 0.0) for item in resolved) / trades
    fee_loss_pressure = 0.0
    now = datetime.now()
    for item in resolved[-6:]:
        if not (
            float(item.get("outcome_pnl", 0.0) or 0.0) < 0
            and float(item.get("max_fee_multiple", 0.0) or 0.0) < 0.4
        ):
            continue
        ts = parse_iso_dt(item.get("timestamp"))
        age_minutes = max((now - ts).total_seconds() / 60.0, 0.0) if ts else 180.0
        fee_loss_pressure += max(0.0, min(1.0, np.exp(-age_minutes / 75.0)))
    recent_fee_only_losses = sum(
        1
        for item in resolved[-3:]
        if float(item.get("outcome_pnl", 0.0) or 0.0) < 0
        and float(item.get("max_fee_multiple", 0.0) or 0.0) < 0.5
    )
    return {
        "trades": trades,
        "fee_clear_rate": fee_clears / trades,
        "avg_peak_fee_multiple": avg_peak_fee_multiple,
        "avg_outcome_pnl": avg_outcome_pnl,
        "recent_fee_only_losses": recent_fee_only_losses,
        "recent_fee_loss_pressure": round(fee_loss_pressure, 4),
    }


def get_flat_duration_minutes() -> float:
    started_at = parse_iso_dt(brain.get("flat_started_at"))
    if not started_at:
        return 0.0
    return max((datetime.now() - started_at).total_seconds() / 60.0, 0.0)


def get_caution_decay_multiplier() -> float:
    flat_minutes = get_flat_duration_minutes()
    if flat_minutes <= CAUTION_DECAY_START_MINUTES:
        return 1.0
    progress = min(
        (flat_minutes - CAUTION_DECAY_START_MINUTES)
        / max(CAUTION_DECAY_FULL_MINUTES - CAUTION_DECAY_START_MINUTES, 1.0),
        1.0,
    )
    return 1.0 - (1.0 - CAUTION_DECAY_MIN_MULTIPLIER) * progress


def get_chop_reactivation_relief(state: dict[str, Any]) -> float:
    regime = str(state.get("regime", "unknown"))
    if regime != "chop":
        return 0.0
    signal_ctx = state.get("signal_ctx", {}) or {}
    oracle_insight = state.get("oracle_insight", {}) or {}
    quality = float(state.get("quality", 0.0) or 0.0)
    flat_minutes = get_flat_duration_minutes()
    if flat_minutes < FLAT_REACTIVATION_START_MINUTES:
        return 0.0

    flat_progress = min(
        max(flat_minutes - FLAT_REACTIVATION_START_MINUTES, 0.0)
        / max(FLAT_REACTIVATION_FULL_MINUTES - FLAT_REACTIVATION_START_MINUTES, 1.0),
        1.0,
    )
    replay_support = min(max((float(oracle_insight.get("score", 0.0) or 0.0) - 0.52) / 0.12, 0.0), 1.0)
    spread_support = 1.0 if float(signal_ctx.get("spread_shock", 1.0) or 1.0) <= 1.20 else 0.0
    vol_state = str(signal_ctx.get("volatility_state", "normal"))
    volatility_support = 1.0 if vol_state in {"compressed", "normal"} else 0.0
    mtf_support = 1.0 if str(signal_ctx.get("mtf_alignment", "mixed")) == "mixed" else 0.0
    quality_support = min(max((quality - 0.30) / 0.12, 0.0), 1.0)

    relief = (
        flat_progress * 0.35
        + replay_support * 0.25
        + spread_support * 0.15
        + volatility_support * 0.10
        + mtf_support * 0.05
        + quality_support * 0.10
    ) * MAX_CHOP_REACTIVATION_RELIEF
    return round(relief, 4)


def get_default_chop_alignment() -> dict[str, Any]:
    return {
        "score": 0.0,
        "live_evidence": {},
        "components": {},
        "component_summary": "n/a",
    }


def is_hard_exit_reason(reason: str) -> bool:
    normalized = str(reason or "").upper()
    return any(token in normalized for token in ("SL_HIT", "TP_HIT", "KILL_SWITCH"))


def get_broken_exit_adverse_bps(side: str = "") -> float:
    regime = str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown")
    # Recent live losses showed the old squeeze override waited too long:
    # weak longs were reduced only after 37-65bps adverse moves. Keep the same
    # strict two-factor gate, but do not loosen it just because the market is
    # coiled.
    base = BROKEN_EXIT_ADVERSE_MOVE_BPS
    biases = get_exit_quality_bias().get("biases", {})
    if side == "long":
        loosening = float(biases.get("det_long_loosening_bps", 0.0) or 0.0)
    elif side == "short":
        loosening = float(biases.get("det_short_loosening_bps", 0.0) or 0.0)
    else:
        # Unknown side: use the larger of the two (conservative — don't exit too early)
        loosening = max(
            float(biases.get("det_long_loosening_bps", 0.0) or 0.0),
            float(biases.get("det_short_loosening_bps", 0.0) or 0.0),
        )
    return base + loosening


def get_broken_exit_thesis_score() -> float:
    return BROKEN_EXIT_THESIS_SCORE


def is_clearly_broken_exit(position: "PositionState", thesis: dict[str, Any], price: float) -> tuple[bool, str]:
    thesis_score = float(thesis.get("score", 0.0) or 0.0)
    raw_move_bps = get_raw_entry_move_bps(position, price)
    adverse_move_bps = raw_move_bps if position.side == "short" else -raw_move_bps
    broken_exit_thesis = get_broken_exit_thesis_score()
    broken_exit_adverse = get_broken_exit_adverse_bps(position.side or "")
    close_alignment = compute_close_alignment(position, thesis, price)
    close_align_score = float(close_alignment.get("score", 0.0) or 0.0)
    peak_fee_multiple = float(thesis.get("peak_fee_multiple", 0.0) or 0.0)
    max_hold_minutes = float(position.max_hold_minutes or 0.0)
    age_minutes = float(position.age_minutes or 0.0)
    stale_broken_escape = bool(
        max_hold_minutes > 0.0
        and age_minutes >= max(max_hold_minutes, 28.0)
        and thesis_score <= (broken_exit_thesis - 0.05)
        and adverse_move_bps >= max(10.0, BROKEN_EXIT_ADVERSE_MOVE_BPS - 2.0)
        and (close_align_score >= 0.30 or peak_fee_multiple < 0.25)
    )
    clearly_broken = bool(
        (
            thesis_score <= broken_exit_thesis
            and adverse_move_bps >= broken_exit_adverse
        )
        or stale_broken_escape
    )
    escape_note = (
        f" stale_escape age={age_minutes:.1f}/{max_hold_minutes:.1f}m "
        f"close_align={close_align_score:+.2f} peak_fee={peak_fee_multiple:+.2f}"
        if stale_broken_escape else ""
    )
    return (
        clearly_broken,
        (
            f"thesis={thesis_score:+.2f} raw_move={raw_move_bps:+.1f}bps "
            f"adverse={adverse_move_bps:+.1f}bps{escape_note}"
        ),
    )


def ai_review_close_gate(position: "PositionState", thesis: dict[str, Any], price: float) -> tuple[bool, float, float]:
    thesis_score = float(thesis.get("score", 0.0) or 0.0)
    raw_move_bps = get_raw_entry_move_bps(position, price)
    clearly_broken, _ = is_clearly_broken_exit(position, thesis, price)
    return clearly_broken, thesis_score, raw_move_bps


def format_strict_exit_requirement() -> str:
    return (
        f"requires thesis<={get_broken_exit_thesis_score():+.2f} "
        f"and adverse move>={get_broken_exit_adverse_bps():.0f}bps"
    )


def get_squeeze_mean_revert_allowance(
    signal_ctx: dict[str, Any],
    direction: str = "",
    broader_structure: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    """Return whether a squeeze mean-revert setup is structured enough to trade.

    This is intentionally stricter than the normal level gate. It only permits a
    squeeze fade when the parent structure, range location, level edge, and room
    to the opposite side all agree. Random middle-of-range squeeze fades remain
    blocked because they have historically bled fees.
    """
    broader_structure = broader_structure or brain.get("broader_structure") or compute_broader_structure_context(signal_ctx)
    broader_action = str(broader_structure.get("action", "wait") or "wait")
    broader_conf = float(broader_structure.get("confidence", 0.0) or 0.0)
    direction = str(direction or "").lower()
    if not direction and broader_action in {"mean_revert_long", "mean_revert_short"}:
        direction = "long" if broader_action.endswith("long") else "short"
    if direction not in {"long", "short"}:
        return False, "no directional mean-revert structure"
    if broader_action != f"mean_revert_{direction}":
        return False, f"broader_action={broader_action} does not match {direction}"
    if broader_conf < SQUEEZE_MEAN_REVERT_STRUCTURE_MIN_CONF:
        return False, f"broader_conf={broader_conf:.2f} below {SQUEEZE_MEAN_REVERT_STRUCTURE_MIN_CONF:.2f}"

    range_established = bool(
        signal_ctx.get("range_established", False)
        or signal_ctx.get("micro_range_established", False)
    )
    at_directional_edge = bool(
        (
            direction == "long"
            and (signal_ctx.get("at_support", False) or signal_ctx.get("sweep_reclaim_long", False))
        )
        or (
            direction == "short"
            and (signal_ctx.get("at_resistance", False) or signal_ctx.get("sweep_reclaim_short", False))
        )
    )
    room_to_target_bps = float(
        signal_ctx.get(
            "room_to_resistance_bps" if direction == "long" else "room_to_support_bps",
            0.0,
        )
        or 0.0
    )
    min_room_bps = max(SQUEEZE_MEAN_REVERT_MIN_ROOM_BPS, get_level_min_room_bps())
    if not range_established:
        return False, "range not established"
    if not at_directional_edge:
        return False, f"{direction} lacks directional level edge"
    if room_to_target_bps < min_room_bps:
        return False, f"room={room_to_target_bps:.1f}bps < min={min_room_bps:.1f}"
    return True, f"{direction} structured mean-revert room={room_to_target_bps:.1f}bps"


def get_squeeze_structure_block_reason(direction: str, intent: str = "") -> str | None:
    """Final squeeze guard for live orders.

    Earlier gates can be bypassed by later signal mutation or stale context. This
    helper is intentionally repeated at the order boundary: in squeeze, live
    orders need a directional spring/reclaim, confirmed directional breakout, or
    a same-direction level-backed mean-revert setup with enough room to pay fees.
    """
    if str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown") != "squeeze":
        return None

    signal_ctx = get_signal_context()
    direction = str(direction or "").lower()
    intent = str(intent or "").lower()
    if direction == "long" and (
        signal_ctx.get("wyckoff_spring_long", False)
        or signal_ctx.get("sweep_reclaim_long", False)
    ):
        return None
    if direction == "short" and (
        signal_ctx.get("wyckoff_spring_short", False)
        or signal_ctx.get("sweep_reclaim_short", False)
    ):
        return None

    broader_structure = brain.get("broader_structure") or compute_broader_structure_context(signal_ctx)
    broader_action = str(broader_structure.get("action", "wait") or "wait")
    broader_conf = float(broader_structure.get("confidence", 0.0) or 0.0)
    breakout_matches = (
        intent == "breakout"
        and broader_conf >= 0.65
        and (
            (direction == "long" and broader_action == "breakout_long")
            or (direction == "short" and broader_action == "breakout_short")
        )
    )
    if breakout_matches:
        return None

    if intent == "mean_revert":
        mean_revert_allowed, mean_revert_reason = get_squeeze_mean_revert_allowance(signal_ctx, direction, broader_structure)
        if mean_revert_allowed:
            return None
        return (
            "squeeze final structural gate | require directional spring/reclaim or "
            f"confirmed same-direction breakout/level-backed mean-revert before live order ({mean_revert_reason})"
        )

    return (
        "squeeze final structural gate | require directional spring/reclaim or "
        "confirmed same-direction breakout/level-backed mean-revert before live order"
    )


def get_default_close_alignment() -> dict[str, Any]:
    return {
        "score": 0.0,
        "components": {},
        "component_summary": "n/a",
    }


def sanitize_legacy_drawdown(value: Any) -> float:
    try:
        raw = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(raw):
        return 0.0
    return clamp(raw, 0.0, 1.0)


def refresh_legacy_equity_drawdown(net_pnl: float = 0.0) -> None:
    total_margin = float(brain.get("last_margin", {}).get("total_margin", 0.0) or 0.0)
    baseline_equity = max(total_margin, SMALL_ACCOUNT_DYNAMIC_MIN_SATS)

    previous_equity = float(brain.get("current_equity", 0.0) or 0.0)
    if previous_equity <= 0:
        previous_equity = baseline_equity
    current_equity = max(previous_equity + net_pnl, 0.0)

    previous_peak = float(brain.get("equity_peak", 0.0) or 0.0)
    if previous_peak <= 0:
        previous_peak = max(previous_equity, baseline_equity)
    peak = max(previous_peak, current_equity, baseline_equity)

    brain["current_equity"] = round(current_equity, 6)
    brain["equity_peak"] = round(peak, 6)
    brain["drawdown"] = round(sanitize_legacy_drawdown((peak - current_equity) / max(peak, 1.0)), 6)


def update_sizing_balance_snapshot(raw_usable: float, total_margin: float, running_margin: float) -> float:
    raw = max(float(raw_usable or 0.0), 0.0)
    snapped = float(brain.get("sizing_balance_snapped", 0.0) or 0.0)
    if snapped <= 0.0:
        snapped = raw
    elif raw > 0.0 and abs(raw - snapped) / max(snapped, 1.0) >= SIZING_BALANCE_HYSTERESIS_PCT:
        snapped = raw
    brain["sizing_balance_raw"] = round(raw, 2)
    brain["sizing_balance_snapped"] = round(snapped, 2)
    brain["sizing_balance_updated_at"] = datetime.now().isoformat()
    brain["exposure_budget_context"] = {
        "total_margin": round(float(total_margin or 0.0), 2),
        "running_margin": round(float(running_margin or 0.0), 2),
        "usable_raw": round(raw, 2),
        "usable_snapped": round(snapped, 2),
        "hysteresis_pct": SIZING_BALANCE_HYSTERESIS_PCT,
    }
    return snapped


def get_sizing_usable(raw_usable: float) -> float:
    snapped = float(brain.get("sizing_balance_snapped", 0.0) or 0.0)
    if snapped <= 0.0:
        return float(raw_usable or 0.0)
    return snapped


def compute_exposure_budget(signal: Optional[EntrySignal], usable: float, leverage: int) -> dict[str, Any]:
    regime = str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown")
    risk_mode = str(brain.get("risk_mode", "normal") or "normal")
    edge = max(
        float(getattr(signal, "expected_edge", 0.0) or 0.0) if signal else 0.0,
        float(getattr(signal, "predictive_setup_score", 0.0) or 0.0) if signal else 0.0,
    )
    base = 0.10
    if risk_mode == "caution":
        base *= 0.70
    elif risk_mode == "protection":
        base *= 0.35
    if regime in {"trend", "squeeze"}:
        base += clamp((edge - 0.18) * 0.25, -0.02, 0.10)
    elif regime == "chop":
        base *= 0.75
    if get_strategic_aggression_context().get("default_aggressive"):
        base += 0.04
    exposure_pct = clamp(base, EXPOSURE_BUDGET_MIN, EXPOSURE_BUDGET_MAX)
    approx_entry = float(brain.get("last_price") or market_state.get("last_price") or 0.0)
    max_qty = 0
    if usable > 0 and leverage > 0 and approx_entry > 0:
        max_qty = int((usable * exposure_pct * approx_entry * leverage) / 100_000_000)
    plan = {
        "exposure_pct": round(exposure_pct, 4),
        "budget_sats": round(float(usable or 0.0) * exposure_pct, 2),
        "max_qty": max(1, max_qty),
        "usable": round(float(usable or 0.0), 2),
        "leverage": int(leverage or MIN_LEVERAGE),
        "reason": f"exposure_budget regime={regime} risk={risk_mode} edge={edge:.2f}",
    }
    brain["last_exposure_budget"] = plan
    return plan


def compute_chop_alignment(signal_ctx: dict[str, Any], quality: float, oracle_insight: dict[str, Any]) -> dict[str, Any]:
    replay_score = float(oracle_insight.get("score", 0.0) or 0.0)
    live_evidence = get_live_chop_evidence()
    session_bucket = str(signal_ctx.get("session_bucket", "offhours"))
    mtf_alignment = str(signal_ctx.get("mtf_alignment", "mixed"))
    volatility_state = str(signal_ctx.get("volatility_state", "normal"))
    volatility_expansion = float(signal_ctx.get("volatility_expansion", 1.0) or 1.0)
    spread_shock = float(signal_ctx.get("spread_shock", 1.0) or 1.0)

    components: dict[str, float] = {}
    components["replay"] = min(max(replay_score - 0.35, 0.0) / 0.35, 1.0) * 0.28
    components["quality"] = min(max(quality - 0.30, 0.0) / 0.18, 1.0) * 0.30

    if session_bucket in {"london", "ny_open", "ny_late"}:
        components["session"] = 0.06
    elif session_bucket in {"asia", "rollover"}:
        components["session"] = -0.02
    else:
        components["session"] = 0.0

    if mtf_alignment == "mixed":
        components["mtf"] = 0.07
    else:
        components["mtf"] = -0.015

    if volatility_state == "compressed":
        components["vol_state"] = 0.06
    elif volatility_state == "expanded":
        components["vol_state"] = -0.03
    else:
        components["vol_state"] = 0.0

    if volatility_expansion <= 1.05:
        components["vol_expansion"] = 0.05
    elif volatility_expansion >= 1.20:
        components["vol_expansion"] = -0.02
    else:
        components["vol_expansion"] = 0.0

    if spread_shock <= 1.25:
        components["spread"] = 0.05
    elif spread_shock >= 1.90:
        components["spread"] = -0.06
    else:
        components["spread"] = 0.0

    if int(live_evidence.get("trades", 0)) >= 2:
        components["live_fee_clear"] = min(max(float(live_evidence.get("fee_clear_rate", 0.0) or 0.0), 0.0), 1.0) * 0.15
        components["live_peak_fee"] = clamp(float(live_evidence.get("avg_peak_fee_multiple", 0.0) or 0.0) / 2.8, -0.05, 0.09)
        components["live_outcome"] = clamp(float(live_evidence.get("avg_outcome_pnl", 0.0) or 0.0) / 500.0, -0.04, 0.06)
    else:
        components["live_fee_clear"] = 0.0
        components["live_peak_fee"] = 0.0
        components["live_outcome"] = 0.0

    fee_loss_pressure = float(live_evidence.get("recent_fee_loss_pressure", 0.0) or 0.0)
    components["fee_loss_penalty"] = -clamp(fee_loss_pressure * 0.06, 0.0, 0.12)

    # Range position: reward entries at extremes, penalize mid-range entries
    range_position = float(signal_ctx.get("range_position", 0.5) or 0.5)
    range_width_pct = float(signal_ctx.get("range_width_pct", 0.0) or 0.0)
    range_established = bool(signal_ctx.get("range_established", False))
    if range_established and range_width_pct >= CHOP_MIN_RANGE_WIDTH_PCT:
        distance_from_edge = min(range_position, 1.0 - range_position)  # 0=at edge, 0.5=center
        components["range_edge"] = clamp((0.25 - distance_from_edge) / 0.25, -0.10, CHOP_RANGE_EDGE_BONUS)
        width_bonus = clamp((range_width_pct - CHOP_MIN_RANGE_WIDTH_PCT) / 0.006, 0.0, 1.0) * CHOP_RANGE_WIDTH_BONUS_MAX
        components["range_width"] = width_bonus
    elif range_established and range_width_pct < CHOP_MIN_RANGE_WIDTH_PCT:
        components["range_edge"] = -0.06  # tight range penalty
        components["range_width"] = 0.0
    else:
        components["range_edge"] = 0.0
        components["range_width"] = 0.0

    score = clamp(sum(components.values()), 0.0, 1.0)
    component_summary = ", ".join(
        f"{name}={value:+.2f}"
        for name, value in sorted(components.items(), key=lambda item: abs(item[1]), reverse=True)
        if abs(value) >= 0.015
    ) or "flat"

    return {
        "score": round(score, 3),
        "components": {key: round(value, 3) for key, value in components.items()},
        "component_summary": component_summary,
        "live_evidence": live_evidence,
        "session_bucket": session_bucket,
        "mtf_alignment": mtf_alignment,
        "volatility_state": volatility_state,
        "volatility_expansion": round(volatility_expansion, 3),
        "spread_shock": round(spread_shock, 3),
        "range_position": round(range_position, 4),
        "range_width_pct": round(range_width_pct, 6),
        "range_established": range_established,
    }


def compute_close_alignment(
    position: PositionState,
    thesis: dict[str, Any],
    price: Optional[float] = None,
    *,
    signal_ctx: Optional[dict[str, Any]] = None,
    oracle_insight: Optional[dict[str, Any]] = None,
    chop_alignment: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if not position.is_open:
        return get_default_close_alignment()

    resolved_signal_ctx = signal_ctx or get_signal_context()
    regime_state = brain.get("market_regime", {}) or {}
    regime = str(regime_state.get("regime", "unknown"))
    regime_bias = str(regime_state.get("bias", "neutral"))
    resolved_oracle = oracle_insight or get_oracle_regime_insight(regime)
    resolved_chop_alignment = (
        chop_alignment
        if chop_alignment is not None
        else compute_chop_alignment(
            resolved_signal_ctx,
            float(brain.get("last_market_quality_components", {}).get("raw_score", 0.0) or 0.0),
            resolved_oracle,
        )
        if regime == "chop"
        else get_default_chop_alignment()
    )
    side_sign = 1.0 if position.side == "long" else -1.0
    mtf_alignment = str(resolved_signal_ctx.get("mtf_alignment", "mixed"))
    session_bucket = str(resolved_signal_ctx.get("session_bucket", "offhours"))
    volatility_state = str(resolved_signal_ctx.get("volatility_state", "normal"))
    volatility_expansion = float(resolved_signal_ctx.get("volatility_expansion", 1.0) or 1.0)
    replay_bias = str(resolved_oracle.get("dominant_bias", "neutral"))
    replay_mtf = float(resolved_oracle.get("avg_mtf_alignment_score", 0.0) or 0.0)
    quality_delta = float(thesis.get("quality_delta", 0.0) or 0.0)
    thesis_score = float(thesis.get("score", 0.0) or 0.0)
    raw_move_bps = get_raw_entry_move_bps(position, price or float(brain.get("last_price") or position.entry or 0.0))
    adverse_move_bps = raw_move_bps if position.side == "short" else -raw_move_bps
    fee_ratio = float(thesis.get("fee_ratio", 0.0) or 0.0)
    peak_fee = float(thesis.get("peak_fee_multiple", 0.0) or 0.0)
    no_progress_penalty = float(thesis.get("no_progress_penalty", 0.0) or 0.0)
    directional_align = float(
        thesis.get("pressure_align", 0.0) if position.intent != "mean_revert"
        else thesis.get("momentum_turn", 0.0)
    )

    components: dict[str, float] = {}
    components["weak_thesis"] = clamp(
        (BROKEN_EXIT_THESIS_SCORE - thesis_score) / 0.35,
        0.0,
        1.0,
    ) * 0.30
    components["adverse_move"] = clamp(
        (adverse_move_bps - BROKEN_EXIT_ADVERSE_MOVE_BPS) / 35.0,
        0.0,
        1.0,
    ) * 0.24
    components["fee_failure"] = clamp((0.45 - peak_fee) / 0.45, 0.0, 1.0) * 0.10
    components["fee_ratio"] = clamp((0.10 - fee_ratio) / 0.20, 0.0, 1.0) * 0.06
    components["quality_decay"] = clamp((-quality_delta) / 0.18, 0.0, 1.0) * 0.08
    components["no_progress"] = clamp(no_progress_penalty, 0.0, 1.0) * 0.06
    components["directional_pressure"] = clamp((-directional_align + 0.05) / 0.40, 0.0, 1.0) * 0.05

    if regime_bias != "neutral":
        bias_against = (regime_bias == "bearish" and position.side == "long") or (regime_bias == "bullish" and position.side == "short")
        components["regime_bias"] = 0.04 if bias_against else -0.02
    else:
        components["regime_bias"] = 0.0

    if replay_bias != "neutral":
        replay_against = (replay_bias == "bearish" and position.side == "long") or (replay_bias == "bullish" and position.side == "short")
        components["replay_bias"] = 0.03 if replay_against else -0.01
    else:
        components["replay_bias"] = 0.0

    if mtf_alignment != "mixed":
        mtf_against = (mtf_alignment == "bearish" and position.side == "long") or (mtf_alignment == "bullish" and position.side == "short")
        components["mtf"] = 0.04 if mtf_against else -0.02
    else:
        components["mtf"] = 0.02

    if regime == "chop":
        components["chop_alignment"] = clamp((0.52 - float(resolved_chop_alignment.get("score", 0.0) or 0.0)) / 0.52, 0.0, 1.0) * 0.05
        if volatility_state == "expanded":
            components["volatility"] = 0.03
        elif volatility_state == "compressed":
            components["volatility"] = -0.02
        else:
            components["volatility"] = 0.0
    else:
        mtf_against_replay = -side_sign * replay_mtf
        components["replay_mtf"] = clamp((mtf_against_replay - 0.25) / 2.75, 0.0, 1.0) * 0.03
        components["volatility"] = 0.03 if volatility_state == "expanded" and regime == "squeeze" else 0.0

    if session_bucket in {"london", "ny_open", "ny_late"} and volatility_expansion > 1.35:
        components["active_session"] = 0.02
    else:
        components["active_session"] = 0.0

    score = clamp(sum(components.values()), 0.0, 1.0)
    component_summary = ", ".join(
        f"{name}={value:+.2f}"
        for name, value in sorted(components.items(), key=lambda item: abs(item[1]), reverse=True)
        if abs(value) >= 0.015
    ) or "flat"
    return {
        "score": round(score, 3),
        "components": {key: round(value, 3) for key, value in components.items()},
        "component_summary": component_summary,
    }


def build_trade_signal_snapshot(
    regime: Optional[str] = None,
    quality: Optional[float] = None,
    signal_ctx: Optional[dict[str, Any]] = None,
    oracle_insight: Optional[dict[str, Any]] = None,
    chop_alignment: Optional[dict[str, Any]] = None,
    close_alignment: Optional[dict[str, Any]] = None,
    chop_learner_lane_active: Optional[bool] = None,
) -> dict[str, Any]:
    resolved_regime = str(regime or brain.get("market_regime", {}).get("regime", "unknown"))
    resolved_signal_ctx = signal_ctx or get_signal_context()
    resolved_quality = float(
        quality
        if quality is not None
        else brain.get("last_market_quality_components", {}).get("raw_score", 0.0) or 0.0
    )
    resolved_oracle = oracle_insight or get_oracle_regime_insight(resolved_regime)
    regime_state = brain.get("market_regime", {}) or {}
    resolved_alignment = (
        chop_alignment
        if chop_alignment is not None
        else compute_chop_alignment(resolved_signal_ctx, resolved_quality, resolved_oracle)
        if resolved_regime == "chop"
        else get_default_chop_alignment()
    )
    resolved_close_alignment = close_alignment or get_default_close_alignment()
    broader_structure = brain.get("broader_structure") or compute_broader_structure_context(resolved_signal_ctx)
    live_evidence = resolved_alignment.get("live_evidence", {}) or {}
    position_blob = brain.get("position", {}) or {}
    last_trade_blob = brain.get("last_trade", {}) or {}
    last_decision_blob = brain.get("last_decision", {}) or {}
    predictive_setup_score = 0.0
    predictive_setup_summary = "n/a"
    predictive_expected_edge = 0.0
    if position_blob.get("is_open"):
        predictive_setup_score = float(position_blob.get("entry_predictive_setup_score", 0.0) or 0.0)
        predictive_setup_summary = str(position_blob.get("entry_predictive_setup_summary", "n/a") or "n/a")
        predictive_expected_edge = float(position_blob.get("entry_expected_edge", 0.0) or 0.0)
    else:
        predictive_setup_score = float(
            last_trade_blob.get("predictive_setup_score", last_decision_blob.get("predictive_setup_score", 0.0)) or 0.0
        )
        predictive_setup_summary = str(
            last_trade_blob.get("predictive_setup_summary", last_decision_blob.get("predictive_setup_summary", "n/a")) or "n/a"
        )
        predictive_expected_edge = float(
            last_trade_blob.get("expected_edge", last_decision_blob.get("expected_edge", 0.0)) or 0.0
        )
    reactivation_relief = (
        get_chop_reactivation_relief(
            {
                "regime": resolved_regime,
                "quality": resolved_quality,
                "oracle_insight": resolved_oracle,
                "signal_ctx": resolved_signal_ctx,
                "chop_alignment": resolved_alignment,
            }
        )
        if resolved_regime == "chop"
        else 0.0
    )
    if chop_learner_lane_active is None:
        if position_blob.get("is_open"):
            chop_learner_lane_active = bool(position_blob.get("entry_chop_learner_lane_active", False))
        else:
            chop_learner_lane_active = bool(
                last_trade_blob.get(
                    "chop_learner_lane_active",
                    last_decision_blob.get("chop_learner_lane_active", False),
                )
            )

    return {
        "regime": resolved_regime,
        "regime_bias": regime_state.get("bias", "neutral"),
        "regime_flavor": regime_state.get("regime_flavor", resolved_regime),
        "oracle_regime_bias": resolved_oracle.get("dominant_bias", "neutral"),
        "oracle_regime_flavor": resolved_oracle.get("dominant_flavor", resolved_regime),
        "market_quality": round(resolved_quality, 4),
        "flat_duration_minutes": round(get_flat_duration_minutes(), 2),
        "reactivation_relief": round(float(reactivation_relief or 0.0), 4),
        "funding_momentum": resolved_signal_ctx.get("funding_momentum", "stable"),
        "funding_bias": resolved_signal_ctx.get("funding_bias", "neutral"),
        "session_bucket": resolved_signal_ctx.get("session_bucket", "offhours"),
        "session_bias": resolved_signal_ctx.get("session_bias", "neutral"),
        "spread_shock": round(float(resolved_signal_ctx.get("spread_shock", 1.0) or 1.0), 3),
        "volatility_expansion": round(float(resolved_signal_ctx.get("volatility_expansion", 1.0) or 1.0), 3),
        "volatility_state": resolved_signal_ctx.get("volatility_state", "normal"),
        "mtf_alignment": resolved_signal_ctx.get("mtf_alignment", "mixed"),
        "regime_mtf_alignment_score": round(float(regime_state.get("mtf_alignment_score", 0.0) or 0.0), 3),
        "broader_structure_direction": str(broader_structure.get("direction", "neutral")),
        "broader_structure_action": str(broader_structure.get("action", "wait")),
        "broader_structure_confidence": round(float(broader_structure.get("confidence", 0.0) or 0.0), 4),
        "broader_structure_summary": str(broader_structure.get("summary", "n/a")),
        "signed_trend_strength": round(float(regime_state.get("signed_trend_strength", 0.0) or 0.0), 6),
        "directional_drift": round(float(regime_state.get("directional_drift", 0.0) or 0.0), 6),
        "momentum_1m": round(float(resolved_signal_ctx.get("momentum_1m", 0.0) or 0.0), 6),
        "momentum_5m": round(float(resolved_signal_ctx.get("momentum_5m", 0.0) or 0.0), 6),
        "momentum_15m": round(float(resolved_signal_ctx.get("momentum_15m", 0.0) or 0.0), 6),
        "external_bias": resolved_signal_ctx.get("external_bias", "neutral"),
        "external_conviction": round(float(resolved_signal_ctx.get("external_conviction", 0.0) or 0.0), 4),
        "external_source": str(resolved_signal_ctx.get("external_source", "none")),
        "external_data_quality": str(resolved_signal_ctx.get("external_data_quality", "none")),
        "bitget_status": str(resolved_signal_ctx.get("bitget_status", "missing")),
        "bitget_open_interest": round(float(resolved_signal_ctx.get("bitget_open_interest", 0.0) or 0.0), 4),
        "bitget_account_long_ratio": round(float(resolved_signal_ctx.get("bitget_account_long_ratio", 0.5) or 0.5), 4),
        "bitget_position_long_ratio": round(float(resolved_signal_ctx.get("bitget_position_long_ratio", 0.5) or 0.5), 4),
        "binance_status": str(resolved_signal_ctx.get("binance_status", "missing")),
        "deribit_status": str(resolved_signal_ctx.get("deribit_status", "missing")),
        "external_component_summary": str(resolved_signal_ctx.get("external_component_summary", "n/a")),
        "orderbook_live": bool(resolved_signal_ctx.get("orderbook_live", False)),
        "spread_live": bool(resolved_signal_ctx.get("spread_live", False)),
        "external_live": bool(resolved_signal_ctx.get("external_live", False)),
        "feature_health_summary": str(resolved_signal_ctx.get("feature_health_summary", "n/a")),
        "feature_health_source": str(resolved_signal_ctx.get("feature_health_source", "n/a")),
        "feature_health_reason": str(resolved_signal_ctx.get("feature_health_reason", "n/a")),
        "level_map_ready": bool(resolved_signal_ctx.get("level_map_ready", False)),
        "nearest_support": round(float(resolved_signal_ctx.get("nearest_support", 0.0) or 0.0), 2),
        "nearest_resistance": round(float(resolved_signal_ctx.get("nearest_resistance", 0.0) or 0.0), 2),
        "support_distance_bps": round(float(resolved_signal_ctx.get("support_distance_bps", 0.0) or 0.0), 2),
        "resistance_distance_bps": round(float(resolved_signal_ctx.get("resistance_distance_bps", 0.0) or 0.0), 2),
        "room_to_support_bps": round(float(resolved_signal_ctx.get("room_to_support_bps", 0.0) or 0.0), 2),
        "room_to_resistance_bps": round(float(resolved_signal_ctx.get("room_to_resistance_bps", 0.0) or 0.0), 2),
        "at_support": bool(resolved_signal_ctx.get("at_support", False)),
        "at_resistance": bool(resolved_signal_ctx.get("at_resistance", False)),
        "sweep_reclaim_long": bool(resolved_signal_ctx.get("sweep_reclaim_long", False)),
        "sweep_reclaim_short": bool(resolved_signal_ctx.get("sweep_reclaim_short", False)),
        "wyckoff_spring_long": bool(resolved_signal_ctx.get("wyckoff_spring_long", False)),
        "wyckoff_spring_short": bool(resolved_signal_ctx.get("wyckoff_spring_short", False)),
        "level_position": round(float(resolved_signal_ctx.get("level_position", 0.5) or 0.5), 4),
        "level_alignment": str(resolved_signal_ctx.get("level_alignment", "unknown")),
        "level_summary": str(resolved_signal_ctx.get("level_summary", "n/a")),
        "swing_support_count": int(resolved_signal_ctx.get("swing_support_count", 0) or 0),
        "swing_resistance_count": int(resolved_signal_ctx.get("swing_resistance_count", 0) or 0),
        "range_position": round(float(resolved_signal_ctx.get("range_position", 0.5) or 0.5), 4),
        "range_width_pct": round(float(resolved_signal_ctx.get("range_width_pct", 0.0) or 0.0), 6),
        "range_high": round(float(resolved_signal_ctx.get("range_high", 0.0) or 0.0), 2),
        "range_low": round(float(resolved_signal_ctx.get("range_low", 0.0) or 0.0), 2),
        "range_mid": round(float(resolved_signal_ctx.get("range_mid", 0.0) or 0.0), 2),
        "range_established": bool(resolved_signal_ctx.get("range_established", False)),
        "micro_range_established": bool(resolved_signal_ctx.get("micro_range_established", False)),
        "micro_range_reason": str(resolved_signal_ctx.get("micro_range_reason", "n/a")),
        "binance_oi_delta_pct": round(float(resolved_signal_ctx.get("binance_oi_delta_pct", 0.0) or 0.0), 4),
        "binance_taker_ratio": round(float(resolved_signal_ctx.get("binance_taker_ratio", 1.0) or 1.0), 4),
        "binance_top_position_ratio": round(float(resolved_signal_ctx.get("binance_top_position_ratio", 1.0) or 1.0), 4),
        "binance_top_account_ratio": round(float(resolved_signal_ctx.get("binance_top_account_ratio", 1.0) or 1.0), 4),
        "deribit_funding_1h": round(float(resolved_signal_ctx.get("deribit_funding_1h", 0.0) or 0.0), 6),
        "deribit_funding_8h": round(float(resolved_signal_ctx.get("deribit_funding_8h", 0.0) or 0.0), 6),
        "replay_score": round(float(resolved_oracle.get("score", 0.0) or 0.0), 4),
        "replay_samples": int(resolved_oracle.get("samples", 0) or 0),
        "replay_fee_clear_rate": round(float(resolved_oracle.get("fee_clear_rate", 0.0) or 0.0), 4),
        "replay_avg_peak_bps": round(float(resolved_oracle.get("avg_peak_bps", 0.0) or 0.0), 3),
        "replay_avg_adverse_bps": round(float(resolved_oracle.get("avg_adverse_bps", 0.0) or 0.0), 3),
        "replay_avg_time_to_fee_clear": round(float(resolved_oracle.get("avg_time_to_fee_clear", 0.0) or 0.0), 3),
        "replay_fee_clear_before_half_rate": round(float(resolved_oracle.get("fee_clear_before_half_rate", 0.0) or 0.0), 4),
        "replay_avg_fade_after_peak": round(float(resolved_oracle.get("avg_fade_after_peak", 0.0) or 0.0), 3),
        "replay_degrade_after_peak_rate": round(float(resolved_oracle.get("degrade_after_peak_rate", 0.0) or 0.0), 4),
        "replay_signed_trend_strength": round(float(resolved_oracle.get("avg_signed_trend_strength", 0.0) or 0.0), 6),
        "replay_directional_drift": round(float(resolved_oracle.get("avg_directional_drift", 0.0) or 0.0), 6),
        "replay_mtf_alignment_score": round(float(resolved_oracle.get("avg_mtf_alignment_score", 0.0) or 0.0), 3),
        "replay_bullish_bias_rate": round(float(resolved_oracle.get("bullish_bias_rate", 0.0) or 0.0), 4),
        "replay_bearish_bias_rate": round(float(resolved_oracle.get("bearish_bias_rate", 0.0) or 0.0), 4),
        "replay_neutral_bias_rate": round(float(resolved_oracle.get("neutral_bias_rate", 0.0) or 0.0), 4),
        "predictive_horizon_score": round(float(resolved_signal_ctx.get("predictive_horizon_score", 0.0) or 0.0), 4),
        "predictive_horizon_confidence": round(float(resolved_signal_ctx.get("predictive_horizon_confidence", 0.0) or 0.0), 4),
        "predictive_next_15_60_bias": str(resolved_signal_ctx.get("predictive_next_15_60_bias", "neutral")),
        "predictive_upside_break_prob": round(float(resolved_signal_ctx.get("predictive_upside_break_prob", 0.5) or 0.5), 4),
        "predictive_downside_break_prob": round(float(resolved_signal_ctx.get("predictive_downside_break_prob", 0.5) or 0.5), 4),
        "predictive_summary": str(resolved_signal_ctx.get("predictive_summary", "n/a")),
        "predictive_setup_score": round(float(predictive_setup_score or 0.0), 4),
        "predictive_setup_summary": predictive_setup_summary,
        "predictive_expected_edge": round(float(predictive_expected_edge or 0.0), 4),
        "chop_learner_lane_active": bool(chop_learner_lane_active),
        "chop_alignment": round(float(resolved_alignment.get("score", 0.0) or 0.0), 4),
        "chop_alignment_summary": str(resolved_alignment.get("component_summary", "n/a")),
        "live_fee_clear_rate": round(float(live_evidence.get("fee_clear_rate", 0.0) or 0.0), 4),
        "live_avg_peak_fee_multiple": round(float(live_evidence.get("avg_peak_fee_multiple", 0.0) or 0.0), 4),
        "live_avg_outcome_pnl": round(float(live_evidence.get("avg_outcome_pnl", 0.0) or 0.0), 2),
        "recent_fee_only_losses": int(live_evidence.get("recent_fee_only_losses", 0) or 0),
        "recent_fee_loss_pressure": round(float(live_evidence.get("recent_fee_loss_pressure", 0.0) or 0.0), 4),
        "close_alignment": round(float(resolved_close_alignment.get("score", 0.0) or 0.0), 4),
        "close_alignment_summary": str(resolved_close_alignment.get("component_summary", "n/a")),
    }


def get_runtime_trade_context(regime: Optional[str] = None) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    resolved_regime = str(regime or brain.get("market_regime", {}).get("regime", "unknown"))
    signal_ctx = get_signal_context()
    quality = float(brain.get("last_market_quality_components", {}).get("raw_score", 0.0) or 0.0)
    oracle_insight = get_oracle_regime_insight(resolved_regime)
    chop_alignment = (
        compute_chop_alignment(signal_ctx, quality, oracle_insight)
        if resolved_regime == "chop"
        else get_default_chop_alignment()
    )
    trade_signal_snapshot = build_trade_signal_snapshot(
        regime=resolved_regime,
        quality=quality,
        signal_ctx=signal_ctx,
        oracle_insight=oracle_insight,
        chop_alignment=chop_alignment,
    )
    return resolved_regime, signal_ctx, oracle_insight, chop_alignment, trade_signal_snapshot


def build_exploration_attempt_record(
    *,
    timestamp: datetime,
    policy: str,
    intent: str,
    direction: str,
    regime: str,
    fingerprint: str,
    lane_key: str,
    selected_score: float,
    quality: float,
    expected_edge: float,
    predictive_setup_score: float,
    predictive_setup_summary: str,
    chop_learner_lane_active: bool,
    trade_signal_snapshot: dict[str, Any],
    signal_features: dict[str, Any],
) -> dict[str, Any]:
    return {
        "timestamp": timestamp.isoformat(),
        "policy": policy,
        "intent": intent,
        "direction": direction,
        "regime": regime,
        "fingerprint": fingerprint,
        "lane_key": lane_key,
        "score": round(selected_score, 4),
        "quality": round(quality, 4),
        "expected_edge": round(float(expected_edge or 0.0), 4),
        "predictive_setup_score": round(float(predictive_setup_score or 0.0), 4),
        "predictive_setup_summary": str(predictive_setup_summary or "n/a"),
        "chop_learner_lane_active": bool(chop_learner_lane_active),
        "momentum_delta": signal_features.get("momentum_delta", 0.0),
        "imbalance_delta": signal_features.get("imbalance_delta", 0.0),
        "momentum_persistence": signal_features.get("momentum_persistence", 0.0),
        "imbalance_persistence": signal_features.get("imbalance_persistence", 0.0),
        **trade_signal_snapshot,
    }


def get_entry_gate_state(usable: float) -> dict[str, Any]:
    regime_state = brain.get("market_regime", {}) or {}
    regime = regime_state.get("regime", "unknown")
    transition = brain.get("regime_transition", {})
    market = brain.get("market_context", {})
    quality = compute_market_quality(market, regime, transition)
    small_account = usable > 0 and usable < SMALL_ACCOUNT_CHOP_SUPPRESS_SATS
    oracle_insight = get_oracle_regime_insight(regime)
    signal_ctx = get_signal_context()
    chop_alignment = compute_chop_alignment(signal_ctx, quality, oracle_insight) if regime == "chop" else get_default_chop_alignment()
    reactivation_relief = get_chop_reactivation_relief(
        {
            "regime": regime,
            "quality": quality,
            "oracle_insight": oracle_insight,
            "signal_ctx": signal_ctx,
            "chop_alignment": chop_alignment,
        }
    )
    effective_elite_quality = max(0.30, ELITE_CHOP_MIN_QUALITY - reactivation_relief)
    effective_elite_align = max(0.38, get_chop_align_min() - reactivation_relief * 0.9)
    elite_chop = bool(
        regime == "chop"
        and oracle_insight.get("samples", 0) >= ELITE_CHOP_MIN_REPLAY_SAMPLES
        and oracle_insight.get("score", 0.0) >= ELITE_CHOP_MIN_REPLAY_SCORE
        and quality >= effective_elite_quality
        and float(chop_alignment.get("score", 0.0) or 0.0) >= effective_elite_align
    )
    fingerprint = get_exploration_context_fingerprint(regime)
    chop_learner_support = (
        regime == "chop"
        and has_shadow_chop_learner_support(fingerprint)
    )
    return {
        "regime": regime,
        "regime_bias": regime_state.get("bias", "neutral"),
        "regime_flavor": regime_state.get("regime_flavor", regime),
        "quality": quality,
        "small_account": small_account,
        "oracle_insight": oracle_insight,
        "signal_ctx": signal_ctx,
        "chop_alignment": chop_alignment,
        "elite_chop": elite_chop,
        "chop_learner_support": chop_learner_support,
        "reactivation_relief": reactivation_relief,
    }


def get_post_win_cooldown_minutes(net_pnl: float) -> float:
    if net_pnl < POST_WIN_MEDIUM_THRESHOLD:
        return POST_WIN_COOLDOWN_MINUTES
    if net_pnl < POST_WIN_LARGE_THRESHOLD:
        return POST_WIN_MEDIUM_COOLDOWN_MINUTES
    return POST_WIN_LARGE_COOLDOWN_MINUTES


def is_post_win_cooldown_exempt(net_pnl: float) -> bool:
    return POST_WIN_BREAKEVEN_EXEMPT_MIN < net_pnl < POST_WIN_BREAKEVEN_EXEMPT_MAX


def get_recent_post_win_reentry_context() -> Optional[tuple[float, float, float]]:
    # Keep immediate re-entries after winners selective without weakening post-loss cooldowns or exit gates.
    last_exit = brain.get("last_exit", {}) if isinstance(brain.get("last_exit", {}), dict) else {}
    last_exit_ts = parse_iso_dt(last_exit.get("timestamp"))
    last_exit_pnl = float(last_exit.get("realized_pnl", 0.0) or 0.0)
    if is_post_win_cooldown_exempt(last_exit_pnl):
        return None
    if not last_exit_ts or last_exit_pnl <= POST_WIN_COOLDOWN_THRESHOLD:
        return None
    elapsed_minutes = (time.time() - last_exit_ts.timestamp()) / 60.0
    cooldown_minutes = get_post_win_cooldown_minutes(last_exit_pnl)
    if elapsed_minutes < cooldown_minutes:
        return elapsed_minutes, cooldown_minutes, last_exit_pnl
    return None


def get_post_win_reentry_block_reason(signal: EntrySignal) -> Optional[str]:
    last_exit = brain.get("last_exit", {}) if isinstance(brain.get("last_exit", {}), dict) else {}
    last_exit_ts = parse_iso_dt(last_exit.get("timestamp"))
    last_exit_pnl = float(last_exit.get("realized_pnl", 0.0) or 0.0)
    last_exit_reason = str(last_exit.get("exit_reason", ""))
    last_exit_type = str(last_exit.get("exit_type", ""))
    last_exit_type_norm = str(last_exit.get("exit_type_normalized", ""))
    if is_post_win_cooldown_exempt(last_exit_pnl):
        return None
    tp_exit = (
        "TP_HIT" in last_exit_reason.upper()
        or last_exit_type == "take_profit"
        or last_exit_type_norm in {"take_profit", "trailed_profit"}
    )
    if not tp_exit or not last_exit_ts or last_exit_pnl <= POST_WIN_COOLDOWN_THRESHOLD:
        return None
    elapsed = (time.time() - last_exit_ts.timestamp()) / 60.0
    if elapsed >= POST_WIN_REENTRY_EDGE_WINDOW_MINUTES:
        return None
    edge = float(getattr(signal, "expected_edge", 0.0) or 0.0)
    effective_edge_min = POST_WIN_REENTRY_EDGE_MIN
    blocked = edge < effective_edge_min
    try:
        append_review_report(
            "post_tp_edge_gate_eval",
            {
                "elapsed_minutes": round(elapsed, 2),
                "window_minutes": POST_WIN_REENTRY_EDGE_WINDOW_MINUTES,
                "last_exit_type": last_exit_type,
                "last_exit_type_normalized": last_exit_type_norm,
                "last_exit_pnl": round(last_exit_pnl, 2),
                "edge_score": round(edge, 4),
                "edge_min": POST_WIN_REENTRY_EDGE_MIN,
                "effective_edge_min": effective_edge_min,
                "blocked": blocked,
                "candidate_policy": getattr(signal, "policy", None),
                "candidate_direction": getattr(signal, "side", None),
            },
        )
    except Exception:
        pass
    if blocked:
        return (
            f"post-win edge gate | {elapsed:.1f}m < {POST_WIN_REENTRY_EDGE_WINDOW_MINUTES:.0f}m "
            f"after TP net={last_exit_pnl:+.0f} edge_score={edge:.2f} < {effective_edge_min:.2f}"
        )
    return None


def get_feature_warmup_block_reason() -> Optional[str]:
    status = get_feature_warmup_status()
    if not status["ready"]:
        reason = "feature warmup incomplete | " + ", ".join(status["reasons"])
        emit_gate_event_if_changed("feature_warmup", "blocked", {"reason": reason, "status": status})
        return reason
    emit_gate_event_if_changed("feature_warmup", "ready", status)
    return None


def get_feature_warmup_status() -> dict[str, Any]:
    price_n = len(PRICE_WINDOW)
    momentum_n = len(brain.get("momentum_history", []) or [])
    oracle_points = int((brain.get("oracle_replay", {}) or {}).get("points", 0) or 0)
    market_ctx = brain.get("market_context", {}) if isinstance(brain.get("market_context", {}), dict) else {}
    market_age_ts = parse_iso_dt(market_ctx.get("updated_at"))
    market_age = (time.time() - market_age_ts.timestamp()) if market_age_ts else float("inf")
    reasons = []
    if price_n < FEATURE_WARMUP_MIN_PRICES:
        reasons.append(f"prices={price_n}/{FEATURE_WARMUP_MIN_PRICES}")
    if momentum_n < FEATURE_WARMUP_MIN_MOMENTUM:
        reasons.append(f"momentum={momentum_n}/{FEATURE_WARMUP_MIN_MOMENTUM}")
    if oracle_points < FEATURE_WARMUP_MIN_ORACLE_POINTS:
        reasons.append(f"oracle={oracle_points}/{FEATURE_WARMUP_MIN_ORACLE_POINTS}")
    if market_age > 180:
        reasons.append(f"market_ctx_stale={market_age:.0f}s")
    return {
        "ready": not reasons,
        "reasons": reasons,
        "prices": price_n,
        "momentum": momentum_n,
        "oracle_points": oracle_points,
        "market_context_age_seconds": None if market_age == float("inf") else round(market_age, 1),
        "market_data_ok": bool(market_ctx.get("data_ok", False)),
    }


def build_entry_tag(signal: EntrySignal) -> str:
    regime = str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown")
    bias = str(brain.get("market_regime", {}).get("bias", "neutral") or "neutral")
    lane = str(getattr(signal, "tuned_lane_key", "") or "")
    proof = "shadow" if summarize_shadow_direction_proof(regime, signal.direction).get("proven") else "live"
    parts = [regime, bias, str(signal.policy or "unknown"), str(signal.intent or "unknown"), str(signal.direction or "unknown"), proof]
    if lane:
        parts.append(lane.replace("|", "_")[:48])
    return "_".join(re.sub(r"[^a-zA-Z0-9]+", "_", part).strip("_") for part in parts if part)[:120]


def infer_trade_attribution_from_tag(entry_tag: str) -> dict[str, str]:
    """Best-effort parser for build_entry_tag() output.

    Entry tags are intentionally lossy strings, but the first five fields are
    stable enough to repair missing policy/intent/direction in post-close data.
    """
    result = {"policy": "", "intent": "", "direction": ""}
    tag = str(entry_tag or "")
    for policy in (
        "mean_revert_imbalance_fade",
        "mean_revert_reclaim",
        "mean_revert_micro",
        "orderbook_imbalance_follow",
        "momentum_follow",
        "breakout_probe",
        "trend_pullback",
        "ai_primary",
    ):
        if f"_{policy}_" in f"_{tag}_":
            result["policy"] = policy
            break
    for intent in ("trend_follow", "mean_revert", "breakout", "scalp"):
        if f"_{intent}_" in f"_{tag}_":
            result["intent"] = intent
            break
    if "_long_" in f"_{tag}_":
        result["direction"] = "long"
    elif "_short_" in f"_{tag}_":
        result["direction"] = "short"
    return result


def normalize_trade_attribution(position: PositionState) -> dict[str, str]:
    """Repair missing trade labels before learning writes.

    Policy/intent attribution is critical for the tuner. A recovered exchange
    position or old persisted record can be generic (`ai_primary`) even though
    the last live trade and entry tag still identify the setup.
    """
    last_trade = brain.get("last_trade", {}) or {}
    parsed = infer_trade_attribution_from_tag(position.entry_tag)
    policy = str(position.policy or "").strip()
    intent = str(position.intent or "").strip()
    direction = str(position.side or "").strip()

    if not policy or policy in {"unknown", "ai_primary"}:
        policy = str(last_trade.get("policy") or parsed.get("policy") or policy or "unknown")
    if not intent or intent in {"unknown", "neutral"}:
        intent = str(last_trade.get("intent") or parsed.get("intent") or intent or "unknown")
    if not direction or direction in {"unknown", "flat"}:
        direction = str(last_trade.get("side") or parsed.get("direction") or direction or "unknown")

    if policy == "ai_primary" and intent == "mean_revert":
        policy = "mean_revert_reclaim"
    elif policy == "ai_primary" and intent == "breakout":
        policy = "breakout_probe"
    elif policy == "ai_primary" and intent == "trend_follow":
        policy = "momentum_follow"
    if intent in {"", "unknown", "neutral"}:
        if policy.startswith("mean_revert"):
            intent = "mean_revert"
        elif "breakout" in policy:
            intent = "breakout"
        elif policy in {"momentum_follow", "trend_pullback"}:
            intent = "trend_follow"

    if policy and policy != position.policy:
        position.policy = policy
    if intent and intent != position.intent:
        position.intent = intent
    if direction in {"long", "short"} and direction != position.side:
        position.side = direction

    return {"policy": position.policy, "intent": position.intent, "direction": position.side or "unknown"}


def build_exit_tag(reason: str, position: Optional[PositionState] = None) -> str:
    exit_type = classify_exit_type_normalized(reason, 0.0, 0.0)
    policy = str(getattr(position, "policy", "") or "unknown")
    side = str(getattr(position, "side", "") or "flat")
    return "_".join(part for part in (exit_type, policy, side) if part)[:120]


def get_evidence_validity(signal: Optional[EntrySignal] = None) -> dict[str, Any]:
    regime = str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown")
    oracle = brain.get("oracle_replay", {}) or {}
    oracle_ts = parse_iso_dt(oracle.get("last_run_at"))
    oracle_age = time.time() - oracle_ts.timestamp() if oracle_ts else float("inf")
    oracle_points = int(oracle.get("points", 0) or 0)
    instability = float((brain.get("regime_transition", {}) or {}).get("instability", 0.0) or 0.0)
    reasons = []
    if oracle_age > EVIDENCE_VALID_MAX_ORACLE_AGE_SECONDS:
        reasons.append(f"oracle_stale={oracle_age:.0f}s")
    if oracle_points < FEATURE_WARMUP_MIN_ORACLE_POINTS:
        reasons.append(f"oracle_points={oracle_points}")
    if instability >= TUNER_DRIFT_FREEZE_INSTABILITY:
        reasons.append(f"drift_freeze={instability:.2f}")
    if signal is not None:
        proof = summarize_shadow_direction_proof(regime, signal.direction)
        if signal.mode == "explore" and not proof.get("proven") and float(signal.predictive_setup_score or 0.0) < 0.48:
            reasons.append("explore_unproven_low_predictive")
    return {
        "valid": not reasons,
        "reason": ", ".join(reasons) or "valid",
        "oracle_age_seconds": None if oracle_age == float("inf") else round(oracle_age, 1),
        "oracle_points": oracle_points,
        "instability": round(instability, 4),
    }


def get_small_account_chop_block_reason(usable: float, state: dict[str, Any]) -> Optional[str]:
    regime = str(state.get("regime", "unknown"))
    quality = float(state.get("quality", 0.0) or 0.0)
    small_account = bool(state.get("small_account"))
    elite_chop = bool(state.get("elite_chop"))
    oracle_insight = state.get("oracle_insight", {})
    chop_alignment = state.get("chop_alignment", {})
    relief = float(state.get("reactivation_relief", 0.0) or 0.0)
    effective_min_quality = max(0.28, SMALL_ACCOUNT_CHOP_MIN_QUALITY - relief)
    effective_min_align = max(0.38, get_chop_align_min() - relief * 0.9)
    learner_lane_ready = (
        quality >= CHOP_LEARNER_LANE_MIN_QUALITY
        and float(chop_alignment.get("score", 0.0) or 0.0) >= CHOP_LEARNER_LANE_MIN_ALIGN
        and bool(state.get("chop_learner_support"))
    )

    if not (small_account and regime == "chop" and not elite_chop):
        return None
    if learner_lane_ready:
        return None
    if quality < effective_min_quality:
        return f"small-account chop suppression | usable={usable:.0f} q={quality:.2f}"
    if float(chop_alignment.get("score", 0.0) or 0.0) < effective_min_align:
        return (
            f"chop alignment weak | usable={usable:.0f} q={quality:.2f} "
            f"align={float(chop_alignment.get('score', 0.0) or 0.0):.2f} "
            f"| {str(chop_alignment.get('component_summary', 'n/a'))}"
        )
    return (
        f"chop requires elite replay support | usable={usable:.0f} q={quality:.2f} "
        f"replay={float(oracle_insight.get('score', 0.0) or 0.0):+.2f}/{int(oracle_insight.get('samples', 0) or 0)}"
    )


def get_common_entry_block_reason(usable: float, state: dict[str, Any]) -> Optional[str]:
    regime = str(state.get("regime", "unknown"))
    quality = float(state.get("quality", 0.0) or 0.0)
    regime_bias = str(state.get("regime_bias", "neutral"))

    warmup_block = get_feature_warmup_block_reason()
    if warmup_block:
        return warmup_block

    if brain.get("cooldown_until", 0) > time.time():
        return "cooldown active"

    # Post-loss cooldown: avoid immediate flip-flop after a net losing exit.
    _last_exit = brain.get("last_exit", {}) if isinstance(brain.get("last_exit", {}), dict) else {}
    _last_exit_ts = parse_iso_dt(_last_exit.get("timestamp"))
    _last_exit_pnl = float(_last_exit.get("realized_pnl", 0.0) or 0.0)
    if (
        _last_exit_ts
        and _last_exit_pnl <= POST_LOSS_COOLDOWN_THRESHOLD
        and time.time() - _last_exit_ts.timestamp() < POST_LOSS_COOLDOWN_MINUTES * 60
    ):
        elapsed = (time.time() - _last_exit_ts.timestamp()) / 60.0
        return (
            f"post-loss cooldown | {elapsed:.1f}m < {POST_LOSS_COOLDOWN_MINUTES:.0f}m "
            f"required after net={_last_exit_pnl:+.0f}"
        )

    post_win_context = get_recent_post_win_reentry_context()
    if post_win_context:
        elapsed, cooldown_minutes, _ = post_win_context
        return (
            f"post-win cooldown | {elapsed:.1f}m < {cooldown_minutes:.0f}m "
            f"required after net={_last_exit_pnl:+.0f}"
        )

    _lessons = brain.get("trade_lessons", [])
    if _lessons:
        _last = _lessons[-1]
        _last_ts = parse_iso_dt(_last.get("timestamp"))
        _last_pnl = float(_last.get("net_pnl", 0.0) or 0.0)
        _risk_mode = brain.get("risk_mode", "normal")
        _cooldown_mins = 10.0 if _risk_mode == "caution" else 5.0
        if _last_ts and _last_pnl < -30 and time.time() - _last_ts.timestamp() < _cooldown_mins * 60:
            return f"post-loss cooldown | {(time.time() - _last_ts.timestamp()) / 60:.1f}m < {_cooldown_mins:.0f}m required after loss"

    if usable < 1200:
        return "low margin"
    if quality < get_quality_floor():
        return f"low quality {quality:.2f} < floor={get_quality_floor():.2f}"
    if regime == "unknown" and quality < 0.35:
        return "unknown regime without edge"
    if state.get("small_account") and regime in {"trend", "squeeze"} and quality < 0.28:
        return f"small-account directional suppression | regime={regime} bias={regime_bias} q={quality:.2f}"

    # Chop fee kill switch: halt chop trading when chop entries are purely fee losses.
    # Only applies when current regime is chop — directional/trend/squeeze trades are never blocked.
    # Range-edge entries with strong alignment bypass the kill switch: the losses were random
    # mid-range entries; a confirmed range-edge setup is a qualitatively different trade.
    if regime == "chop":
        _fk_now = time.time()
        recent_chop_lessons = [
            t for t in brain.get("trade_lessons", [])[-12:]
            if str(t.get("regime", "")) == "chop"
            and _fk_now - (parse_iso_dt(t.get("timestamp")).timestamp()
                           if parse_iso_dt(t.get("timestamp")) else float("inf")) < FEE_KILL_LOOKBACK_SECONDS
        ][-8:]
        if len(recent_chop_lessons) >= 5:
            fee_only_losses = sum(
                1 for t in recent_chop_lessons
                if float(t.get("net_pnl", 0) or 0) < -80
                and abs(float(t.get("gross_pnl", 0) or 0)) < 10
            )
            fee_kill_ratio = fee_only_losses / len(recent_chop_lessons)
            fee_kill_active = fee_kill_ratio >= get_fee_kill_ratio()
            emit_gate_event_if_changed(
                "fee_kill_circuit",
                "active" if fee_kill_active else "inactive",
                {"fee_only_losses": fee_only_losses, "recent_chop": len(recent_chop_lessons), "ratio": round(fee_kill_ratio, 3)},
            )
            if fee_kill_active:
                # Check if this entry qualifies for range-edge override
                signal_ctx = state.get("signal_ctx", {}) or {}
                range_established = bool(signal_ctx.get("range_established", False))
                range_width_pct = float(signal_ctx.get("range_width_pct", 0.0) or 0.0)
                range_position = float(signal_ctx.get("range_position", 0.5) or 0.5)
                chop_alignment = state.get("chop_alignment", {})
                align_score = float(chop_alignment.get("score", 0.0) or 0.0)
                at_long_edge = range_position <= get_range_long_max()
                at_short_edge = range_position >= get_range_short_min()
                at_range_edge = at_long_edge or at_short_edge
                range_edge_override = (
                    range_established
                    and range_width_pct >= get_range_width_min()
                    and at_range_edge
                    and align_score >= get_chop_align_live_min()
                )
                if not range_edge_override:
                    return f"fee-kill circuit: {fee_only_losses}/{len(recent_chop_lessons)} recent chop trades are fee-only losses — range-edge setups with strong alignment still allowed"

    # Universal chop alignment gate: applies to ALL account sizes
    if regime == "chop":
        chop_alignment = state.get("chop_alignment", {})
        align_score = float(chop_alignment.get("score", 0.0) or 0.0)
        elite_chop = bool(state.get("elite_chop"))
        if not elite_chop and align_score < get_chop_align_min():
            return (
                f"chop alignment too weak (all accounts) | align={align_score:.2f} "
                f"min={get_chop_align_min():.2f} | {str(chop_alignment.get('component_summary', 'n/a'))}"
            )
        # Range width gate: range must be wide enough to be profitable after fees
        signal_ctx = state.get("signal_ctx", {}) or {}
        range_established = bool(signal_ctx.get("range_established", False))
        range_width_pct = float(signal_ctx.get("range_width_pct", 0.0) or 0.0)
        if range_established and range_width_pct < get_range_width_min():
            return (
                f"chop range too tight | width={range_width_pct:.4f} ({range_width_pct*100:.2f}%) "
                f"< min={get_range_width_min()*100:.2f}% — fees would exceed range"
            )

    # Oracle replay fee-clear gate: stale/noisy replay should not freeze live trading.
    # Hard-block only when replay has enough samples and both FCR/score are materially bad.
    # Strong live structure may bypass the caution band so the bot can attack clean setups.
    oracle_insight = state.get("oracle_insight", {}) or {}
    oracle_samples = int(oracle_insight.get("samples", 0) or 0)
    oracle_fcr = float(oracle_insight.get("fee_clear_rate", 0.0) or 0.0)
    oracle_score = float(oracle_insight.get("score", 0.0) or 0.0)
    oracle_peak_bps = float(oracle_insight.get("avg_peak_bps", 0.0) or 0.0)
    oracle_bias = str(oracle_insight.get("dominant_bias", "neutral") or "neutral")
    elite_chop = bool(state.get("elite_chop"))
    _oracle_min_samples = ORACLE_FCR_SQUEEZE_MIN_SAMPLES if regime == "squeeze" else ORACLE_FCR_MIN_SAMPLES
    if not elite_chop and oracle_samples >= _oracle_min_samples:
        signal_ctx = state.get("signal_ctx", {}) or {}
        chop_alignment = state.get("chop_alignment", {}) or {}
        align_score = float(chop_alignment.get("score", 0.0) or 0.0)
        mtf_alignment = str(signal_ctx.get("mtf_alignment", "mixed"))
        flat_minutes = get_flat_duration_minutes()
        structural_level_ready = bool(
            signal_ctx.get("at_support", False)
            or signal_ctx.get("at_resistance", False)
            or signal_ctx.get("sweep_reclaim_long", False)
            or signal_ctx.get("sweep_reclaim_short", False)
        )
        # Breakout bypass: oracle FCR measures in-regime random entries; a high-confidence
        # breakout is exiting the regime — its FCR is irrelevant to the oracle measurement.
        broader_structure = brain.get("broader_structure") or {}
        broader_action = str(broader_structure.get("action", "wait") or "wait")
        broader_conf = float(broader_structure.get("confidence", 0.0) or 0.0)
        is_high_conf_breakout = broader_action in {"breakout_long", "breakout_short"} and broader_conf >= 0.70
        if is_high_conf_breakout:
            return None
        squeeze_fcr_threshold = ORACLE_FCR_SQUEEZE_BASE_THRESHOLD
        if flat_minutes >= CAUTION_DECAY_START_MINUTES:
            squeeze_fcr_threshold = ORACLE_FCR_SQUEEZE_FLAT20_THRESHOLD
        squeeze_align_override = (
            flat_minutes >= ORACLE_FCR_SQUEEZE_ALIGN_OVERRIDE_MINUTES
            and structural_level_ready
            and align_score >= ORACLE_FCR_SQUEEZE_ALIGN_OVERRIDE_MIN
        )
        range_pos = float(signal_ctx.get("range_position", 0.5) or 0.5)
        at_range_extreme = range_pos <= get_range_long_max() or range_pos >= get_range_short_min()
        squeeze_bypass_ok = (
            oracle_fcr >= squeeze_fcr_threshold
            or squeeze_align_override
            or (
                flat_minutes >= CAUTION_DECAY_START_MINUTES
                and structural_level_ready
                and quality >= max(0.62, get_exploration_min_score())
                and mtf_alignment in {"bullish", "bearish"}
            )
            or (
                # Range-extreme bypass: oracle simulates random entries;
                # at a genuine structural extreme the level gate already ensures room.
                at_range_extreme
                and structural_level_ready
                and quality >= 0.65
            )
        )
        strong_live_setup = bool(
            quality >= get_exploration_min_score()
            and structural_level_ready
            and (
                regime in {"trend", "squeeze"}
                or align_score >= get_chop_align_live_min()
                or mtf_alignment in {"bullish", "bearish"}
            )
            and (
                regime != "squeeze"
                or squeeze_bypass_ok
            )
        )
        # Direction-aware hard block: oracle score reflects quality of dominant_bias direction.
        # If oracle says bullish-bias failed (score<0.40), block LONG setups — but a SHORT setup
        # is trading the fade of that failed signal, which is valid.
        broader_action_str = str((brain.get("broader_structure") or {}).get("action", "wait") or "wait")
        oracle_fading_long = oracle_bias == "bullish" and oracle_score < 0.40
        oracle_fading_short = oracle_bias == "bearish" and oracle_score < 0.40
        structure_is_short = broader_action_str in {"mean_revert_short", "breakout_short", "trend_short"}
        structure_is_long = broader_action_str in {"mean_revert_long", "breakout_long", "trend_long"}
        # Suppress hard block when structure direction FADES the failed oracle bias
        fade_bypass = (oracle_fading_long and structure_is_short) or (oracle_fading_short and structure_is_long)
        hard_bad_replay = oracle_fcr < ORACLE_FCR_HARD_BLOCK and oracle_score < 0.40 and not fade_bypass
        oracle_blocked = (hard_bad_replay and not strong_live_setup) or (
            oracle_score < ORACLE_SCORE_HARD_BLOCK and oracle_fcr < ORACLE_FCR_CAUTION and not strong_live_setup and not fade_bypass
        )
        emit_gate_event_if_changed(
            "oracle_hard_block",
            "blocking" if oracle_blocked else "open",
            {"score": round(oracle_score, 4), "fcr": round(oracle_fcr, 3), "samples": oracle_samples, "strong_live": strong_live_setup, "fade_bypass": fade_bypass},
        )
        if hard_bad_replay and not strong_live_setup:
            return (
                f"oracle FCR hard block | fcr={oracle_fcr:.2f} < {ORACLE_FCR_HARD_BLOCK:.2f} "
                f"score={oracle_score:.3f} samples={oracle_samples}"
            )
        if oracle_score < ORACLE_SCORE_HARD_BLOCK and oracle_fcr < ORACLE_FCR_CAUTION and not strong_live_setup:
            return (
                f"oracle score hard block | score={oracle_score:.3f} < {ORACLE_SCORE_HARD_BLOCK:.2f} "
                f"fcr={oracle_fcr:.2f} samples={oracle_samples}"
            )
        if regime == "squeeze" and oracle_fcr < squeeze_fcr_threshold and not squeeze_bypass_ok:
            return (
                f"squeeze oracle caution block | fcr={oracle_fcr:.2f} < {squeeze_fcr_threshold:.2f} "
                f"align={align_score:.2f} flat={flat_minutes:.1f}m"
            )
        if oracle_fcr < ORACLE_FCR_CAUTION:
            log(
                f"⚠️ ORACLE FCR CAUTION BYPASSED | fcr={oracle_fcr:.2f} "
                f"score={oracle_score:.3f} peak={oracle_peak_bps:.1f}bps "
                f"samples={oracle_samples} q={quality:.2f} align={align_score:.2f} "
                f"squeeze_thr={squeeze_fcr_threshold:.2f} "
                f"squeeze_bypass={'yes' if regime == 'squeeze' and squeeze_bypass_ok else 'n/a'}"
            )

    # Squeeze structural gate: random mid-range fades inside a squeeze bleed fees.
    # Live trades need a spring/reclaim, breakout, or same-direction level-backed
    # mean-revert setup with enough room to the opposite side.
    if regime == "squeeze":
        signal_ctx = state.get("signal_ctx", {}) or {}
        has_structural_signal = bool(
            signal_ctx.get("wyckoff_spring_long", False)
            or signal_ctx.get("wyckoff_spring_short", False)
            or signal_ctx.get("sweep_reclaim_long", False)
            or signal_ctx.get("sweep_reclaim_short", False)
        )
        broader_structure = brain.get("broader_structure") or {}
        broader_action = str(broader_structure.get("action", "wait") or "wait")
        broader_conf = float(broader_structure.get("confidence", 0.0) or 0.0)
        is_breakout = broader_action.startswith("breakout") and broader_conf >= 0.65
        mean_revert_allowed, mean_revert_reason = get_squeeze_mean_revert_allowance(
            signal_ctx,
            broader_structure=broader_structure,
        )
        if not has_structural_signal and not is_breakout and not mean_revert_allowed:
            return (
                "squeeze structural gate | require spring/reclaim/breakout or "
                f"level-backed mean-revert ({mean_revert_reason})"
            )

    return get_small_account_chop_block_reason(usable, state)


def get_regime_risk_scalar() -> float:
    regime = brain.get("market_regime", {}).get("regime", "unknown")
    edge = brain.get("regime_weights", {}).get(regime, 0.0)
    if edge > 0.02:
        return 1.2 + min(edge * 10, 0.6)
    if edge < -0.02:
        return max(0.3, 1.0 + edge * 8)
    return 0.9


def get_allowed_open_intents(regime: str) -> set[str]:
    if regime == "trend":
        return {"trend_follow", "breakout"}
    if regime == "chop":
        return {"mean_revert"}
    if regime == "volatile":
        return {"breakout", "scalp"}
    if regime == "squeeze":
        return {"breakout", "trend_follow", "mean_revert"}
    return {"mean_revert", "scalp"}


def is_strategy_allowed_for_regime(signal: EntrySignal, regime: str, position_open: bool = False) -> tuple[bool, str]:
    if signal.action not in {"open", "add", "reverse"}:
        return True, ""

    if regime == "unknown" and signal.mode == "exploit":
        return False, "Exploit entries blocked while regime is unknown"

    allowed_intents = get_allowed_open_intents(regime)
    if signal.intent not in allowed_intents:
        return False, f"Intent {signal.intent} blocked in regime {regime}"

    return True, ""


def get_adaptive_trade_parameters() -> dict[str, Any]:
    base_risk = min(float(brain.get("base_risk_per_trade", RISK_PER_TRADE)), RISK_PER_TRADE)
    base_conf_threshold = 0.6

    perf = get_performance_stats()
    regime = brain.get("market_regime", {}).get("regime", "unknown")
    regime_weights = get_regime_weights()
    regime_edge = regime_weights.get(regime, 0.0)
    risk_mode = brain.get("risk_mode", "normal")
    transition = brain.get("regime_transition", {})

    streak = get_risk_streak()
    trades = max(int(perf.get("total_trades", 0)), 1)
    winrate = float(perf.get("win_rate", 50.0)) / 100.0
    confidence_bias = float(brain.get("confidence_bias", 0.0))

    regime_multiplier = 1.0
    if regime_edge >= 0.6:
        regime_multiplier *= 1.3
    elif regime_edge >= 0.2:
        regime_multiplier *= 1.1
    elif regime_edge <= -0.6:
        regime_multiplier *= 0.3
    elif regime_edge <= -0.3:
        regime_multiplier *= 0.6

    if regime == "trend":
        regime_multiplier *= 1.1
    elif regime == "chop":
        regime_multiplier *= 0.45
    elif regime == "volatile":
        regime_multiplier *= 0.6
    elif regime == "squeeze":
        regime_multiplier *= 0.85
    elif regime == "unknown":
        regime_multiplier *= 0.40

    performance_multiplier = 1.0
    if winrate > 0.55 and streak > 2:
        performance_multiplier *= 1.2
    if winrate < 0.45 or streak < -3:
        performance_multiplier *= 0.6
    if abs(confidence_bias) > 0.15:
        performance_multiplier *= 0.85

    risk_multiplier = regime_multiplier * performance_multiplier * transition.get("risk_multiplier", 1.0)
    risk_multiplier *= get_regime_risk_scalar()
    risk_multiplier = max(0.2, min(1.6, risk_multiplier))

    conf_threshold = base_conf_threshold
    if confidence_bias > 0.1:
        conf_threshold += 0.05
    if confidence_bias < -0.1 and winrate > 0.52:
        conf_threshold -= 0.05
    if regime == "chop":
        conf_threshold = max(conf_threshold, 0.62)
    if regime == "unknown":
        conf_threshold = max(conf_threshold, 0.70)
    conf_threshold = max(0.4, min(0.8, conf_threshold))

    risk_permission = True
    if risk_mode == "caution":
        risk_multiplier *= 0.6 + 0.4 * (1.0 - get_caution_decay_multiplier())
    elif risk_mode == "protection":
        risk_multiplier *= 0.25
        conf_threshold = max(conf_threshold, 0.7)
        risk_permission = False

    if regime == "chop" and winrate < 0.45:
        risk_permission = False
    if regime == "volatile" and streak <= -2:
        risk_permission = False
    if regime_edge < -0.7:
        risk_permission = False

    leverage_cap = MAX_LEVERAGE

    risk_per_trade = min(base_risk * risk_multiplier, MAX_RISK_PER_TRADE)
    if regime == "chop":
        risk_per_trade = min(risk_per_trade, CHOP_RISK_CAP)
    elif regime == "unknown":
        risk_per_trade = min(risk_per_trade, UNKNOWN_RISK_CAP)
    return {
        "risk_multiplier": risk_multiplier,
        "risk_per_trade": risk_per_trade,
        "confidence_threshold": conf_threshold,
        "leverage_cap": leverage_cap,
        "winrate": winrate,
        "streak": streak,
        "regime": regime,
        "regime_edge": regime_edge,
        "risk_mode": risk_mode,
        "risk_permission": risk_permission,
    }


def trim_trade_timestamps():
    cutoff = time.time() - 3600
    brain["trade_timestamps"] = [
        item
        for item in brain.get("trade_timestamps", [])
        if isinstance(item, dict) and float(item.get("ts", 0.0)) >= cutoff
    ][-200:]


def get_recent_trade_counts() -> dict[str, int]:
    trim_trade_timestamps()
    items = brain.get("trade_timestamps", [])
    total = len(items)
    explore = sum(1 for item in items if item.get("mode") == "explore")
    exploit = total - explore
    open_count = sum(1 for item in items if item.get("action") == "open")
    add_count = sum(1 for item in items if item.get("action") == "add")
    attack_open = sum(
        1
        for item in items
        if item.get("action") == "open" and item.get("mode") == "exploit"
    )
    return {
        "total": total,
        "explore": explore,
        "exploit": exploit,
        "open": open_count,
        "add": add_count,
        "attack_open": attack_open,
    }


def is_technical_exit_reason(reason: Optional[str]) -> bool:
    text = str(reason or "").lower()
    if not text:
        return False
    return any(token in text for token in TECHNICAL_EXIT_REASON_TOKENS)


def should_exclude_pnl_from_risk(reason: Optional[str], net_pnl: float) -> bool:
    return net_pnl < 0 and is_technical_exit_reason(reason)


def record_legacy_pnl_history(net_pnl: float):
    recent_pnls.append(net_pnl)
    brain.setdefault("last_pnls", []).append(net_pnl)
    brain["last_pnls"] = brain["last_pnls"][-80:]


def refresh_risk_persistence_fields() -> None:
    persisted_window = max(10, RISK_RECENT_PNL_WINDOW, RISK_STREAK_WINDOW)
    brain["last_pnls"] = [float(pnl) for pnl in get_risk_relevant_pnls(limit=persisted_window)]
    brain["streak"] = int(get_risk_streak())


def build_realized_record(
    now: datetime,
    gross_pnl: float,
    net_pnl: float,
    fee: float,
    reason: str,
    exit_type: str,
    position: Optional["PositionState"] = None,
) -> dict[str, Any]:
    if position is not None:
        normalize_trade_attribution(position)
    learner_lane_active = bool(position.entry_chop_learner_lane_active) if position else False
    record = {
        "date": now.date().isoformat(),
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "fee": fee,
        "reason": reason,
        "exit_type": exit_type,
        "exclude_from_risk": should_exclude_pnl_from_risk(reason, net_pnl),
        "exclude_from_protection": bool(learner_lane_active and net_pnl < 0),
        "chop_learner_lane_active": learner_lane_active,
    }
    if position is not None:
        record["policy"] = position.policy
        record["mode"] = position.mode
        record["intent"] = position.intent
        record["entry_expected_edge"] = round(float(position.entry_expected_edge or 0.0), 4)
        record["entry_predictive_setup_score"] = round(float(position.entry_predictive_setup_score or 0.0), 4)
        record["entry_predictive_setup_summary"] = position.entry_predictive_setup_summary
        record["entry_tag"] = position.entry_tag
        record["exit_tag"] = build_exit_tag(reason, position)
        record["signal_price"] = round(float(position.signal_price or 0.0), 2)
        record["evidence_valid"] = bool(position.evidence_valid)
        record["evidence_reason"] = position.evidence_reason
        record["roi_schedule_reason"] = position.roi_schedule_reason
    return record


def should_exclude_realized_from_protection(item: dict[str, Any]) -> bool:
    try:
        net_pnl = float(item.get("net_pnl", item.get("pnl", 0.0)) or 0.0)
    except (TypeError, ValueError):
        net_pnl = 0.0
    if bool(item.get("exclude_from_risk", False)):
        return True
    if bool(item.get("exclude_from_protection", False)):
        return True
    return net_pnl < 0 and bool(item.get("chop_learner_lane_active", False))


def get_risk_relevant_pnls(limit: int = 80) -> list[float]:
    items = []
    for item in brain.get("daily_realized", [])[-500:]:
        try:
            net_pnl = float(item.get("net_pnl", item.get("pnl", 0.0)) or 0.0)
        except (TypeError, ValueError):
            continue
        reason = item.get("reason", "")
        exclude_from_risk = item.get("exclude_from_risk")
        if exclude_from_risk is None:
            exclude_from_risk = should_exclude_pnl_from_risk(reason, net_pnl)
        if exclude_from_risk:
            continue
        items.append(net_pnl)
    return items[-limit:]


def get_risk_relevant_realized(limit: int = 500) -> list[dict[str, Any]]:
    items = []
    for item in brain.get("daily_realized", [])[-500:]:
        try:
            net_pnl = float(item.get("net_pnl", item.get("pnl", 0.0)) or 0.0)
        except (TypeError, ValueError):
            continue
        reason = item.get("reason", "")
        exclude_from_risk = item.get("exclude_from_risk")
        if exclude_from_risk is None:
            exclude_from_risk = should_exclude_pnl_from_risk(reason, net_pnl)
        if exclude_from_risk:
            continue
        normalized = dict(item)
        normalized["net_pnl"] = net_pnl
        items.append(normalized)
    return items[-limit:]


def get_protection_relevant_realized(limit: int = 500) -> list[dict[str, Any]]:
    items = []
    for item in get_risk_relevant_realized(limit=limit):
        if should_exclude_realized_from_protection(item):
            continue
        items.append(dict(item))
    return items[-limit:]


def get_risk_streak() -> int:
    streak = 0
    for pnl in reversed(get_risk_relevant_pnls(limit=RISK_STREAK_WINDOW)):
        if pnl > 0:
            streak = streak + 1 if streak >= 0 else 1
            continue
        if pnl < 0:
            streak = streak - 1 if streak <= 0 else -1
            continue
        break
    return streak


def get_consecutive_losses() -> int:
    count = 0
    for pnl in reversed(get_risk_relevant_pnls(limit=RISK_STREAK_WINDOW)):
        if pnl < 0:
            count += 1
            continue
        break
    return count


def get_effective_consecutive_losses() -> int:
    losses = int(get_consecutive_losses())
    flat_minutes = get_flat_duration_minutes()
    if losses <= 0:
        return 0
    if flat_minutes >= CONSECUTIVE_LOSS_DECAY_RESET_MINUTES:
        return 0
    if flat_minutes >= CONSECUTIVE_LOSS_DECAY_REDUCED_MINUTES:
        return min(losses, 3)
    return losses


def get_max_add_count(position: Optional[PositionState] = None, thesis: Optional[dict[str, Any]] = None) -> int:
    risk_mode = str(brain.get("risk_mode", "normal") or "normal")
    if risk_mode == "caution" or get_effective_consecutive_losses() >= 3:
        return 3
    if not position or not thesis:
        return MAX_ADD_COUNT
    thesis_score = float(thesis.get("score", 0.0) or 0.0)
    peak_fee = float(thesis.get("peak_fee_multiple", 0.0) or 0.0)
    if bool(thesis.get("intact")) and thesis_score >= 0.30 and peak_fee >= 0.60:
        return 6
    if bool(thesis.get("intact")) and thesis_score >= 0.18 and peak_fee >= 0.40:
        return 5
    return 3


def get_dynamic_hourly_trade_limit(signal: Optional[EntrySignal] = None) -> int:
    base_limit = MAX_TRADES_PER_HOUR
    if not signal:
        return base_limit
    action = str(getattr(signal, "action", "") or "")
    if action == "add":
        return MAX_ADD_TRADES_PER_HOUR
    if action == "open" and str(getattr(signal, "mode", "") or "") == "exploit":
        return MAX_ATTACK_ENTRIES_PER_HOUR
    return base_limit


def get_daily_risk_pnl() -> float:
    today = datetime.now().date().isoformat()
    total = 0.0
    for item in get_risk_relevant_realized(limit=500):
        if item.get("date") != today:
            continue
        total += float(item.get("net_pnl", 0.0) or 0.0)
    return total


def get_total_risk_pnl() -> float:
    return sum(float(item.get("net_pnl", 0.0) or 0.0) for item in get_risk_relevant_realized(limit=500))


def get_risk_relevant_win_rate(limit: int = 80) -> float:
    pnls = get_risk_relevant_pnls(limit=limit)
    if not pnls:
        return 0.5
    return sum(1 for pnl in pnls if pnl > 0) / len(pnls)


def get_recent_risk_snapshot() -> dict[str, float]:
    update_daily_pnl()

    recent_pnls_local = [float(pnl) for pnl in get_risk_relevant_pnls(limit=RISK_RECENT_PNL_WINDOW)]
    protection_recent_items = get_protection_relevant_realized(limit=max(500, RISK_RECENT_PNL_WINDOW))
    protection_recent_pnls = [
        float(item.get("net_pnl", 0.0) or 0.0) for item in protection_recent_items[-RISK_RECENT_PNL_WINDOW:]
    ]
    total_margin = float(brain.get("last_margin", {}).get("total_margin", 0.0) or 0.0)
    margin_base = max(total_margin, 800.0)

    recent_loss_sats = sum(-min(0.0, pnl) for pnl in recent_pnls_local)
    recent_net_pnl = sum(recent_pnls_local)
    daily_pnl = get_daily_risk_pnl()
    daily_loss_sats = abs(min(0.0, daily_pnl))

    recent_loss_ratio = recent_loss_sats / margin_base
    daily_loss_ratio = daily_loss_sats / margin_base
    protection_recent_loss_sats = sum(-min(0.0, pnl) for pnl in protection_recent_pnls)
    protection_daily_pnl = 0.0
    today = datetime.now().date().isoformat()
    for item in protection_recent_items:
        if item.get("date") != today:
            continue
        protection_daily_pnl += float(item.get("net_pnl", 0.0) or 0.0)
    protection_daily_loss_sats = abs(min(0.0, protection_daily_pnl))
    protection_recent_loss_ratio = protection_recent_loss_sats / margin_base
    protection_daily_loss_ratio = protection_daily_loss_sats / margin_base
    legacy_drawdown = sanitize_legacy_drawdown(brain.get("drawdown", 0.0))
    consecutive_losses = float(get_effective_consecutive_losses())
    raw_consecutive_losses = float(get_consecutive_losses())

    snapshot = {
        "recent_loss_sats": recent_loss_sats,
        "recent_net_pnl": recent_net_pnl,
        "recent_loss_ratio": recent_loss_ratio,
        "daily_risk_pnl": daily_pnl,
        "daily_loss_sats": daily_loss_sats,
        "daily_loss_ratio": daily_loss_ratio,
        "protection_recent_loss_sats": protection_recent_loss_sats,
        "protection_recent_loss_ratio": protection_recent_loss_ratio,
        "protection_daily_risk_pnl": protection_daily_pnl,
        "protection_daily_loss_sats": protection_daily_loss_sats,
        "protection_daily_loss_ratio": protection_daily_loss_ratio,
        "legacy_drawdown": legacy_drawdown,
        "consecutive_losses": consecutive_losses,
        "raw_consecutive_losses": raw_consecutive_losses,
        "margin_base": margin_base,
        "strategic_mode": str((brain.get("last_strategic_context", {}) or {}).get("mode", "observe") or "observe"),
        "effective_explore_rate": float(
            (((brain.get("exploration", {}) or {}).get("last_mix_detail", {}) or {}).get(
                "final",
                (brain.get("exploration", {}) or {}).get("mix_rate", EXPLORATION_BASE_RATE),
            ) or EXPLORATION_BASE_RATE)
        ),
    }
    refresh_risk_persistence_fields()
    brain["recent_risk_snapshot"] = safe_serialize(snapshot)
    return snapshot


def describe_risk_mode() -> str:
    snapshot = brain.get("recent_risk_snapshot") or get_recent_risk_snapshot()
    recent_loss_ratio = float(snapshot.get("recent_loss_ratio", 0.0))
    daily_loss_ratio = float(snapshot.get("daily_loss_ratio", 0.0))
    protection_recent_loss_ratio = float(snapshot.get("protection_recent_loss_ratio", recent_loss_ratio))
    protection_daily_loss_ratio = float(snapshot.get("protection_daily_loss_ratio", daily_loss_ratio))
    consecutive_losses = int(get_effective_consecutive_losses())
    streak = get_risk_streak()
    cooldown_remaining = max(0, int(brain.get("cooldown_until", 0) - time.time()))
    strategic_mode = str(snapshot.get("strategic_mode", "observe") or "observe")

    reasons: list[str] = []
    if cooldown_remaining > 0:
        reasons.append(f"cooldown={cooldown_remaining}s")
    if protection_recent_loss_ratio > RISK_PROTECTION_RECENT_LOSS_RATIO:
        reasons.append(f"recent_loss={protection_recent_loss_ratio:.3f}>{RISK_PROTECTION_RECENT_LOSS_RATIO:.3f}")
    elif recent_loss_ratio > RISK_CAUTION_RECENT_LOSS_RATIO:
        reasons.append(f"recent_loss={recent_loss_ratio:.3f}>{RISK_CAUTION_RECENT_LOSS_RATIO:.3f}")
    if protection_daily_loss_ratio > RISK_PROTECTION_DAILY_LOSS_RATIO:
        reasons.append(f"daily_loss={protection_daily_loss_ratio:.3f}>{RISK_PROTECTION_DAILY_LOSS_RATIO:.3f}")
    elif daily_loss_ratio > RISK_CAUTION_DAILY_LOSS_RATIO:
        reasons.append(f"daily_loss={daily_loss_ratio:.3f}>{RISK_CAUTION_DAILY_LOSS_RATIO:.3f}")
    if consecutive_losses >= RISK_CAUTION_CONSECUTIVE_LOSSES:
        reasons.append(f"effective_consec_losses={consecutive_losses}>={RISK_CAUTION_CONSECUTIVE_LOSSES}")
    elif consecutive_losses > 0:
        reasons.append(f"effective_consec_losses={consecutive_losses}")
    if streak <= RISK_CAUTION_STREAK:
        reasons.append(f"streak={streak}<={RISK_CAUTION_STREAK}")
    reasons.append(f"strategic={strategic_mode}")

    if reasons:
        return ", ".join(reasons[:3])

    return (
        f"recent_loss={recent_loss_ratio:.3f} "
        f"daily_loss={daily_loss_ratio:.3f} "
        f"effective_consec_losses={consecutive_losses} "
        f"strategic={strategic_mode} "
        f"explore_rate={float(snapshot.get('effective_explore_rate', EXPLORATION_BASE_RATE) or EXPLORATION_BASE_RATE):.2f}"
    )


def maybe_arm_protection_cooldown(now: datetime, realized_record: dict[str, Any]) -> None:
    if bool(realized_record.get("exclude_from_protection", False)):
        return
    try:
        net_pnl = float(realized_record.get("net_pnl", realized_record.get("pnl", 0.0)) or 0.0)
    except (TypeError, ValueError):
        net_pnl = 0.0
    if net_pnl >= 0:
        return

    snapshot = get_recent_risk_snapshot()
    protection_recent_loss_ratio = float(snapshot.get("protection_recent_loss_ratio", 0.0))
    protection_daily_loss_ratio = float(snapshot.get("protection_daily_loss_ratio", 0.0))
    if (
        protection_recent_loss_ratio <= RISK_PROTECTION_RECENT_LOSS_RATIO
        and protection_daily_loss_ratio <= RISK_PROTECTION_DAILY_LOSS_RATIO
    ):
        return

    desired_cooldown_until = int(now.timestamp()) + RISK_PROTECTION_COOLDOWN_SECONDS
    current_cooldown_until = int(brain.get("cooldown_until", 0) or 0)
    if desired_cooldown_until > current_cooldown_until:
        brain["cooldown_until"] = desired_cooldown_until


def compute_exploration_mix_rate(adaptive: dict[str, Any], market_quality: float) -> float:
    thresholds = get_exploration_thresholds()
    regime = str(adaptive.get("regime", brain.get("market_regime", {}).get("regime", "unknown")) or "unknown")
    usable = float(brain.get("last_margin", {}).get("usable", 0.0) or 0.0)
    small_account = usable > 0 and usable < SMALL_ACCOUNT_CHOP_SUPPRESS_SATS
    market = brain.get("market_context", {}) or {}
    oracle_insight = get_oracle_regime_insight(regime)
    risk_mode = str(brain.get("risk_mode", "normal") or "normal")
    counts = get_recent_trade_counts()
    strategic = get_strategic_aggression_context()
    flat_minutes = get_flat_duration_minutes()
    range_established = bool(market.get("range_established", False))
    regime_bias = str(brain.get("market_regime", {}).get("bias", "neutral") or "neutral")
    mtf_alignment = str(market.get("mtf_alignment", "mixed") or "mixed")
    adaptive_metrics = ((thresholds.get("adaptive_trade_management", {}) or {}).get("last_metrics", {}) or {})

    rate_floor = float(thresholds.get("mix_floor", 0.10) or 0.10)
    rate_ceiling = float(thresholds.get("mix_ceiling", 0.72) or 0.72)
    anchor = clamp(
        EXPLORATION_BASE_RATE + float(thresholds.get("mix_bias", 0.0) or 0.0),
        rate_floor,
        rate_ceiling,
    )
    rate = anchor
    detail = {
        "anchor": round(anchor, 4),
        "floor": round(rate_floor, 4),
        "ceiling": round(rate_ceiling, 4),
    }

    regime_adj = 0.0
    if regime == "trend":
        regime_adj += 0.14 if regime_bias in {"bullish", "bearish"} else 0.08
    elif regime == "volatile":
        regime_adj += 0.08
    elif regime == "squeeze":
        regime_adj += 0.06 if range_established else -0.06
        if regime_bias == "neutral":
            regime_adj -= 0.02
    elif regime == "chop":
        regime_adj -= 0.02
    else:
        regime_adj -= 0.10
    if small_account and regime == "chop":
        regime_adj -= 0.06
    detail["regime_adj"] = round(regime_adj, 4)
    rate += regime_adj

    range_adj = 0.0
    if range_established:
        range_width_pct = float(market.get("range_width_pct", 0.0) or 0.0)
        range_adj += min(0.06, max(0.0, range_width_pct - get_range_width_min()) * 18.0)
    elif regime == "squeeze":
        range_adj -= 0.04
    detail["range_adj"] = round(range_adj, 4)
    rate += range_adj

    oracle_fcr = float(oracle_insight.get("fee_clear_rate", 0.0) or 0.0)
    oracle_score = float(oracle_insight.get("score", 0.0) or 0.0)
    oracle_peak_bps = float(oracle_insight.get("avg_peak_bps", 0.0) or 0.0)
    oracle_adj = clamp(
        (oracle_fcr - 0.35) * 0.28
        + (oracle_score - 0.50) * 0.35
        + (oracle_peak_bps - ORACLE_REPLAY_FEE_PROXY_BPS) / 180.0,
        -0.16,
        0.20,
    )
    detail["oracle_adj"] = round(oracle_adj, 4)
    rate += oracle_adj

    quality_adj = clamp((market_quality - 0.45) * 0.40, -0.10, 0.12)
    if mtf_alignment in {"bullish", "bearish"} and regime_bias in {"bullish", "bearish"} and mtf_alignment == regime_bias:
        quality_adj += 0.04
    detail["quality_adj"] = round(quality_adj, 4)
    rate += quality_adj

    flat_bonus = 0.0
    if regime == "squeeze" and flat_minutes > SQUEEZE_PATIENCE_START_MINUTES:
        flat_bonus = min(
            SQUEEZE_PATIENCE_BONUS_MAX,
            (flat_minutes - SQUEEZE_PATIENCE_START_MINUTES)
            / max(SQUEEZE_PATIENCE_FULL_MINUTES - SQUEEZE_PATIENCE_START_MINUTES, 1.0)
            * SQUEEZE_PATIENCE_BONUS_MAX,
        )
    elif flat_minutes > FLAT_REACTIVATION_START_MINUTES:
        flat_bonus = min(
            0.08,
            (flat_minutes - FLAT_REACTIVATION_START_MINUTES)
            / max(FLAT_REACTIVATION_FULL_MINUTES - FLAT_REACTIVATION_START_MINUTES, 1.0)
            * 0.08,
        )
    detail["flat_bonus"] = round(flat_bonus, 4)
    rate += flat_bonus

    add_success_rate = float(adaptive_metrics.get("add_success_rate", 0.0) or 0.0)
    fee_clear_rate = float(adaptive_metrics.get("fee_clear_rate", oracle_fcr) or oracle_fcr)
    post_win_churn_rate = float(adaptive_metrics.get("post_win_churn_rate", 0.0) or 0.0)
    add_to_stop_rate = float(adaptive_metrics.get("add_to_stop_rate", 0.0) or 0.0)
    stats_adj = clamp(
        (fee_clear_rate - 0.40) * 0.22
        + (add_success_rate - 0.40) * 0.16
        - post_win_churn_rate * 0.12
        - add_to_stop_rate * 0.14,
        -0.18,
        0.14,
    )
    detail["stats_adj"] = round(stats_adj, 4)
    rate += stats_adj

    frequency_penalty = min(
        EXPLORATION_FREQUENCY_PENALTY_MAX,
        max(0.0, (float(counts["explore"]) - EXPLORATION_FREQUENCY_SOFT_COUNT) / max(EXPLORATION_FREQUENCY_SOFT_COUNT, 1.0))
        * EXPLORATION_FREQUENCY_PENALTY_MAX,
    )
    detail["frequency_penalty"] = round(frequency_penalty, 4)
    rate -= frequency_penalty

    gate_state = brain.get("last_entry_gate_state", {}) or {}
    align_score = float((gate_state.get("chop_alignment") or {}).get("score", 0.0) or 0.0)
    setup_edge = float(gate_state.get("quality", 0.0) or 0.0)
    loss_penalty = min(get_effective_consecutive_losses() * 0.04, 0.16)
    if strategic.get("default_aggressive"):
        loss_penalty *= 0.50
    risk_adj = -loss_penalty
    if risk_mode == "caution":
        risk_adj -= 0.10 * get_caution_decay_multiplier()
    elif risk_mode == "protection":
        risk_adj -= 0.24
    detail["risk_adj"] = round(risk_adj, 4)
    rate += risk_adj

    if strategic.get("default_aggressive"):
        structure_boost = min(0.10, float(strategic.get("structure_confidence", 0.0) or 0.0) * 0.08)
        rate += structure_boost
        detail["structure_boost"] = round(structure_boost, 4)
    else:
        detail["structure_boost"] = 0.0

    if regime in {"trend", "squeeze"} and market_quality >= 0.50 and oracle_fcr >= 0.38:
        rate_floor = max(rate_floor, 0.18 if regime == "squeeze" else 0.22)
    caution_floor = None
    if risk_mode == "caution" and flat_minutes >= CAUTION_DECAY_START_MINUTES:
        caution_progress = min(
            (flat_minutes - CAUTION_DECAY_START_MINUTES)
            / max(CAUTION_DECAY_FULL_MINUTES - CAUTION_DECAY_START_MINUTES, 1.0),
            1.0,
        )
        squeeze_floor = 0.50 + 0.06 * caution_progress
        directional_floor = 0.45 + 0.05 * caution_progress
        caution_floor = squeeze_floor if regime == "squeeze" else directional_floor
        rate_floor = max(rate_floor, caution_floor)
    attack_floor = None
    if str(strategic.get("mode", "observe") or "observe") == "attack":
        attack_floor = 0.55
        rate_floor = max(rate_floor, attack_floor)
        rate_ceiling = max(rate_ceiling, attack_floor)
        rate = max(rate, attack_floor)
    if (
        regime == "squeeze"
        and flat_minutes >= CONSECUTIVE_LOSS_DECAY_REDUCED_MINUTES
        and (setup_edge >= 0.55 or align_score >= 0.65)
    ):
        rate_floor = max(rate_floor, 0.50)
        rate = max(rate, 0.50)
    if regime == "squeeze" and not range_established and oracle_fcr < 0.30:
        rate_ceiling = min(rate_ceiling, 0.28)
    if risk_mode == "protection":
        rate_ceiling = min(rate_ceiling, 0.18)

    final_rate = clamp(rate, max(EXPLORATION_MIN_RATE, rate_floor), min(EXPLORATION_MAX_RATE, rate_ceiling))
    if caution_floor is not None:
        final_rate = max(final_rate, caution_floor)
    if attack_floor is not None:
        final_rate = max(final_rate, attack_floor)
    detail["final"] = round(final_rate, 4)
    if caution_floor is not None:
        detail["caution_floor"] = round(caution_floor, 4)
    if attack_floor is not None:
        detail["attack_floor"] = round(attack_floor, 4)
    detail["setup_edge"] = round(setup_edge, 4)
    detail["align_score"] = round(align_score, 4)
    detail["regime"] = regime
    detail["flat_minutes"] = round(flat_minutes, 1)
    detail["oracle_fcr"] = round(oracle_fcr, 4)
    detail["oracle_score"] = round(oracle_score, 4)
    detail["range_established"] = range_established
    detail["explore_count_1h"] = counts["explore"]
    detail["total_count_1h"] = counts["total"]
    exploration = brain.setdefault("exploration", {})
    exploration["last_mix_detail"] = detail
    exploration["mix_rate"] = round(final_rate, 4)
    return final_rate


def get_effective_explore_rate() -> float:
    exploration = brain.get("exploration", {}) or {}
    final_rate = float(((exploration.get("last_mix_detail", {}) or {}).get("final", exploration.get("mix_rate", EXPLORATION_BASE_RATE)) or EXPLORATION_BASE_RATE))
    strategic_mode = str((brain.get("last_strategic_context", {}) or {}).get("mode", "observe") or "observe")
    if strategic_mode == "attack":
        final_rate = max(final_rate, 0.55)
    brain.setdefault("exploration", {})["mix_rate"] = round(final_rate, 4)
    return final_rate


def get_exploration_context_fingerprint(regime: str) -> str:
    market = brain.get("market_context", {})
    price_action = brain.get("price_action_summary", "neutral")
    momentum = float(brain.get("momentum", 0.0) or 0.0)
    imbalance = float(market.get("imbalance", 0.0) or 0.0)
    spread = float(market.get("spread_pct", 0.0) or 0.0)

    def bucket(value: float, thresholds: list[float]) -> int:
        for idx, threshold in enumerate(thresholds):
            if value < threshold:
                return idx
        return len(thresholds)

    momentum_bucket = bucket(abs(momentum), [0.00015, 0.00045, 0.0009])
    imbalance_bucket = bucket(abs(imbalance), [0.05, 0.12, 0.22])
    spread_bucket = bucket(spread, [0.02, 0.04, 0.07])
    range_pos = float(market.get("range_position", 0.5) or 0.5)
    range_bucket = 0 if range_pos <= get_range_long_max() else 2 if range_pos >= get_range_short_min() else 1

    return f"{regime}|{price_action}|m{momentum_bucket}|i{imbalance_bucket}|s{spread_bucket}|r{range_bucket}"


def get_context_policy_stats(fingerprint: str) -> dict[str, dict[str, Any]]:
    recent = brain.get("exploration", {}).get("recent", [])
    stats: dict[str, dict[str, Any]] = {}

    for item in recent[-60:]:
        if item.get("fingerprint") != fingerprint:
            continue
        policy = item.get("policy")
        if not policy:
            continue
        entry = stats.setdefault(
            policy,
            {
                "attempts": 0,
                "wins": 0,
                "score_sum": 0.0,
                "resolved": 0,
                "net_pnl_sum": 0.0,
                "fee_clears": 0,
                "peak_fee_multiple_sum": 0.0,
                "time_to_mfe_sum": 0.0,
                "timed_mfe_count": 0,
            },
        )
        entry["attempts"] += 1
        outcome_pnl = float(item.get("outcome_pnl", 0.0) or 0.0)
        if outcome_pnl > 0:
            entry["wins"] += 1
        entry["score_sum"] += float(item.get("score", 0.0) or 0.0)
        if item.get("outcome_pnl") is not None:
            entry["resolved"] += 1
            entry["net_pnl_sum"] += outcome_pnl
            if item.get("fee_cleared"):
                entry["fee_clears"] += 1
            entry["peak_fee_multiple_sum"] += float(item.get("max_fee_multiple", 0.0) or 0.0)
            time_to_mfe = item.get("time_to_mfe_minutes")
            if time_to_mfe is not None:
                entry["time_to_mfe_sum"] += float(time_to_mfe or 0.0)
                entry["timed_mfe_count"] += 1

    return stats


def get_shadow_context_policy_stats(fingerprint: str) -> dict[str, dict[str, Any]]:
    recent = brain.get("shadow_exploration", {}).get("recent", [])
    stats: dict[str, dict[str, Any]] = {}

    for item in recent[-120:]:
        if item.get("fingerprint") != fingerprint or item.get("outcome_bps") is None:
            continue
        policy = item.get("policy")
        if not policy:
            continue
        entry = stats.setdefault(
            policy,
            {
                "resolved": 0,
                "wins": 0,
                "outcome_bps_sum": 0.0,
                "fee_clears": 0,
                "peak_fee_multiple_sum": 0.0,
                "time_to_mfe_sum": 0.0,
                "timed_mfe_count": 0,
            },
        )
        entry["resolved"] += 1
        outcome_bps = float(item.get("outcome_bps", 0.0) or 0.0)
        entry["outcome_bps_sum"] += outcome_bps
        if outcome_bps > 0:
            entry["wins"] += 1
        if item.get("fee_cleared"):
            entry["fee_clears"] += 1
        entry["peak_fee_multiple_sum"] += float(item.get("max_fee_multiple", 0.0) or 0.0)
        time_to_mfe = item.get("time_to_mfe_minutes")
        if time_to_mfe is not None:
            entry["time_to_mfe_sum"] += float(time_to_mfe or 0.0)
            entry["timed_mfe_count"] += 1

    return stats


def get_shadow_policy_direction_stats(fingerprint: str, policy: str, direction: str) -> dict[str, Any]:
    recent = brain.get("shadow_exploration", {}).get("recent", [])
    stats = {
        "resolved": 0,
        "wins": 0,
        "outcome_bps_sum": 0.0,
        "fee_clears": 0,
        "peak_fee_multiple_sum": 0.0,
        "time_to_mfe_sum": 0.0,
        "timed_mfe_count": 0,
    }

    for item in recent[-120:]:
        if item.get("fingerprint") != fingerprint:
            continue
        if item.get("policy") != policy or item.get("direction") != direction:
            continue
        if item.get("outcome_bps") is None:
            continue
        stats["resolved"] += 1
        outcome_bps = float(item.get("outcome_bps", 0.0) or 0.0)
        stats["outcome_bps_sum"] += outcome_bps
        if outcome_bps > 0:
            stats["wins"] += 1
        if item.get("fee_cleared"):
            stats["fee_clears"] += 1
        stats["peak_fee_multiple_sum"] += float(item.get("max_fee_multiple", 0.0) or 0.0)
        time_to_mfe = item.get("time_to_mfe_minutes")
        if time_to_mfe is not None:
            stats["time_to_mfe_sum"] += float(time_to_mfe or 0.0)
            stats["timed_mfe_count"] += 1

    return stats


def summarize_shadow_direction_proof(
    regime: str,
    direction: str,
    *,
    policies: Optional[set[str]] = None,
) -> dict[str, Any]:
    recent = brain.get("shadow_exploration", {}).get("recent", [])
    fingerprint = get_exploration_context_fingerprint(regime)
    resolved_items = []
    for item in recent[-120:]:
        if item.get("fingerprint") != fingerprint:
            continue
        if item.get("direction") != direction or item.get("outcome_bps") is None:
            continue
        if policies and item.get("policy") not in policies:
            continue
        resolved_items.append(item)

    resolved = len(resolved_items)
    fee_clears = sum(1 for item in resolved_items if item.get("fee_cleared"))
    avg_outcome = (
        sum(float(item.get("outcome_bps", 0.0) or 0.0) for item in resolved_items) / max(resolved, 1)
        if resolved else 0.0
    )
    avg_peak_fee = (
        sum(float(item.get("max_fee_multiple", 0.0) or 0.0) for item in resolved_items) / max(resolved, 1)
        if resolved else 0.0
    )
    fee_clear_rate = fee_clears / max(resolved, 1) if resolved else 0.0
    proven = bool(
        resolved >= 2
        and fee_clears >= 1
        and fee_clear_rate >= 0.50
        and avg_outcome >= 16.0
        and avg_peak_fee >= 1.10
    )
    return {
        "proven": proven,
        "resolved": resolved,
        "fee_clears": fee_clears,
        "fee_clear_rate": round(fee_clear_rate, 4),
        "avg_outcome_bps": round(avg_outcome, 3),
        "avg_peak_fee": round(avg_peak_fee, 3),
        "fingerprint": fingerprint,
    }


def summarize_live_direction_drag(regime: str, policy: str, direction: str) -> dict[str, Any]:
    recent = brain.get("exploration", {}).get("recent", [])
    fingerprint = get_exploration_context_fingerprint(regime)
    resolved_items = []
    for item in recent[-60:]:
        if item.get("fingerprint") != fingerprint:
            continue
        if item.get("policy") != policy or item.get("direction") != direction:
            continue
        if item.get("outcome_pnl") is None:
            continue
        resolved_items.append(item)

    resolved = len(resolved_items)
    avg_pnl = (
        sum(float(item.get("outcome_pnl", 0.0) or 0.0) for item in resolved_items) / max(resolved, 1)
        if resolved else 0.0
    )
    losses = sum(1 for item in resolved_items if float(item.get("outcome_pnl", 0.0) or 0.0) < 0.0)
    loss_rate = losses / max(resolved, 1) if resolved else 0.0
    dragging = bool(resolved >= 2 and avg_pnl < 0.0 and loss_rate >= 0.60)
    return {
        "dragging": dragging,
        "resolved": resolved,
        "loss_rate": round(loss_rate, 4),
        "avg_pnl": round(avg_pnl, 2),
        "fingerprint": fingerprint,
    }


def apply_custom_roi_plan(signal: EntrySignal) -> None:
    """
    Entry-time ROI shaping inspired by strategy callbacks: protect mean-revert
    probes from overholding while letting shadow-proven breakouts keep room.
    """
    regime = str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown")
    signal_ctx = get_signal_context()
    original_tp = int(signal.tp_bps or 0)
    original_hold = int(signal.max_hold_minutes or 0)
    min_tp = max(50, int(signal.sl_bps * MIN_TP_TO_SL))
    proof = summarize_shadow_direction_proof(
        regime,
        signal.direction,
        policies={"breakout_probe"} if signal.intent == "breakout" else None,
    )

    if regime == "squeeze" and signal.intent == "mean_revert":
        range_established = bool(signal_ctx.get("range_established", False))
        # Squeeze reclaims are probes unless the range is established; don't
        # let them become stale narrative holds.
        if not range_established:
            signal.tp_bps = max(min_tp, min(signal.tp_bps, 95))
            signal.max_hold_minutes = min(signal.max_hold_minutes, 36)
    elif signal.intent == "breakout" and proof.get("proven"):
        signal.tp_bps = max(signal.tp_bps, max(min_tp, 110))
        signal.max_hold_minutes = max(signal.max_hold_minutes, 45)

    signal.roi_schedule_reason = (
        f"roi_schedule 0m={signal.tp_bps}bps "
        f"10m={max(50, int(signal.tp_bps * 0.75))}bps "
        f"30m={max(35, int(signal.tp_bps * 0.50))}bps "
        f"max_hold={signal.max_hold_minutes}m"
    )

    if signal.tp_bps != original_tp or signal.max_hold_minutes != original_hold:
        log(
            f"🎯 Custom ROI plan | tp {original_tp}->{signal.tp_bps}bps "
            f"hold {original_hold}->{signal.max_hold_minutes}m | "
            f"proof={proof.get('proven')} avg={float(proof.get('avg_outcome_bps', 0.0)):+.1f}bps"
        )
    append_review_report(
        "roi_schedule_plan",
        {
            "entry_tag": signal.entry_tag,
            "policy": signal.policy,
            "intent": signal.intent,
            "direction": signal.direction,
            "tp_bps": signal.tp_bps,
            "sl_bps": signal.sl_bps,
            "max_hold_minutes": signal.max_hold_minutes,
            "reason": signal.roi_schedule_reason,
        },
    )


def confirm_live_entry(signal: EntrySignal, usable: float) -> tuple[bool, str]:
    """
    Final deterministic entry confirmation. It can only block or explain; level,
    risk, cooldown, tuner, and exchange gates still run separately.
    """
    if signal.action != "open":
        return True, "not_open"

    regime = str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown")
    signal_ctx = get_signal_context()
    direction = str(signal.direction or "")
    opposite = "short" if direction == "long" else "long"
    same_proof = summarize_shadow_direction_proof(regime, direction)
    opposite_breakout_proof = summarize_shadow_direction_proof(regime, opposite, policies={"breakout_probe"})
    live_drag = summarize_live_direction_drag(regime, signal.policy, direction)
    alignment = get_broader_structure_alignment(direction, signal.intent)
    gate_state = dict(getattr(signal, "entry_gate_state_snapshot", None) or brain.get("last_entry_gate_state", {}) or {})
    align_score = float((gate_state.get("chop_alignment") or {}).get("score", 0.0) or 0.0)
    expected_edge = float(signal.expected_edge or 0.0)
    pred = float(getattr(signal, "predictive_setup_score", 0.0) or 0.0)
    level_edge = bool(
        (direction == "long" and (signal_ctx.get("at_support", False) or signal_ctx.get("sweep_reclaim_long", False)))
        or (direction == "short" and (signal_ctx.get("at_resistance", False) or signal_ctx.get("sweep_reclaim_short", False)))
    )
    caution_decay = get_caution_decay_multiplier()
    caution_alignment_override = bool(
        level_edge
        and (
            (alignment == "aligned" and expected_edge >= 0.32 and pred >= 0.48)
            or (alignment == "supportive" and expected_edge >= 0.32 and pred >= 0.48 and caution_decay <= 0.95)
            or (align_score >= 0.55 and expected_edge >= 0.32 and pred >= 0.48)
            or (
                brain.get("risk_mode") == "caution"
                and get_flat_duration_minutes() >= 25.0
                and (alignment in {"aligned", "supportive"} or align_score >= 0.55)
                and expected_edge >= 0.32
                and pred >= 0.48
            )
        )
    )
    evidence = get_evidence_validity(signal)
    signal.evidence_valid = bool(evidence.get("valid", False))
    signal.evidence_reason = str(evidence.get("reason", "n/a"))
    if signal.mode == "explore" and not signal.evidence_valid:
        return False, f"evidence invalid for exploration | {signal.evidence_reason}"

    small_account = usable < SMALL_ACCOUNT_DYNAMIC_SIZING_SATS
    elite_chop = bool(gate_state.get("elite_chop", False))
    expected_edge_floor = get_exploration_min_edge(regime, signal.intent, small_account, elite_chop)
    if regime == "squeeze":
        expected_edge_floor = max(expected_edge_floor, 0.20)
    if signal.policy == "ai_primary":
        expected_edge_floor = max(expected_edge_floor, 0.22)
    if brain.get("risk_mode") == "caution" and not same_proof.get("proven"):
        expected_edge_floor = max(expected_edge_floor, 0.22)
    structure = brain.get("broader_structure") or {}
    effective_edge, edge_lift, edge_lift_reason = compute_aggressive_learning_edge_lift(
        base_edge=expected_edge,
        predictive_score=pred,
        alignment=alignment,
        level_edge=level_edge,
        same_proof=same_proof,
        structure_confidence=float(structure.get("confidence", 0.0) or 0.0),
    )
    if edge_lift > 0.0:
        signal.expected_edge = max(float(signal.expected_edge or 0.0), effective_edge)
        expected_edge = effective_edge
        expected_edge_floor = max(
            AGGRESSIVE_LEARNING_MIN_EFFECTIVE_EDGE,
            expected_edge_floor - min(0.10, edge_lift * 0.45),
        )
    if expected_edge < expected_edge_floor:
        return False, (
            f"weak expected edge blocked | policy={signal.policy} mode={signal.mode} "
            f"dir={direction} ev={expected_edge:.2f} < min={expected_edge_floor:.2f} "
            f"pred={pred:.2f} align={alignment} shadow_same={same_proof.get('proven')} "
            f"lift={edge_lift:.2f}/{edge_lift_reason}"
        )

    if regime == "squeeze" and signal.intent == "mean_revert":
        room_to_target_bps = float(
            signal_ctx.get(
                "room_to_resistance_bps" if direction == "long" else "room_to_support_bps",
                0.0,
            )
            or 0.0
        )
        min_live_room_bps = max(LEVEL_MIN_ROOM_HARD_FLOOR_BPS, get_level_min_room_bps())
        has_directional_reclaim = bool(
            (
                direction == "long"
                and (signal_ctx.get("wyckoff_spring_long", False) or signal_ctx.get("sweep_reclaim_long", False))
            )
            or (
                direction == "short"
                and (signal_ctx.get("wyckoff_spring_short", False) or signal_ctx.get("sweep_reclaim_short", False))
            )
        )
        if not has_directional_reclaim and room_to_target_bps < min_live_room_bps:
            return False, (
                f"squeeze mean-revert room gate | room={room_to_target_bps:.1f}bps "
                f"< min={min_live_room_bps:.1f}bps"
            )

    if regime == "squeeze" and signal.intent == "trend_follow":
        range_established = bool(signal_ctx.get("range_established", False))
        replay_mtf = float(get_oracle_regime_insight(regime).get("avg_mtf_alignment_score", 0.0) or 0.0)
        if not range_established or replay_mtf < 0.50:
            return False, (
                f"weak squeeze trend_follow blocked | range={range_established} "
                f"replay_mtf={replay_mtf:.2f}"
            )

    if (
        regime == "squeeze"
        and direction == "short"
        and signal.intent in {"mean_revert", "mean_revert_reclaim"}
        and opposite_breakout_proof.get("proven")
    ):
        range_pos = float(signal_ctx.get("range_position", 0.5) or 0.5)
        at_resistance = bool(signal_ctx.get("at_resistance", False) or signal_ctx.get("sweep_reclaim_short", False))
        room_down = float(signal_ctx.get("room_to_support_bps", 0.0) or 0.0)
        short_edge_ok = at_resistance and range_pos >= get_range_short_min() and room_down >= get_level_min_room_bps()
        if not short_edge_ok:
            return False, (
                "shadow side proof blocks squeeze short reclaim | "
                f"long_breakout avg={float(opposite_breakout_proof.get('avg_outcome_bps', 0.0)):+.1f}bps "
                f"peak={float(opposite_breakout_proof.get('avg_peak_fee', 0.0)):.2f}"
            )

    if opposite_breakout_proof.get("proven") and alignment not in {"aligned", "supportive"}:
        return False, (
            f"entry conflicts with proven shadow {opposite} breakout | align={alignment} "
            f"avg={float(opposite_breakout_proof.get('avg_outcome_bps', 0.0)):+.1f}bps"
        )

    caution_block_edge = 0.55 - min((1.0 - caution_decay) * 0.30, 0.24)
    if (
        brain.get("risk_mode") == "caution"
        and not caution_alignment_override
        and not same_proof.get("proven")
        and live_drag.get("dragging")
        and expected_edge < caution_block_edge
    ):
        return False, (
            f"caution blocks unproven dragging lane | policy={signal.policy} dir={direction} "
            f"ev={expected_edge:.2f} min={caution_block_edge:.2f} pred={pred:.2f} "
            f"live_avg={float(live_drag.get('avg_pnl', 0.0)):+.0f}"
        )

    # Intraday MTF directional filter (hard block — htf_bias_score is soft only)
    mtf = str(signal_ctx.get("mtf_alignment", "mixed") or "mixed")
    going_against_mtf = mtf in {"bullish", "bearish"} and (
        (direction == "long" and mtf == "bearish") or (direction == "short" and mtf == "bullish")
    )
    if going_against_mtf and pred < 0.70:
        mtf_bypass = bool(
            expected_edge >= 0.32
            and pred >= 0.50
            and get_flat_duration_minutes() >= AGGRESSIVE_LEARNING_FLAT_BYPASS_MINUTES
            and (level_edge or alignment in {"aligned", "supportive"})
            and str(brain.get("risk_mode", "normal") or "normal") != "protection"
        )
        if not mtf_bypass:
            return False, (
                f"MTF directional block | mtf={mtf} dir={direction} "
                f"pred={pred:.2f} < 0.70 required against strong MTF"
            )
        log(
            f"⚡ MTF BYPASS: mtf={mtf} dir={direction} pred={pred:.2f} "
            f"ev={expected_edge:.2f} align={alignment}"
        )

    return True, (
        f"confirmed | shadow_same={same_proof.get('proven')} "
        f"live_drag={live_drag.get('dragging')} ev={expected_edge:.2f} pred={pred:.2f} "
        f"lift={edge_lift:.2f}/{edge_lift_reason} caution_decay={caution_decay:.2f} "
        f"high_align={caution_alignment_override} usable={usable:.0f}"
    )


def confirm_live_exit(position: PositionState, thesis: dict[str, Any], price: float, reason: str) -> tuple[bool, str]:
    """
    Strict exit confirmation wrapper. It never relaxes DET_THESIS_BREAK; it only
    makes repeated clearly-broken states explicit and auditable.
    """
    clearly_broken, broken_reason = is_clearly_broken_exit(position, thesis, price)
    if is_hard_exit_reason(reason):
        return True, f"hard_exit | {reason}"
    if not clearly_broken:
        brain.pop("broken_thesis_started_at", None)
        return False, broken_reason
    if "stale_escape" in broken_reason:
        return True, f"DET_THESIS_BREAK confirmed | stale_escape | {broken_reason}"

    now = time.time()
    started_at = float(brain.get("broken_thesis_started_at", 0.0) or 0.0)
    if started_at <= 0.0:
        brain["broken_thesis_started_at"] = now
        started_at = now
    close_alignment = compute_close_alignment(position, thesis, price)
    close_align_score = float(close_alignment.get("score", 0.0) or 0.0)
    persistent = (now - started_at) >= 20.0
    decisive = close_align_score >= 0.58 or float(thesis.get("score", 0.0) or 0.0) <= (BROKEN_EXIT_THESIS_SCORE - 0.20)
    if persistent or decisive:
        return True, (
            f"DET_THESIS_BREAK confirmed | persistent={persistent} "
            f"close_align={close_align_score:+.2f} | {broken_reason}"
        )
    return False, (
        f"DET_THESIS_BREAK observed, waiting persistence | "
        f"age={now - started_at:.0f}s close_align={close_align_score:+.2f} | {broken_reason}"
    )


def confirm_entry_price_deviation(signal: EntrySignal) -> tuple[bool, str]:
    signal_price = float(signal.signal_price or 0.0)
    current_price = float(brain.get("last_price") or market_state.get("last_price") or 0.0)
    if signal_price <= 0.0 or current_price <= 0.0:
        return False, "missing signal/current price"
    move_bps = ((current_price / signal_price) - 1.0) * 10000.0
    chasing_long = signal.direction == "long" and move_bps > ENTRY_PRICE_DEVIATION_MAX_BPS
    chasing_short = signal.direction == "short" and move_bps < -ENTRY_PRICE_DEVIATION_MAX_BPS
    if chasing_long or chasing_short:
        return False, (
            f"entry price deviation | signal={signal_price:.0f} current={current_price:.0f} "
            f"move={move_bps:+.1f}bps max={ENTRY_PRICE_DEVIATION_MAX_BPS:.1f}bps"
        )
    return True, f"price deviation ok | move={move_bps:+.1f}bps"


def on_position_filled(signal: EntrySignal, position: PositionState) -> None:
    try:
        append_review_report(
            "position_filled",
            {
                "side": position.side,
                "qty": round(float(position.qty or 0.0), 4),
                "leverage": round(float(position.leverage or 0.0), 3),
                "intent": signal.intent,
                "policy": signal.policy,
                "mode": signal.mode,
                "entry_tag": signal.entry_tag,
                "signal_price": round(float(signal.signal_price or 0.0), 2),
                "evidence_valid": bool(signal.evidence_valid),
                "evidence_reason": signal.evidence_reason,
                "roi_schedule_reason": signal.roi_schedule_reason,
                "tp_bps": int(signal.tp_bps or 0),
                "sl_bps": int(signal.sl_bps or 0),
                "trail_bps": int(signal.trail_bps or 0),
                "max_hold_minutes": int(signal.max_hold_minutes or 0),
                "expected_edge": round(float(signal.expected_edge or 0.0), 4),
                "predictive_setup_score": round(float(signal.predictive_setup_score or 0.0), 4),
                "parent_allocation_reason": signal.parent_allocation_reason or "n/a",
                "tuned_allocation_reason": signal.tuned_allocation_reason or "n/a",
                "exposure_budget": safe_serialize(brain.get("last_exposure_budget", {})),
            },
        )
    except Exception:
        pass


def has_shadow_chop_learner_support(fingerprint: str) -> bool:
    shadow_stats = get_shadow_context_policy_stats(fingerprint)
    for policy in ("mean_revert_micro", "mean_revert_imbalance_fade", "mean_revert_reclaim"):
        stats = shadow_stats.get(policy, {})
        resolved = int(stats.get("resolved", 0) or 0)
        if resolved <= 0:
            continue
        fee_clears = int(stats.get("fee_clears", 0) or 0)
        avg_peak_fee = float(stats.get("peak_fee_multiple_sum", 0.0) or 0.0) / max(resolved, 1)
        if fee_clears > 0 and avg_peak_fee >= CHOP_LEARNER_LANE_MIN_PEAK_FEE:
            return True
    return False


def compute_shadow_selector_bonus(
    shadow_stats: dict[str, Any],
    *,
    cap: float = SHADOW_SELECTOR_BONUS_CAP,
    fee_clear_weight: float = 0.03,
    peak_fee_scale: float = 10.0,
) -> float:
    resolved = int(shadow_stats.get("resolved", 0))
    if not resolved:
        return 0.0
    fee_clear_rate = float(shadow_stats.get("fee_clears", 0)) / max(resolved, 1)
    avg_bps = float(shadow_stats.get("outcome_bps_sum", 0.0) or 0.0) / max(resolved, 1)
    avg_peak_fee = float(shadow_stats.get("peak_fee_multiple_sum", 0.0) or 0.0) / max(resolved, 1)
    bonus = clamp(avg_bps / 40.0, -cap, cap)
    bonus += clamp(fee_clear_rate * fee_clear_weight, 0.0, fee_clear_weight)
    bonus += clamp(avg_peak_fee / peak_fee_scale, -0.01, 0.02)
    return clamp(bonus, -cap, cap)


def compute_predictive_setup_score(
    *,
    regime: str,
    intent: str,
    direction: str,
    context_stats: dict[str, Any],
    shadow_context_stats: dict[str, Any],
    shadow_direction_stats: dict[str, Any],
    oracle_insight: dict[str, Any],
    signal_ctx: Optional[dict[str, Any]] = None,
    llm_predictive_prob: Optional[float] = None,
) -> dict[str, Any]:
    resolved_signal_ctx = signal_ctx or get_signal_context()
    direction_sign = 1.0 if direction == "long" else -1.0
    broader_structure = brain.get("broader_structure") or compute_broader_structure_context(resolved_signal_ctx)
    broader_alignment = get_broader_structure_alignment(direction, intent, broader_structure)
    wyckoff_spring = bool(
        (direction == "long" and resolved_signal_ctx.get("wyckoff_spring_long", False))
        or (direction == "short" and resolved_signal_ctx.get("wyckoff_spring_short", False))
    )
    level_edge = bool(
        (direction == "long" and (resolved_signal_ctx.get("at_support", False) or resolved_signal_ctx.get("sweep_reclaim_long", False) or resolved_signal_ctx.get("wyckoff_spring_long", False)))
        or (direction == "short" and (resolved_signal_ctx.get("at_resistance", False) or resolved_signal_ctx.get("sweep_reclaim_short", False) or resolved_signal_ctx.get("wyckoff_spring_short", False)))
    )
    range_established = bool(resolved_signal_ctx.get("range_established", False))
    range_position = float(resolved_signal_ctx.get("range_position", 0.5) or 0.5)
    range_edge = bool(
        range_established
        and (
            (direction == "long" and range_position <= get_range_long_max())
            or (direction == "short" and range_position >= get_range_short_min())
        )
    )
    oracle_score = float(oracle_insight.get("score", 0.0) or 0.0)
    oracle_fcr = float(oracle_insight.get("fee_clear_rate", 0.0) or 0.0)
    oracle_peak_bps = float(oracle_insight.get("avg_peak_bps", 0.0) or 0.0)
    predictive_horizon = float(resolved_signal_ctx.get("predictive_horizon_score", 0.0) or 0.0)
    predictive_confidence = float(resolved_signal_ctx.get("predictive_horizon_confidence", 0.0) or 0.0)
    orderbook_trend = float(resolved_signal_ctx.get("predictive_orderbook_trend", 0.0) or 0.0)
    funding_accel = float(resolved_signal_ctx.get("predictive_funding_acceleration", 0.0) or 0.0)
    micro_accel = float(resolved_signal_ctx.get("predictive_micro_acceleration", 0.0) or 0.0)
    upside_break = float(resolved_signal_ctx.get("predictive_upside_break_prob", 0.5) or 0.5)
    downside_break = float(resolved_signal_ctx.get("predictive_downside_break_prob", 0.5) or 0.5)
    mtf_alignment = str(resolved_signal_ctx.get("mtf_alignment", "mixed") or "mixed")
    mtf_support = 1.0 if ((direction == "long" and mtf_alignment == "bullish") or (direction == "short" and mtf_alignment == "bearish")) else 0.0
    strategic_mode = str((brain.get("last_strategic_context", {}) or {}).get("mode", "observe") or "observe")
    shadow_bias = get_recent_shadow_bias(regime, direction, intent)
    fee_clear_rate = max(
        float(context_stats.get("fee_clear_rate", 0.0) or 0.0),
        float(shadow_context_stats.get("fee_clear_rate", 0.0) or 0.0),
        oracle_fcr,
    )
    context_peak_fee = max(
        float(context_stats.get("avg_peak_fee_multiple", 0.0) or 0.0),
        float(shadow_context_stats.get("avg_peak_fee_multiple", 0.0) or 0.0),
        float(shadow_direction_stats.get("avg_peak_fee_multiple", 0.0) or 0.0),
    )
    flat_bonus = min(0.08, max(get_flat_duration_minutes() - CAUTION_DECAY_START_MINUTES, 0.0) / 90.0 * 0.08)
    directional_break = upside_break if direction == "long" else downside_break
    opposing_break = downside_break if direction == "long" else upside_break

    score = 0.18
    score += clamp((oracle_score - 0.48) * 0.30, -0.10, 0.14)
    score += clamp((fee_clear_rate - 0.34) * 0.18, -0.04, 0.10)
    score += clamp((oracle_peak_bps - ORACLE_REPLAY_FEE_PROXY_BPS) / 120.0, -0.04, 0.08)
    score += 0.18 if level_edge else 0.0
    score += 0.08 if range_edge else 0.0
    score += 0.10 if broader_alignment == "aligned" else 0.05 if broader_alignment == "supportive" else -0.04
    score += clamp(direction_sign * predictive_horizon * 0.14, -0.08, 0.12)
    score += clamp(direction_sign * orderbook_trend * 0.06, -0.04, 0.05)
    score += clamp(direction_sign * micro_accel * 0.05, -0.03, 0.04)
    score += clamp(-direction_sign * funding_accel * 0.03, -0.02, 0.03)
    score += 0.05 if mtf_support else 0.0
    score += clamp((directional_break - 0.50) * 0.22, -0.05, 0.09)
    score += clamp((directional_break - opposing_break) * 0.10, -0.03, 0.04)
    score += clamp((predictive_confidence - 0.45) * 0.10, -0.03, 0.04)
    score += clamp((context_peak_fee - 0.8) * 0.03, -0.02, 0.03)
    score += flat_bonus if regime == "squeeze" and level_edge else 0.0
    score += float(shadow_bias.get("success_bonus", 0.0) or 0.0)
    if regime == "squeeze" and strategic_mode == "attack":
        score += min(0.08, float(shadow_bias.get("success_bonus", 0.0) or 0.0))
    if regime == "squeeze" and not level_edge and not range_edge:
        score -= 0.08
    if wyckoff_spring:
        score += 0.10
    # Apply learned entry quality biases: penalise wrong-side entries (longs at resistance, shorts at support)
    _eq_bias = get_entry_quality_bias().get("biases", {})
    level_alignment_now = str(resolved_signal_ctx.get("level_alignment", "mid") or "mid")
    if direction == "long" and level_alignment_now == "resistance":
        score += float(_eq_bias.get("wrong_side_long_penalty", -0.06) or -0.06)
    elif direction == "short" and level_alignment_now == "support":
        score += float(_eq_bias.get("wrong_side_short_penalty", -0.06) or -0.06)
    if llm_predictive_prob is not None:
        score += clamp((float(llm_predictive_prob) - 0.50) * 0.12, -0.04, 0.05)

    final_score = clamp(score, 0.0, 1.0)
    edge_bonus = max(0.0, final_score - 0.55) * 0.18
    component_summary = (
        f"pred={final_score:.2f} oracle={oracle_score:.2f}/{oracle_fcr:.2f} "
        f"level={int(level_edge)} spring={int(wyckoff_spring)} range={int(range_edge)} align={broader_alignment} "
        f"break={directional_break:.2f}>{opposing_break:.2f} mtf={mtf_alignment} "
        f"shadow={float(shadow_bias.get('success_bonus', 0.0) or 0.0):+.2f}"
    )
    return {
        "score": round(final_score, 4),
        "edge_bonus": round(edge_bonus, 4),
        "component_summary": component_summary,
        "shadow_success_bonus": round(float(shadow_bias.get("success_bonus", 0.0) or 0.0), 4),
    }


def record_exploration_outcome(policy: str, realized_pnl: float, reason: str, outcome: Optional[dict[str, Any]] = None):
    recent = brain.get("exploration", {}).get("recent", [])
    for item in reversed(recent):
        if item.get("policy") != policy:
            continue
        if item.get("outcome_pnl") is None:
            item["outcome_pnl"] = round(realized_pnl, 2)
            item["exit_reason"] = reason
            item["resolved_at"] = datetime.now().isoformat()
            if outcome:
                item.update(safe_serialize(outcome))
            break


def update_shadow_policy_stats(policy: str, recent_item: dict[str, Any]):
    policy_stats = (
        brain.setdefault("shadow_exploration", {})
        .setdefault("policies", {})
        .setdefault(
            policy,
            {
                "resolved": 0,
                "wins": 0,
                "outcome_bps_sum": 0.0,
                "avg_outcome_bps": 0.0,
                "fee_clear_rate": 0.0,
                "avg_peak_fee_multiple": 0.0,
                "avg_time_to_mfe_minutes": 0.0,
                "timed_mfe_count": 0,
            },
        )
    )
    policy_stats["resolved"] = int(policy_stats.get("resolved", 0)) + 1
    resolved = int(policy_stats["resolved"])
    outcome_bps = float(recent_item.get("outcome_bps", 0.0) or 0.0)
    policy_stats["outcome_bps_sum"] = float(policy_stats.get("outcome_bps_sum", 0.0) or 0.0) + outcome_bps
    policy_stats["avg_outcome_bps"] = round(policy_stats["outcome_bps_sum"] / max(resolved, 1), 4)
    if outcome_bps > 0:
        policy_stats["wins"] = int(policy_stats.get("wins", 0)) + 1
    prior = max(resolved - 1, 0)
    policy_stats["fee_clear_rate"] = round(
        _running_avg(float(policy_stats.get("fee_clear_rate", 0.0) or 0.0), prior,
                     1.0 if recent_item.get("fee_cleared") else 0.0), 4)
    policy_stats["avg_peak_fee_multiple"] = round(
        _running_avg(float(policy_stats.get("avg_peak_fee_multiple", 0.0) or 0.0), prior,
                     float(recent_item.get("max_fee_multiple", 0.0) or 0.0)), 4)
    if recent_item.get("time_to_mfe_minutes") is not None:
        timed_count = int(policy_stats.get("timed_mfe_count", 0) or 0)
        policy_stats["avg_time_to_mfe_minutes"] = round(
            _running_avg(float(policy_stats.get("avg_time_to_mfe_minutes", 0.0) or 0.0), timed_count,
                         float(recent_item.get("time_to_mfe_minutes", 0.0) or 0.0)), 4)
        timed_count += 1
        policy_stats["timed_mfe_count"] = timed_count


def update_structured_squeeze_shadow_stats(recent_item: dict[str, Any]) -> None:
    reason = str(recent_item.get("blocked_reason", "") or "")
    regime = str(recent_item.get("regime", "") or "")
    if regime != "squeeze" or "squeeze structural gate" not in reason:
        return
    stats = brain.setdefault(
        "structured_squeeze_shadow",
        {
            "resolved": 0,
            "fee_clears": 0,
            "wins": 0,
            "outcome_bps_sum": 0.0,
            "avg_outcome_bps": 0.0,
            "last": {},
        },
    )
    stats["resolved"] = int(stats.get("resolved", 0) or 0) + 1
    stats["fee_clears"] = int(stats.get("fee_clears", 0) or 0) + (1 if recent_item.get("fee_cleared") else 0)
    outcome_bps = float(recent_item.get("outcome_bps", 0.0) or 0.0)
    stats["wins"] = int(stats.get("wins", 0) or 0) + (1 if outcome_bps > 0 else 0)
    stats["outcome_bps_sum"] = float(stats.get("outcome_bps_sum", 0.0) or 0.0) + outcome_bps
    resolved = max(int(stats.get("resolved", 0) or 0), 1)
    stats["avg_outcome_bps"] = round(float(stats["outcome_bps_sum"]) / resolved, 4)
    stats["fee_clear_rate"] = round(int(stats.get("fee_clears", 0) or 0) / resolved, 4)
    stats["win_rate"] = round(int(stats.get("wins", 0) or 0) / resolved, 4)
    stats["last"] = {
        "timestamp": datetime.now().isoformat(),
        "policy": recent_item.get("policy", "unknown"),
        "direction": recent_item.get("direction", "unknown"),
        "reason": reason,
        "outcome_bps": round(outcome_bps, 3),
        "fee_cleared": bool(recent_item.get("fee_cleared", False)),
        "expected_edge": recent_item.get("expected_edge"),
        "predictive_setup_score": recent_item.get("predictive_setup_score"),
    }


def get_recent_shadow_bias(
    regime: str,
    direction: str,
    intent: str,
    *,
    limit: int = 8,
) -> dict[str, float]:
    recent = brain.get("shadow_exploration", {}).get("recent", [])[-80:]
    matched: list[dict[str, Any]] = []
    for item in reversed(recent):
        if item.get("outcome_bps") is None:
            continue
        if str(item.get("regime", "unknown") or "unknown") != str(regime or "unknown"):
            continue
        if str(item.get("direction", "long") or "long") != str(direction or "long"):
            continue
        if str(item.get("intent", "") or "") != str(intent or ""):
            continue
        matched.append(item)
        if len(matched) >= limit:
            break
    if not matched:
        return {
            "resolved": 0.0,
            "win_rate": 0.0,
            "fee_clear_rate": 0.0,
            "avg_outcome_bps": 0.0,
            "last_outcome_bps": 0.0,
            "success_bonus": 0.0,
            "room_relief_bps": 0.0,
        }

    resolved = float(len(matched))
    win_rate = sum(1 for item in matched if float(item.get("outcome_bps", 0.0) or 0.0) > 0.0) / max(len(matched), 1)
    fee_clear_rate = sum(1 for item in matched if bool(item.get("fee_cleared"))) / max(len(matched), 1)
    avg_outcome_bps = sum(float(item.get("outcome_bps", 0.0) or 0.0) for item in matched) / max(len(matched), 1)
    last_outcome_bps = float(matched[0].get("outcome_bps", 0.0) or 0.0)
    bonus = 0.0
    room_relief_bps = 0.0
    if len(matched) >= 4 and fee_clear_rate > 0.50 and (
        win_rate > 0.55
        or last_outcome_bps > 20.0
    ):
        bonus = 0.12
        room_relief_bps = min(1.50, max(avg_outcome_bps, last_outcome_bps) / 20.0)
    return {
        "resolved": resolved,
        "win_rate": round(win_rate, 4),
        "fee_clear_rate": round(fee_clear_rate, 4),
        "avg_outcome_bps": round(avg_outcome_bps, 4),
        "last_outcome_bps": round(last_outcome_bps, 4),
        "success_bonus": round(bonus, 4),
        "room_relief_bps": round(room_relief_bps, 4),
    }


def build_shadow_exploration_attempt_record(
    *,
    timestamp: datetime,
    candidate: dict[str, Any],
    regime: str,
    fingerprint: str,
    selected_score: float,
    quality: float,
    expected_edge: float,
    predictive_setup_score: float,
    predictive_setup_summary: str,
    trade_signal_snapshot: dict[str, Any],
    signal_features: dict[str, Any],
    blocked_reason: str,
    entry_price: float,
) -> dict[str, Any]:
    attempt_id = f"shadow_{candidate['policy']}_{int(timestamp.timestamp())}"
    lane_key = exploration_lane_key_from_candidate(candidate, regime, trade_signal_snapshot, trade_signal_snapshot.get("regime_bias"))
    return {
        "id": attempt_id,
        "timestamp": timestamp.isoformat(),
        "mode": "shadow",
        "policy": candidate["policy"],
        "intent": candidate["intent"],
        "direction": candidate["direction"],
        "regime": regime,
        "fingerprint": fingerprint,
        "lane_key": lane_key,
        "score": round(selected_score, 4),
        "quality": round(quality, 4),
        "expected_edge": round(float(expected_edge or 0.0), 4),
        "predictive_setup_score": round(float(predictive_setup_score or 0.0), 4),
        "predictive_setup_summary": str(predictive_setup_summary or "n/a"),
        "blocked_reason": blocked_reason,
        "entry_price": round(float(entry_price or 0.0), 2),
        "sl_bps": int(candidate["sl_bps"]),
        "tp_bps": int(candidate["tp_bps"]),
        "max_hold_minutes": int(candidate["max_hold_minutes"]),
        "momentum_delta": signal_features.get("momentum_delta", 0.0),
        "imbalance_delta": signal_features.get("imbalance_delta", 0.0),
        "momentum_persistence": signal_features.get("momentum_persistence", 0.0),
        "imbalance_persistence": signal_features.get("imbalance_persistence", 0.0),
        "outcome_bps": None,
        **trade_signal_snapshot,
    }


def build_shadow_pending_record(record: dict[str, Any], blocked_reason: str) -> dict[str, Any]:
    return {
        "id": record["id"],
        "policy": record["policy"],
        "direction": record["direction"],
        "entry_price": record["entry_price"],
        "opened_at": record["timestamp"],
        "sl_bps": record["sl_bps"],
        "tp_bps": record["tp_bps"],
        "max_hold_minutes": record["max_hold_minutes"],
        "max_favorable_bps": 0.0,
        "max_adverse_bps": 0.0,
        "time_to_mfe_minutes": None,
        "time_to_mae_minutes": None,
        "blocked_reason": blocked_reason,
    }


def is_shadow_proven_breakout_level(direction: str, signal_ctx: dict[str, Any]) -> bool:
    """
    Allow breakout probes through micro-level room blocks via two paths:
    - Path A (tuner-approved): shadow proof exists + recent + live tape agrees (OR-logic)
    - Path B (live-tape only): stricter AND-logic — regime_bias AND (mtf OR price_action)
      must both confirm + volx >= 1.40 or hard breakout price_action.
      Fixes chicken-and-egg: first breakout ever was permanently blocked because tuner
      proof could never accumulate without a first entry.
    """
    lt = brain.get("level_thresholds", {}) or {}
    tuner_ok = bool(lt.get(f"breakout_{direction}_shadow_ok", False))

    regime = str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown")
    regime_bias = str(brain.get("market_regime", {}).get("bias", "neutral") or "neutral")
    mtf = str(signal_ctx.get("mtf_alignment", "mixed") or "mixed")
    price_action = str(brain.get("price_action_summary", "neutral") or "neutral")
    volx = float(signal_ctx.get("volatility_expansion", 1.0) or 1.0)

    if regime not in {"squeeze", "trend"}:
        return False

    if tuner_ok:
        # Path A: tuner-approved — check recency, drift guard, OR-direction logic
        tuned_at = parse_iso_dt(lt.get("last_tuned"))
        if not tuned_at:
            return False
        if (datetime.now() - tuned_at).total_seconds() > LEVEL_BREAKOUT_SHADOW_PROOF_MAX_AGE_HOURS * 3600:
            return False
        # Freeze bypass while the promoted lane no longer matches live regime/bias/session.
        if get_top_lane_drift_guard_reason((brain.get("exploration_thresholds", {}) or {}).get("top_lane", {}) or {}):
            return False
        if direction == "long":
            directional_ok = regime_bias == "bullish" or mtf == "bullish" or price_action in {"higher_highs", "bullish_breakout"}
        else:
            directional_ok = regime_bias == "bearish" or mtf == "bearish" or price_action == "bearish_breakdown"
        if not directional_ok:
            return False
        return volx >= 1.10 or price_action in {"higher_highs", "bullish_breakout", "bearish_breakdown"}

    # Path B: no tuner proof — require stricter AND-logic
    # regime_bias must confirm AND (mtf OR price_action) must also confirm
    if direction == "long":
        bias_ok = regime_bias == "bullish"
        tape_ok = mtf == "bullish" or price_action in {"higher_highs", "bullish_breakout"}
    else:
        bias_ok = regime_bias == "bearish"
        tape_ok = mtf == "bearish" or price_action == "bearish_breakdown"
    if not (bias_ok and tape_ok):
        return False
    # Higher volx bar without tuner proof — must be a real expansion, not noise.
    # higher_highs + bullish bias + bullish mtf is valid breakout confluence in squeeze/trend.
    return volx >= 1.40 or price_action in {"higher_highs", "bullish_breakout", "bearish_breakdown"}


def is_open_air_breakout_allowed(direction: str, signal_ctx: dict[str, Any]) -> bool:
    """
    Fresh highs/lows have no next local level by definition. Let breakout/trend
    candidates see that as open air only when the broader tape confirms it.
    """
    regime = str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown")
    regime_bias = str(brain.get("market_regime", {}).get("bias", "neutral") or "neutral")
    mtf = str(signal_ctx.get("mtf_alignment", "mixed") or "mixed")
    price_action = str(brain.get("price_action_summary", "neutral") or "neutral")
    volx = float(signal_ctx.get("volatility_expansion", 1.0) or 1.0)
    volatility_state = str(signal_ctx.get("volatility_state", "normal") or "normal")
    if regime not in {"squeeze", "trend"}:
        return False
    if direction == "long":
        if bool(signal_ctx.get("resistance_valid", False)):
            return False
        if regime == "squeeze":
            # In squeeze "higher_highs" is just normal oscillation near the range top.
            # Require an explicit breakout signal or strong vol expansion for open-air longs.
            directional_ok = price_action == "bullish_breakout" or (regime_bias == "bullish" and mtf == "bullish")
            tape_ok = volx >= 1.35 or volatility_state == "expanded" or price_action == "bullish_breakout"
        else:
            directional_ok = regime_bias == "bullish" or mtf == "bullish" or price_action in {"higher_highs", "bullish_breakout"}
            tape_ok = volx >= 1.10 or volatility_state == "expanded" or price_action in {"higher_highs", "bullish_breakout"}
    else:
        if bool(signal_ctx.get("support_valid", False)):
            return False
        if regime == "squeeze":
            directional_ok = price_action == "bearish_breakdown" or (regime_bias == "bearish" and mtf == "bearish")
            tape_ok = volx >= 1.35 or volatility_state == "expanded" or price_action == "bearish_breakdown"
        else:
            directional_ok = regime_bias == "bearish" or mtf == "bearish" or price_action == "bearish_breakdown"
            tape_ok = volx >= 1.10 or volatility_state == "expanded" or price_action == "bearish_breakdown"
    return directional_ok and tape_ok


def get_candidate_level_block_reason(
    direction: str,
    intent: str,
    policy: str,
    signal_ctx: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    ctx = signal_ctx or get_signal_context()
    if not bool(ctx.get("level_map_ready", False)):
        return "level gate | level map not ready"
    if policy == "orderbook_imbalance_follow" and not bool(ctx.get("orderbook_live", False)):
        return f"feature health gate | policy={policy} orderbook stale"

    room_to_resistance = float(ctx.get("room_to_resistance_bps", 0.0) or 0.0)
    room_to_support = float(ctx.get("room_to_support_bps", 0.0) or 0.0)
    at_support = bool(ctx.get("at_support", False) or ctx.get("sweep_reclaim_long", False) or ctx.get("wyckoff_spring_long", False))
    at_resistance = bool(ctx.get("at_resistance", False) or ctx.get("sweep_reclaim_short", False) or ctx.get("wyckoff_spring_short", False))
    support_valid = bool(ctx.get("support_valid", False))
    resistance_valid = bool(ctx.get("resistance_valid", False))
    min_room_bps = get_level_min_room_bps()
    breakout_min_room_bps = get_level_breakout_min_room_bps()
    broader_structure = brain.get("broader_structure") or {}
    structure_confidence = float(broader_structure.get("confidence", 0.0) or 0.0)
    structure_alignment = get_broader_structure_alignment(direction, intent, broader_structure)
    strategic_mode = str((brain.get("last_strategic_context", {}) or {}).get("mode", "observe") or "observe")
    regime = str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown")
    flat_minutes = get_flat_duration_minutes()
    shadow_bias = get_recent_shadow_bias(regime, direction, intent)
    structure_room_relief = 1.0
    if structure_alignment == "aligned" and structure_confidence >= 0.62:
        structure_room_relief = 0.55
    elif structure_alignment == "supportive" and structure_confidence >= 0.70:
        structure_room_relief = 0.75
    room_floor_bps = 6.0
    if regime == "squeeze" and strategic_mode == "attack":
        room_floor_bps = 1.8 if direction == "long" else 2.2
        if flat_minutes > 35.0:
            relief_progress = min((flat_minutes - 35.0) / 25.0, 1.0)
            room_floor_bps -= 0.8 * relief_progress
        room_floor_bps = max(1.0, room_floor_bps)
    if float(shadow_bias.get("success_bonus", 0.0) or 0.0) > 0.0:
        room_floor_bps = max(1.0, room_floor_bps - float(shadow_bias.get("room_relief_bps", 0.0) or 0.0))
    effective_min_room_bps = max(room_floor_bps, min_room_bps * structure_room_relief)

    # Keep buy-low/sell-high discipline: mean reversion needs a nearby edge and room to the opposite edge.
    if intent in {"mean_revert", "scalp"}:
        if direction == "long":
            if not at_support:
                return "level gate | long needs support/reclaim"
            if room_to_resistance < effective_min_room_bps:
                return f"level gate | long room={room_to_resistance:.1f}bps < min={effective_min_room_bps:.1f}"
            if structure_room_relief < 1.0 and room_to_resistance < min_room_bps:
                log(
                    f"LEVEL STRUCTURE RELIEF | long {intent} room={room_to_resistance:.1f}bps "
                    f"base={min_room_bps:.1f} eff={effective_min_room_bps:.1f} "
                    f"structure={broader_structure.get('action', 'wait')}/{structure_confidence:.2f}"
                )
        elif direction == "short":
            if not at_resistance:
                return "level gate | short needs resistance/reclaim"
            if room_to_support < effective_min_room_bps:
                return f"level gate | short room={room_to_support:.1f}bps < min={effective_min_room_bps:.1f}"
            if structure_room_relief < 1.0 and room_to_support < min_room_bps:
                log(
                    f"LEVEL STRUCTURE RELIEF | short {intent} room={room_to_support:.1f}bps "
                    f"base={min_room_bps:.1f} eff={effective_min_room_bps:.1f} "
                    f"structure={broader_structure.get('action', 'wait')}/{structure_confidence:.2f}"
                )

    if intent in {"trend_follow", "breakout"}:
        breakout_shadow_ok = is_shadow_proven_breakout_level(direction, ctx) if intent == "breakout" else False
        open_air_ok = is_open_air_breakout_allowed(direction, ctx)
        if direction == "long":
            if at_resistance and not breakout_shadow_ok and not open_air_ok:
                return "level gate | long trend into resistance"
            if (not resistance_valid or room_to_resistance < breakout_min_room_bps) and not breakout_shadow_ok and not open_air_ok:
                return f"level gate | long breakout room={room_to_resistance:.1f}bps < min={breakout_min_room_bps:.1f}"
            if open_air_ok and not resistance_valid:
                log(
                    f"LEVEL OPEN-AIR BYPASS | long {intent} no above resistance | "
                    f"volx={float(ctx.get('volatility_expansion', 1.0) or 1.0):.2f} mtf={ctx.get('mtf_alignment', 'mixed')}"
                )
            if breakout_shadow_ok and (not resistance_valid or room_to_resistance < breakout_min_room_bps):
                log(
                    f"LEVEL SHADOW BYPASS | long breakout room={room_to_resistance:.1f}bps "
                    f"min={breakout_min_room_bps:.1f} support_valid={support_valid} resistance_valid={resistance_valid}"
                )
        elif direction == "short":
            if at_support and not breakout_shadow_ok and not open_air_ok:
                return "level gate | short trend into support"
            if (not support_valid or room_to_support < breakout_min_room_bps) and not breakout_shadow_ok and not open_air_ok:
                return f"level gate | short breakout room={room_to_support:.1f}bps < min={breakout_min_room_bps:.1f}"
            if open_air_ok and not support_valid:
                log(
                    f"LEVEL OPEN-AIR BYPASS | short {intent} no below support | "
                    f"volx={float(ctx.get('volatility_expansion', 1.0) or 1.0):.2f} mtf={ctx.get('mtf_alignment', 'mixed')}"
                )
            if breakout_shadow_ok and (not support_valid or room_to_support < breakout_min_room_bps):
                log(
                    f"LEVEL SHADOW BYPASS | short breakout room={room_to_support:.1f}bps "
                    f"min={breakout_min_room_bps:.1f} support_valid={support_valid} resistance_valid={resistance_valid}"
                )
    return None


def update_edge_calibration_snapshot(
    policy: str,
    policy_stats: dict[str, Any],
    context_stats: dict[str, Any],
    shadow_context_stats: dict[str, Any],
    shadow_direction_stats: dict[str, Any],
) -> dict[str, Any]:
    resolved = int(context_stats.get("resolved", 0) or 0)
    shadow_resolved = int(shadow_context_stats.get("resolved", 0) or 0)
    shadow_dir_resolved = int(shadow_direction_stats.get("resolved", 0) or 0)
    snapshot = {
        "updated_at": datetime.now().isoformat(),
        "trades": int(policy_stats.get("trades", 0) or 0),
        "wins": int(policy_stats.get("wins", 0) or 0),
        "avg_pnl": round(float(policy_stats.get("avg_pnl", 0.0) or 0.0), 2),
        "fee_clear_rate": round(float(policy_stats.get("fee_clear_rate", 0.0) or 0.0), 4),
        "avg_peak_fee_multiple": round(float(policy_stats.get("avg_peak_fee_multiple", 0.0) or 0.0), 4),
        "context_resolved": resolved,
        "context_fee_clear_rate": round(float(context_stats.get("fee_clears", 0) or 0.0) / max(resolved, 1), 4) if resolved else 0.0,
        "context_avg_pnl": round(float(context_stats.get("net_pnl_sum", 0.0) or 0.0) / max(resolved, 1), 2) if resolved else 0.0,
        "shadow_resolved": shadow_resolved,
        "shadow_fee_clear_rate": round(float(shadow_context_stats.get("fee_clears", 0) or 0.0) / max(shadow_resolved, 1), 4) if shadow_resolved else 0.0,
        "shadow_direction_resolved": shadow_dir_resolved,
        "shadow_direction_fee_clear_rate": (
            round(float(shadow_direction_stats.get("fee_clears", 0) or 0.0) / max(shadow_dir_resolved, 1), 4)
            if shadow_dir_resolved else 0.0
        ),
    }
    brain.setdefault("edge_calibration", {})[policy] = snapshot
    return snapshot


def is_live_calibration_probe_allowed(candidate: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    """
    Let the bot relearn small mean-reversion probes when current structure is
    strong enough. This does not bypass directional proof or risk gates.
    """
    if brain.get("risk_mode") == "protection":
        return False
    if str(candidate.get("intent", "") or "") != "mean_revert":
        return False
    if str(candidate.get("policy", "") or "") not in {"mean_revert_reclaim", "mean_revert_micro"}:
        return False
    avg_pnl = float(snapshot.get("avg_pnl", 0.0) or 0.0)
    context_avg_pnl = float(snapshot.get("context_avg_pnl", 0.0) or 0.0)
    if avg_pnl < -250.0 or context_avg_pnl < -250.0:
        return False
    gate_state = brain.get("last_entry_gate_state", {}) or {}
    quality = float(gate_state.get("quality", 0.0) or 0.0)
    direction = str(candidate.get("direction", "long") or "long")
    structure = brain.get("broader_structure") or {}
    structure_confidence = float(structure.get("confidence", 0.0) or 0.0)
    structure_aligned = get_broader_structure_alignment(direction, str(candidate.get("intent", "") or ""), structure) == "aligned"
    min_quality = 0.50 if structure_aligned and structure_confidence >= 0.62 else 0.55
    min_flat_minutes = 18.0 if structure_aligned and structure_confidence >= 0.62 else 30.0
    if quality < min_quality or get_flat_duration_minutes() < min_flat_minutes:
        return False
    regime = str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown")
    if regime not in {"chop", "squeeze"}:
        return False
    oracle = get_oracle_regime_insight(regime)
    oracle_score = float(oracle.get("score", 0.0) or 0.0)
    oracle_edge = float(oracle.get("edge", 0.0) or 0.0)
    if oracle_score < 0.55 and oracle_edge < 0.10:
        return False
    ctx = brain.get("market_context", {}) or {}
    if direction == "long":
        return bool(ctx.get("at_support", False) or ctx.get("sweep_reclaim_long", False))
    return bool(ctx.get("at_resistance", False) or ctx.get("sweep_reclaim_short", False))


def get_edge_calibration_block_reason(
    candidate: dict[str, Any],
    policy_stats: dict[str, Any],
    context_stats: dict[str, Any],
    shadow_context_stats: dict[str, Any],
    shadow_direction_stats: dict[str, Any],
) -> Optional[str]:
    policy = str(candidate.get("policy", "") or "")
    intent = str(candidate.get("intent", "") or "")
    snapshot = update_edge_calibration_snapshot(
        policy,
        policy_stats,
        context_stats,
        shadow_context_stats,
        shadow_direction_stats,
    )
    trades = int(snapshot.get("trades", 0) or 0)
    fee_clear_rate = float(snapshot.get("fee_clear_rate", 0.0) or 0.0)
    avg_peak = float(snapshot.get("avg_peak_fee_multiple", 0.0) or 0.0)
    avg_pnl = float(snapshot.get("avg_pnl", 0.0) or 0.0)
    context_resolved = int(snapshot.get("context_resolved", 0) or 0)
    context_fcr = float(snapshot.get("context_fee_clear_rate", 0.0) or 0.0)
    context_avg_pnl = float(snapshot.get("context_avg_pnl", 0.0) or 0.0)
    shadow_resolved = int(snapshot.get("shadow_resolved", 0) or 0)
    shadow_fcr = float(snapshot.get("shadow_fee_clear_rate", 0.0) or 0.0)
    shadow_dir_resolved = int(snapshot.get("shadow_direction_resolved", 0) or 0)
    shadow_dir_fcr = float(snapshot.get("shadow_direction_fee_clear_rate", 0.0) or 0.0)
    shadow_repair = shadow_resolved >= EDGE_CALIBRATION_MIN_CONTEXT_RESOLVED and shadow_fcr >= EDGE_CALIBRATION_MIN_FEE_CLEAR * 1.5
    calibration_probe_ok = is_live_calibration_probe_allowed(candidate, snapshot)

    if (
        trades >= EDGE_CALIBRATION_MIN_TRADES
        and avg_pnl < 0.0
        and fee_clear_rate < EDGE_CALIBRATION_MIN_FEE_CLEAR
        and avg_peak < EDGE_CALIBRATION_MIN_PEAK_FEE
        and not shadow_repair
        and not calibration_probe_ok
    ):
        return (
            f"edge calibration gate | policy={policy} avg_pnl={avg_pnl:+.0f} "
            f"fcr={fee_clear_rate:.2f} peak={avg_peak:.2f}"
        )
    if (
        context_resolved >= EDGE_CALIBRATION_MIN_CONTEXT_RESOLVED
        and context_avg_pnl < 0.0
        and context_fcr < EDGE_CALIBRATION_MIN_FEE_CLEAR
        and not shadow_repair
        and not calibration_probe_ok
    ):
        return (
            f"context calibration gate | policy={policy} ctx_pnl={context_avg_pnl:+.0f} "
            f"ctx_fcr={context_fcr:.2f}"
        )
    if calibration_probe_ok and (avg_pnl < 0.0 or context_avg_pnl < 0.0):
        structure = brain.get("broader_structure") or {}
        log(
            f"EDGE CALIBRATION PROBE BYPASS | policy={policy} avg_pnl={avg_pnl:+.0f} "
            f"ctx_pnl={context_avg_pnl:+.0f} flat={get_flat_duration_minutes():.1f}m "
            f"structure={structure.get('action', 'wait')}/{float(structure.get('confidence', 0.0) or 0.0):.2f}"
        )
    if (
        intent in {"trend_follow", "breakout"}
        and shadow_dir_resolved < DIRECTIONAL_PROOF_MIN_RESOLVED
        and trades < DIRECTIONAL_PROOF_MIN_RESOLVED
    ):
        return (
            f"directional proof gate | policy={policy} "
            f"live={trades} shadow_dir={shadow_dir_resolved}"
        )
    if (
        intent in {"trend_follow", "breakout"}
        and shadow_dir_resolved >= DIRECTIONAL_PROOF_MIN_RESOLVED
        and shadow_dir_fcr < EDGE_CALIBRATION_MIN_FEE_CLEAR
    ):
        return (
            f"directional proof gate | policy={policy} "
            f"shadow_dir_fcr={shadow_dir_fcr:.2f}"
        )

    return None


def get_level_entry_block_reason(signal: EntrySignal) -> Optional[str]:
    if signal.action != "open":
        return None
    return get_candidate_level_block_reason(
        str(signal.direction or "long"),
        str(signal.intent or ""),
        str(signal.policy or ""),
        get_signal_context(),
    )


def build_aggressive_learning_fallback_signal(adaptive: dict[str, Any]) -> Optional[EntrySignal]:
    if str(brain.get("risk_mode", "normal") or "normal") == "protection":
        return None
    gate_state = brain.get("last_entry_gate_state", {}) or {}
    ok, reason = should_aggressive_learning_bypass_block(
        str(brain.get("last_flat_entry_block_reason", "") or "squeeze structural gate"),
        gate_state,
    )
    if not ok:
        return None

    structure = brain.get("broader_structure") or {}
    action = str(structure.get("action", "wait") or "wait")
    direction = "short" if "short" in action else "long" if "long" in action else ""
    if not direction:
        mtf = str((gate_state.get("signal_ctx", {}) or {}).get("mtf_alignment", "mixed") or "mixed")
        bias = str(brain.get("market_regime", {}).get("bias", "neutral") or "neutral")
        if mtf == "bearish" or bias == "bearish":
            direction = "short"
        elif mtf == "bullish" or bias == "bullish":
            direction = "long"
        else:
            direction = "long" if random.random() < 0.5 else "short"

    intent = "breakout" if "breakout" in action else "mean_revert"
    policy = "breakout_probe" if intent == "breakout" else "mean_revert_reclaim"
    signal_ctx = get_signal_context()
    level_edge = bool(
        (direction == "long" and (signal_ctx.get("at_support", False) or signal_ctx.get("sweep_reclaim_long", False)))
        or (direction == "short" and (signal_ctx.get("at_resistance", False) or signal_ctx.get("sweep_reclaim_short", False)))
    )
    alignment = get_broader_structure_alignment(direction, intent, structure)
    pred = 0.52 if alignment in {"aligned", "supportive"} else 0.46
    effective_edge, _, lift_reason = compute_aggressive_learning_edge_lift(
        base_edge=0.10,
        predictive_score=pred,
        alignment=alignment,
        level_edge=level_edge,
        same_proof=summarize_shadow_direction_proof(
            str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown"),
            direction,
        ),
        structure_confidence=float(structure.get("confidence", 0.0) or 0.0),
    )
    confidence = clamp(max(0.52, pred + 0.08), 0.0, 0.78)
    return EntrySignal(
        action="open",
        direction=direction,
        intent=intent,
        mode="exploit",
        policy=policy,
        confidence=confidence,
        quantity=1,
        sl_bps=48 if intent == "mean_revert" else 60,
        tp_bps=85 if intent == "mean_revert" else 110,
        trail_bps=28,
        leverage=min(MAX_LEVERAGE, 8),
        max_hold_minutes=36,
        risk_per_trade=float(adaptive.get("risk_per_trade", RISK_PER_TRADE) or RISK_PER_TRADE),
        expected_edge=effective_edge,
        predictive_setup_score=pred,
        predictive_setup_summary=f"aggressive_learning_fallback | {reason} | {lift_reason}",
        reason=(
            f"aggressive learning fallback after extended flat period | "
            f"structure={action}/{float(structure.get('confidence', 0.0) or 0.0):.2f} "
            f"edge={effective_edge:.2f}"
        )[:240],
    )


def build_dry_run_entry_report(usable: float, gate_state: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    state = gate_state or get_entry_gate_state(usable)
    signal_ctx = state.get("signal_ctx", {}) or get_signal_context()
    regime = str(state.get("regime", brain.get("market_regime", {}).get("regime", "unknown")))
    quality = float(state.get("quality", 0.0) or 0.0)
    common_block = get_common_entry_block_reason(usable, state)
    report: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "regime": regime,
        "quality": round(quality, 4),
        "usable": round(float(usable or 0.0), 2),
        "broader_structure": brain.get("broader_structure") or compute_broader_structure_context(signal_ctx),
        "feature_health": signal_ctx.get("feature_health_summary", "n/a"),
        "feature_health_reason": signal_ctx.get("feature_health_reason", "n/a"),
        "level_summary": signal_ctx.get("level_summary", "n/a"),
        "common_block": common_block,
        "exploration_thresholds": get_exploration_thresholds(),
        "hypothetical": {},
    }
    for direction in ("long", "short"):
        intent = "mean_revert" if regime in {"chop", "squeeze", "unknown"} else "trend_follow"
        policy = "mean_revert_reclaim" if intent == "mean_revert" else "momentum_follow"
        level_block = get_candidate_level_block_reason(direction, intent, policy, signal_ctx)
        report["hypothetical"][direction] = {
            "intent": intent,
            "policy": policy,
            "level_block": level_block,
            "would_pass_static_gates": common_block is None and level_block is None,
        }
    brain["dry_run_entry_report"] = safe_serialize(report)
    return report


def maybe_log_gate_snapshot(usable: float, gate_state: dict[str, Any], blocked_reason: Optional[str] = None):
    now_ts = time.time()
    if now_ts - float(brain.get("last_gate_snapshot_log_at", 0.0) or 0.0) < GATE_SNAPSHOT_LOG_INTERVAL_SECONDS:
        return
    report = build_dry_run_entry_report(usable, gate_state)
    hypotheticals = report.get("hypothetical", {}) or {}
    long_block = (hypotheticals.get("long", {}) or {}).get("level_block")
    short_block = (hypotheticals.get("short", {}) or {}).get("level_block")
    log(
        "GATE SNAPSHOT | "
        f"regime={report['regime']} q={report['quality']:.2f} usable={report['usable']:.0f} "
        f"blocker={blocked_reason or report.get('common_block') or 'n/a'} | "
        f"structure={(report.get('broader_structure') or {}).get('action', 'wait')}/"
        f"{(report.get('broader_structure') or {}).get('confidence', 0.0):.2f} | "
        f"health={report.get('feature_health')} reason={report.get('feature_health_reason')} | "
        f"levels={report.get('level_summary')} | "
        f"dry_long={long_block or 'pass'} dry_short={short_block or 'pass'}"
    )
    append_review_report(
        "gate_snapshot",
        {
            **report,
            "blocked_reason": blocked_reason,
            "dry_long_block": long_block,
            "dry_short_block": short_block,
        },
    )
    brain["last_gate_snapshot_log_at"] = now_ts


def estimate_candidate_edge(
    candidate: dict[str, Any],
    quality: float,
    regime: str,
    market: dict[str, Any],
    context_stats: dict[str, Any],
    signal_ctx: dict[str, Any],
    oracle_insight: Optional[dict[str, Any]] = None,
) -> float:
    spread = float(market.get("spread_pct", 0.0) or 0.0)
    reward_ratio = candidate["tp_bps"] / max(candidate["sl_bps"], 1)
    resolved = int(context_stats.get("resolved", 0))
    avg_net_pnl = float(context_stats.get("net_pnl_sum", 0.0) or 0.0) / max(resolved, 1)
    context_edge = max(-0.30, min(0.30, avg_net_pnl / 220.0)) if resolved else 0.0
    fee_clear_rate = float(context_stats.get("fee_clears", 0)) / max(resolved, 1) if resolved else 0.0
    avg_peak_fee_multiple = float(context_stats.get("peak_fee_multiple_sum", 0.0) or 0.0) / max(resolved, 1) if resolved else 0.0
    avg_time_to_mfe = float(context_stats.get("time_to_mfe_sum", 0.0) or 0.0) / max(int(context_stats.get("timed_mfe_count", 0)), 1) if context_stats.get("timed_mfe_count", 0) else 0.0
    fee_drag = 0.18 if candidate["tp_bps"] < 85 else 0.12 if candidate["tp_bps"] < 95 else 0.07
    spread_drag = min(spread * 10.0, 0.10)
    hold_drag = 0.025 if candidate["max_hold_minutes"] > 32 else 0.0
    regime_bonus = 0.05 if regime == "chop" and candidate["intent"] == "mean_revert" else 0.0
    fee_clear_bonus = fee_clear_rate * 0.18 + clamp(avg_peak_fee_multiple / 2.0, -0.12, 0.16)
    timing_bonus = 0.0
    if avg_time_to_mfe:
        timing_bonus = clamp((candidate["max_hold_minutes"] - avg_time_to_mfe) / max(candidate["max_hold_minutes"], 1.0), -0.08, 0.08)
    session_bias = str(signal_ctx.get("session_bias", "neutral"))
    funding_bias = str(signal_ctx.get("funding_bias", "neutral"))
    funding_momentum = str(signal_ctx.get("funding_momentum", "stable"))
    direction = str(candidate.get("direction", "long"))
    directional_bonus = 0.0
    replay_bonus = 0.0
    resolved_oracle = oracle_insight or {}
    if regime in {"trend", "squeeze"}:
        if session_bias in {"trend", "follow_through"} and candidate["intent"] in {"trend_follow", "breakout"}:
            directional_bonus += 0.04
        if funding_bias == "bullish" and direction == "long":
            directional_bonus += 0.03
        elif funding_bias == "bearish" and direction == "short":
            directional_bonus += 0.03
        if funding_momentum == "rising" and direction == "short":
            directional_bonus += 0.02
        elif funding_momentum == "falling" and direction == "long":
            directional_bonus += 0.02
        if candidate["intent"] in {"trend_follow", "breakout"}:
            replay_bonus += min(
                0.10,
                float(resolved_oracle.get("fee_clear_before_half_rate", 0.0) or 0.0) * 0.10
                + clamp(float(resolved_oracle.get("avg_peak_bps", 0.0) or 0.0) / 80.0, -0.04, 0.08)
                - clamp(float(resolved_oracle.get("avg_time_to_fee_clear", 0.0) or 0.0) / max(ORACLE_REPLAY_HOLD_STEPS, 1), 0.0, 1.0) * 0.04
                - float(resolved_oracle.get("degrade_after_peak_rate", 0.0) or 0.0) * 0.05
            )
    elif regime == "chop" and candidate["intent"] == "mean_revert":
        if session_bias == "chop":
            directional_bonus += 0.03
        if funding_momentum == "stable":
            directional_bonus += 0.01

    edge = (
        candidate["fit"] * 0.42
        + quality * 0.28
        + max(0.0, min(0.20, (reward_ratio - 1.3) * 0.20))
        + candidate["confidence"] * 0.08
        + context_edge
        + regime_bonus
        + fee_clear_bonus
        + timing_bonus
        + directional_bonus
        + replay_bonus
        - fee_drag
        - spread_drag
        - hold_drag
    )
    return round(edge, 4)


def rank_exploration_candidates(
    *,
    regime: str,
    quality: float,
    market: dict[str, Any],
    signal_ctx: dict[str, Any],
    price_action: str,
    small_account: bool,
    elite_chop: bool,
    oracle_insight: dict[str, Any],
    last_policy: Optional[str],
    chop_alignment: dict[str, Any],
    shadow_mode: bool = False,
) -> tuple[list[tuple[float, dict[str, Any]]], dict[str, int]]:
    candidates = build_exploration_candidates(regime, quality)
    allowed_intents = get_allowed_open_intents(regime)
    candidates = [candidate for candidate in candidates if candidate.get("intent") in allowed_intents]
    policies = brain.get("exploration", {}).get("policies", {})
    context_fingerprint = get_exploration_context_fingerprint(regime)
    context_policy_stats = get_context_policy_stats(context_fingerprint)
    shadow_context_stats = get_shadow_context_policy_stats(context_fingerprint)

    scored_candidates: list[tuple[float, dict[str, Any]]] = []
    rejection_reasons: dict[str, int] = {}

    for candidate in candidates:
        stats = policies.get(candidate["policy"], {})
        context_stats = context_policy_stats.get(candidate["policy"], {})
        evaluated, rejection_reason = evaluate_exploration_candidate(
            candidate,
            regime=regime,
            quality=quality,
            market=market,
            signal_ctx=signal_ctx,
            price_action=price_action,
            small_account=small_account,
            elite_chop=elite_chop,
            oracle_insight=oracle_insight,
            last_policy=last_policy,
            policy_stats=stats,
            context_stats=context_stats,
            shadow_context_stats=shadow_context_stats.get(candidate["policy"], {}),
            shadow_direction_stats=get_shadow_policy_direction_stats(
                context_fingerprint,
                str(candidate.get("policy", "")),
                str(candidate.get("direction", "long")),
            ),
            chop_alignment=chop_alignment,
            shadow_mode=shadow_mode,
        )
        if rejection_reason:
            rejection_reasons[rejection_reason] = rejection_reasons.get(rejection_reason, 0) + 1
            continue
        if evaluated:
            scored_candidates.append(evaluated)

    scored_candidates.sort(key=lambda item: item[0], reverse=True)
    return scored_candidates, rejection_reasons


def build_exploration_candidates(regime: str, quality: float) -> list[dict[str, Any]]:
    market = brain.get("market_context", {})
    momentum = float(brain.get("momentum", 0.0))
    imbalance = float(market.get("imbalance", 0.0))
    spread = float(market.get("spread_pct", 0.0))
    price_action = brain.get("price_action_summary", "neutral")
    regime_bias = str(brain.get("market_regime", {}).get("bias", "neutral"))
    broader_structure = brain.get("broader_structure") or {}
    broader_action = str(broader_structure.get("action", "wait") or "wait")
    broader_direction = str(broader_structure.get("direction", "neutral") or "neutral")

    # Buy low / sell high: anchor to range or live level edge before momentum.
    _rpos = float(market.get("range_position", 0.5) or 0.5)
    _range_established = bool(market.get("range_established", False))
    _at_support = bool(market.get("at_support", False))
    _at_resistance = bool(market.get("at_resistance", False))
    _room_up_bps = float(market.get("room_to_resistance_bps", 0.0) or 0.0)
    _room_down_bps = float(market.get("room_to_support_bps", 0.0) or 0.0)
    _replay_mtf_alignment = float(get_oracle_regime_insight(regime).get("avg_mtf_alignment_score", 0.0) or 0.0)
    if _range_established:
        _mean_revert_dir = "long" if _rpos < 0.50 else "short"
    elif broader_action in {"mean_revert_long", "mean_revert_short"}:
        _mean_revert_dir = "long" if broader_action.endswith("long") else "short"
    elif _at_support and _at_resistance:
        _mean_revert_dir = "long" if _room_up_bps >= _room_down_bps else "short"
    elif _at_support:
        _mean_revert_dir = "long"
    elif _at_resistance:
        _mean_revert_dir = "short"
    else:
        _mean_revert_dir = "long" if momentum > 0 else "short" if momentum < 0 else "long"

    def direction_from_signal(primary: float, fallback: str = "long") -> str:
        if primary > 0:
            return "long"
        if primary < 0:
            return "short"
        return fallback

    def directional_breakout_side() -> str:
        if broader_action in {"breakout_long", "trend_long"} or broader_direction == "long":
            return "long"
        if broader_action in {"breakout_short", "trend_short"} or broader_direction == "short":
            return "short"
        if regime_bias == "bullish":
            return "long"
        if regime_bias == "bearish":
            return "short"
        return direction_from_signal(momentum, "long")

    candidates = [
        {
            "policy": "mean_revert_micro",
            "intent": "mean_revert",
            "direction": _mean_revert_dir,
            "confidence": 0.49,
            "sl_bps": 52,
            "tp_bps": 88,
            "trail_bps": 32,
            "leverage": 2,
            "max_hold_minutes": 34 if regime == "squeeze" else 24,
            "fit": 0.58 if regime == "chop" else 0.34 if regime == "squeeze" and regime_bias == "neutral" else 0.18,
            "reason": "dynamic exploration: micro mean reversion probe",
        },
        {
            "policy": "mean_revert_reclaim",
            "intent": "mean_revert",
            "direction": _mean_revert_dir,
            "confidence": 0.50,
            "sl_bps": 58,
            "tp_bps": 96,
            "trail_bps": 26,
            "leverage": 2,
            "max_hold_minutes": 36 if regime == "squeeze" else 24,
            "fit": 0.60 if regime == "chop" and "range" in price_action else 0.30 if regime == "squeeze" and regime_bias == "neutral" else 0.16,
            "reason": "dynamic exploration: reclaim the short-term range midpoint",
        },
        {
            "policy": "mean_revert_imbalance_fade",
            "intent": "mean_revert",
            "direction": "short" if imbalance > 0.08 else "long" if imbalance < -0.08 else _mean_revert_dir,
            "confidence": 0.48,
            "sl_bps": 54,
            "tp_bps": 90,
            "trail_bps": 24,
            "leverage": 2,
            "max_hold_minutes": 32 if regime == "squeeze" else 22,
            "fit": 0.63 if regime == "chop" and abs(imbalance) > 0.08 else 0.28 if regime == "squeeze" and regime_bias == "neutral" else 0.15,
            "reason": "dynamic exploration: fade one-sided orderbook pressure in chop",
        },
        {
            "policy": "breakout_probe",
            "intent": "breakout",
            "direction": directional_breakout_side(),
            "confidence": 0.52,
            "sl_bps": 55,
            "tp_bps": 110,
            "trail_bps": 40,
            "leverage": 3,
            "max_hold_minutes": 60 if regime in {"squeeze", "trend"} else 30,
            "fit": 0.68 if regime == "squeeze" and regime_bias in {"bullish", "bearish"} else 0.62 if regime in {"trend", "squeeze"} or "break" in price_action else 0.24,
            "reason": "dynamic exploration: breakout probe near expansion",
        },
        {
            "policy": "momentum_follow",
            "intent": "trend_follow",
            "direction": directional_breakout_side(),
            "confidence": 0.50,
            "sl_bps": 60,
            "tp_bps": 105,
            "trail_bps": 45,
            "leverage": 3,
            "max_hold_minutes": 75 if regime in {"squeeze", "trend"} else 36,
            "fit": 0.66 if regime == "squeeze" and regime_bias in {"bullish", "bearish"} else 0.64 if regime == "trend" else 0.26,
            "reason": "dynamic exploration: small momentum continuation test",
        },
        {
            "policy": "orderbook_imbalance_follow",
            "intent": "scalp",
            "direction": direction_from_signal(imbalance, direction_from_signal(momentum, "long")),
            "confidence": 0.48,
            "sl_bps": 50,
            "tp_bps": 80,
            "trail_bps": 28,
            "leverage": 2,
            "max_hold_minutes": 12,
            "fit": 0.55 if abs(imbalance) > 0.14 and spread < 0.04 else 0.18,
            "reason": "dynamic exploration: orderbook imbalance scalp",
        },
        {
            "policy": "quick_scalp",
            "intent": "scalp",
            "direction": direction_from_signal(momentum + imbalance * 0.5, "long"),
            "confidence": 0.46,
            "sl_bps": 48,
            "tp_bps": 72,
            "trail_bps": 20,
            "leverage": 2,
            "max_hold_minutes": 10,
            "fit": 0.46 if quality >= 0.45 and spread < 0.035 else 0.12,
            "reason": "dynamic exploration: quick scalp parameter probe",
        },
    ]
    mean_revert_policies = {"mean_revert_micro", "mean_revert_reclaim", "mean_revert_imbalance_fade"}
    for c in candidates:
        if (
            regime == "squeeze"
            and c.get("intent") == "trend_follow"
            and (not _range_established or _replay_mtf_alignment < 0.50)
        ):
            c.update(
                {
                    "policy": "mean_revert_reclaim",
                    "intent": "mean_revert",
                    "direction": _mean_revert_dir,
                    "leverage": min(int(c.get("leverage", 3) or 3), 2),
                    "max_hold_minutes": min(int(c.get("max_hold_minutes", 36) or 36), 36),
                }
            )
            c["reason"] += (
                f" | squeeze trend_follow downgraded: range_est={_range_established} "
                f"replay_mtf={_replay_mtf_alignment:+.2f}"
            )
        if c.get("policy") in mean_revert_policies:
            c["tp_bps"] = get_range_based_tp_bps(c["direction"], c["tp_bps"])
            if regime == "squeeze":
                range_edge = (_rpos <= get_range_long_max() and c["direction"] == "long") or (
                    _rpos >= get_range_short_min() and c["direction"] == "short"
                )
                if regime_bias in {"bullish", "bearish"} and range_edge:
                    c["fit"] = max(float(c.get("fit", 0.0) or 0.0), 0.40)
                    c["max_hold_minutes"] = max(int(c.get("max_hold_minutes", 0) or 0), 30)
                    c["leverage"] = max(int(c.get("leverage", 2) or 2), 3)
                    c["reason"] += " | squeeze edge mean-reversion lane"
                elif regime_bias == "neutral" and not range_edge:
                    c["fit"] = 0.0  # unbiased squeeze needs a real range edge
    return candidates


def evaluate_exploration_candidate(
    candidate: dict[str, Any],
    *,
    regime: str,
    quality: float,
    market: dict[str, Any],
    signal_ctx: dict[str, Any],
    price_action: str,
    small_account: bool,
    elite_chop: bool,
    oracle_insight: dict[str, Any],
    last_policy: Optional[str],
    policy_stats: dict[str, Any],
    context_stats: dict[str, Any],
    shadow_context_stats: dict[str, Any],
    shadow_direction_stats: dict[str, Any],
    chop_alignment: dict[str, Any],
    shadow_mode: bool = False,
) -> tuple[Optional[tuple[float, dict[str, Any]]], Optional[str]]:
    if not shadow_mode:
        level_block = get_candidate_level_block_reason(
            str(candidate.get("direction", "long") or "long"),
            str(candidate.get("intent", "") or ""),
            str(candidate.get("policy", "") or ""),
            signal_ctx,
        )
        if level_block:
            bypass_level_block, bypass_level_reason = should_aggressive_learning_bypass_block(level_block)
            if not bypass_level_block:
                return None, level_block
            log(f"⚡ LEVEL BYPASS: {level_block} | {bypass_level_reason}")

        calibration_block = get_edge_calibration_block_reason(
            candidate,
            policy_stats,
            context_stats,
            shadow_context_stats,
            shadow_direction_stats,
        )
        if calibration_block:
            return None, calibration_block

    trades = int(policy_stats.get("trades", 0))
    avg_pnl = float(policy_stats.get("avg_pnl", 0.0) or 0.0)
    wins = int(policy_stats.get("wins", 0))
    context_attempts = int(context_stats.get("attempts", 0))
    context_wins = int(context_stats.get("wins", 0))
    resolved = int(context_stats.get("resolved", 0))
    avg_peak_fee_multiple = (
        float(context_stats.get("peak_fee_multiple_sum", 0.0) or 0.0) / max(resolved, 1) if resolved else 0.0
    )
    expected_edge = estimate_candidate_edge(candidate, quality, regime, market, context_stats, signal_ctx, oracle_insight)
    predictive_setup = compute_predictive_setup_score(
        regime=regime,
        intent=str(candidate.get("intent", "")),
        direction=str(candidate.get("direction", "long")),
        context_stats=context_stats,
        shadow_context_stats=shadow_context_stats,
        shadow_direction_stats=shadow_direction_stats,
        oracle_insight=oracle_insight,
        signal_ctx=signal_ctx,
    )
    predictive_score = float(predictive_setup.get("score", 0.0) or 0.0)
    expected_edge += float(predictive_setup.get("edge_bonus", 0.0) or 0.0)
    structure = brain.get("broader_structure") or {}
    structure_confidence = float(structure.get("confidence", 0.0) or 0.0)
    structure_alignment = get_broader_structure_alignment(
        str(candidate.get("direction", "long") or "long"),
        str(candidate.get("intent", "") or ""),
        structure,
    )
    if structure_alignment == "aligned":
        expected_edge += min(0.08, structure_confidence * 0.10)
    elif structure_alignment == "supportive":
        expected_edge += min(0.04, structure_confidence * 0.06)
    elif structure_alignment == "conflict":
        expected_edge -= min(0.10, structure_confidence * 0.12)
    if small_account and regime == "chop":
        expected_edge -= 0.08
    if elite_chop and regime == "chop":
        expected_edge += 0.10 + min(0.10, float(oracle_insight.get("score", 0.0) or 0.0) * 0.12)
    if small_account and regime in {"trend", "squeeze"}:
        expected_edge += 0.05
    if regime == "chop" and candidate.get("intent") == "mean_revert":
        alignment_score = float(chop_alignment.get("score", 0.0) or 0.0)
        candidate_direction = str(candidate.get("direction", "long") or "long")
        regime_bias = str(brain.get("market_regime", {}).get("bias", "neutral") or "neutral")
        oracle_bias = str(oracle_insight.get("dominant_bias", "neutral") or "neutral")
        mtf_alignment = str(signal_ctx.get("mtf_alignment", "mixed") or "mixed")
        shadow_direction_resolved = int(shadow_direction_stats.get("resolved", 0) or 0)
        effective_live_align = max(
            0.40,
            get_chop_align_live_min() - float(brain.get("last_entry_gate_state", {}).get("reactivation_relief", 0.0) or 0.0) * 0.9,
        )
        learner_lane = False
        shadow_direction_peak_fee = (
            float(shadow_direction_stats.get("peak_fee_multiple_sum", 0.0) or 0.0) / max(shadow_direction_resolved, 1)
            if shadow_direction_resolved else 0.0
        )
        shadow_direction_fee_clears = int(shadow_direction_stats.get("fee_clears", 0) or 0)
        same_direction_shadow_ready = (
            shadow_direction_fee_clears > 0
            and shadow_direction_peak_fee >= CHOP_LEARNER_LANE_MIN_PEAK_FEE
        )
        expected_edge += max(-0.12, min(0.16, (alignment_score - 0.50) * 0.40))
        if not shadow_mode:
            if oracle_bias == "bearish" and mtf_alignment == "bearish" and candidate_direction == "long":
                return None, "live chop directional veto | oracle+mtf bearish vs long"
            if oracle_bias == "bullish" and mtf_alignment == "bullish" and candidate_direction == "short":
                return None, "live chop directional veto | oracle+mtf bullish vs short"
            _mc = brain.get("market_context", {})
            _range_pos = float(_mc.get("range_position", 0.5) or 0.5)
            _range_est = bool(_mc.get("range_established", False))
            _range_w = float(_mc.get("range_width_pct", 0.0) or 0.0)
            if _range_est and _range_w >= CHOP_MIN_RANGE_WIDTH_PCT:
                _long_max = get_range_long_max()
                _short_min = get_range_short_min()
                if candidate_direction == "long" and _range_pos > _long_max:
                    return None, f"range position gate | long blocked | pos={_range_pos:.2f} > max={_long_max:.2f}"
                if candidate_direction == "short" and _range_pos < _short_min:
                    return None, f"range position gate | short blocked | pos={_range_pos:.2f} < min={_short_min:.2f}"
        if not shadow_mode and small_account and not same_direction_shadow_ready:
            return None, (
                f"live chop shadow-proof filter | policy={candidate['policy']} dir={candidate['direction']} "
                f"fee_clears={shadow_direction_fee_clears} peak_fee={shadow_direction_peak_fee:.2f}"
            )
        if not shadow_mode and alignment_score < effective_live_align:
            learner_lane = (
                small_account
                and candidate.get("policy") in {"mean_revert_micro", "mean_revert_imbalance_fade", "mean_revert_reclaim"}
                and quality >= CHOP_LEARNER_LANE_MIN_QUALITY
                and alignment_score >= CHOP_LEARNER_LANE_MIN_ALIGN
                and predictive_score >= CHOP_LEARNER_LANE_MIN_PREDICTIVE
                and same_direction_shadow_ready
                and int(candidate.get("leverage", 0) or 0) <= 2
            )
        candidate["chop_learner_lane_active"] = learner_lane
        if not shadow_mode and small_account and not learner_lane:
            return None, "small-account live chop requires learner lane"
        if not shadow_mode and alignment_score < effective_live_align and not learner_lane:
            return None, (
                f"chop alignment filter | policy={candidate['policy']} "
                f"align={alignment_score:.2f} < min={effective_live_align:.2f}"
            )
        if not shadow_mode:
            if not learner_lane and predictive_score < LIVE_CHOP_MIN_PREDICTIVE:
                return None, (
                    f"live chop predictive filter | policy={candidate['policy']} "
                    f"pred={predictive_score:.2f} < min={LIVE_CHOP_MIN_PREDICTIVE:.2f}"
                )
            if not learner_lane and expected_edge < LIVE_CHOP_MIN_EDGE:
                return None, (
                    f"live chop edge filter | policy={candidate['policy']} "
                    f"edge={expected_edge:.2f} < min={LIVE_CHOP_MIN_EDGE:.2f}"
                )

    empirical_wr = wins / trades if trades else 0.5
    context_wr = context_wins / context_attempts if context_attempts else 0.5
    shadow_resolved = int(shadow_context_stats.get("resolved", 0))
    shadow_bonus = compute_shadow_selector_bonus(shadow_context_stats)
    shadow_direction_resolved = int(shadow_direction_stats.get("resolved", 0))
    shadow_direction_bonus = 0.0
    if not shadow_mode and regime == "chop" and candidate.get("intent") == "mean_revert" and shadow_direction_resolved:
        shadow_direction_bonus = compute_shadow_selector_bonus(
            shadow_direction_stats,
            cap=min(SHADOW_SELECTOR_BONUS_CAP, 0.035),
            fee_clear_weight=0.02,
            peak_fee_scale=12.0,
        )
    novelty = 1.0 / (trades + 1)
    context_novelty = 1.0 / (context_attempts + 1)

    rotation_penalty = 0.08 if candidate["policy"] == last_policy else 0.0
    context_repeat_penalty = 0.12 if context_attempts >= 2 else 0.0

    if regime == "chop" and candidate.get("intent") == "mean_revert":
        mtf_alignment = str(signal_ctx.get("mtf_alignment", "mixed"))
        session_bucket = str(signal_ctx.get("session_bucket", "offhours"))
        volatility_expansion = float(signal_ctx.get("volatility_expansion", 1.0) or 1.0)
        fading_bullish = (
            candidate["direction"] == "short"
            and mtf_alignment == "bullish"
            and session_bucket in {"london", "ny_open", "ny_late"}
            and volatility_expansion >= CHOP_FADE_VETO_VOLX
            and price_action in {"higher_highs", "bullish_breakout"}
        )
        fading_bearish = (
            candidate["direction"] == "long"
            and mtf_alignment == "bearish"
            and session_bucket in {"london", "ny_open", "ny_late"}
            and volatility_expansion >= CHOP_FADE_VETO_VOLX
            and price_action in {"range_bound", "bearish_breakdown"}
        )
        if not shadow_mode and (fading_bullish or fading_bearish):
            return None, (
                f"aligned pressure veto | dir={candidate['direction']} mtf={mtf_alignment} "
                f"session={session_bucket} volx={volatility_expansion:.2f} pa={price_action}"
            )

    if regime in {"trend", "squeeze"} and candidate.get("intent") in {"trend_follow", "breakout"}:
        regime_bias = str(brain.get("market_regime", {}).get("bias", "neutral"))
        mtf_alignment = str(signal_ctx.get("mtf_alignment", "mixed"))
        volatility_expansion = float(signal_ctx.get("volatility_expansion", 1.0) or 1.0)
        volatility_state = str(signal_ctx.get("volatility_state", "normal"))
        direction = str(candidate.get("direction", "long"))

        if regime_bias in {"bullish", "bearish"}:
            expected_direction = "long" if regime_bias == "bullish" else "short"
            if direction != expected_direction:
                return None, (
                    f"directional bias mismatch | policy={candidate['policy']} "
                    f"dir={direction} bias={regime_bias}"
                )

        directional_structure = 0.0
        if mtf_alignment == "mixed":
            directional_structure += 0.18
        elif (mtf_alignment == "bullish" and direction == "long") or (mtf_alignment == "bearish" and direction == "short"):
            directional_structure += 0.34
        else:
            directional_structure -= 0.18

        if (direction == "long" and price_action in {"higher_highs", "bullish_breakout"}) or (
            direction == "short" and price_action == "bearish_breakdown"
        ):
            directional_structure += 0.24
        elif price_action == "range_bound":
            directional_structure -= 0.10

        if volatility_expansion >= 1.05 or volatility_state == "expanded":
            directional_structure += 0.12

        if quality >= get_directional_min_quality():
            directional_structure += 0.12

        shadow_direction_peak_fee = (
            float(shadow_direction_stats.get("peak_fee_multiple_sum", 0.0) or 0.0) / max(shadow_direction_resolved, 1)
            if shadow_direction_resolved else 0.0
        )
        live_or_shadow_fee_ready = (
            avg_peak_fee_multiple >= DIRECTIONAL_MIN_PEAK_FEE_MULTIPLE
            or shadow_direction_peak_fee >= DIRECTIONAL_SHADOW_MIN_PEAK_FEE_MULTIPLE
        )

        if small_account and not shadow_mode:
            flat_relief = get_directional_flat_relief(regime, signal_ctx)
            eff_dir_quality = max(0.30, get_directional_min_quality() - flat_relief)
            eff_dir_structure = max(0.28, get_directional_min_structure() - flat_relief)
            eff_dir_edge = max(0.08, get_directional_min_edge() - flat_relief * 0.5)
            predictive_floor = max(
                0.40,
                (get_breakout_min_predictive() if candidate.get("intent") == "breakout" else get_directional_min_predictive())
                - flat_relief * 0.5,
            )
            if quality < eff_dir_quality:
                return None, (
                    f"directional quality filter | policy={candidate['policy']} "
                    f"q={quality:.2f} < min={eff_dir_quality:.2f} (base={get_directional_min_quality():.2f} relief={flat_relief:.3f})"
                )
            if predictive_score < predictive_floor:
                return None, (
                    f"directional predictive filter | policy={candidate['policy']} "
                    f"pred={predictive_score:.2f} < min={predictive_floor:.2f} (relief={flat_relief:.3f})"
                )
            if directional_structure < eff_dir_structure:
                return None, (
                    f"directional structure filter | policy={candidate['policy']} "
                    f"struct={directional_structure:.2f} < min={eff_dir_structure:.2f} (relief={flat_relief:.3f})"
                )
            if expected_edge < eff_dir_edge:
                return None, (
                    f"directional edge filter | policy={candidate['policy']} "
                    f"edge={expected_edge:.2f} < min={eff_dir_edge:.2f} (relief={flat_relief:.3f})"
                )
            if resolved >= 2 or shadow_direction_resolved >= 2:
                if not live_or_shadow_fee_ready:
                    return None, (
                        f"directional fee-clear filter | policy={candidate['policy']} "
                        f"live_peak={avg_peak_fee_multiple:.2f} shadow_peak={shadow_direction_peak_fee:.2f}"
                    )

        expected_edge += max(-0.06, min(0.10, (directional_structure - 0.45) * 0.22))

    candidate_direction = str(candidate.get("direction", "long") or "long")
    candidate_level_edge = bool(
        (candidate_direction == "long" and (signal_ctx.get("at_support", False) or signal_ctx.get("sweep_reclaim_long", False)))
        or (candidate_direction == "short" and (signal_ctx.get("at_resistance", False) or signal_ctx.get("sweep_reclaim_short", False)))
    )
    effective_edge, edge_lift, edge_lift_reason = compute_aggressive_learning_edge_lift(
        base_edge=expected_edge,
        predictive_score=predictive_score,
        alignment=structure_alignment,
        level_edge=candidate_level_edge,
        same_proof=summarize_shadow_direction_proof(regime, candidate_direction),
        shadow_bonus=shadow_bonus,
        shadow_direction_bonus=shadow_direction_bonus,
        structure_confidence=structure_confidence,
    )
    if not shadow_mode and edge_lift > 0.0:
        expected_edge = effective_edge

    score = (
        candidate["fit"]
        + (0.08 if structure_alignment == "aligned" else 0.04 if structure_alignment == "supportive" else -0.08 if structure_alignment == "conflict" else 0.0)
        + get_exploration_policy_fit_adjustment(str(candidate.get("policy", "")))
        + (
            0.08
            if candidate_matches_best_lane(
                candidate,
                regime=regime,
                regime_bias=str(brain.get("market_regime", {}).get("bias", "neutral") or "neutral"),
                signal_ctx=signal_ctx,
            )[0]
            else 0.0
        )
        + quality * 0.35
        + empirical_wr * 0.18
        + context_wr * 0.10
        + expected_edge * 0.42
        + predictive_score * 0.18
        + shadow_bonus
        + shadow_direction_bonus
        + max(-0.12, min(0.12, avg_pnl / 3000.0))
        + novelty * 0.30
        + context_novelty * 0.22
        - rotation_penalty
        - context_repeat_penalty
    )

    min_edge = get_exploration_min_edge(
        regime,
        str(candidate.get("intent", "")),
        small_account,
        elite_chop,
    )

    min_peak_fee_multiple = 0.0
    if regime == "chop" and candidate.get("intent") == "mean_revert":
        min_peak_fee_multiple = ELITE_CHOP_MIN_PEAK_FEE_MULTIPLE if elite_chop else CHOP_MIN_PEAK_FEE_MULTIPLE
    if not shadow_mode and resolved >= 2 and avg_peak_fee_multiple < min_peak_fee_multiple:
        return None, (
            f"fee-clear filter | policy={candidate['policy']} peak_fee={avg_peak_fee_multiple:.2f} "
            f"< min={min_peak_fee_multiple:.2f}"
        )

    if not shadow_mode and edge_lift > 0.0:
        min_edge = max(AGGRESSIVE_LEARNING_MIN_EFFECTIVE_EDGE, min_edge - min(0.10, edge_lift * 0.45))

    if not shadow_mode and expected_edge < min_edge:
        return None, f"edge filter | policy={candidate['policy']} edge={expected_edge:.2f} < min={min_edge:.2f}"

    enriched = dict(candidate)
    enriched["expected_edge"] = expected_edge
    enriched["predictive_setup_score"] = predictive_score
    enriched["predictive_setup_summary"] = str(predictive_setup.get("component_summary", "n/a"))
    enriched["predictive_setup_edge_bonus"] = float(predictive_setup.get("edge_bonus", 0.0) or 0.0)
    enriched["broader_structure_alignment"] = structure_alignment
    enriched["broader_structure_action"] = str(structure.get("action", "wait") or "wait")
    enriched["shadow_bonus"] = round(shadow_bonus, 4)
    enriched["shadow_direction_bonus"] = round(shadow_direction_bonus, 4)
    enriched["aggressive_learning_edge_lift"] = round(edge_lift, 4)
    enriched["aggressive_learning_edge_lift_reason"] = edge_lift_reason
    return (score, enriched), None


def choose_exploration_signal(adaptive: dict[str, Any], usable: float) -> Optional[EntrySignal]:
    regime = str(adaptive.get("regime", brain.get("market_regime", {}).get("regime", "unknown")) or "unknown")
    market = brain.get("market_context", {}) or {}
    signal_ctx = get_signal_context()
    gate_state = get_entry_gate_state(usable)
    quality = float(gate_state.get("quality", 0.0) or 0.0)
    oracle_insight = gate_state.get("oracle_insight", {}) or {}
    chop_alignment = gate_state.get("chop_alignment", {}) or {}
    elite_chop = bool(gate_state.get("elite_chop"))
    strategic = get_strategic_aggression_context()
    if str(strategic.get("mode", "observe") or "observe") != "attack":
        return None

    scored_candidates, _ = rank_exploration_candidates(
        regime=regime,
        quality=quality,
        market=market,
        signal_ctx=signal_ctx,
        price_action=str(brain.get("price_action_summary", "neutral") or "neutral"),
        small_account=bool(gate_state.get("small_account")),
        elite_chop=elite_chop,
        oracle_insight=oracle_insight,
        last_policy=brain.get("exploration", {}).get("last_policy"),
        chop_alignment=chop_alignment,
        shadow_mode=False,
    )
    if not scored_candidates:
        return None

    selected_score, best = scored_candidates[0]
    shadow_bias = get_recent_shadow_bias(
        regime,
        str(best.get("direction", "long") or "long"),
        str(best.get("intent", "") or ""),
    )
    if (
        float(shadow_bias.get("success_bonus", 0.0) or 0.0) <= 0.0
        and float(shadow_bias.get("last_outcome_bps", 0.0) or 0.0) <= 20.0
        and float(best.get("predictive_setup_score", 0.0) or 0.0) < 0.70
    ):
        return None
    expected_edge = float(best.get("expected_edge", 0.0) or 0.0)
    predictive_score = float(best.get("predictive_setup_score", 0.0) or 0.0)
    if max(expected_edge, predictive_score, selected_score) < 0.35:
        return None

    return EntrySignal(
        action="open",
        direction=str(best.get("direction", "long") or "long"),
        intent=str(best.get("intent", "mean_revert") or "mean_revert"),
        mode="exploit",
        policy=str(best.get("policy", "mean_revert_reclaim") or "mean_revert_reclaim"),
        confidence=clamp(float(best.get("confidence", 0.5) or 0.5), 0.0, 0.95),
        quantity=1,
        sl_bps=int(best.get("sl_bps", 60) or 60),
        tp_bps=int(best.get("tp_bps", 90) or 90),
        trail_bps=int(best.get("trail_bps", 30) or 30),
        leverage=get_dynamic_leverage(
            max(expected_edge, predictive_score),
            "good" if str(best.get("broader_structure_alignment", "")) == "aligned" else "supportive",
            regime,
            str(brain.get("risk_mode", "normal") or "normal"),
        ),
        max_hold_minutes=int(best.get("max_hold_minutes", 36) or 36),
        risk_per_trade=float(adaptive.get("risk_per_trade", RISK_PER_TRADE) or RISK_PER_TRADE),
        expected_edge=expected_edge,
        predictive_setup_score=predictive_score,
        predictive_setup_summary=str(best.get("predictive_setup_summary", "n/a")),
        reason=(
            f"shadow-backed deterministic live entry | policy={best.get('policy')} "
            f"score={selected_score:.2f} edge={expected_edge:.2f} "
            f"shadow={float(shadow_bias.get('success_bonus', 0.0) or 0.0):+.2f}"
        )[:240],
    )


def should_record_shadow_for_blocked_entry(regime: str, blocked_reason: str) -> bool:
    shadow_worthy = ("level gate", "feature health gate", "calibration gate", "directional proof gate")
    if any(token in blocked_reason for token in shadow_worthy):
        return True
    if regime == "chop" and "chop" in blocked_reason:
        return True
    if regime == "squeeze" and (
        "directional suppression" in blocked_reason
        or "edge filter" in blocked_reason
        or "small-account" in blocked_reason
        or "squeeze structural gate" in blocked_reason
        or "level-backed mean-revert" in blocked_reason
    ):
        return True
    return False


def maybe_record_shadow_exploration(adaptive: dict[str, Any], usable: float, blocked_reason: str):
    regime = str(adaptive.get("regime", brain.get("market_regime", {}).get("regime", "unknown")))
    if not should_record_shadow_for_blocked_entry(regime, blocked_reason):
        return
    if brain.get("risk_mode") == "protection":
        return
    shadow = ensure_shadow_exploration_state()
    pending = shadow.setdefault("pending", [])
    if len(pending) >= SHADOW_MAX_PENDING:
        return
    now_ts = time.time()
    if now_ts - float(shadow.get("last_shadow_at", 0.0) or 0.0) < SHADOW_EXPLORATION_COOLDOWN_SECONDS:
        return

    market = brain.get("market_context", {})
    signal_ctx = get_signal_context()
    price_action = str(brain.get("price_action_summary", "neutral"))
    gate_state = get_entry_gate_state(usable)
    quality = float(gate_state.get("quality", 0.0) or 0.0)
    oracle_insight = gate_state.get("oracle_insight", {})
    chop_alignment = gate_state.get("chop_alignment", {})
    elite_chop = bool(gate_state.get("elite_chop"))
    scored_candidates, _ = rank_exploration_candidates(
        regime=regime,
        quality=quality,
        market=market,
        signal_ctx=signal_ctx,
        price_action=price_action,
        small_account=bool(gate_state.get("small_account")),
        elite_chop=elite_chop,
        oracle_insight=oracle_insight,
        last_policy=brain.get("exploration", {}).get("last_policy"),
        chop_alignment=chop_alignment,
        shadow_mode=True,
    )
    if not scored_candidates:
        return

    selected_score, best = scored_candidates[0]
    entry_price = float(brain.get("last_price") or market_state.get("last_price") or 0.0)
    if entry_price <= 0:
        return

    candidate_blocked_reason = blocked_reason
    if "level gate" in blocked_reason:
        # Attribute shadow learning to the candidate actually being tracked;
        # the top rejection reason may come from a different direction.
        candidate_blocked_reason = get_candidate_level_block_reason(
            str(best.get("direction", "long") or "long"),
            str(best.get("intent", "") or ""),
            str(best.get("policy", "") or ""),
            signal_ctx,
        ) or blocked_reason

    timestamp = datetime.now()
    trade_signal_snapshot = build_trade_signal_snapshot(
        regime=regime,
        quality=quality,
        signal_ctx=signal_ctx,
        oracle_insight=oracle_insight,
        chop_alignment=chop_alignment,
    )
    signal_features = get_market_path_features()
    record = build_shadow_exploration_attempt_record(
        timestamp=timestamp,
        candidate=best,
        regime=regime,
        fingerprint=get_exploration_context_fingerprint(regime),
        selected_score=selected_score,
        quality=quality,
        expected_edge=float(best.get("expected_edge", 0.0) or 0.0),
        predictive_setup_score=float(best.get("predictive_setup_score", 0.0) or 0.0),
        predictive_setup_summary=str(best.get("predictive_setup_summary", "n/a")),
        trade_signal_snapshot=trade_signal_snapshot,
        signal_features=signal_features,
        blocked_reason=candidate_blocked_reason,
        entry_price=entry_price,
    )
    pending.append(build_shadow_pending_record(record, candidate_blocked_reason))
    shadow.setdefault("recent", []).append(record)
    trim_shadow_exploration_state()
    shadow["last_shadow_at"] = now_ts
    log(
        f"🕶️ SHADOW TRADE | {best['policy']} | dir={best['direction']} "
        f"score={selected_score:.2f} edge={best.get('expected_edge', 0.0):.2f} "
        f"pred={best.get('predictive_setup_score', 0.0):.2f} | blocked={candidate_blocked_reason}"
    )


def maybe_log_shadow_report():
    now_ts = time.time()
    if now_ts - float(brain.get("last_shadow_report_log_at", 0.0) or 0.0) < SHADOW_REPORT_LOG_INTERVAL_SECONDS:
        return
    recent = brain.get("shadow_exploration", {}).get("recent", [])[-80:]
    resolved = [item for item in recent if item.get("outcome_bps") is not None]
    blocked_counts: dict[str, int] = {}
    profitable_by_block: dict[str, int] = {}
    for item in recent:
        reason = str(item.get("blocked_reason", "unknown") or "unknown")
        key = reason.split("|", 1)[0].strip()
        blocked_counts[key] = blocked_counts.get(key, 0) + 1
        if float(item.get("outcome_bps", 0.0) or 0.0) > ORACLE_REPLAY_FEE_PROXY_BPS:
            profitable_by_block[key] = profitable_by_block.get(key, 0) + 1
    top_block = max(blocked_counts.items(), key=lambda item: item[1], default=("none", 0))
    top_profitable = max(profitable_by_block.items(), key=lambda item: item[1], default=("none", 0))
    report = {
        "timestamp": datetime.now().isoformat(),
        "recent": len(recent),
        "resolved": len(resolved),
        "top_block": top_block[0],
        "top_block_count": top_block[1],
        "top_profitable_block": top_profitable[0],
        "top_profitable_count": top_profitable[1],
    }
    brain["shadow_report"] = report
    brain["last_shadow_report_log_at"] = now_ts
    append_review_report("shadow_report", report)
    if recent:
        log(
            f"SHADOW REPORT | recent={len(recent)} resolved={len(resolved)} "
            f"top_block={top_block[0]}:{top_block[1]} "
            f"profitable_block={top_profitable[0]}:{top_profitable[1]}"
        )


def update_shadow_exploration_pending(price: float):
    if price <= 0:
        return
    shadow = ensure_shadow_exploration_state()
    pending = shadow.setdefault("pending", [])
    if not pending:
        return

    now = datetime.now()
    remaining: list[dict[str, Any]] = []
    recent = shadow.setdefault("recent", [])
    for item in pending:
        entry_price = float(item.get("entry_price", 0.0) or 0.0)
        if entry_price <= 0:
            continue
        opened_at = parse_iso_dt(item.get("opened_at"))
        age_minutes = max((now - opened_at).total_seconds() / 60.0, 0.0) if opened_at else 0.0
        direction = str(item.get("direction", "long"))
        side = 1.0 if direction == "long" else -1.0
        current_bps = (((price / entry_price) - 1.0) * 10000.0) * side
        max_favorable = max(float(item.get("max_favorable_bps", 0.0) or 0.0), current_bps)
        max_adverse = min(float(item.get("max_adverse_bps", 0.0) or 0.0), current_bps)
        if max_favorable > float(item.get("max_favorable_bps", 0.0) or 0.0):
            item["time_to_mfe_minutes"] = round(age_minutes, 2)
        if max_adverse < float(item.get("max_adverse_bps", 0.0) or 0.0):
            item["time_to_mae_minutes"] = round(age_minutes, 2)
        item["max_favorable_bps"] = round(max_favorable, 3)
        item["max_adverse_bps"] = round(max_adverse, 3)

        resolve_reason = None
        if current_bps >= float(item.get("tp_bps", 0) or 0):
            resolve_reason = "shadow_tp"
        elif current_bps <= -float(item.get("sl_bps", 0) or 0):
            resolve_reason = "shadow_sl"
        elif age_minutes >= float(item.get("max_hold_minutes", 0) or 0):
            resolve_reason = "shadow_max_hold"

        if not resolve_reason:
            remaining.append(item)
            continue

        fee_cleared = max_favorable >= ORACLE_REPLAY_FEE_PROXY_BPS
        entry_price_value = float(item.get("entry_price", 0.0) or 0.0)
        shadow_position = PositionState()
        shadow_position.side = direction
        shadow_position.intent = "mean_revert" if "mean_revert" in str(item.get("policy", "")) else "trend_follow"
        shadow_position.entry = entry_price_value
        shadow_position.qty = 1.0
        shadow_position.opened_at = opened_at or now
        shadow_position.best_price = entry_price_value * (1.0 + (max_favorable / 10000.0) * side)
        shadow_position.worst_price = entry_price_value * (1.0 + (max_adverse / 10000.0) * side)
        shadow_position.max_unrealized_pnl = max_favorable
        shadow_position.min_unrealized_pnl = min(max_adverse, 0.0)
        shadow_position.time_to_mfe_minutes = item.get("time_to_mfe_minutes")
        shadow_position.time_to_mae_minutes = item.get("time_to_mae_minutes")
        shadow_thesis = get_position_thesis_metrics(shadow_position, price)
        shadow_close_alignment = compute_close_alignment(shadow_position, shadow_thesis, price)
        resolved_payload = {
            "resolved_at": now.isoformat(),
            "resolve_reason": resolve_reason,
            "outcome_bps": round(current_bps, 3),
            "fee_cleared": fee_cleared,
            "max_fee_multiple": round(max_favorable / max(ORACLE_REPLAY_FEE_PROXY_BPS, 1.0), 3),
            "time_to_mfe_minutes": item.get("time_to_mfe_minutes"),
            "time_to_mae_minutes": item.get("time_to_mae_minutes"),
            "max_favorable_bps": round(max_favorable, 3),
            "max_adverse_bps": round(max_adverse, 3),
            "close_alignment": round(float(shadow_close_alignment.get("score", 0.0) or 0.0), 4),
            "close_alignment_summary": str(shadow_close_alignment.get("component_summary", "n/a")),
        }
        for recent_item in reversed(recent):
            if recent_item.get("id") != item.get("id"):
                continue
            recent_item.update(resolved_payload)
            update_shadow_policy_stats(str(recent_item.get("policy", "")), recent_item)
            update_structured_squeeze_shadow_stats(recent_item)
            log(
                f"🕶️ SHADOW RESOLVED | {recent_item.get('policy', 'unknown')} "
                f"| dir={recent_item.get('direction', 'n/a')} "
                f"| reason={resolve_reason} "
                f"| outcome_bps={resolved_payload['outcome_bps']:+.1f} "
                f"| fee_cleared={str(fee_cleared).lower()} "
                f"| peak_fee={resolved_payload['max_fee_multiple']:+.2f} "
                f"| mfe={resolved_payload['max_favorable_bps']:+.1f}bps "
                f"| mae={resolved_payload['max_adverse_bps']:+.1f}bps "
                f"| close_align={resolved_payload['close_alignment']:+.2f} "
                f"| ttmfe={resolved_payload.get('time_to_mfe_minutes')}m"
            )
            break

    shadow["pending"] = remaining
    trim_shadow_exploration_state()

    # Tune range thresholds every 25 newly-resolved mean_revert shadows
    rt = brain.setdefault("range_thresholds", {})
    _ = rt


def get_volatility_factor() -> float:
    vol = float(brain.get("market_regime", {}).get("volatility", market_state.get("volatility", 0.001)))
    baseline = 0.001
    factor = baseline / max(vol, 0.0005)
    return max(0.5, min(factor, 2.0))


def estimate_margin_capped_qty(usable: float, leverage: int, margin_util: float) -> int:
    approx_entry = float(brain.get("last_price") or market_state.get("last_price") or 73000)
    if usable <= 0 or leverage <= 0 or approx_entry <= 0:
        return 1
    max_margin_sats = usable * clamp(margin_util, 0.20, 0.85)
    return max(1, int((max_margin_sats * approx_entry * leverage) / 100_000_000))


def estimate_add_margin_capped_qty(usable: float, leverage: int) -> int:
    """Conservative add-only cap. Unlike entry sizing, returning 0 is valid."""
    approx_entry = float(brain.get("last_price") or market_state.get("last_price") or 0.0)
    if usable <= ADD_MARGIN_RESERVE_SATS or leverage <= 0 or approx_entry <= 0:
        return 0
    max_margin_sats = max(0.0, usable - ADD_MARGIN_RESERVE_SATS) * ADD_MARGIN_UTILIZATION
    return max(0, int((max_margin_sats * approx_entry * leverage) / 100_000_000))


def get_small_account_quantity_plan(
    usable: float,
    leverage: int,
    signal: Optional[EntrySignal] = None,
) -> tuple[int, int, str]:
    standard_account = usable >= SMALL_ACCOUNT_DYNAMIC_SIZING_SATS
    state = brain.get("last_entry_gate_state", {}) or {}
    regime = str(state.get("regime", brain.get("market_regime", {}).get("regime", "unknown")))
    quality = float(state.get("quality", brain.get("market_quality_score", 0.0)) or 0.0)
    selected_edge = float(state.get("selected_expected_edge", 0.0) or 0.0)
    selected_pred = float(state.get("selected_predictive_setup_score", 0.0) or 0.0)
    if signal is not None:
        selected_edge = max(selected_edge, float(getattr(signal, "expected_edge", 0.0) or 0.0))
        selected_pred = max(selected_pred, float(getattr(signal, "predictive_setup_score", 0.0) or 0.0))
    elite_chop = bool(state.get("elite_chop"))
    learner_lane_active = bool(state.get("chop_learner_lane_active"))
    oracle_insight = state.get("oracle_insight", {}) or {}
    oracle_score = float(oracle_insight.get("score", 0.0) or 0.0)
    chop_alignment = state.get("chop_alignment", {}) or {}
    align = float(chop_alignment.get("score", 0.0) or 0.0)
    risk_mode = str(brain.get("risk_mode", "normal") or "normal")
    signal_mode = str(getattr(signal, "mode", "") or "")
    signal_risk = float(getattr(signal, "risk_per_trade", RISK_PER_TRADE) or RISK_PER_TRADE) if signal else RISK_PER_TRADE
    _et = get_exploration_thresholds()
    _dyn_edge = float(_et.get("min_edge", 0.16) or 0.16)
    _dyn_conf = float(_et.get("confidence_floor", 0.44) or 0.44)
    margin_util = SMALL_ACCOUNT_CAUTION_MARGIN_UTIL if risk_mode == "caution" else SMALL_ACCOUNT_MAX_MARGIN_UTIL
    if (
        risk_mode == "normal"
        and regime in {"trend", "squeeze"}
        and quality >= get_exploration_min_score()
        and selected_pred >= _dyn_conf + 0.14
        and selected_edge >= _dyn_edge + 0.04
    ):
        margin_util = min(0.85, margin_util + 0.05)
    margin_cap = min(MAX_QTY, estimate_margin_capped_qty(usable, leverage, margin_util))
    oracle_backed_good_setup = bool(
        quality >= get_exploration_min_score()
        and selected_pred >= _dyn_conf + 0.11
        and oracle_score >= 0.60
        and regime != "unknown"
        and not learner_lane_active
    )
    if oracle_backed_good_setup:
        if risk_mode == "caution":
            target = SMALL_ACCOUNT_STRONG_QTY
        elif usable >= SMALL_ACCOUNT_DYNAMIC_MIN_SATS or selected_pred >= _dyn_conf + 0.20 or signal_risk >= 0.006:
            target = SMALL_ACCOUNT_AGGRESSIVE_QTY
        else:
            target = SMALL_ACCOUNT_STRONG_QTY
        if signal_mode == "explore":
            target = min(target, SMALL_ACCOUNT_STRONG_QTY)
        margin_cap = min(MAX_QTY, max(margin_cap, target))
        return target, margin_cap, (
            f"oracle_backed_good_setup q={quality:.2f} pred={selected_pred:.2f} "
            f"oracle={oracle_score:.2f} risk={signal_risk:.4f} usable={usable:.0f} "
            f"target={target} margin_cap={margin_cap}"
        )

    if standard_account:
        return 1, MAX_QTY, "standard"

    if usable < SMALL_ACCOUNT_DYNAMIC_MIN_SATS:
        if (
            regime in {"trend", "squeeze"}
            and quality >= 0.40
            and selected_pred >= _dyn_conf + 0.08
            and selected_edge >= max(0.10, _dyn_edge - 0.04)
        ):
            target = SMALL_ACCOUNT_MEDIUM_QTY
            if quality >= get_exploration_min_score() and selected_pred >= _dyn_conf + 0.14 and selected_edge >= _dyn_edge + 0.04:
                target = SMALL_ACCOUNT_STRONG_QTY
            if quality >= get_exploration_min_score() + 0.08 and selected_pred >= _dyn_conf + 0.20 and selected_edge >= _dyn_edge + 0.12:
                target = SMALL_ACCOUNT_AGGRESSIVE_QTY
            if signal_mode == "explore":
                target = min(target, 2)
            capped = min(target, margin_cap)
            return max(1, capped), max(1, capped), (
                f"tiny_{regime}_edge q={quality:.2f} pred={selected_pred:.2f} "
                f"edge={selected_edge:.2f} margin_cap={margin_cap}"
            )
        return 1, 1, f"tiny_balance usable={usable:.0f}"
    if regime == "unknown":
        return 1, 1, "unknown_regime"
    if learner_lane_active:
        return 1, 1, f"chop_learner_lane q={quality:.2f} align={align:.2f}"
    if signal_mode == "explore":
        if (
            regime in {"trend", "squeeze"}
            and quality >= max(0.40, get_exploration_min_score() - 0.02)
            and selected_pred >= _dyn_conf + 0.08
            and selected_edge >= _dyn_edge + 0.04
        ):
            qty = min(SMALL_ACCOUNT_EXPLORE_WINNER_QTY, margin_cap)
            return qty, qty, (
                f"explore_{regime}_edge q={quality:.2f} pred={selected_pred:.2f} "
                f"edge={selected_edge:.2f} margin_cap={margin_cap}"
            )
        return 1, min(2, max(1, margin_cap)), (
            f"explore_marginal_cap q={quality:.2f} pred={selected_pred:.2f} "
            f"oracle={oracle_score:.2f} margin_cap={margin_cap}"
        )

    if regime == "chop":
        if (
            elite_chop
            and quality >= 0.46
            and align >= get_chop_align_min()
            and selected_pred >= _dyn_conf + 0.20
            and selected_edge >= _dyn_edge + 0.12
        ):
            qty = min(SMALL_ACCOUNT_STRONG_QTY, margin_cap)
            return qty, qty, (
                f"elite_chop_strong q={quality:.2f} align={align:.2f} "
                f"pred={selected_pred:.2f} edge={selected_edge:.2f} margin_cap={margin_cap}"
            )
        if (
            elite_chop
            and quality >= 0.40
            and align >= get_chop_align_live_min()
            and selected_pred >= _dyn_conf + 0.14
            and selected_edge >= _dyn_edge + 0.04
        ):
            qty = min(SMALL_ACCOUNT_MEDIUM_QTY, margin_cap)
            return qty, qty, (
                f"elite_chop_medium q={quality:.2f} align={align:.2f} "
                f"pred={selected_pred:.2f} edge={selected_edge:.2f} margin_cap={margin_cap}"
            )
        return 1, 1, f"small_chop q={quality:.2f} align={align:.2f} elite={elite_chop}"

    if (
        regime in {"trend", "squeeze"}
        and quality >= get_exploration_min_score() + 0.08
        and selected_pred >= _dyn_conf + 0.20
        and selected_edge >= _dyn_edge + 0.12
    ):
        qty = min(SMALL_ACCOUNT_AGGRESSIVE_QTY, margin_cap)
        return qty, qty, f"{regime}_elite q={quality:.2f} pred={selected_pred:.2f} edge={selected_edge:.2f} margin_cap={margin_cap}"
    if regime in {"trend", "squeeze"} and quality >= get_exploration_min_score() and selected_pred >= _dyn_conf + 0.12:
        qty = min(SMALL_ACCOUNT_STRONG_QTY, margin_cap)
        return qty, qty, f"{regime}_strong q={quality:.2f} pred={selected_pred:.2f} edge={selected_edge:.2f} margin_cap={margin_cap}"
    if regime in {"trend", "squeeze"} and quality >= get_exploration_min_score():
        qty = min(SMALL_ACCOUNT_MEDIUM_QTY, margin_cap)
        return qty, qty, f"{regime}_medium q={quality:.2f} pred={selected_pred:.2f} edge={selected_edge:.2f} margin_cap={margin_cap}"

    return 1, 1, f"small_{regime} q={quality:.2f}"


def calculate_quantity(
    usable: float,
    risk_per_trade: float,
    sl_bps: int,
    leverage: int,
    signal: Optional[EntrySignal] = None,
) -> int:
    sizing_usable = get_sizing_usable(usable)
    buffered_usable = sizing_usable * LEVERAGE_MARGIN_BUFFER
    exposure_budget = compute_exposure_budget(signal, buffered_usable, leverage)
    risk_amount = buffered_usable * min(risk_per_trade, MAX_RISK_PER_TRADE)
    stop_distance = max(sl_bps / 10000.0, 0.003)
    approx_entry = float(brain.get("last_price") or market_state.get("last_price") or 73000)
    raw_qty = int((risk_amount * leverage * get_volatility_factor()) / max(stop_distance * approx_entry, 1e-9) * 0.92)
    raw_qty = min(raw_qty, int(exposure_budget.get("max_qty", MAX_QTY) or MAX_QTY))

    min_qty, max_qty, reason = get_small_account_quantity_plan(buffered_usable, leverage, signal)
    max_qty = min(max_qty, int(exposure_budget.get("max_qty", max_qty) or max_qty))
    if sizing_usable < SMALL_ACCOUNT_DYNAMIC_SIZING_SATS:
        sized_qty = max(min_qty, max(1, raw_qty))
        final_qty = min(sized_qty, max_qty)
        log(
            f"📌 Small account sizing | usable={usable:.0f} snapped={sizing_usable:.0f} buffered={buffered_usable:.0f} "
            f"raw={raw_qty} floor={min_qty} cap={max_qty} final={final_qty} | "
            f"{reason} | {exposure_budget.get('reason')}"
        )
        qty_mult = float(getattr(signal, "tuned_qty_multiplier", 1.0) or 1.0) if signal else 1.0
        parent_qty_mult = float(getattr(signal, "parent_qty_multiplier", 1.0) or 1.0) if signal else 1.0
        qty_mult *= parent_qty_mult
        if abs(qty_mult - 1.0) > 0.01:
            risk_mode = str(brain.get("risk_mode", "normal") or "normal")
            margin_util = SMALL_ACCOUNT_CAUTION_MARGIN_UTIL if risk_mode == "caution" else SMALL_ACCOUNT_MAX_MARGIN_UTIL
            dynamic_cap = min(MAX_QTY, estimate_margin_capped_qty(buffered_usable, leverage, margin_util), max_qty)
            tuned_qty = int(clamp(round(final_qty * qty_mult), 1, dynamic_cap))
            log(
                f"📌 Allocation sizing | base={final_qty} qtyx={qty_mult:.2f} "
                f"dynamic_cap={dynamic_cap} final={tuned_qty} | "
                f"lane={getattr(signal, 'tuned_allocation_reason', 'n/a')} | "
                f"parent={getattr(signal, 'parent_allocation_reason', 'n/a')}"
            )
            return tuned_qty
        return final_qty

    qty_mult = float(getattr(signal, "tuned_qty_multiplier", 1.0) or 1.0) if signal else 1.0
    parent_qty_mult = float(getattr(signal, "parent_qty_multiplier", 1.0) or 1.0) if signal else 1.0
    qty_mult *= parent_qty_mult
    return max(1, min(int(round(raw_qty * qty_mult)), MAX_QTY, max_qty))


def get_raw_entry_move_bps(position: PositionState, price: float) -> float:
    if not position.entry or position.entry <= 0 or price <= 0:
        return 0.0
    return ((price / float(position.entry)) - 1.0) * 10000.0


def get_structure_trade_identity(direction: str, structure: Optional[dict[str, Any]] = None) -> tuple[str, str]:
    action = str((structure or brain.get("broader_structure") or {}).get("action", "wait") or "wait")
    if action.startswith("mean_revert"):
        return "mean_revert", "mean_revert_reclaim"
    if action.startswith("breakout"):
        return "breakout", "breakout_probe"
    if action.startswith("trend"):
        return "trend_follow", "momentum_follow"
    return "mean_revert", "mean_revert_reclaim"


def build_net_rebalance_entry_probe(direction: str, structure: dict[str, Any], quantity: int) -> EntrySignal:
    intent, policy = get_structure_trade_identity(direction, structure)
    confidence = float(structure.get("confidence", 0.0) or 0.0)
    oracle = get_oracle_regime_insight(str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown"))
    edge = max(confidence - 0.45, float(oracle.get("score", 0.0) or 0.0))
    return EntrySignal(
        action="open",
        direction=direction,
        intent=intent,
        mode="exploit",
        policy=policy,
        confidence=clamp(confidence, 0.0, 0.95),
        quantity=quantity,
        sl_bps=120,
        tp_bps=240,
        trail_bps=60,
        leverage=get_dynamic_leverage(
            edge,
            "good" if confidence >= 0.55 else "supportive",
            str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown"),
            str(brain.get("risk_mode", "normal") or "normal"),
        ),
        max_hold_minutes=45,
        risk_per_trade=float(brain.get("current_risk_per_trade", RISK_PER_TRADE) or RISK_PER_TRADE),
        expected_edge=edge,
        predictive_setup_score=edge,
        reason=f"net rebalance cross | {structure.get('summary', 'n/a')}",
    )


def get_net_rebalance_action(
    position: PositionState,
    thesis: dict[str, Any],
    price: float,
    *,
    allow_cross: bool = False,
) -> Optional[dict[str, Any]]:
    if not position.is_open or not position.side or position.qty <= 0:
        return None
    structure = brain.get("broader_structure") or compute_broader_structure_context(refresh_market_signal_context())
    target_direction = str(structure.get("direction", "neutral") or "neutral")
    if target_direction not in {"long", "short"} or target_direction == position.side:
        return None

    confidence = float(structure.get("confidence", 0.0) or 0.0)
    if confidence < NET_REBALANCE_MIN_STRUCTURE_CONF:
        return None

    close_alignment = compute_close_alignment(position, thesis, price)
    close_align_score = float(close_alignment.get("score", 0.0) or 0.0)
    thesis_score = float(thesis.get("score", 0.0) or 0.0)
    raw_move_bps = get_raw_entry_move_bps(position, price)
    favorable_move_bps = raw_move_bps if position.side == "long" else -raw_move_bps
    adverse_move_bps = max(0.0, -favorable_move_bps)
    clearly_broken, broken_reason = is_clearly_broken_exit(position, thesis, price)
    current_qty = int(max(1, position.qty))

    if allow_cross:
        if not clearly_broken or confidence < NET_REBALANCE_CROSS_MIN_STRUCTURE_CONF:
            return None
        if position.unrealized_pnl(price) > 0:
            return None
        base_qty = max(1.0, float(position.original_qty or position.qty or 1.0))
        target_qty = max(1, int(base_qty * NET_REBALANCE_CROSS_TARGET_FRACTION))
        return {
            "action": "reverse",
            "direction": target_direction,
            "quantity": current_qty + target_qty,
            "target_qty": target_qty,
            "reason": (
                f"DYN_REBALANCE_CROSS target={target_direction} target_qty={target_qty} "
                f"structure={structure.get('action', 'wait')}/{confidence:.2f} "
                f"thesis={thesis_score:+.2f} raw_move={raw_move_bps:+.1f}bps | {broken_reason}"
            ),
            "structure": structure,
        }

    if current_qty <= 1:
        return None
    if thesis_score > 0.0 and raw_move_bps > 0.0:
        return None
    if not (
        thesis_score <= NET_REBALANCE_REDUCE_MAX_THESIS_SCORE
        or adverse_move_bps > NET_REBALANCE_REDUCE_MIN_ADVERSE_BPS
        or (close_align_score < 0.02 and thesis_score <= -0.35 and adverse_move_bps > 18.0)
    ):
        return None
    if close_align_score < NET_REBALANCE_REDUCE_MIN_CLOSE_ALIGN and thesis_score > 0.02 and favorable_move_bps > -4.0:
        return None

    pressure = clamp(
        (confidence - NET_REBALANCE_MIN_STRUCTURE_CONF) / 0.25
        + close_align_score
        + max(0.0, -thesis_score) * 0.6
        + max(0.0, -favorable_move_bps) / 40.0,
        0.20,
        NET_REBALANCE_MAX_REDUCE_FRACTION,
    )
    reduce_qty = max(1, int(current_qty * pressure))
    reduce_qty = min(reduce_qty, current_qty - 1)
    reduce_qty = min(reduce_qty, 1)  # cap to 1 unit per trigger — prevents cascade lock-in
    if reduce_qty < 1:
        return None
    return {
        "action": "reduce",
        "direction": target_direction,
        "quantity": reduce_qty,
        "reason": (
            f"DYN_REBALANCE_REDUCE target={target_direction} qty={reduce_qty} "
            f"structure={structure.get('action', 'wait')}/{confidence:.2f} "
            f"thesis={thesis_score:+.2f} close_align={close_align_score:+.2f} "
            f"fav_move={favorable_move_bps:+.1f}bps"
        ),
        "structure": structure,
    }


def get_add_confidence_floor(thesis: dict[str, Any], favorable_move_bps: float, hold_minutes: float = 0.0) -> float:
    thesis_score = float(thesis.get("score", 0.0) or 0.0)
    fee_ratio = float(thesis.get("fee_ratio", 0.0) or 0.0)
    peak_fee = float(thesis.get("peak_fee_multiple", 0.0) or 0.0)
    if peak_fee >= 0.35 or hold_minutes > 15.0:
        return 0.32
    if str((brain.get("last_strategic_context", {}) or {}).get("mode", "observe") or "observe") == "attack":
        return 0.35
    if str((brain.get("market_regime", {}) or {}).get("regime", "unknown") or "unknown") == "squeeze":
        return 0.38
    if (
        thesis_score >= 0.42
        and favorable_move_bps >= ADD_MOVE_BPS_THRESHOLD * 1.6
        and fee_ratio >= 0.85
        and peak_fee >= 0.85
    ):
        return ADD_STRONG_WINNER_CONFIDENCE_FLOOR
    return ADD_CONFIDENCE_FLOOR


def get_winner_add_min_move_bps(thesis: dict[str, Any], hold_minutes: float = 0.0) -> float:
    peak_fee = float(thesis.get("peak_fee_multiple", 0.0) or 0.0)
    if peak_fee > 0.40 or hold_minutes > 20.0:
        return 3.5
    return 5.0


def scale_action_cooldown_active(position: PositionState) -> bool:
    if not position.last_scale_action_at:
        return False
    last_action = position.last_scale_action_at
    # Normalize tz-aware datetimes to naive local time so subtraction always works.
    # last_scale_action_at is set with datetime.now() (naive), but parse_iso_dt on
    # restart may return tz-aware if the stored string included offset info.
    if last_action.tzinfo is not None:
        last_action = last_action.astimezone().replace(tzinfo=None)
    return (datetime.now() - last_action).total_seconds() < SCALE_ACTION_COOLDOWN_SECONDS


def get_dynamic_position_management_action(
    position: PositionState,
    thesis: dict[str, Any],
    price: float,
) -> Optional[dict[str, Any]]:
    if not position.is_open or price <= 0 or position.pending_close or position.pending_add or position.pending_reduce:
        return None
    if scale_action_cooldown_active(position):
        return None

    thesis_score = float(thesis.get("score", 0.0) or 0.0)
    raw_move_bps = get_raw_entry_move_bps(position, price)
    favorable_move_bps = raw_move_bps if position.side == "long" else -raw_move_bps
    adverse_move_bps = max(0.0, -favorable_move_bps)
    fee_ratio = float(thesis.get("fee_ratio", 0.0) or 0.0)
    peak_fee = float(thesis.get("peak_fee_multiple", 0.0) or 0.0)
    no_progress_penalty = float(thesis.get("no_progress_penalty", 0.0) or 0.0)
    move_stalled = bool(
        position.age_minutes >= SCALE_OUT_STALL_MINUTES
        and favorable_move_bps > 0.0
        and peak_fee >= 0.75
        and no_progress_penalty >= 0.55
    )

    if position.intent == "mean_revert":
        thesis_alignment = float(thesis.get("momentum_turn", 0.0) or 0.0)
    else:
        thesis_alignment = max(
            float(thesis.get("pressure_align", 0.0) or 0.0),
            float(thesis.get("persistence_score", 0.0) or 0.0),
        )

    gross_pnl = position.unrealized_pnl(price)
    fee_floor = max(estimate_round_trip_fee_from_position(position), 1.0)
    close_alignment = compute_close_alignment(position, thesis, price)
    close_align_score = float(close_alignment.get("score", 0.0) or 0.0)
    clearly_broken, broken_reason = is_clearly_broken_exit(position, thesis, price)
    attack_mode = str((brain.get("last_strategic_context", {}) or {}).get("mode", "observe") or "observe") == "attack"
    attack_add_window = bool(attack_mode and thesis_score >= 0.02)
    attack_fee_proven_add = bool(
        attack_mode
        and -0.08 <= thesis_score <= 0.02
        and peak_fee >= 0.40
        and close_align_score > 0.08
    )

    # Recovery ladder: add into a moderate adverse move only while the measured
    # thesis remains intact. This is deliberately small and bounded by max adds,
    # margin caps, strict exit checks, and close-pressure limits.
    recovery_add_ready = bool(
        position.add_count < get_max_add_count(position, thesis)
        and bool(thesis.get("intact", False))
        and not clearly_broken
        and RECOVERY_ADD_MIN_ADVERSE_BPS <= adverse_move_bps <= RECOVERY_ADD_MAX_ADVERSE_BPS
        and thesis_score >= RECOVERY_ADD_MIN_THESIS_SCORE
        and close_align_score <= RECOVERY_ADD_MAX_CLOSE_ALIGN
        and no_progress_penalty < 0.70
    )
    if recovery_add_ready:
        base_qty = float(position.original_qty or position.qty or 0.0)
        add_fraction = max(0.20, 0.34 - position.add_count * 0.07)
        add_qty = max(1, int(base_qty * add_fraction))
        return {
            "action": "add",
            "quantity": add_qty,
            "reason": (
                f"DYN_RECOVERY_ADD thesis={thesis_score:+.2f} raw_move={raw_move_bps:+.1f}bps "
                f"adverse={adverse_move_bps:.1f}bps close_align={close_align_score:+.2f} "
                f"fee_ratio={fee_ratio:+.2f}"
            ),
        }

    if (
        position.add_count < get_max_add_count(position, thesis)
        and bool(thesis.get("intact", False))
        and (
            thesis_score >= 0.02
            or (thesis_score >= 0.00 and peak_fee >= 0.40)
            or (thesis_score >= -0.05 and peak_fee > 0.45 and close_align_score > 0.10)
            or attack_add_window
            or attack_fee_proven_add
        )
        and (
            favorable_move_bps >= get_winner_add_min_move_bps(thesis, position.age_minutes)
            or favorable_move_bps > 4.0
            or close_align_score > 0.12
        )
        and fee_ratio >= WINNER_ADD_MIN_FEE_RATIO
        and thesis_alignment >= -0.05
    ):
        base_qty = float(position.original_qty or position.qty or 0.0)
        if thesis_score >= 0.40 and favorable_move_bps >= ADD_MOVE_BPS_THRESHOLD * 1.4:
            add_fraction = 1.25   # strong proven runner: full add
        elif thesis_score >= 0.20 and favorable_move_bps >= ADD_MOVE_BPS_THRESHOLD:
            add_fraction = 0.75   # decent winner: press harder
        else:
            add_fraction = 0.20   # marginal threshold: minimum add
        add_qty = max(1, int(base_qty * add_fraction))
        return {
            "action": "add",
            "quantity": add_qty,
            "reason": (
                f"DYN_PYRAMID thesis={thesis_score:+.2f} raw_move={raw_move_bps:+.1f}bps "
                f"fee_ratio={fee_ratio:+.2f} align={thesis_alignment:+.2f}"
            ),
        }

    # At qty ≤ 2 the fee on a 1-unit reduce exceeds any lockable profit —
    # skip profit-locking scale-outs. Net-rebalance reduces are in a separate
    # function and intentionally unaffected (they step toward a direction flip).
    if position.qty <= 2:
        return None

    peak_pnl = float(position.max_unrealized_pnl or 0.0)
    peak_giveback = max(0.0, peak_pnl - gross_pnl)
    move_reversed = favorable_move_bps <= 0.0
    weak_thesis_exit = bool(
        clearly_broken
        and thesis_score <= BROKEN_EXIT_THESIS_SCORE
        and (move_stalled or move_reversed)
    )
    peaking_profit_exit = bool(
        peak_fee >= SCALE_OUT_PEAK_FEE_MULTIPLE
        and fee_ratio >= SCALE_OUT_MIN_FEE_RATIO
        and peak_giveback >= fee_floor * SCALE_OUT_GIVEBACK_FRACTION
        and thesis_score < 0.45
    )
    should_scale_out = bool(
        position.scale_out_count < MAX_SCALE_OUT_COUNT
        and position.qty > 1
        and fee_ratio >= SCALE_OUT_MIN_FEE_RATIO
        and (weak_thesis_exit or peaking_profit_exit)
    )
    if should_scale_out:
        scale_fraction = 0.50 if weak_thesis_exit else 0.25
        reduce_qty = max(1, int(float(position.qty) * scale_fraction))
        reduce_qty = min(reduce_qty, max(1, int(float(position.qty)) - 1))
        return {
            "action": "reduce",
            "quantity": reduce_qty,
            "reason": (
                f"DYN_SCALE_OUT thesis={thesis_score:+.2f} raw_move={raw_move_bps:+.1f}bps "
                f"stalled={move_stalled} reversed={move_reversed} peak_giveback={peak_giveback:+.0f} "
                f"close_align={close_align_score:+.2f} fee_ratio={fee_ratio:+.2f} {broken_reason}"
            ),
        }

    rebound_scale_out = bool(
        position.add_count > 0
        and position.scale_out_count < MAX_SCALE_OUT_COUNT
        and position.qty > 1
        and favorable_move_bps >= REBOUND_SCALE_OUT_MIN_MOVE_BPS
        and fee_ratio >= REBOUND_SCALE_OUT_MIN_FEE_RATIO
        and not (thesis_score > 0.0 and raw_move_bps > 0.0)
        and (thesis_score < 0.18 or close_align_score >= 0.08 or peak_fee >= 0.80)
    )
    if rebound_scale_out:
        reduce_qty = max(1, int(float(position.qty) * 0.25))
        reduce_qty = min(reduce_qty, max(1, int(float(position.qty)) - 1))
        return {
            "action": "reduce",
            "quantity": reduce_qty,
            "reason": (
                f"DYN_REBOUND_SCALE_OUT thesis={thesis_score:+.2f} "
                f"fee_ratio={fee_ratio:+.2f} move={favorable_move_bps:+.1f}bps "
                f"adds={position.add_count} close_align={close_align_score:+.2f}"
            ),
        }

    # Phase-4: flag-gated early partial scale-out — takes 1/3 off when fee_ratio is
    # very high but thesis is still intact. Goal: lock in some of the fee-cleared move
    # while letting the runner continue. Defaults OFF; requires offline EV proof.
    if (
        ENABLE_EARLY_PARTIAL_SCALE_OUT
        and position.scale_out_count < MAX_SCALE_OUT_COUNT
        and position.qty > 2
        and bool(thesis.get("intact", False))
        and fee_ratio >= EARLY_PARTIAL_SCALE_OUT_FEE_RATIO
        and favorable_move_bps > 0
        and thesis_score >= 0.20
        and peak_fee >= EARLY_PARTIAL_SCALE_OUT_MIN_PEAK_FEE
    ):
        reduce_qty = max(1, int(float(position.qty) * EARLY_PARTIAL_SCALE_OUT_FRACTION))
        reduce_qty = min(reduce_qty, max(1, int(float(position.qty)) - 2))
        return {
            "action": "reduce",
            "quantity": reduce_qty,
            "reason": (
                f"DYN_EARLY_PARTIAL_SCALE_OUT thesis={thesis_score:+.2f} "
                f"fee_ratio={fee_ratio:+.2f} peak_fee={peak_fee:.2f} move={favorable_move_bps:+.1f}bps"
            ),
        }

    return None


def apply_fee_clear_winner_protection(position: PositionState, thesis: dict[str, Any], price: float) -> Optional[str]:
    if not position.is_open or not position.entry or position.entry <= 0 or price <= 0:
        return None
    if position.pending_close or position.pending_reduce or position.pending_reverse:
        return None

    favorable_move_bps = float(thesis.get("entry_move_bps", 0.0) or 0.0)
    peak_fee = float(thesis.get("peak_fee_multiple", 0.0) or 0.0)
    entry = float(position.entry)

    # Tier 1: breakeven lock — once fee is 70% cleared, trail SL to entry
    if favorable_move_bps > 5.0 and peak_fee >= WINNER_LOCK_BREAKEVEN_PEAK_FEE and peak_fee < WINNER_LOCK_PEAK_FEE_MULTIPLE:
        lock_bps = 2.0
        if position.side == "long":
            new_sl = entry * (1.0 + lock_bps / 10000.0)
            if new_sl >= price * 0.9999:
                return None
            if position.sl_price is not None and new_sl <= float(position.sl_price):
                return None
        else:
            new_sl = entry * (1.0 - lock_bps / 10000.0)
            if new_sl <= price * 1.0001:
                return None
            if position.sl_price is not None and new_sl >= float(position.sl_price):
                return None
        old_sl = position.sl_price
        position.sl_price = new_sl
        return (
            f"breakeven lock | old_sl={old_sl or 0:.1f} new_sl={new_sl:.1f} "
            f"peak_fee={peak_fee:.2f} move={favorable_move_bps:.1f}bps"
        )

    # Tier 2: full profit lock — existing logic for strong winners
    if favorable_move_bps <= WINNER_LOCK_MIN_BPS or peak_fee < WINNER_LOCK_PEAK_FEE_MULTIPLE:
        return None

    retained_bps = favorable_move_bps * WINNER_LOCK_RETAIN_MFE
    lock_bps = WINNER_LOCK_MIN_BPS
    if peak_fee >= WINNER_LOCK_STRONG_PEAK_FEE_MULTIPLE:
        lock_bps = max(lock_bps, retained_bps)
    lock_bps = min(lock_bps, max(WINNER_LOCK_MIN_BPS, favorable_move_bps - 3.0))
    if position.side == "long":
        new_sl = entry * (1.0 + lock_bps / 10000.0)
        if new_sl >= price * 0.9998:
            return None
        if position.sl_price is not None and new_sl <= float(position.sl_price):
            return None
    else:
        new_sl = entry * (1.0 - lock_bps / 10000.0)
        if new_sl <= price * 1.0002:
            return None
        if position.sl_price is not None and new_sl >= float(position.sl_price):
            return None

    old_sl = position.sl_price
    position.sl_price = new_sl
    return (
        f"fee-clear winner lock | old_sl={old_sl or 0:.1f} new_sl={new_sl:.1f} "
        f"lock={lock_bps:.1f}bps move={favorable_move_bps:.1f}bps peak_fee={peak_fee:.2f}"
    )


def deterministic_position_action(position: PositionState, price: float) -> Optional[dict[str, Any]]:
    if not position.is_open or price <= 0:
        return None

    regime = brain.get("market_regime", {}).get("regime", "unknown")
    momentum = float(brain.get("momentum", 0.0) or 0.0)
    gross_pnl = position.unrealized_pnl(price)
    fee_floor = max(estimate_round_trip_fee_from_position(position), 1.0)
    age = position.age_minutes
    entry = float(position.entry or price)
    thesis = get_position_thesis_metrics(position, price)
    close_alignment = compute_close_alignment(position, thesis, price)
    learner_lane_active = bool(position.entry_chop_learner_lane_active)
    close_align_score = float(close_alignment.get("score", 0.0) or 0.0)
    clearly_broken, broken_reason = is_clearly_broken_exit(position, thesis, price)
    setup_quality = max(
        float(position.entry_predictive_setup_score or 0.0),
        float(position.entry_expected_edge or 0.0),
    )

    if position.side == "long":
        thesis_broken = momentum <= -DETERMINISTIC_MOMENTUM_BREAK and price <= entry * (1 - DETERMINISTIC_PRICE_BREAK_PCT)
        opposite_momentum = momentum < -0.0007
    else:
        thesis_broken = momentum >= DETERMINISTIC_MOMENTUM_BREAK and price >= entry * (1 + DETERMINISTIC_PRICE_BREAK_PCT)
        opposite_momentum = momentum > 0.0007

    adverse_move_bps = max(0.0, -float(thesis.get("entry_move_bps", 0.0) or 0.0))
    _broken_exit_adverse = get_broken_exit_adverse_bps(position.side or "")
    _broken_exit_thesis = get_broken_exit_thesis_score()
    hard_thesis_break = bool(
        clearly_broken
        and gross_pnl <= -fee_floor * 2.2
        and adverse_move_bps >= _broken_exit_adverse
        and (thesis_broken or float(thesis.get("score", 0.0) or 0.0) <= _broken_exit_thesis)
    )
    early_decent_setup = bool(
        age < 10.0
        and setup_quality >= 0.20
        and adverse_move_bps < _broken_exit_adverse * 1.2
        and gross_pnl > -fee_floor * 2.8
    )
    measured_thesis_break = bool(
        clearly_broken
        and age >= 4.0
        and close_align_score >= 0.58
        and gross_pnl <= -fee_floor * 1.6
        and (
            thesis_broken
            or float(thesis.get("score", 0.0) or 0.0) <= _broken_exit_thesis
            or (not thesis.get("intact") and adverse_move_bps >= _broken_exit_adverse)
        )
    )
    if (hard_thesis_break or (measured_thesis_break and not early_decent_setup)):
        return {"action": "close", "reason": f"DET_THESIS_BREAK | {broken_reason}"}

    if regime == "chop" and gross_pnl >= fee_floor * 1.4 and age >= 6 and opposite_momentum:
        log(
            f"DET_CHOP_PROFIT_LOCK suppressed: letting winner run | "
            f"gross={gross_pnl:+.0f} fee_floor={fee_floor:.0f}"
        )

    weak_recycle_base_match = (
        regime == "chop"
        and clearly_broken
        and age >= CHOP_WEAK_THESIS_EXIT_MINUTES
        and thesis.get("score", 0.0) <= CHOP_WEAK_THESIS_SCORE
        and abs(thesis.get("fee_ratio", 0.0)) <= CHOP_WEAK_THESIS_FEE_RATIO
        and adverse_move_bps >= BROKEN_EXIT_ADVERSE_MOVE_BPS
        and (
            not learner_lane_active
            or (
                not bool(thesis.get("intact", False))
                and float(close_alignment.get("score", 0.0) or 0.0) >= 0.58
            )
        )
    )
    if weak_recycle_base_match:
        # Don't recycle if price is still near the range edge where the position was entered.
        # Protection zone = entry zone + 0.05 buffer, using the same tuned thresholds as entry gates.
        _sctx = get_signal_context()
        _rpos = float(_sctx.get("range_position", 0.5) or 0.5)
        _range_ok = bool(_sctx.get("range_established", False))
        _long_protect = min(get_range_long_max() + 0.05, 0.45)
        _short_protect = max(get_range_short_min() - 0.05, 0.55)
        _range_edge_protected = _range_ok and (
            (position.side == "long" and _rpos <= _long_protect)
            or (position.side == "short" and _rpos >= _short_protect)
        )
        if position.mode == "explore" and not _range_edge_protected:
            return {
                "action": "close",
                "reason": f"DET_CHOP_WEAK_THESIS_RECYCLE | {broken_reason}",
                "close_alignment": close_alignment,
            }

    stale_recycle_base_match = (
        regime == "chop"
        and clearly_broken
        and age >= max(float(position.max_hold_minutes or CHOP_STALE_EXIT_MINUTES) * 0.70, CHOP_STALE_EXIT_MINUTES)
        and abs(gross_pnl) <= max(fee_floor * 0.90, 5.0)
        and not bool(thesis.get("intact", False))
        and thesis.get("score", 0.0) <= (-0.12 if learner_lane_active else -0.02)
        and thesis.get("fee_ratio", 0.0) <= 0.15
        and float(close_alignment.get("score", 0.0) or 0.0) >= (0.68 if learner_lane_active else 0.60)
    )
    if stale_recycle_base_match:
        if position.mode == "explore":
            return {
                "action": "close",
                "reason": f"DET_CHOP_STALE_RECYCLE | {broken_reason}",
                "close_alignment": close_alignment,
            }

    if regime == "unknown" and clearly_broken and age >= 15 and gross_pnl <= -fee_floor:
        return {"action": "close", "reason": f"DET_UNKNOWN_REGIME_EXIT | {broken_reason}"}

    return None


def compute_market_quality(market: dict, regime: str, transition: dict) -> float:
    momentum = abs(float(brain.get("momentum", 0.0)))
    volatility = max(float(brain.get("market_regime", {}).get("volatility", 0.0008)), 0.00005)
    spread = float(market.get("spread_pct", 0.0))
    imbalance = float(market.get("imbalance", 0.0))
    instability = float(transition.get("instability", 0.0))
    signal_features = get_market_path_features()
    signal_ctx = get_signal_context()

    momentum_score = min(momentum * 800, 1.0)
    imbalance_score = min(abs(imbalance) * 1.5, 1.0)
    spread_penalty = min(spread * 25, 1.0)
    spread_shock_penalty = min(max(float(signal_ctx.get("spread_shock", 1.0)) - 1.0, 0.0) / 2.0, 1.0)
    volatility_penalty = min(volatility * 120, 1.0)
    instability_penalty = min(instability, 1.0)
    momentum_persistence = abs(float(signal_features.get("momentum_persistence", 0.0) or 0.0))
    imbalance_persistence = abs(float(signal_features.get("imbalance_persistence", 0.0) or 0.0))
    path_bonus = min(0.12, momentum_persistence * 0.08 + imbalance_persistence * 0.04)
    mtf_alignment = str(signal_ctx.get("mtf_alignment", "mixed"))
    mtf_bonus = 0.05 if mtf_alignment in {"bullish", "bearish"} else -0.02
    funding_bias = str(signal_ctx.get("funding_bias", "neutral"))
    funding_bonus = 0.04 if funding_bias != "neutral" and regime in {"trend", "squeeze"} else 0.0
    session_bias = str(signal_ctx.get("session_bias", "neutral"))
    session_bonus = 0.05 if session_bias in {"trend", "follow_through"} else -0.05 if session_bias == "chop" else 0.0
    funding_momentum = str(signal_ctx.get("funding_momentum", "stable"))
    if funding_momentum in {"rising", "falling"} and regime in {"trend", "squeeze"}:
        funding_bonus += 0.02
    volatility_state = str(signal_ctx.get("volatility_state", "normal"))
    vol_bonus = 0.06 if volatility_state == "expanded" and regime in {"trend", "squeeze"} else 0.05 if volatility_state == "compressed" and regime == "chop" else 0.0
    external_bias = str(signal_ctx.get("external_bias", "neutral"))
    external_conviction = float(signal_ctx.get("external_conviction", 0.0) or 0.0)
    external_bonus = 0.0
    if regime in {"trend", "squeeze"} and external_bias in {"bullish", "bearish"}:
        external_bonus += min(0.08, external_conviction * 0.10)
    elif regime == "chop" and external_bias != "neutral":
        external_bonus -= min(0.05, external_conviction * 0.07)

    regime_bonus = 0.0
    if regime == "trend":
        regime_bonus = 0.15
    elif regime == "squeeze":
        regime_bonus = 0.08
    elif regime == "chop":
        regime_bonus = -0.10
    elif regime == "volatile":
        regime_bonus = -0.15
    elif regime == "unknown":
        regime_bonus = -0.05

    score = (
        0.40 * momentum_score
        + 0.25 * imbalance_score
        + 0.20 * (1 - spread_penalty)
        + 0.15 * (1 - volatility_penalty)
        - 0.60 * instability_penalty
        - 0.12 * spread_shock_penalty
        + path_bonus
        + mtf_bonus
        + funding_bonus
        + session_bonus
        + vol_bonus
        + external_bonus
        + regime_bonus
    )
    score = max(0.15, min(0.95, score))
    brain["last_market_quality_components"] = {
        "momentum": momentum_score,
        "imbalance": imbalance_score,
        "momentum_persistence": momentum_persistence,
        "imbalance_persistence": imbalance_persistence,
        "spread_penalty": spread_penalty,
        "spread_shock_penalty": spread_shock_penalty,
        "volatility_penalty": volatility_penalty,
        "instability": instability_penalty,
        "mtf_alignment": mtf_alignment,
        "funding_bias": funding_bias,
        "session_bias": session_bias,
        "volatility_state": volatility_state,
        "external_bias": external_bias,
        "external_conviction": external_conviction,
        "regime": regime,
        "raw_score": score,
    }
    return score


def get_open_position_aggression_override(position: Optional["PositionState"], thesis: Optional[dict[str, Any]] = None) -> bool:
    if position is None or not getattr(position, "is_open", False):
        return False
    regime = str((brain.get("market_regime", {}) or {}).get("regime", "unknown") or "unknown")
    if regime != "squeeze":
        return False
    metrics = thesis or get_position_thesis_metrics(position)
    signal_ctx = get_signal_context()
    level_edge = bool(
        (position.side == "long" and (signal_ctx.get("at_support", False) or signal_ctx.get("sweep_reclaim_long", False)))
        or (position.side == "short" and (signal_ctx.get("at_resistance", False) or signal_ctx.get("sweep_reclaim_short", False)))
    )
    return bool(
        metrics.get("intact")
        and float(metrics.get("predictive_align", 0.0) or 0.0) > 0.10
        and float(metrics.get("quality_delta", 0.0) or 0.0) >= 0.0
        and float(metrics.get("peak_fee_multiple", 0.0) or 0.0) >= 0.10
        and level_edge
    )


def get_position_thesis_metrics(position: PositionState, price: Optional[float] = None) -> dict[str, Any]:
    if not position.is_open or not position.entry or position.entry <= 0:
        return {
            "score": 0.0,
            "entry_move_bps": 0.0,
            "mfe_bps": 0.0,
            "mae_bps": 0.0,
            "entry_quality": 0.0,
            "quality_now": 0.0,
            "quality_delta": 0.0,
            "fee_ratio": 0.0,
            "pressure_align": 0.0,
            "imbalance_align": 0.0,
            "momentum_turn": 0.0,
            "imbalance_turn": 0.0,
            "momentum_persistence": 0.0,
            "imbalance_persistence": 0.0,
            "persistence_score": 0.0,
            "peak_fee_multiple": 0.0,
            "fee_clear_progress": 0.0,
            "predictive_align": 0.0,
            "predictive_break_align": 0.0,
            "predictive_bias": "neutral",
            "predictive_summary": "n/a",
            "time_to_mfe_minutes": None,
            "time_to_mae_minutes": None,
            "no_progress_penalty": 0.0,
            "add_ready": False,
            "intact": False,
        }

    if price is None:
        price = float(brain.get("last_price") or position.entry or 0.0)
    if price <= 0:
        price = float(position.entry)

    market = brain.get("market_context", {})
    regime = brain.get("market_regime", {}).get("regime", "unknown")
    transition = brain.get("regime_transition", {})
    quality_now = compute_market_quality(market, regime, transition)
    entry_quality = float(position.entry_market_quality or 0.0)
    momentum = float(brain.get("momentum", 0.0) or 0.0)
    imbalance = float(market.get("imbalance", 0.0) or 0.0)
    signal_features = get_market_path_features()
    momentum_delta = float(signal_features.get("momentum_delta", 0.0) or 0.0)
    imbalance_delta = float(signal_features.get("imbalance_delta", 0.0) or 0.0)
    momentum_persistence = float(signal_features.get("momentum_persistence", 0.0) or 0.0)
    imbalance_persistence = float(signal_features.get("imbalance_persistence", 0.0) or 0.0)
    signal_ctx = get_signal_context()
    fee_floor = max(estimate_round_trip_fee_from_position(position), 1.0)
    pnl = position.unrealized_pnl(price)
    side_sign = 1.0 if position.side == "long" else -1.0
    pressure_align = clamp(side_sign * momentum * 1800.0, -1.0, 1.0)
    imbalance_align_now = clamp(side_sign * imbalance * 5.0, -1.0, 1.0)
    momentum_turn = clamp(side_sign * momentum_delta / 0.00022, -1.0, 1.0)
    imbalance_turn = clamp(side_sign * imbalance_delta / 0.05, -1.0, 1.0)
    persistence_align = clamp(side_sign * momentum_persistence, -1.0, 1.0)
    imbalance_persistence_align = clamp(side_sign * imbalance_persistence, -1.0, 1.0)
    predictive_align = clamp(side_sign * float(signal_ctx.get("predictive_horizon_score", 0.0) or 0.0), -1.0, 1.0)
    predictive_break_prob = (
        float(signal_ctx.get("predictive_upside_break_prob", 0.5) or 0.5)
        if position.side == "long"
        else float(signal_ctx.get("predictive_downside_break_prob", 0.5) or 0.5)
    )
    predictive_break_align = clamp((predictive_break_prob - 0.50) / 0.30, -1.0, 1.0)

    if position.side == "long":
        entry_move_bps = ((price / position.entry) - 1.0) * 10000.0
        best_price = float(position.best_price or position.entry)
        worst_price = float(position.worst_price or position.entry)
        mfe_bps = max(0.0, ((best_price / position.entry) - 1.0) * 10000.0)
        mae_bps = max(0.0, (1.0 - (worst_price / position.entry)) * 10000.0)
    else:
        entry_move_bps = ((position.entry / price) - 1.0) * 10000.0
        best_price = float(position.best_price or position.entry)
        worst_price = float(position.worst_price or position.entry)
        mfe_bps = max(0.0, ((position.entry / best_price) - 1.0) * 10000.0)
        mae_bps = max(0.0, ((worst_price / position.entry) - 1.0) * 10000.0)

    quality_delta = quality_now - entry_quality
    fee_ratio = pnl / fee_floor
    peak_fee_multiple = float(position.max_unrealized_pnl or 0.0) / fee_floor
    fee_clear_progress = clamp(peak_fee_multiple / 1.4, -1.0, 1.0)
    age_minutes = max(position.age_minutes, 0.01)
    time_to_mfe = float(position.time_to_mfe_minutes or 0.0)
    time_to_mae = float(position.time_to_mae_minutes or 0.0)
    no_progress_penalty = clamp((age_minutes - max(time_to_mfe, 0.0) - 2.0) / 12.0, 0.0, 1.0) if mfe_bps < 0.35 * mae_bps + 4.0 else 0.0
    timing_edge = 0.0
    if time_to_mfe > 0:
        timing_edge += clamp((12.0 - time_to_mfe) / 12.0, -0.4, 0.4)
    if time_to_mae > 0:
        timing_edge -= clamp((8.0 - time_to_mae) / 8.0, 0.0, 0.4)

    intent = position.intent
    if intent == "mean_revert":
        directional_align = momentum_turn * 0.60 + imbalance_turn * 0.40
        persistence_score = (-persistence_align) * 0.55 + (-imbalance_persistence_align) * 0.45
    else:
        directional_align = pressure_align * 0.55 + imbalance_align_now * 0.45
        persistence_score = persistence_align * 0.55 + imbalance_persistence_align * 0.45

    score = (
        clamp(entry_move_bps / 30.0, -1.0, 1.0) * 0.30
        + clamp(mfe_bps / 40.0, 0.0, 1.0) * 0.20
        - clamp(mae_bps / 35.0, 0.0, 1.0) * 0.25
        + clamp(fee_ratio / 1.5, -1.0, 1.0) * 0.15
        + pressure_align * 0.10
    )
    score = clamp(score, -1.0, 1.0)
    intact = bool(
        score > -0.10
        and mae_bps < 0.85 * max(48.0, abs(entry_move_bps) + 12.0)
        and no_progress_penalty < 0.85
    )
    profitable_winner = bool(
        entry_move_bps >= ADD_MOVE_BPS_THRESHOLD * 1.4
        and fee_ratio >= 0.75
        and peak_fee_multiple >= 0.75
    )
    add_ready = bool(
        score >= (0.28 if profitable_winner else 0.32)
        and fee_ratio >= (0.25 if profitable_winner else 0.30)
        and quality_now >= max(0.18, entry_quality - (0.08 if profitable_winner else 0.02))
        and directional_align >= (-0.05 if profitable_winner else 0.10)
        and persistence_score >= (-0.35 if profitable_winner else -0.15)
        and peak_fee_multiple >= (0.45 if profitable_winner else 0.55)
        and position.age_minutes >= 2.0
    )
    if (
        not add_ready
        and regime == "squeeze"
        and intact
        and score >= 0.04
        and fee_ratio >= 0.10
        and peak_fee_multiple >= 0.10
        and predictive_align >= 0.10
        and (directional_align >= 0.05 or persistence_score >= 0.05)
        and position.age_minutes >= 1.0
    ):
        add_ready = True
    if get_open_position_aggression_override(
        position,
        {
            "intact": intact,
            "predictive_align": predictive_align,
            "quality_delta": quality_delta,
            "peak_fee_multiple": peak_fee_multiple,
        },
    ):
        add_ready = bool(
            score >= 0.02
            and fee_ratio >= 0.08
            and peak_fee_multiple >= 0.10
            and position.age_minutes >= 1.0
        )
    return {
        "score": round(score, 3),
        "entry_move_bps": round(entry_move_bps, 2),
        "mfe_bps": round(mfe_bps, 2),
        "mae_bps": round(mae_bps, 2),
        "entry_quality": round(entry_quality, 3),
        "quality_now": round(quality_now, 3),
        "quality_delta": round(quality_delta, 3),
        "fee_ratio": round(fee_ratio, 3),
        "pressure_align": round(pressure_align, 3),
        "imbalance_align": round(imbalance_align_now, 3),
        "momentum_turn": round(momentum_turn, 3),
        "imbalance_turn": round(imbalance_turn, 3),
        "momentum_persistence": round(momentum_persistence, 3),
        "imbalance_persistence": round(imbalance_persistence, 3),
        "persistence_score": round(persistence_score, 3),
        "peak_fee_multiple": round(peak_fee_multiple, 3),
        "fee_clear_progress": round(fee_clear_progress, 3),
        "predictive_align": round(predictive_align, 3),
        "predictive_break_align": round(predictive_break_align, 3),
        "predictive_bias": str(signal_ctx.get("predictive_next_15_60_bias", "neutral")),
        "predictive_summary": str(signal_ctx.get("predictive_summary", "n/a")),
        "time_to_mfe_minutes": None if position.time_to_mfe_minutes is None else round(float(position.time_to_mfe_minutes), 2),
        "time_to_mae_minutes": None if position.time_to_mae_minutes is None else round(float(position.time_to_mae_minutes), 2),
        "no_progress_penalty": round(no_progress_penalty, 3),
        "add_ready": add_ready,
        "intact": intact,
    }


def format_thesis_reason(thesis: dict[str, Any], pnl: float) -> str:
    if not thesis.get("intact"):
        return (
            f"Measured thesis weak | score={thesis.get('score', 0.0):+.2f} "
            f"move={thesis.get('entry_move_bps', 0.0):+.1f}bps fee_ratio={thesis.get('fee_ratio', 0.0):+.2f}"
        )[:240]
    if thesis.get("add_ready"):
        return (
            f"Measured thesis improving | score={thesis.get('score', 0.0):+.2f} "
            f"mfe={thesis.get('mfe_bps', 0.0):.1f}bps fee_ratio={thesis.get('fee_ratio', 0.0):+.2f}"
        )[:240]
    if thesis.get("intact"):
        return (
            f"Measured thesis intact; waiting for add trigger, not exit | "
            f"score={thesis.get('score', 0.0):+.2f} pnl={pnl:+.0f} "
            f"fee_ratio={thesis.get('fee_ratio', 0.0):+.2f} peak_fee={thesis.get('peak_fee_multiple', 0.0):+.2f}"
        )[:240]
    return (
        f"Measured thesis intact but not improved enough to add | "
        f"score={thesis.get('score', 0.0):+.2f} pnl={pnl:+.0f} "
        f"fee_ratio={thesis.get('fee_ratio', 0.0):+.2f} peak_fee={thesis.get('peak_fee_multiple', 0.0):+.2f}"
    )[:240]


def align_review_with_thesis(
    review: dict[str, Any],
    position: PositionState,
    thesis: dict[str, Any],
    pnl: float,
) -> dict[str, Any]:
    action = review.get("action", "hold")
    price = float(brain.get("last_price") or position.entry or 0.0)
    close_gate, thesis_score, move_bps = ai_review_close_gate(position, thesis, price)

    if thesis_score > 0.20 and move_bps > 15.0 and action not in {"hold", "add"}:
        review["action"] = "hold"
        review["direction"] = ""
        review["quantity"] = None
        review["reason"] = (
            f"AI review suppressed: winning thesis still intact "
            f"(score={thesis_score:+.2f}, move={move_bps:+.1f}bps)"
        )
        return review

    if action == "reverse":
        review["action"] = "hold"
        review["direction"] = ""
        review["quantity"] = None
        review["reason"] = (
            "Reverse suppressed: AI review cannot flip an open position"
        )
        return review

    raw_move_bps = get_raw_entry_move_bps(position, price)
    favorable_move_bps = raw_move_bps if position.side == "long" else -raw_move_bps
    adverse_move_bps = max(0.0, -favorable_move_bps)
    close_alignment = compute_close_alignment(position, thesis, price)
    close_align_score = float(close_alignment.get("score", 0.0) or 0.0)
    ai_recovery_add_ok = bool(
        action == "add"
        and bool(thesis.get("intact", False))
        and RECOVERY_ADD_MIN_ADVERSE_BPS <= adverse_move_bps <= RECOVERY_ADD_MAX_ADVERSE_BPS
        and thesis_score >= RECOVERY_ADD_MIN_THESIS_SCORE
        and close_align_score <= RECOVERY_ADD_MAX_CLOSE_ALIGN
    )
    if action == "add" and not thesis.get("add_ready") and not ai_recovery_add_ok:
        review["action"] = "hold"
        review["direction"] = ""
        review["quantity"] = None
        review["reason"] = "Add suppressed: neither winner-add nor recovery-ladder metrics are ready"
        return review

    if action == "reduce":
        requested_qty = float(review.get("quantity") or 0.0)
        current_qty = float(position.qty or 0.0)
        requested_reduce = current_qty > 0 and requested_qty > 0.0
        if requested_reduce and not close_gate:
            review["action"] = "hold"
            review["direction"] = ""
            review["quantity"] = None
            review["reason"] = (
                f"Reduce suppressed: {format_strict_exit_requirement()}"
            )
            return review

    if action == "close":
        if not close_gate:
            review["action"] = "hold"
            review["direction"] = ""
            review["quantity"] = None
            review["reason"] = (
                f"Close suppressed: thesis={thesis_score:+.2f}, raw_move={move_bps:+.1f}bps; "
                f"{format_strict_exit_requirement()}"
            )
            return review
        estimated_fee = max(estimate_round_trip_fee_from_position(position), 1.0)
        hard_broken = (
            pnl <= -estimated_fee * 2.0
            and not bool(thesis.get("intact", False))
        )
        if not hard_broken or should_block_fee_dominated_ai_close(position, pnl):
            review["action"] = "hold"
            review["direction"] = ""
            review["quantity"] = None
            review["reason"] = (
                "Close suppressed: close gate passed, but existing thesis/fee guard did not"
            )
            return review

    if action == "hold":
        review["reason"] = format_thesis_reason(thesis, pnl)

    return review


def should_close_on_max_hold(position: PositionState, thesis: dict[str, Any], price: float) -> tuple[bool, str]:
    gross_pnl = position.unrealized_pnl(price)
    thesis_score = float(thesis.get("score", 0.0) or 0.0)
    move_bps = float(thesis.get("entry_move_bps", 0.0) or 0.0)
    fee_floor = max(estimate_round_trip_fee_from_position(position), 1.0)
    close_alignment = compute_close_alignment(position, thesis, price)
    close_align_score = float(close_alignment.get("score", 0.0) or 0.0)
    clearly_broken, broken_reason = is_clearly_broken_exit(position, thesis, price)

    # Max-hold is a review point, not an automatic churn trigger.
    if (
        clearly_broken
        and gross_pnl <= -fee_floor * 2.0
        and not thesis.get("intact")
        and close_align_score >= 0.70
    ):
        return True, "MAX_HOLD_EXPIRED_BROKEN_THESIS"

    # Trade still profitable or thesis still positive — extend and hold
    position.max_hold_minutes = min(float(position.age_minutes + 10.0), 240.0)
    persist_open_position_plan(position)
    maybe_save_memory(force=True)
    log(
        f"MAX_HOLD deferred | thesis={thesis_score:+.2f} "
        f"gross={gross_pnl:+.0f} move={move_bps:+.1f}bps close_align={close_align_score:+.2f} "
        f"broken={clearly_broken} {broken_reason} "
        f"next={position.max_hold_minutes:.1f}m"
    )
    return False, "MAX_HOLD_DEFERRED"


def refresh_position_thesis(position: PositionState, price: Optional[float] = None) -> dict[str, Any]:
    if not position.is_open or not position.entry:
        return get_position_thesis_metrics(position, price)

    if price is None:
        price = float(brain.get("last_price") or position.entry or 0.0)
    if price <= 0:
        price = float(position.entry)

    if position.best_price is None:
        position.best_price = position.entry
    if position.worst_price is None:
        position.worst_price = position.entry

    if position.trailing_min_since_open <= 0:
        position.trailing_min_since_open = float(position.entry)
    if position.trailing_max_since_min <= 0:
        position.trailing_max_since_min = float(position.entry)
    if position.trailing_max_since_open <= 0:
        position.trailing_max_since_open = float(position.entry)
    if position.trailing_min_since_max <= 0:
        position.trailing_min_since_max = float(position.entry)
    if float(price) < position.trailing_min_since_open:
        position.trailing_min_since_open = float(price)
        position.trailing_max_since_min = float(price)
    else:
        position.trailing_max_since_min = max(position.trailing_max_since_min, float(price))
    if float(price) > position.trailing_max_since_open:
        position.trailing_max_since_open = float(price)
        position.trailing_min_since_max = float(price)
    else:
        position.trailing_min_since_max = min(position.trailing_min_since_max, float(price))

    if position.side == "long":
        if float(price) > float(position.best_price):
            position.best_price = float(price)
            position.time_to_mfe_minutes = round(position.age_minutes, 3)
        if float(price) < float(position.worst_price):
            position.worst_price = float(price)
            position.time_to_mae_minutes = round(position.age_minutes, 3)
    else:
        if float(price) < float(position.best_price):
            position.best_price = float(price)
            position.time_to_mfe_minutes = round(position.age_minutes, 3)
        if float(price) > float(position.worst_price):
            position.worst_price = float(price)
            position.time_to_mae_minutes = round(position.age_minutes, 3)

    pnl = position.unrealized_pnl(price)
    position.max_unrealized_pnl = max(float(position.max_unrealized_pnl), pnl)
    position.min_unrealized_pnl = min(float(position.min_unrealized_pnl), pnl)

    metrics = get_position_thesis_metrics(position, price)
    position.last_thesis_score = float(metrics["score"])
    position.last_add_ready = bool(metrics["add_ready"])
    maybe_emit_thesis_trajectory(position, metrics, price)
    maybe_emit_stuck_position_report(position, metrics, price)
    return metrics


def update_daily_pnl():
    global _last_daily_update
    if time.time() - _last_daily_update < 30:
        return
    _last_daily_update = time.time()

    today = datetime.now().date().isoformat()
    if brain.get("daily_start_time") != today:
        brain["daily_start_time"] = today
        brain["daily_pnl"] = 0.0

    total = 0.0
    fresh = []
    for item in brain.get("daily_realized", []):
        if item.get("date") != today:
            continue
        fresh.append(item)
        total += float(item.get("net_pnl", item.get("pnl", 0.0)) or 0.0)

    brain["daily_realized"] = fresh[-500:]
    brain["daily_pnl"] = total


def check_drawdown_protection() -> tuple[bool, str]:
    update_daily_pnl()

    daily_risk_pnl = get_daily_risk_pnl()
    if daily_risk_pnl < -MAX_DAILY_LOSS_SATS:
        brain["cooldown_until"] = time.time() + COOLDOWN_AFTER_BIG_LOSS_MIN * 60
        log(f"Daily risk loss limit hit: {daily_risk_pnl:.0f}")
        return False, "Daily loss limit hit"

    total_pnl = get_total_risk_pnl()
    total_margin = float(brain.get("last_margin", {}).get("total_margin", 50000))
    if total_pnl < 0:
        drawdown_pct = abs(total_pnl) / max(total_margin, 50000)
        if drawdown_pct > MAX_SESSION_DRAWDOWN_PCT:
            brain["cooldown_until"] = time.time() + 4 * 3600
            log(f"Session risk drawdown exceeded: {drawdown_pct:.1%}")
            return False, "Session drawdown exceeded"

    if brain.get("cooldown_until", 0) > time.time():
        remaining = int((brain["cooldown_until"] - time.time()) / 60)
        return False, f"Cooldown active ({remaining}m)"

    return True, ""


def risk_gate(signal: EntrySignal, usable: float) -> tuple[bool, str]:
    if usable < 1000:
        return False, "Insufficient margin"

    if brain.get("cooldown_until", 0) > time.time():
        return False, "Cooldown active"

    if signal.leverage > MAX_LEVERAGE:
        original_leverage = int(signal.leverage or DEFAULT_LEVERAGE)
        signal.leverage = MAX_LEVERAGE
        log(f"⚡ Risk gate leverage clamp | {original_leverage}->{signal.leverage}")

    counts = get_recent_trade_counts()
    hourly_trade_limit = get_dynamic_hourly_trade_limit(signal)
    if signal.mode != "explore":
        action = str(getattr(signal, "action", "") or "")
        if action == "add" and counts["add"] >= hourly_trade_limit:
            return False, "Hourly add limit reached"
        if action == "open" and str(getattr(signal, "mode", "") or "") == "exploit" and counts["attack_open"] >= hourly_trade_limit:
            return False, "Hourly attack-entry limit reached"
        if action == "open" and counts["open"] >= hourly_trade_limit:
            return False, "Hourly entry limit reached"

    effective_losses = get_effective_consecutive_losses()
    gate_state = dict(getattr(signal, "entry_gate_state_snapshot", None) or brain.get("last_entry_gate_state", {}) or {})
    align_score = float((gate_state.get("chop_alignment") or {}).get("score", 0.0) or 0.0)
    setup_edge = max(
        float(getattr(signal, "predictive_setup_score", 0.0) or 0.0),
        float(getattr(signal, "expected_edge", 0.0) or 0.0),
    )
    add_winner_override = bool(getattr(signal, "add_winner_override", False))
    high_align_override = bool(
        str(brain.get("risk_mode", "normal") or "normal") == "caution"
        and (setup_edge > 0.55 or align_score > 0.65)
    )
    if (
        signal.mode == "exploit"
        and effective_losses >= MAX_CONSECUTIVE_LOSSES
        and not high_align_override
        and not add_winner_override
    ):
        return False, (
            f"Consecutive loss guard active | raw={get_consecutive_losses()} "
            f"effective={effective_losses} flat={get_flat_duration_minutes():.1f}m"
        )

    market = brain.get("market_context", {})
    regime = brain.get("market_regime", {}).get("regime", "unknown")
    transition = brain.get("regime_transition", {})

    quality = compute_market_quality(market, regime, transition)
    brain["market_quality_score"] = quality

    if signal.mode == "exploit" and quality < get_quality_floor():
        log(f"🚫 BLOCK EXPLOIT | quality={quality:.2f}")
        return False, f"Poor market quality ({quality:.2f})"

    if signal.mode == "explore" and quality < 0.15:
        log(f"🚫 BLOCK EXPLORE | quality={quality:.2f}")
        return False, f"Exploration extremely low quality ({quality:.2f})"

    win_rate = get_risk_relevant_win_rate(limit=30)

    risk_hist = brain.setdefault("risk_history", [])
    recent_risk_perf = risk_hist[-50:]
    avg_risk_return = (
        sum(item.get("pnl", 0.0) for item in recent_risk_perf) / len(recent_risk_perf)
        if recent_risk_perf else 0.0
    )

    # === RISK MULTIPLIER CALCULATION ===
    risk_multiplier = 1.0

    # Softer regime penalty when trying to add to an existing position
    is_adding = (signal.action == "add") or (signal.mode == "add") or brain.get("position", {}).get("is_open", False)

    if win_rate > 0.55:
        risk_multiplier *= 1.15
    elif win_rate < 0.45:
        risk_multiplier *= 0.75

    if avg_risk_return > 0:
        risk_multiplier *= 1.10
    elif avg_risk_return < 0:
        risk_multiplier *= 0.85

    if quality > 0.75:
        risk_multiplier *= 1.20
    elif quality < 0.50:
        risk_multiplier *= 0.80

    regime_vol = float(brain.get("market_regime", {}).get("volatility", 0.0))
    if regime_vol > 0.003:
        risk_multiplier *= 0.70

    if regime == "trend":
        risk_multiplier *= 1.10
    elif regime == "chop":
        risk_multiplier *= 0.85 if is_adding else 0.70
    elif regime == "volatile":
        risk_multiplier *= 0.75 if is_adding else 0.65
    elif regime == "squeeze":
        risk_multiplier *= 0.90

    if signal.mode == "explore":
        risk_multiplier *= 0.75

    base_risk = float(getattr(signal, "base_risk_per_trade", signal.risk_per_trade) or RISK_PER_TRADE)
    effective_risk = base_risk * risk_multiplier

    if signal.mode == "exploit":
        effective_risk = min(effective_risk, MAX_RISK_PER_TRADE)
    else:
        effective_risk = min(effective_risk, MAX_RISK_PER_TRADE * 0.85)

    effective_risk = max(0.0015, effective_risk)

    signal.effective_risk_per_trade = effective_risk
    signal.risk_per_trade = effective_risk

    risk_hist.append(
        {
            "time": datetime.now().isoformat(),
            "base_risk": round(base_risk, 5),
            "effective_risk": round(effective_risk, 5),
            "mult": round(risk_multiplier, 4),
            "quality": round(quality, 4),
            "win_rate": round(win_rate, 4),
            "approved": True,
            "pnl": 0.0,
            "mode": signal.mode,
            "policy": signal.policy,
            "regime": regime,
        }
    )
    brain["risk_history"] = risk_hist[-500:]
    brain["current_risk_multiplier"] = risk_multiplier

    log(
        f"✅ RISK GATE PASS | mode={signal.mode} policy={signal.policy} "
        f"rm={risk_multiplier:.2f} q={quality:.2f} risk={effective_risk:.4f}"
    )

    return True, f"OK | rm={risk_multiplier:.2f} | q={quality:.2f} | risk={effective_risk:.4f}"


def get_performance_stats() -> dict[str, Any]:
    filtered_realized = get_risk_relevant_realized(limit=80)
    filtered_pnls = [float(item.get("net_pnl", 0.0) or 0.0) for item in filtered_realized]
    trades = len(filtered_pnls)
    wins = sum(1 for pnl in filtered_pnls if pnl > 0)
    win_rate = (wins / trades * 100) if trades else 50.0
    recent_win_rate = (sum(1 for pnl in filtered_pnls if pnl > 0) / len(filtered_pnls) * 100) if filtered_pnls else win_rate
    return {
        "total_trades": trades,
        "wins": wins,
        "win_rate": round(win_rate, 1),
        "recent_win_rate": round(recent_win_rate, 1),
        "streak": get_risk_streak(),
        "total_pnl": round(get_total_risk_pnl(), 1),
        "recent_pnls": ", ".join(f"{p:.0f}" for p in filtered_pnls[-12:]),
    }


def get_position_plan_summary(position: PositionState) -> str:
    if not position.is_open:
        return "No active thesis."
    thesis = get_position_thesis_metrics(position)
    return (
        f"Intent={position.intent} | Mode={position.mode} | Policy={position.policy} | "
        f"Conf={position.confidence:.2f} | ThesisScore={thesis['score']:+.2f} | "
        f"AddReady={thesis['add_ready']} | PeakFee={thesis.get('peak_fee_multiple', 0.0):+.2f} | "
        f"TtMFE={thesis.get('time_to_mfe_minutes', 0.0) or 0.0:.1f}m | Reason={position.last_reason or 'N/A'}"
    )


def get_historical_summary() -> str:
    if brain.get("learning_epoch") == LEARNING_EPOCH and not brain.get("historical_stats"):
        return f"No in-epoch historical data yet. Epoch={LEARNING_EPOCH}"
    hist = brain.get("historical_stats", {})
    if not hist:
        return "No historical data yet."
    intent_lines = []
    for key, values in list(brain.get("intent_stats", {}).items())[:4]:
        trades = values.get("trades", 0)
        wins = values.get("wins", 0)
        wr = (wins / trades * 100) if trades else 0
        intent_lines.append(f"{key}:{wr:.0f}%")
    return (
        f"Hist: {hist.get('trades', 0)} trades | WR={hist.get('win_rate', 0):.1f}% | "
        f"Avg={hist.get('avg_pnl', 0):.1f} | Intent: {' | '.join(intent_lines)}"
    )


def get_intent_bias_summary() -> str:
    lines = []
    for intent, stats in brain.get("intent_stats", {}).items():
        trades = stats.get("trades", 0)
        if not trades:
            continue
        wr = stats.get("wins", 0) / trades * 100
        lines.append(f"{intent}: WR={wr:.0f}% | T={trades} | PnL={stats.get('pnl', 0):+.0f}")
    return "\n".join(lines) if lines else "No intent data yet."


def get_last_exit_summary() -> str:
    last_exit = brain.get("last_exit", {})
    if not last_exit:
        return "No previous exits yet."
    return (
        f"Last: {last_exit.get('exit_reason', '?')} | {last_exit.get('side', '?')} | "
        f"PnL={last_exit.get('realized_pnl', 0):+.0f} | Hold={last_exit.get('hold_time_minutes', 0):.1f}m | "
        f"Intent={last_exit.get('intent', '?')} | Conf={last_exit.get('confidence', 0):.2f}"
    )


def get_leaderboard_summary() -> str:
    lb = brain.get("leaderboard", {})
    if not lb:
        return "No leaderboard data."
    return (
        f"Top={lb.get('top_daily_pnl', 0):+.0f} | You={lb.get('your_pnl', 0):+.0f} | "
        f"Gap={lb.get('gap_to_top', 0):+.0f} | Pos={lb.get('relative_strength', '?')} | "
        f"Sentiment={lb.get('market_sentiment', 'neutral')}"
    )


def _build_regime_verdict(regime: str, bias: str, mtf: str, signal_ctx: dict, flat_minutes: float) -> str:
    pa = str(brain.get("price_action_summary", "neutral"))
    vol_state = str(signal_ctx.get("volatility_state", "normal") or "normal")
    relief = get_directional_flat_relief(regime, signal_ctx)

    if regime in {"squeeze", "trend"} and bias in {"bullish", "bearish"}:
        direction = "LONG" if bias == "bullish" else "SHORT"
        mtf_str = f"MTF {mtf}" if mtf != "mixed" else "MTF mixed"
        urgency = ""
        if flat_minutes >= 240:
            urgency = f" ⚠️ FLAT {flat_minutes:.0f}m — thresholds relaxed by {relief:.3f}"
        elif flat_minutes >= 120:
            urgency = f" (flat {flat_minutes:.0f}m, relief={relief:.3f})"
        return (
            f"⚡ DIRECTIONAL SETUP: {bias} {regime} | pa={pa} | {mtf_str} | "
            f"Suggested direction: {direction}{urgency}\n"
            f"NOTE: Do NOT describe this as choppy. This is a {bias} {regime} regime. "
            f"Low quality score reflects slow session, not range-bound conditions. "
            f"In squeeze, do not use trend_follow unless range is established and replay_mtf >= 0.50."
        )
    elif regime == "chop" or (regime in {"squeeze", "trend"} and bias == "neutral"):
        return (
            f"📊 RANGE/NEUTRAL: {regime} | bias={bias} | pa={pa} | MTF={mtf}\n"
            f"This IS a low-directional-conviction environment. Range-edge entries only if at level."
        )
    elif regime == "volatile":
        return f"⚠️ VOLATILE REGIME: extreme caution, reduced size only."
    return f"❓ REGIME UNCLEAR: {regime} | bias={bias} — wait for cleaner signal."


def get_common_prompt_context() -> str:
    imbalance_hist = [float(x) for x in list(brain.get("imbalance_history", []))[-12:] if isinstance(x, (int, float))]
    avg_imbalance = sum(imbalance_hist) / len(imbalance_hist) if imbalance_hist else 0.0
    imbalance_trend = "bullish" if avg_imbalance > 0.12 else "bearish" if avg_imbalance < -0.12 else "neutral"

    signal_ctx = get_signal_context()
    funding_trend = str(signal_ctx.get("funding_momentum", "stable"))
    spread_shock = float(signal_ctx.get("spread_shock", 1.0) or 1.0)
    session_bucket = str(signal_ctx.get("session_bucket", "offhours"))
    session_bias = str(signal_ctx.get("session_bias", "neutral"))
    volatility_state = str(signal_ctx.get("volatility_state", "normal"))
    volatility_expansion = float(signal_ctx.get("volatility_expansion", 1.0) or 1.0)
    mtf_alignment = str(signal_ctx.get("mtf_alignment", "mixed"))
    broader_structure = brain.get("broader_structure") or compute_broader_structure_context(signal_ctx)
    strategic_posture = get_strategic_aggression_context()
    regime_state = brain.get("market_regime", {}) or {}
    regime_bias = str(regime_state.get("bias", "neutral"))
    regime_flavor = str(regime_state.get("regime_flavor", regime_state.get("regime", "unknown")))
    directional_drift = float(regime_state.get("directional_drift", 0.0) or 0.0)
    signed_trend_strength = float(regime_state.get("signed_trend_strength", 0.0) or 0.0)
    exploration_thresholds = get_exploration_thresholds()
    allocation_caps = exploration_thresholds.get("allocation_caps", {}) or {}
    simple_gate_summary = (
        f"Entry floors: min_score={float(exploration_thresholds.get('min_score', 0.0) or 0.0):.2f} "
        f"min_edge={float(exploration_thresholds.get('min_edge', 0.0) or 0.0):.2f} "
        f"cooldown={int(exploration_thresholds.get('cooldown_seconds', 0) or 0)}s | "
        f"qty_max={float(allocation_caps.get('qty_multiplier_max', 1.0) or 1.0):.2f}x "
        f"risk_max={float(allocation_caps.get('risk_multiplier_max', 1.0) or 1.0):.2f}x"
    )

    # === FEE SUMMARY ===
    avg_fee = brain.get("avg_fee", 0.0)
    total_fees = brain.get("total_fees_paid", 0.0)
    fee_summary = f"Average fee per trade: {avg_fee:.1f} sats | Total fees paid: {total_fees:.0f} sats"

    meta_lessons_text = "\n".join(f"- {item.get('meta_lesson', '')}" for item in brain.get("meta_lessons", [])[-3:]) or "No meta-lessons yet."

    lessons_text = "\n".join(
        f"- {item.get('summary', '')} | PnL={item.get('pnl', 0):+.0f} | Regime={item.get('regime', 'unknown')} | "
        f"Lesson: {(item.get('key_lessons') or ['N/A'])[0]}"
        for item in brain.get("trade_lessons", [])[-8:]
    ) or "No lessons yet."

    lb = brain.get("leaderboard", {})
    oracle = brain.get("oracle_replay", {})
    oracle_weights = oracle.get("regime_weights", {})
    oracle_scores = oracle.get("regime_scores", {})
    oracle_context = oracle.get("regime_context", {})
    chop_blob = (oracle_scores.get("chop") or {})
    chop_score = float(chop_blob.get("score_sum", 0.0) or 0.0) / max(int(chop_blob.get("samples", 0) or 0), 1)
    live_regime = str(regime_state.get("regime", "unknown"))
    oracle_live_blob = {
        **(oracle_context.get(live_regime) or {}),
        **get_oracle_regime_insight(live_regime),
    }
    oracle_summary = (
        f"Oracle replay points: {oracle.get('points', 0)} | "
        f"chop={chop_score:+.2f} | "
        f"trend={float(oracle_weights.get('trend', 0.0) or 0.0):+.2f} | "
        f"squeeze={float(oracle_weights.get('squeeze', 0.0) or 0.0):+.2f} | "
        f"replay_peak={float(oracle_live_blob.get('avg_peak_bps', 0.0) or 0.0):+.1f}bps | "
        f"replay_fee_half={float(oracle_live_blob.get('fee_clear_before_half_rate', 0.0) or 0.0):+.2f} | "
        f"replay_fade={float(oracle_live_blob.get('avg_fade_after_peak', 0.0) or 0.0):+.1f}bps | "
        f"replay_bias={str(oracle_live_blob.get('dominant_bias', 'neutral'))} | "
        f"replay_flavor={str(oracle_live_blob.get('dominant_flavor', live_regime))} | "
        f"replay_drift={float(oracle_live_blob.get('avg_directional_drift', 0.0) or 0.0):+.5f} | "
        f"replay_mtf={float(oracle_live_blob.get('avg_mtf_alignment_score', 0.0) or 0.0):+.2f} | "
        f"status={oracle.get('last_status', 'idle')}"
    )
    predictive_summary = str(signal_ctx.get("predictive_summary", "n/a"))
    return f"""
==================== RECENT LESSONS ====================
{lessons_text}

==================== META-LESSONS FROM REPLAY ====================
{meta_lessons_text}

==================== FEE SUMMARY ====================
{fee_summary}

==================== LEADERBOARD ====================
{get_leaderboard_summary()}
Gap: {lb.get('gap_to_top', 0):+.0f} sats | Position: {lb.get('relative_strength', 'unknown')}

==================== BROADER STRUCTURE ====================
Primary View: {broader_structure.get('summary', 'n/a')}
Directive: broader structure is the parent context. Levels, replay, tuner, and micro reports are inputs to this view; do not fight it unless a hard risk/exit gate blocks the trade.
Confluence Rule: do not require every indicator to align; prefer the broader-structure side when edge, level location, and risk controls are good enough.
Strategic Posture: {strategic_posture.get('mode', 'observe')} | {strategic_posture.get('reason', 'n/a')}. Default to aggressive opportunity capture when posture=attack; do not overreact to one tactical win/loss.
Parent Allocation: final entry size is set by deterministic parent allocation after AI selection, blending broader structure, edge, replay/oracle, level room, risk mode, and margin caps. Leverage is then set by deterministic setup quality rules. AI may suggest direction/intent, but must not try to force size above the parent/margin rails.
Caution directive: in squeeze/caution, do not default to HOLD if support/resistance or reclaim is clear. High-alignment, level-backed setups with thesis/forecast >= 0.35 are valid trades and should be taken when measurable edge is present. Caution should reduce size, not suppress good entries.

==================== MARKET MICRO-STRUCTURE ====================
Price Action: {brain.get('price_action_summary', 'neutral')}
Orderbook Imbalance Trend: {imbalance_trend} (avg {avg_imbalance:+.3f})
Funding Rate Trend: {funding_trend} | Bias: {signal_ctx.get('funding_bias', 'neutral')} | Delta: {signal_ctx.get('funding_delta_pct', 0.0):+.5f}%
Session: {session_bucket} | Session Bias: {session_bias}
Spread Shock: {spread_shock:.2f}x | Avg Spread: {signal_ctx.get('spread_avg_pct', 0.0):.4f}%
Volatility State: {volatility_state} | Expansion: {volatility_expansion:.2f}x
MTF Momentum: 1m={signal_ctx.get('momentum_1m', 0.0):+.5f} | 5m={signal_ctx.get('momentum_5m', 0.0):+.5f} | 15m={signal_ctx.get('momentum_15m', 0.0):+.5f} | Align={mtf_alignment}
External: source={signal_ctx.get('external_source', 'none')} bias={signal_ctx.get('external_bias', 'neutral')} conv={float(signal_ctx.get('external_conviction', 0.0) or 0.0):.2f} quality={signal_ctx.get('external_data_quality', 'none')} | BgLong={float(signal_ctx.get('bitget_account_long_ratio', 0.5) or 0.5):.3f} | BgPos={float(signal_ctx.get('bitget_position_long_ratio', 0.5) or 0.5):.3f} | Dfund1h={float(signal_ctx.get('deribit_funding_1h', 0.0) or 0.0):+.5f}
Feature Health: {signal_ctx.get('feature_health_summary', 'n/a')} | source={signal_ctx.get('feature_health_source', 'n/a')} reason={signal_ctx.get('feature_health_reason', 'n/a')} | orderbook_live={bool(signal_ctx.get('orderbook_live', False))} spread_live={bool(signal_ctx.get('spread_live', False))} external_live={bool(signal_ctx.get('external_live', False))}
Level Map: ready={bool(signal_ctx.get('level_map_ready', False))} | {signal_ctx.get('level_summary', 'n/a')} | room_up={float(signal_ctx.get('room_to_resistance_bps', 0.0) or 0.0):.1f}bps room_down={float(signal_ctx.get('room_to_support_bps', 0.0) or 0.0):.1f}bps | support={bool(signal_ctx.get('at_support', False))} resistance={bool(signal_ctx.get('at_resistance', False))} reclaimL={bool(signal_ctx.get('sweep_reclaim_long', False))} reclaimS={bool(signal_ctx.get('sweep_reclaim_short', False))}
Range: established={bool(signal_ctx.get('range_established', False))} pos={float(signal_ctx.get('range_position', 0.5) or 0.5):.3f} width={float(signal_ctx.get('range_width_pct', 0.0) or 0.0):.4f} high={float(signal_ctx.get('range_high', 0.0) or 0.0):.0f} low={float(signal_ctx.get('range_low', 0.0) or 0.0):.0f} mid={float(signal_ctx.get('range_mid', 0.0) or 0.0):.0f}

==================== FORWARD LOOKING (15-60M) ====================
Forecast: {predictive_summary}
Break Probabilities: up={float(signal_ctx.get('predictive_upside_break_prob', 0.5) or 0.5):.2f} down={float(signal_ctx.get('predictive_downside_break_prob', 0.5) or 0.5):.2f}
Forecast Drivers: orderbook_trend={float(signal_ctx.get('predictive_orderbook_trend', 0.0) or 0.0):+.2f} funding_accel={float(signal_ctx.get('predictive_funding_acceleration', 0.0) or 0.0):+.2f} mtf_div={float(signal_ctx.get('predictive_mtf_divergence', 0.0) or 0.0):+.2f} micro_accel={float(signal_ctx.get('predictive_micro_acceleration', 0.0) or 0.0):+.2f}
Setup Thresholds: quality_floor={get_quality_floor():.3f} chop_align_min={get_chop_align_min():.3f} chop_align_live_min={get_chop_align_live_min():.3f} range_width_min={get_range_width_min():.4f} fee_kill_ratio={get_fee_kill_ratio():.3f}
Entry Gates: {simple_gate_summary}

==================== ORACLE SHADOW REPLAY ====================
{oracle_summary}

==================== REGIME DETAIL ====================
Flavor: {regime_flavor} | Bias: {regime_bias} | Drift: {directional_drift:+.5f} | SignedTrend: {signed_trend_strength:+.6f}
Flat: {get_flat_duration_minutes():.0f}m | DirectionalRelief: {get_directional_flat_relief(live_regime, signal_ctx):.3f}

==================== REGIME VERDICT ====================
{_build_regime_verdict(live_regime, regime_bias, mtf_alignment, signal_ctx, get_flat_duration_minutes())}
"""


async def get_ai_session() -> aiohttp.ClientSession:
    global AI_SESSION
    if AI_SESSION is None or AI_SESSION.closed:
        AI_SESSION = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=90),
            connector=aiohttp.TCPConnector(limit=10, ttl_dns_cache=300),
        )
    return AI_SESSION


async def close_ai_session():
    global AI_SESSION
    if AI_SESSION and not AI_SESSION.closed:
        await AI_SESSION.close()
        log("AI session closed")


async def reason(prompt: str, max_retries: int = 2) -> Optional[str]:
    global _ai_payment_block_until
    if not BEARER_TOKEN:
        log("AI request skipped: missing bearer token")
        return None
    if not prompt or len(prompt) < 10:
        return None
    now = time.time()
    if now < _ai_payment_block_until:
        remaining = int(_ai_payment_block_until - now)
        log(f"AI request skipped: payment/budget cooldown active ({remaining}s remaining)")
        return None

    last_error = None
    async with AI_SEMAPHORE:
        for attempt in range(max_retries):
            try:
                session = await get_ai_session()
                headers = {
                    "Authorization": f"Bearer {BEARER_TOKEN}",
                    "Content-Type": "application/json",
                }
                async with session.post(
                    AI_ENDPOINT,
                    json={"question": prompt},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30, connect=10),
                ) as response:
                    raw_text = await response.text()
                    if response.status == 200:
                        try:
                            data = await response.json()
                        except json.JSONDecodeError:
                            return raw_text.strip() if raw_text else None
                        answer = data.get("answer") or data.get("response") or data.get("output")
                        if isinstance(answer, str) and answer.strip():
                            log(f"AI response | {len(answer)} chars | attempt {attempt + 1}")
                            return answer.strip()
                        return raw_text.strip() if raw_text else None
                    if response.status in (429, 503, 504):
                        wait = (2 ** attempt) * 1.5
                        log(f"AI retryable HTTP {response.status}, sleeping {wait:.1f}s")
                        await asyncio.sleep(wait)
                        continue
                    if response.status in (402, 403):
                        _ai_payment_block_until = time.time() + AI_PAYMENT_BLOCK_COOLDOWN_SECONDS
                        last_error = f"HTTP {response.status}"
                        log(
                            f"AI payment/budget HTTP {response.status}; "
                            f"suppressing AI calls for {AI_PAYMENT_BLOCK_COOLDOWN_SECONDS}s"
                        )
                        break
                    last_error = f"HTTP {response.status}"
                    log(f"AI HTTP error {response.status}")
            except asyncio.TimeoutError:
                last_error = "timeout"
                log(f"AI timeout attempt {attempt + 1}")
            except aiohttp.ClientConnectorError as exc:
                last_error = f"connection_error: {exc}"
                log(f"AI connection error attempt {attempt + 1}")
            except Exception as exc:
                last_error = str(exc)
                log(f"AI exception: {type(exc).__name__}: {exc}")
            if attempt < max_retries - 1:
                await asyncio.sleep((2 ** attempt) * 1.2 + 0.5)
    log(f"AI failed after {max_retries} attempts: {last_error}")
    return None


async def repair_json(text: str) -> Optional[dict]:
    raw = text.strip()[:1500] if isinstance(text, str) else ""
    if not raw:
        return None
    prompt = f"""
You are a strict JSON-only repair bot. Return only valid JSON.

Required fields:
- action: "open", "add", "reduce", "reverse", "close", or "hold"
- direction: "long" or "short"
- intent: "trend_follow", "mean_revert", "breakout", or "scalp"
- confidence: number between 0 and 1
- tp_bps, sl_bps, trail_bps: integers
- max_hold_minutes: integer
- leverage: integer
- reason: short string
- quantity: optional integer quantity for add/reduce/reverse

INPUT:
{raw}
"""
    fixed = await reason(prompt)
    parsed = extract_json(fixed) if fixed else None
    return parsed or extract_json(raw)


async def get_usable_margin(client) -> float:
    try:
        pos = await client.futures.cross.get_position()
        total_margin = 800.0
        running_margin = 0.0
        quantity = 0.0
        if pos:
            total_margin = float(_safe_get(pos, "margin", 0) or 0)
            running_margin = float(_safe_get(pos, "running_margin", 0) or 0)
            signed_qty, quantity_found = extract_signed_quantity(pos)
            if quantity_found and signed_qty is not None:
                quantity = abs(signed_qty)
        usable = total_margin - running_margin if quantity else total_margin
        usable = max(usable, 800.0)
        sizing_usable = update_sizing_balance_snapshot(usable, total_margin, running_margin)
        brain["last_margin"] = {
            "timestamp": datetime.now().isoformat(),
            "total_margin": round(total_margin, 0),
            "running_margin": round(running_margin, 0),
            "quantity": quantity,
            "usable": round(usable, 0),
            "sizing_usable": round(sizing_usable, 0),
            "has_open_position": quantity != 0,
        }
        last_logged_usable = float(brain.get("last_logged_usable", 0))
        if abs(usable - last_logged_usable) > 50 or last_logged_usable == 0:
            log(
                f"Margin | total={brain['last_margin']['total_margin']} "
                f"used={brain['last_margin']['running_margin']} usable={usable:.0f}"
            )
            brain["last_logged_usable"] = usable
        return usable
    except Exception as exc:
        log(f"Margin fetch failed: {exc}")
        return float(brain.get("last_margin", {}).get("usable", 800.0))


def position_hint_from_memory() -> Optional[str]:
    last_trade = brain.get("last_trade", {}) or {}
    last_trade_side = last_trade.get("side")
    if last_trade_side in {"long", "short"}:
        ts_str = last_trade.get("timestamp")
        if ts_str:
            try:
                age_hours = (datetime.now() - datetime.fromisoformat(ts_str)).total_seconds() / 3600
                if age_hours > 2.0:
                    return None  # stale — don't trust a hint from 2+ hours ago
            except Exception:
                pass
        return last_trade_side

    last_decision_side = brain.get("last_decision", {}).get("direction")
    if last_decision_side in {"long", "short"}:
        return last_decision_side

    return None


async def get_current_position_info(client) -> tuple[Optional[str], float, float, Optional[float], Optional[float], Optional[float]]:
    """Returns: side, qty, entry, initial_margin, running_margin, total_pl"""
    try:
        pos = await client.futures.cross.get_position()
        if not pos:
            log("📭 POSITION READ | no position returned")
            return None, 0.0, 0.0, None, None, None

        raw_pos = safe_serialize(pos)
        log(f"📦 RAW POSITION from LN Markets v3: {raw_pos}")

        signed_qty, quantity_found = extract_signed_quantity(pos)
        log(f"Quantity taken from parsed signed quantity: {signed_qty}")

        if not quantity_found or signed_qty is None:
            log("⚠️ Could not parse any valid quantity")
            return None, 0.0, 0.0, None, None, None

        if signed_qty == 0.0:
            log("ℹ️ Exchange reports a flat position")
            return None, 0.0, 0.0, None, None, None

        side: Optional[str] = None
        if signed_qty > 0:
            side = "long"
        elif signed_qty < 0:
            side = "short"

        qty = abs(signed_qty)

        entry = float(
            _safe_get(pos, "entry_price") or
            _safe_get(pos, "average_entry_price") or
            _safe_get(pos, "avg_entry_price") or
            _safe_get(pos, "open_price") or 0
        )

        initial_margin = float(_safe_get(pos, "initial_margin") or _safe_get(pos, "margin") or 0)
        running_margin = float(_safe_get(pos, "running_margin") or 0)
        total_pl = float(_safe_get(pos, "total_pl") or _safe_get(pos, "delta_pl") or 0)

        log(
            f"✅ PARSED POSITION → side={side} | qty={qty:.2f} | entry={entry:.1f} | "
            f"initial_margin={initial_margin:.0f} | running_margin={running_margin:.0f} | total_pl={total_pl:.0f}"
        )

        return side, qty, entry, initial_margin, running_margin, total_pl

    except Exception as exc:
        log(f"get_current_position_info failed: {exc}")
        traceback.print_exc()
        return None, 0.0, 0.0, None, None, None


async def verify_position_with_exchange(client, position: PositionState):
    try:
        side, qty, entry, initial_margin, running_margin, total_pl = await get_current_position_info(client)

        if qty <= 0:
            clear_persisted_position_plan("exchange_no_position")
            if position.is_open:
                log("Exchange reports no active position, resetting local state")
                position.reset("exchange_no_position")
            return

        old_qty = position.qty
        old_side = position.side
        old_entry = position.entry
        old_sl = position.sl_price
        old_tp = position.tp_price
        old_is_open = position.is_open

        if position.is_open and abs(old_qty - qty) > 0.01:
            log(f"Quantity changed significantly: {old_qty:.2f} → {qty:.2f}")

        # === 1. Try to restore SL/TP from memory ===
        sl_price = position.sl_price
        tp_price = position.tp_price
        trail_buffer_pct = position.trail_buffer_pct
        persisted_position = brain.get("position", {})
        persisted_opened_at = parse_iso_dt(persisted_position.get("opened_at"))
        restored_open_plan = bool(
            persisted_position and persisted_position.get("is_open") and persisted_position.get("side") == side
        )

        if restored_open_plan:
            if persisted_position.get("sl_price") is not None:
                sl_price = persisted_position.get("sl_price")
            if persisted_position.get("tp_price") is not None:
                tp_price = persisted_position.get("tp_price")
            if persisted_position.get("trail_buffer_pct") is not None:
                trail_buffer_pct = persisted_position.get("trail_buffer_pct")
            if persisted_position.get("max_hold_minutes") is not None:
                position.max_hold_minutes = persisted_position.get("max_hold_minutes")
            if persisted_position.get("intent"):
                position.intent = persisted_position.get("intent")
            if persisted_position.get("confidence") is not None:
                position.confidence = float(persisted_position.get("confidence"))
            if persisted_position.get("mode"):
                position.mode = persisted_position.get("mode")
            if persisted_position.get("policy"):
                position.policy = persisted_position.get("policy")
            if persisted_position.get("add_count") is not None:
                position.add_count = int(persisted_position.get("add_count") or 0)
            if persisted_position.get("original_qty") is not None:
                position.original_qty = float(persisted_position.get("original_qty") or 0.0)
            if persisted_position.get("scale_out_count") is not None:
                position.scale_out_count = int(persisted_position.get("scale_out_count") or 0)
            if persisted_position.get("last_scale_action_at"):
                position.last_scale_action_at = parse_iso_dt(persisted_position.get("last_scale_action_at"))
            if persisted_position.get("exchange_order_id"):
                position.exchange_order_id = persisted_position.get("exchange_order_id")
            if persisted_position.get("last_reason"):
                position.last_reason = persisted_position.get("last_reason")
            if persisted_position.get("entry_market_quality") is not None:
                position.entry_market_quality = float(persisted_position.get("entry_market_quality") or 0.0)
            if persisted_position.get("entry_momentum") is not None:
                position.entry_momentum = float(persisted_position.get("entry_momentum") or 0.0)
            if persisted_position.get("entry_imbalance") is not None:
                position.entry_imbalance = float(persisted_position.get("entry_imbalance") or 0.0)
            if persisted_position.get("entry_momentum_persistence") is not None:
                position.entry_momentum_persistence = float(persisted_position.get("entry_momentum_persistence") or 0.0)
            if persisted_position.get("entry_imbalance_persistence") is not None:
                position.entry_imbalance_persistence = float(persisted_position.get("entry_imbalance_persistence") or 0.0)
            if persisted_position.get("best_price") is not None:
                position.best_price = float(persisted_position.get("best_price") or 0.0)
            if persisted_position.get("worst_price") is not None:
                position.worst_price = float(persisted_position.get("worst_price") or 0.0)
            if persisted_position.get("trailing_min_since_open") is not None:
                position.trailing_min_since_open = float(persisted_position.get("trailing_min_since_open") or 0.0)
            if persisted_position.get("trailing_max_since_min") is not None:
                position.trailing_max_since_min = float(persisted_position.get("trailing_max_since_min") or 0.0)
            if persisted_position.get("trailing_max_since_open") is not None:
                position.trailing_max_since_open = float(persisted_position.get("trailing_max_since_open") or 0.0)
            if persisted_position.get("trailing_min_since_max") is not None:
                position.trailing_min_since_max = float(persisted_position.get("trailing_min_since_max") or 0.0)
            if persisted_position.get("max_unrealized_pnl") is not None:
                position.max_unrealized_pnl = float(persisted_position.get("max_unrealized_pnl") or 0.0)
            if persisted_position.get("min_unrealized_pnl") is not None:
                position.min_unrealized_pnl = float(persisted_position.get("min_unrealized_pnl") or 0.0)
            if persisted_position.get("time_to_mfe_minutes") is not None:
                position.time_to_mfe_minutes = float(persisted_position.get("time_to_mfe_minutes") or 0.0)
            if persisted_position.get("time_to_mae_minutes") is not None:
                position.time_to_mae_minutes = float(persisted_position.get("time_to_mae_minutes") or 0.0)
            if persisted_position.get("last_thesis_score") is not None:
                position.last_thesis_score = float(persisted_position.get("last_thesis_score") or 0.0)
            if persisted_position.get("last_add_ready") is not None:
                position.last_add_ready = bool(persisted_position.get("last_add_ready"))
            if persisted_position.get("entry_expected_edge") is not None:
                position.entry_expected_edge = float(persisted_position.get("entry_expected_edge") or 0.0)
            if persisted_position.get("entry_predictive_setup_score") is not None:
                position.entry_predictive_setup_score = float(persisted_position.get("entry_predictive_setup_score") or 0.0)
            if persisted_position.get("entry_predictive_setup_summary"):
                position.entry_predictive_setup_summary = str(persisted_position.get("entry_predictive_setup_summary") or "n/a")
            if persisted_position.get("entry_chop_learner_lane_active") is not None:
                position.entry_chop_learner_lane_active = bool(persisted_position.get("entry_chop_learner_lane_active"))
            if persisted_position.get("entry_nearest_support") is not None:
                position.entry_nearest_support = float(persisted_position.get("entry_nearest_support") or 0.0)
            if persisted_position.get("entry_nearest_resistance") is not None:
                position.entry_nearest_resistance = float(persisted_position.get("entry_nearest_resistance") or 0.0)
            if persisted_position.get("entry_room_to_target_bps") is not None:
                position.entry_room_to_target_bps = float(persisted_position.get("entry_room_to_target_bps") or 0.0)
            if persisted_position.get("entry_level_alignment"):
                position.entry_level_alignment = str(persisted_position.get("entry_level_alignment") or "unknown")
            if persisted_position.get("entry_level_summary"):
                position.entry_level_summary = str(persisted_position.get("entry_level_summary") or "n/a")
            if persisted_position.get("entry_feature_health_summary"):
                position.entry_feature_health_summary = str(persisted_position.get("entry_feature_health_summary") or "n/a")
            if persisted_position.get("entry_tag"):
                position.entry_tag = str(persisted_position.get("entry_tag") or "")
            if persisted_position.get("exit_tag"):
                position.exit_tag = str(persisted_position.get("exit_tag") or "")
            if persisted_position.get("signal_price") is not None:
                position.signal_price = float(persisted_position.get("signal_price") or 0.0)
            if persisted_position.get("evidence_valid") is not None:
                position.evidence_valid = bool(persisted_position.get("evidence_valid"))
            if persisted_position.get("evidence_reason"):
                position.evidence_reason = str(persisted_position.get("evidence_reason") or "n/a")
            if persisted_position.get("roi_schedule_reason"):
                position.roi_schedule_reason = str(persisted_position.get("roi_schedule_reason") or "")

        last_trade = brain.get("last_trade", {})

        if last_trade and last_trade.get("side") == side:
            # last_trade is entry metadata and can be stale after winner-lock SL tightening.
            # Only use it as a fallback when no persisted open-position plan supplied live risk fields.
            if last_trade.get("sl_price") is not None and not restored_open_plan:
                sl_price = last_trade.get("sl_price")
            if last_trade.get("tp_price") is not None and not restored_open_plan:
                tp_price = last_trade.get("tp_price")
            if last_trade.get("trail_buffer_pct") is not None and not restored_open_plan:
                trail_buffer_pct = last_trade.get("trail_buffer_pct")
            if last_trade.get("intent"):
                position.intent = last_trade.get("intent")
            if last_trade.get("confidence") is not None:
                position.confidence = float(last_trade.get("confidence"))
            if last_trade.get("mode"):
                position.mode = last_trade.get("mode")
            if last_trade.get("policy"):
                position.policy = last_trade.get("policy")
            if last_trade.get("max_hold_minutes") is not None:
                position.max_hold_minutes = last_trade.get("max_hold_minutes")
            if last_trade.get("qty") is not None and position.original_qty <= 0:
                position.original_qty = float(last_trade.get("qty") or 0.0)
            if last_trade.get("order_id"):
                position.exchange_order_id = last_trade.get("order_id")
            if last_trade.get("reason"):
                position.last_reason = last_trade.get("reason")
            if last_trade.get("expected_edge") is not None:
                position.entry_expected_edge = float(last_trade.get("expected_edge") or 0.0)
            if last_trade.get("predictive_setup_score") is not None:
                position.entry_predictive_setup_score = float(last_trade.get("predictive_setup_score") or 0.0)
            if last_trade.get("predictive_setup_summary"):
                position.entry_predictive_setup_summary = str(last_trade.get("predictive_setup_summary") or "n/a")
            if last_trade.get("chop_learner_lane_active") is not None:
                position.entry_chop_learner_lane_active = bool(last_trade.get("chop_learner_lane_active"))
            if last_trade.get("entry_nearest_support") is not None:
                position.entry_nearest_support = float(last_trade.get("entry_nearest_support") or 0.0)
            if last_trade.get("entry_nearest_resistance") is not None:
                position.entry_nearest_resistance = float(last_trade.get("entry_nearest_resistance") or 0.0)
            if last_trade.get("entry_room_to_target_bps") is not None:
                position.entry_room_to_target_bps = float(last_trade.get("entry_room_to_target_bps") or 0.0)
            if last_trade.get("entry_level_alignment"):
                position.entry_level_alignment = str(last_trade.get("entry_level_alignment") or "unknown")
            if last_trade.get("entry_level_summary"):
                position.entry_level_summary = str(last_trade.get("entry_level_summary") or "n/a")
            if last_trade.get("entry_feature_health_summary"):
                position.entry_feature_health_summary = str(last_trade.get("entry_feature_health_summary") or "n/a")
            if last_trade.get("entry_tag"):
                position.entry_tag = str(last_trade.get("entry_tag") or "")
            if last_trade.get("signal_price") is not None:
                position.signal_price = float(last_trade.get("signal_price") or 0.0)
            if last_trade.get("evidence_valid") is not None:
                position.evidence_valid = bool(last_trade.get("evidence_valid"))
            if last_trade.get("evidence_reason"):
                position.evidence_reason = str(last_trade.get("evidence_reason") or "n/a")
            if last_trade.get("roi_schedule_reason"):
                position.roi_schedule_reason = str(last_trade.get("roi_schedule_reason") or "")

        # === 2. Fallback: Calculate default SL/TP if missing ===
        if entry > 0 and (sl_price is None or tp_price is None):
            sl_bps = 120 if (position.leverage or 20) >= 15 else 180
            tp_bps = int(sl_bps * 2.0)

            if side == "long":
                sl_price = entry * (1 - sl_bps / 10000.0)
                tp_price = entry * (1 + tp_bps / 10000.0)
            else:
                sl_price = entry * (1 + sl_bps / 10000.0)
                tp_price = entry * (1 - tp_bps / 10000.0)

            trail_buffer_pct = sl_bps / 10000.0 * 0.6

            log(
                f"Calculated fallback SL/TP on sync: SL={sl_price:.0f} ({sl_bps}bps) | "
                f"TP={tp_price:.0f} ({tp_bps}bps) | trail={trail_buffer_pct:.4f}"
            )

        # Preserve add count across exchange resyncs.
        add_count = position.add_count
        original_qty = float(position.original_qty or old_qty or qty or 0.0)
        scale_out_count = int(position.scale_out_count or 0)
        last_scale_action_at = position.last_scale_action_at

        position.side = side
        position.entry = entry or position.entry or 0.0
        position.qty = qty
        position.leverage = float(_safe_get((await client.futures.cross.get_position()), "leverage") or position.leverage or 20)
        position.sl_price = sl_price
        position.tp_price = tp_price
        position.trail_buffer_pct = trail_buffer_pct
        if not position.intent:
            synced_regime = str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown")
            position.intent = "mean_revert" if synced_regime in {"chop", "squeeze"} else "trend_follow"
        position.confidence = position.confidence or 0.5
        position.status = "open"
        position.initial_margin = initial_margin
        position.running_margin = running_margin
        position.total_pl = total_pl
        position.add_count = add_count
        position.original_qty = original_qty
        position.scale_out_count = scale_out_count
        position.last_scale_action_at = last_scale_action_at
        if position.opened_at is None:
            position.opened_at = persisted_opened_at or datetime.now()
        if not position.entry_market_quality:
            position.entry_market_quality = float(brain.get("last_market_quality_components", {}).get("raw_score", 0.0) or 0.0)
        if position.best_price is None:
            position.best_price = position.entry
        if position.worst_price is None:
            position.worst_price = position.entry

        if reconcile_open_position_context(position):
            log(
                f"Reconciled open-position context | regime={brain.get('market_regime', {}).get('regime', 'unknown')} "
                f"intent={position.intent} mode={position.mode} policy={position.policy} "
                f"risk={brain.get('current_risk_per_trade', RISK_PER_TRADE):.4f}"
            )

        changed = (
            (not old_is_open)
            or old_side != side
            or abs(old_qty - qty) > 0.01
            or abs((old_entry or 0.0) - (entry or 0.0)) > 0.5
            or (old_sl or 0.0) != (sl_price or 0.0)
            or (old_tp or 0.0) != (tp_price or 0.0)
        )

        if changed:
            log(
                f"✅ Force-synced position: {side.upper()} | "
                f"qty={qty:.2f} | entry={entry or 0:.1f} | "
                f"sl={f'{sl_price:.0f}' if sl_price else 'N/A'} | "
                f"tp={f'{tp_price:.0f}' if tp_price else 'N/A'}"
            )
        persist_open_position_plan(position)

    except Exception as exc:
        log(f"verify_position_with_exchange failed: {exc}")
        traceback.print_exc()
        brain["last_sync_error"] = {
            "error": str(exc),
            "timestamp": datetime.now().isoformat(),
        }


async def confirm_position_fill(client, max_attempts: int = 12) -> tuple[Optional[str], float, float, Optional[float], Optional[float], Optional[float]]:
    """Wait for position fill confirmation after opening a trade.
    Returns: side, qty, entry, initial_margin, running_margin, total_pl
    """
    last_side = None
    last_qty = 0.0
    last_entry = 0.0

    for attempt in range(max_attempts):
        await asyncio.sleep(1.5 if attempt == 0 else 2.0)

        side, qty, entry, initial_margin, running_margin, total_pl = await get_current_position_info(client)

        last_side = side
        last_qty = qty
        last_entry = entry

        log(
            f"🔎 FILL CHECK {attempt + 1}/{max_attempts} | "
            f"side={side} | qty={qty:.2f} | entry={entry:.1f} | "
            f"initial_margin={initial_margin or 'N/A'} | running_margin={running_margin or 'N/A'}"
        )

        if qty <= 0:
            continue

        if entry <= 0:
            log("⚠️ qty present but entry not populated yet")
            continue

        if side is None:
            remembered_side = position_hint_from_memory()
            if remembered_side in {"long", "short"}:
                side = remembered_side
                log(f"⚠️ fill side unresolved, using memory hint: {side}")
            else:
                log("⚠️ qty+entry present but side unresolved")
                return None, qty, entry, None, None, None

        log(
            f"✅ Position fill confirmed on attempt {attempt + 1} | "
            f"qty={qty:.2f} | entry={entry:.1f} | margin={initial_margin or 'N/A'}"
        )

        return side, qty, entry, initial_margin, running_margin, total_pl

    log(
        f"❌ FILL CONFIRM FAILED after {max_attempts} attempts | "
        f"last_side={last_side} last_qty={last_qty:.2f} last_entry={last_entry:.1f}"
    )
    append_review_report(
        "critical_execution_block",
        {
            "path": "confirm_position_fill",
            "max_attempts": max_attempts,
            "last_side": last_side,
            "last_qty": round(last_qty, 4),
            "last_entry": round(last_entry, 2),
            "effect": "entry_not_confirmed",
        },
    )
    return None, 0.0, 0.0, None, None, None


async def safe_close_position(client):
    """Safely close the current position"""
    try:
        await client.futures.cross.close()
        log("Position closed via exchange (safe_close_position)")
    except Exception as exc:
        log(f"Exchange close failed: {exc}")
        append_review_report(
            "critical_execution_error",
            {"path": "safe_close_position", "error": str(exc), "effect": "close_failed_requires_operator_attention"},
        )


async def get_market_context(client) -> dict[str, Any]:
    try:
        ticker = await client.futures.get_ticker()
        last_price = extract_price_lnm(ticker)
        bid = float(_safe_get(ticker, "bid", 0) or _safe_get(ticker, "best_bid", 0) or 0)
        ask = float(_safe_get(ticker, "ask", 0) or _safe_get(ticker, "best_ask", 0) or 0)
        bid_size = float(_safe_get(ticker, "bid_size", 0) or 0)
        ask_size = float(_safe_get(ticker, "ask_size", 0) or 0)
        imbalance = 0.0
        # LN Markets v3 ticker exposes a `prices` ladder instead of flat top-of-book
        # fields. Fall back to it so spread/depth health isn't perpetually stale.
        if (bid <= 0 or ask <= 0 or ask < bid) or (bid_size <= 0 and ask_size <= 0):
            prices_ladder = _safe_get(ticker, "prices", None)
            if isinstance(prices_ladder, list) and prices_ladder:
                top = prices_ladder[0] if isinstance(prices_ladder[0], (dict,)) else None
                if top is None and hasattr(prices_ladder[0], "__dict__"):
                    top = prices_ladder[0]
                bid_top = float(_safe_get(top, "bid_price", 0) or _safe_get(top, "bidPrice", 0) or 0)
                ask_top = float(_safe_get(top, "ask_price", 0) or _safe_get(top, "askPrice", 0) or 0)
                tier_cap = float(_safe_get(top, "max_size", 0) or _safe_get(top, "maxSize", 0) or 0)
                if bid_top > 0 and ask_top >= bid_top:
                    bid = bid_top if bid <= 0 else bid
                    ask = ask_top if ask <= 0 else ask
                    if tier_cap > 0:
                        bid_size = bid_size if bid_size > 0 else tier_cap
                        ask_size = ask_size if ask_size > 0 else tier_cap
                # Price-skew imbalance: if bid_price drops faster than ask_price
                # rises across the ladder, the book is thinner on the bid side.
                try:
                    skew_tier = prices_ladder[min(4, len(prices_ladder) - 1)]
                    bid_deep = float(_safe_get(skew_tier, "bid_price", 0) or _safe_get(skew_tier, "bidPrice", 0) or 0)
                    ask_deep = float(_safe_get(skew_tier, "ask_price", 0) or _safe_get(skew_tier, "askPrice", 0) or 0)
                    if bid_top > 0 and ask_top > 0 and bid_deep > 0 and ask_deep > 0:
                        bid_slip = max(0.0, bid_top - bid_deep)
                        ask_slip = max(0.0, ask_deep - ask_top)
                        denom = bid_slip + ask_slip
                        if denom > 0:
                            imbalance = (ask_slip - bid_slip) / denom
                except Exception:
                    pass
        spread_pct = ((ask - bid) / last_price * 100) if last_price > 0 and ask > bid > 0 else 0.0
        depth_live = bool(bid_size > 0 and ask_size > 0)
        if (bid_size + ask_size) > 0 and imbalance == 0.0:
            imbalance = (bid_size - ask_size) / max(bid_size + ask_size, 1)
        brain["spread_history"].append(round(spread_pct, 4))
        brain["market_context"] = {
        "bid": round(bid, 2),
        "ask": round(ask, 2),
        "spread_pct": round(spread_pct, 4),
        "imbalance": round(imbalance, 3),
        "bid_size": round(bid_size, 4),
        "ask_size": round(ask_size, 4),
        "depth_live": depth_live,
        "mid_price": round((bid + ask) / 2, 2) if bid and ask else last_price,
        "source": "lnmarkets_ticker_top_of_book",
        "updated_at": datetime.now().isoformat(),
        "data_ok": bool(last_price > 0 and (spread_pct >= 0.0)),
    }
        refresh_market_signal_context()
        if spread_pct > 0.05:
            log(f"Spread {spread_pct:.4f}% | Imbalance {imbalance:+.3f}")
        return brain["market_context"]
    except Exception as exc:
        log(f"get_market_context failed: {exc}")
        append_review_report(
            "critical_data_block",
            {"path": "get_market_context", "error": str(exc), "effect": "entries use warmup/stale-context gate"},
        )
        if isinstance(brain.get("market_context"), dict):
            brain["market_context"]["data_ok"] = False
            brain["market_context"]["updated_at"] = brain["market_context"].get("updated_at")
        return brain.get("market_context", {})


async def get_funding_rate(client) -> float:
    try:
        funding_rate = 0.0
        try:
            market = await client.futures.get_market()
            funding_rate = float(
                _safe_get(market, "funding_rate", 0) or _safe_get(market, "predicted_funding_rate", 0) or 0
            )
        except Exception:
            pass

        if funding_rate == 0.0:
            try:
                settlements = await client.futures.get_funding_settlements(limit=1)
                if isinstance(settlements, list) and settlements:
                    funding_rate = float(_safe_get(settlements[0], "funding_rate", 0) or 0)
                elif isinstance(settlements, dict):
                    funding_rate = float(_safe_get(settlements, "funding_rate", 0) or 0)
            except Exception:
                pass

        brain["funding_rate"] = funding_rate
        brain["funding_rate_pct"] = round(funding_rate * 100, 5)
        brain["funding_rate_samples"].append(brain["funding_rate_pct"])
        if isinstance(brain.get("market_context"), dict):
            refresh_market_signal_context()
        direction = "longs pay shorts" if funding_rate > 0 else "shorts pay longs" if funding_rate < 0 else "neutral"
        log(f"Funding {brain['funding_rate_pct']:.5f}% ({direction})")
        return funding_rate
    except Exception as exc:
        log(f"Funding rate fetch failed: {exc}")
        brain["funding_rate"] = 0.0
        brain["funding_rate_pct"] = 0.0
        return 0.0


async def fetch_bitget_market_structure() -> dict[str, Any]:
    session = await get_ai_session()
    base = BITGET_API_BASE.rstrip("/")
    result: dict[str, Any] = {
        "open_interest": 0.0,
        "account_long_ratio": 0.5,
        "position_long_ratio": 0.5,
        "status": "ok",
        "errors": [],
        "ok_count": 0,
        "total_count": 0,
    }
    symbol = "BTCUSDT"
    def _err_tag(prefix: str, exc: Exception) -> str:
        status = getattr(exc, "status", None)
        return f"{prefix}:{type(exc).__name__}:{status}" if status is not None else f"{prefix}:{type(exc).__name__}"

    try:
        result["total_count"] += 1
        async with session.get(
            f"{base}/api/v2/mix/market/open-interest",
            params={"symbol": symbol, "productType": "USDT-FUTURES"},
        ) as response:
            response.raise_for_status()
            payload = await response.json()
        rows = (((payload or {}).get("data") or {}).get("openInterestList") or [])
        if isinstance(rows, list) and rows:
            result["open_interest"] = float((rows[-1] or {}).get("size", 0.0) or 0.0)
        result["ok_count"] += 1
    except Exception as exc:
        result["errors"].append(_err_tag("open_interest", exc))

    try:
        result["total_count"] += 1
        async with session.get(
            f"{base}/api/v2/mix/market/long-short",
            params={"symbol": symbol, "period": "5m"},
        ) as response:
            response.raise_for_status()
            payload = await response.json()
        rows = ((payload or {}).get("data") or [])
        if isinstance(rows, list) and rows:
            result["account_long_ratio"] = float((rows[-1] or {}).get("longRatio", 0.5) or 0.5)
        result["ok_count"] += 1
    except Exception as exc:
        result["errors"].append(_err_tag("account_long_short", exc))

    try:
        result["total_count"] += 1
        async with session.get(
            f"{base}/api/v2/mix/market/position-long-short",
            params={"symbol": symbol, "period": "5m"},
        ) as response:
            response.raise_for_status()
            payload = await response.json()
        rows = ((payload or {}).get("data") or [])
        if isinstance(rows, list) and rows:
            result["position_long_ratio"] = float((rows[-1] or {}).get("longPositionRatio", 0.5) or 0.5)
        result["ok_count"] += 1
    except Exception as exc:
        result["errors"].append(_err_tag("position_long_short", exc))

    ok_count = int(result.get("ok_count", 0) or 0)
    total_count = int(result.get("total_count", 0) or 0)
    if ok_count <= 0:
        result["status"] = "error"
    elif ok_count < total_count:
        result["status"] = "partial"
    else:
        result["status"] = "ok"

    return result


async def fetch_deribit_market_structure() -> dict[str, Any]:
    session = await get_ai_session()
    base = DERIBIT_API_BASE.rstrip("/")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - (24 * 60 * 60 * 1000)
    result: dict[str, Any] = {"funding_1h": 0.0, "funding_8h": 0.0, "status": "ok", "errors": []}
    def _err_tag(prefix: str, exc: Exception) -> str:
        status = getattr(exc, "status", None)
        return f"{prefix}:{type(exc).__name__}:{status}" if status is not None else f"{prefix}:{type(exc).__name__}"

    try:
        async with session.get(
            f"{base}/public/get_funding_rate_history",
            params={
                "instrument_name": "BTC-PERPETUAL",
                "start_timestamp": start_ms,
                "end_timestamp": now_ms,
            },
        ) as response:
            response.raise_for_status()
            payload = await response.json()
        rows = ((payload or {}).get("result") or [])
        if isinstance(rows, list) and rows:
            last = rows[-1] or {}
            result["funding_1h"] = float(last.get("interest_1h", 0.0) or 0.0)
            result["funding_8h"] = float(last.get("interest_8h", 0.0) or 0.0)
    except Exception as exc:
        result["status"] = "error"
        result["errors"].append(_err_tag("funding", exc))
    return result


async def fetch_htf_bias() -> dict[str, Any]:
    session = await get_ai_session()
    base = BITGET_API_BASE.rstrip("/")

    async def _candles(granularity: str, limit: str) -> dict:
        async with session.get(
            f"{base}/api/v2/mix/market/candles",
            params={"symbol": "BTCUSDT", "productType": "USDT-FUTURES", "granularity": granularity, "limit": limit},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    try:
        weekly_payload, daily_payload, h12_payload, h4_payload, h1_payload = await asyncio.gather(
            _candles("1Wutc", "8"),
            _candles("1Dutc", "14"),
            _candles("12H", "14"),
            _candles("4H", "14"),
            _candles("1H", "14"),
        )
    except Exception as exc:
        return {"status": "error", "htf_bias_score": 0.0, "htf_bias": "neutral",
                "htf_daily_score": 0.0, "htf_weekly_score": 0.0,
                "htf_12h_score": 0.0, "htf_4h_score": 0.0, "htf_1h_score": 0.0, "error": str(exc)}

    def slope_score(payload: dict, n: int) -> float:
        rows = (payload or {}).get("data") or []
        closes = [float(r[4]) for r in rows[-n:] if isinstance(r, list) and len(r) > 4]
        if len(closes) < 2 or closes[0] <= 0:
            return 0.0
        return clamp((closes[-1] - closes[0]) / closes[0] / 0.05, -1.0, 1.0)

    weekly_score = slope_score(weekly_payload, 4)
    daily_score  = slope_score(daily_payload, 7)
    h12_score    = slope_score(h12_payload, 7)
    h4_score     = slope_score(h4_payload, 7)
    h1_score     = slope_score(h1_payload, 7)
    htf_score = round(clamp(
        h1_score * 0.25 + h4_score * 0.35 + h12_score * 0.20 + daily_score * 0.13 + weekly_score * 0.07,
        -1.0, 1.0,
    ), 3)
    htf_bias = "bullish" if htf_score > 0.20 else "bearish" if htf_score < -0.20 else "neutral"
    return {
        "status": "ok",
        "htf_bias_score": htf_score,
        "htf_bias": htf_bias,
        "htf_weekly_score": round(weekly_score, 3),
        "htf_daily_score":  round(daily_score, 3),
        "htf_12h_score":    round(h12_score, 3),
        "htf_4h_score":     round(h4_score, 3),
        "htf_1h_score":     round(h1_score, 3),
    }


async def refresh_external_market_data():
    global _last_htf_update
    external = brain.setdefault("external_market", {})
    try:
        htf_stale = time.time() - _last_htf_update > HTF_BIAS_REFRESH_SECONDS
        if htf_stale:
            bitget_data, deribit_data, htf_data = await asyncio.gather(
                fetch_bitget_market_structure(),
                fetch_deribit_market_structure(),
                fetch_htf_bias(),
            )
            _last_htf_update = time.time()
            brain["htf_bias"] = htf_data
            log(
                f"HTF bias updated | bias={htf_data.get('htf_bias', 'n/a')} "
                f"score={htf_data.get('htf_bias_score', 0.0):+.2f} "
                f"weekly={htf_data.get('htf_weekly_score', 0.0):+.2f} "
                f"daily={htf_data.get('htf_daily_score', 0.0):+.2f} "
                f"12h={htf_data.get('htf_12h_score', 0.0):+.2f} "
                f"4h={htf_data.get('htf_4h_score', 0.0):+.2f} "
                f"1h={htf_data.get('htf_1h_score', 0.0):+.2f} "
                f"status={htf_data.get('status', 'n/a')}"
            )
        else:
            bitget_data, deribit_data = await asyncio.gather(
                fetch_bitget_market_structure(),
                fetch_deribit_market_structure(),
            )
        external["bitget"] = safe_serialize(bitget_data)
        external["deribit"] = safe_serialize(deribit_data)
        external["last_updated_at"] = datetime.now().isoformat()
        statuses = {str(bitget_data.get("status", "missing")), str(deribit_data.get("status", "missing"))}
        if statuses == {"ok"}:
            external["status"] = "ok"
        elif "ok" in statuses:
            external["status"] = "partial"
        else:
            external["status"] = "error"
        refresh_market_signal_context()
        signal_ctx = get_signal_context()
        htf = brain.get("htf_bias", {}) or {}
        log(
            f"External market updated | bias={signal_ctx.get('external_bias', 'neutral')} "
            f"conv={float(signal_ctx.get('external_conviction', 0.0) or 0.0):.2f} "
            f"source={signal_ctx.get('external_source', 'none')} "
            f"quality={signal_ctx.get('external_data_quality', 'none')} "
            f"bitget={signal_ctx.get('bitget_status', 'missing')} "
            f"deribit={signal_ctx.get('deribit_status', 'missing')} "
            f"bgLong={float(signal_ctx.get('bitget_account_long_ratio', 0.5) or 0.5):.3f} "
            f"bgPos={float(signal_ctx.get('bitget_position_long_ratio', 0.5) or 0.5):.3f} "
            f"Dfund1h={float(signal_ctx.get('deribit_funding_1h', 0.0) or 0.0):+.5f} "
            f"htf={htf.get('htf_bias', 'n/a')}/{float(htf.get('htf_bias_score', 0.0)):+.2f}"
        )
        maybe_save_memory(force=True)
    except Exception as exc:
        external["status"] = f"error: {exc}"
        external["last_updated_at"] = datetime.now().isoformat()
        log(f"External market refresh failed: {exc}")


def record_exit_to_memory(position: PositionState, exit_price: float, gross_pnl: float, reason: str, fee: float = 0.0):
    """Record exit to long-term memory with SL/TP and fee info"""
    net_pnl = gross_pnl - fee
    exclude_from_risk = should_exclude_pnl_from_risk(reason, net_pnl)
    thesis = get_position_thesis_metrics(position, exit_price)
    close_alignment = compute_close_alignment(position, thesis, exit_price)
    trade_signal_snapshot = build_trade_signal_snapshot(close_alignment=close_alignment)
    append_memory_history(
        {
            "id": position.exchange_order_id or f"local_exit_{int(time.time())}",
            "time": datetime.now().isoformat(),
            "gross_pnl": round(gross_pnl, 2),
            "net_pnl": round(net_pnl, 2),
            "fee": round(fee, 2),
            "exclude_from_risk": exclude_from_risk,
            "side": position.side,
            "entry_tag": position.entry_tag,
            "exit_tag": build_exit_tag(reason, position),
            "signal_price": round(float(position.signal_price or 0.0), 2),
            "evidence_valid": bool(position.evidence_valid),
            "evidence_reason": position.evidence_reason,
            "roi_schedule_reason": position.roi_schedule_reason,
            "exit_reason": reason,
            "entry_price": round(position.entry or 0, 2),
            "exit_price": round(exit_price, 2),
            "sl_price": position.sl_price,
            "tp_price": position.tp_price,
            "intent": position.intent,
            "mode": position.mode,
            "policy": position.policy,
            "confidence": round(position.confidence, 2),
            "leverage": position.leverage,
            "regime": brain.get("market_regime", {}).get("regime", "unknown"),
            "source": "local_exit",
            **trade_signal_snapshot,
        }
    )
    # Re-calibrate quality biases and run batch tuners on trade milestones
    history_len = len(MEMORY.get("history", []))
    if history_len > 0 and history_len % 10 == 0:
        try:
            compute_entry_quality_bias()
            compute_exit_quality_bias()
        except Exception:
            pass
    if history_len > 0 and history_len % 10 == 0:
        try:
            tune_level_thresholds_from_shadow()
        except Exception:
            pass
    if history_len > 0 and history_len % 15 == 0:
        try:
            tune_exploration_thresholds()
        except Exception:
            pass
    if history_len > 0 and history_len % 20 == 0:
        try:
            tune_entry_thresholds()
        except Exception:
            pass
    if history_len > 0 and history_len % 30 == 0:
        try:
            tune_range_thresholds()
        except Exception:
            pass


def append_position_event(event: dict[str, Any]):
    brain.setdefault("position_events", []).append(event)
    brain["position_events"] = brain["position_events"][-200:]


def record_trade_activity(mode: str, action: str, quantity: float):
    brain.setdefault("trade_timestamps", []).append(
        {
            "ts": time.time(),
            "mode": mode,
            "action": action,
            "qty": round(float(quantity), 4),
        }
    )
    trim_trade_timestamps()


def append_exploration_recent_record(
    *,
    timestamp: datetime,
    position: PositionState,
    regime: str,
    pnl: float,
    reason: str,
    exit_type: str,
    exclude_from_risk: bool,
    exclude_from_protection: bool,
    learning_snapshot: dict[str, Any],
    trade_signal_snapshot: dict[str, Any],
):
    brain.setdefault("exploration", {}).setdefault("recent", []).append(
        {
            "timestamp": timestamp.isoformat(),
            "policy": position.policy,
            "intent": position.intent,
            "direction": position.side,
            "entry_tag": position.entry_tag,
            "exit_tag": build_exit_tag(reason, position),
            "signal_price": round(float(position.signal_price or 0.0), 2),
            "evidence_valid": bool(position.evidence_valid),
            "evidence_reason": position.evidence_reason,
            "roi_schedule_reason": position.roi_schedule_reason,
            "lane_key": build_exploration_lane_key(
                str(regime or "unknown"),
                str(trade_signal_snapshot.get("regime_bias", "neutral") or "neutral"),
                str(position.policy or "unknown"),
                str(position.side or "unknown"),
                str(trade_signal_snapshot.get("session_bucket", "offhours") or "offhours"),
            ),
            "mode": position.mode,
            "pnl": round(pnl, 2),
            "regime": regime,
            "reason": reason,
            "exit_type": exit_type,
            "exclude_from_risk": exclude_from_risk,
            "exclude_from_protection": exclude_from_protection,
            **learning_snapshot,
            **trade_signal_snapshot,
        }
    )
    brain["exploration"]["recent"] = brain["exploration"]["recent"][-100:]


def update_behavioral_fitness(position: PositionState, net_pnl: float, is_win: bool):
    confidence = float(position.confidence)
    confidence_error = (1.0 if is_win else 0.0) - confidence
    brain["confidence_bias"] = float(brain.get("confidence_bias", 0.0)) * 0.98 + confidence_error * 0.02
    brain.setdefault("confidence_bias_history", deque(maxlen=30)).append(round(brain["confidence_bias"], 4))

    notional = abs((position.entry or 1) * max(position.qty, 1))
    risk_signal = net_pnl / max(notional, 1e-9)
    brain["risk_signal"] = float(brain.get("risk_signal", 0.0)) * 0.95 + risk_signal * 0.05

    normalized_pnl = net_pnl / max(abs(position.entry or 1), 1)
    brain["strategy_fitness"] = float(brain.get("strategy_fitness", 0.0)) * 0.995 + (normalized_pnl * confidence) * 0.005


def build_last_exit_record(
    *,
    timestamp: datetime,
    position: PositionState,
    exit_price: float,
    gross_pnl: float,
    net_pnl: float,
    fee: float,
    reason: str,
    exit_type: str,
    exclude_from_risk: bool,
    exclude_from_protection: bool,
    learning_snapshot: dict[str, Any],
    trade_signal_snapshot: dict[str, Any],
    closed_qty: Optional[float] = None,
    resulting_side: Optional[str] = None,
    resulting_qty: Optional[float] = None,
    hold_time_minutes: Optional[float] = None,
) -> dict[str, Any]:
    payload = {
        "timestamp": timestamp.isoformat(),
        "side": position.side,
        "entry_price": round(position.entry or 0, 2),
        "exit_price": round(exit_price, 2),
        "gross_pnl": round(gross_pnl, 2),
        "realized_pnl": round(net_pnl, 2),
        "fee": round(fee, 2),
        "exit_reason": reason,
        "exclude_from_risk": exclude_from_risk,
        "exclude_from_protection": exclude_from_protection,
        "exit_type": exit_type,
        "entry_tag": position.entry_tag,
        "exit_tag": build_exit_tag(reason, position),
        "signal_price": round(float(position.signal_price or 0.0), 2),
        "evidence_valid": bool(position.evidence_valid),
        "evidence_reason": position.evidence_reason,
        "roi_schedule_reason": position.roi_schedule_reason,
        "intent": position.intent,
        "mode": position.mode,
        "policy": position.policy,
        "confidence": round(position.confidence, 2),
        "leverage": position.leverage,
        **learning_snapshot,
        **trade_signal_snapshot,
    }
    if hold_time_minutes is not None:
        payload["hold_time_minutes"] = hold_time_minutes
    if closed_qty is not None:
        payload["closed_qty"] = round(closed_qty, 4)
    if resulting_side is not None:
        payload["resulting_side"] = resulting_side
    if resulting_qty is not None:
        payload["resulting_qty"] = round(resulting_qty, 4)
    if position.sl_price is not None:
        payload["sl_price"] = position.sl_price
    if position.tp_price is not None:
        payload["tp_price"] = position.tp_price
    return payload


def append_decision_event(
    action: str,
    direction: Optional[str],
    quantity: Optional[float],
    intent: str,
    mode: str,
    policy: str,
    confidence: float,
    leverage: Optional[float],
    reason: str,
    extra: Optional[dict[str, Any]] = None,
):
    item = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "direction": direction,
        "quantity": quantity,
        "intent": intent,
        "mode": mode,
        "policy": policy,
        "confidence": round(confidence, 3),
        "leverage": leverage,
        "reason": reason,
        "outcome": "recorded",
    }
    if extra:
        item.update(extra)
    append_past_ai_decision(item)


def append_past_ai_decision(item: dict[str, Any]):
    brain.setdefault("past_ai_decisions", []).append(item)
    brain["past_ai_decisions"] = brain["past_ai_decisions"][-100:]


def append_memory_history(item: dict[str, Any]):
    MEMORY.setdefault("history", []).append(item)
    MEMORY["history"] = MEMORY.get("history", [])[-500:]


def record_adjustment_to_memory(
    position: PositionState,
    event_type: str,
    exit_price: float,
    gross_pnl: float,
    fee: float,
    reason: str,
    closed_qty: float,
    resulting_side: Optional[str],
    resulting_qty: float,
):
    net_pnl = gross_pnl - fee
    exclude_from_risk = should_exclude_pnl_from_risk(reason, net_pnl)
    thesis = get_position_thesis_metrics(position, exit_price)
    close_alignment = compute_close_alignment(position, thesis, exit_price)
    trade_signal_snapshot = build_trade_signal_snapshot(close_alignment=close_alignment)
    append_memory_history(
        {
            "id": f"{event_type}_{int(time.time())}",
            "time": datetime.now().isoformat(),
            "event_type": event_type,
            "gross_pnl": round(gross_pnl, 2),
            "net_pnl": round(net_pnl, 2),
            "fee": round(fee, 2),
            "exclude_from_risk": exclude_from_risk,
            "side": position.side,
            "exit_reason": reason,
            "entry_price": round(position.entry or 0, 2),
            "exit_price": round(exit_price, 2),
            "closed_qty": round(closed_qty, 4),
            "resulting_side": resulting_side,
            "resulting_qty": round(resulting_qty, 4),
            "intent": position.intent,
            "mode": position.mode,
            "policy": position.policy,
            "confidence": round(position.confidence, 2),
            "leverage": position.leverage,
            "regime": brain.get("market_regime", {}).get("regime", "unknown"),
            "source": "position_adjustment",
            **trade_signal_snapshot,
        }
    )


def register_partial_realization(
    position: PositionState,
    exit_price: float,
    reason: str,
    closed_qty: float,
    event_type: str,
    resulting_side: Optional[str],
    resulting_qty: float,
):
    closed_qty = max(0.0, min(closed_qty, position.qty))
    if closed_qty <= 0 or not position.qty:
        return

    gross_full = position.unrealized_pnl(exit_price)
    realized_ratio = closed_qty / max(position.qty, 1e-9)
    gross_pnl = gross_full * realized_ratio
    fee = estimate_round_trip_fee_from_position(position) * realized_ratio
    net_pnl = gross_pnl - fee
    now = datetime.now()
    realized_record = build_realized_record(now, gross_pnl, net_pnl, fee, reason, event_type, position)
    # Partial exits (reduce/scale) are sub-legs of a single trade — exclude from risk/streak
    # so only the final full close counts toward consecutive loss tracking.
    realized_record["exclude_from_risk"] = True
    realized_record["exclude_from_protection"] = True
    exclude_from_risk = True
    exclude_from_protection = True

    record_legacy_pnl_history(net_pnl)

    brain["trades"] = int(brain.get("trades", 0)) + 1
    is_win = net_pnl > 0
    if is_win:
        brain["wins"] = int(brain.get("wins", 0)) + 1
    else:
        brain["losses"] = int(brain.get("losses", 0)) + 1

    brain["total_pnl"] = float(brain.get("total_pnl", 0.0)) + net_pnl
    brain["last_exit_reason"] = reason
    brain.setdefault("daily_realized", []).append(realized_record)
    update_daily_pnl()
    maybe_arm_protection_cooldown(now, realized_record)

    refresh_legacy_equity_drawdown(net_pnl)

    regime = brain.get("market_regime", {}).get("regime", "unknown")
    regime_stats = brain.setdefault("regime_stats", {}).setdefault(regime, {"trades": 0, "wins": 0, "pnl": 0.0})
    regime_stats["trades"] += 1
    regime_stats["pnl"] += net_pnl
    if is_win:
        regime_stats["wins"] = regime_stats.get("wins", 0) + 1

    intent_stats = brain.setdefault("intent_stats", {}).setdefault(position.intent, {"trades": 0, "wins": 0, "pnl": 0.0, "winrate": 0.0})
    intent_stats["trades"] += 1
    intent_stats["pnl"] += net_pnl
    if is_win:
        intent_stats["wins"] += 1
    intent_stats["winrate"] = intent_stats["wins"] / max(intent_stats["trades"], 1)

    conf_bucket = round(float(position.confidence), 1)
    conf_stats = brain.setdefault("confidence_stats", {}).setdefault(conf_bucket, {"trades": 0, "wins": 0, "pnl": 0.0, "winrate": 0.0})
    conf_stats["trades"] += 1
    conf_stats["pnl"] += net_pnl
    if is_win:
        conf_stats["wins"] += 1
    conf_stats["winrate"] = conf_stats["wins"] / max(conf_stats["trades"], 1)

    learning_snapshot = build_position_learning_snapshot(position)
    thesis = get_position_thesis_metrics(position, exit_price)
    close_alignment = compute_close_alignment(position, thesis, exit_price)
    trade_signal_snapshot = build_trade_signal_snapshot(regime=regime, close_alignment=close_alignment)
    policy_stats = (
        brain.setdefault("exploration", {})
        .setdefault("policies", {})
        .setdefault(
            position.policy,
            {
                "trades": 0,
                "wins": 0,
                "pnl": 0.0,
                "avg_pnl": 0.0,
                "score": 0.0,
                "last_used_at": None,
                "last_regime": None,
                "fee_clear_rate": 0.0,
                "avg_peak_fee_multiple": 0.0,
                "avg_time_to_mfe_minutes": 0.0,
                "timed_mfe_count": 0,
            },
        )
    )
    update_policy_learning_stats(policy_stats, net_pnl, is_win, learning_snapshot, now, regime)
    update_winner_fade_stats(position, learning_snapshot, net_pnl)

    append_exploration_recent_record(
        timestamp=now,
        position=position,
        regime=regime,
        pnl=net_pnl,
        reason=reason,
        exit_type=event_type,
        exclude_from_risk=exclude_from_risk,
        exclude_from_protection=exclude_from_protection,
        learning_snapshot=learning_snapshot,
        trade_signal_snapshot=trade_signal_snapshot,
    )
    update_behavioral_fitness(position, net_pnl, is_win)

    record_trade_activity(position.mode, event_type, closed_qty)

    append_position_event(
        {
            "timestamp": now.isoformat(),
            "event_type": event_type,
            "reason": reason,
            "side": position.side,
            "entry_tag": position.entry_tag,
            "exit_tag": build_exit_tag(reason, position),
            "closed_qty": round(closed_qty, 4),
            "resulting_side": resulting_side,
            "resulting_qty": round(resulting_qty, 4),
            "gross_pnl": round(gross_pnl, 2),
            "net_pnl": round(net_pnl, 2),
            "fee": round(fee, 2),
            "exclude_from_risk": exclude_from_risk,
            "exclude_from_protection": exclude_from_protection,
            "policy": position.policy,
            "mode": position.mode,
        }
    )

    record_adjustment_to_memory(
        position,
        event_type,
        exit_price,
        gross_pnl,
        fee,
        reason,
        closed_qty,
        resulting_side,
        resulting_qty,
    )

    brain["last_exit"] = build_last_exit_record(
        timestamp=now,
        position=position,
        exit_price=exit_price,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        fee=fee,
        reason=reason,
        exit_type=event_type,
        exclude_from_risk=exclude_from_risk,
        exclude_from_protection=exclude_from_protection,
        learning_snapshot=learning_snapshot,
        trade_signal_snapshot=trade_signal_snapshot,
        closed_qty=closed_qty,
        resulting_side=resulting_side,
        resulting_qty=resulting_qty,
    )
    if position.mode == "explore":
        record_exploration_outcome(position.policy, net_pnl, reason, learning_snapshot)

    if exclude_from_risk:
        log(f"⚠️ Excluding {event_type} pnl from risk stats | net={net_pnl:+.0f} | reason={reason}")

    log(
        f"{event_type.upper()} REALIZED | {position.side.upper()} | "
        f"closed={closed_qty:.2f} net={net_pnl:+.0f} gross={gross_pnl:+.0f} fee≈{fee:.0f} | {reason}"
    )
    maybe_save_memory(force=True)


def update_outcome_weighted_memory(position: PositionState, gross_pnl: float, hold_minutes: float, reason: str, fee: float = 0.0):
    """Update past decisions with outcome, including SL/TP and fee"""
    net_pnl = gross_pnl - fee
    outcome = "win" if net_pnl > 0 else "loss"
    updated = False
    _, _, _, _, trade_signal_snapshot = get_runtime_trade_context()

    for decision in reversed(brain.get("past_ai_decisions", [])):
        if (
            decision.get("action") == "open"
            and decision.get("direction") == position.side
            and decision.get("outcome") == "pending"
        ):
            decision["outcome"] = outcome
            decision["gross_pnl"] = round(gross_pnl, 2)
            decision["outcome_pnl"] = round(net_pnl, 2)
            decision["fee"] = round(fee, 2)
            decision["hold_minutes"] = round(hold_minutes, 1)
            decision["exit_reason"] = reason
            decision["sl_price"] = position.sl_price
            decision["tp_price"] = position.tp_price
            decision.update(trade_signal_snapshot)
            updated = True
            break

    if not updated:
        append_past_ai_decision(
            {
                "timestamp": datetime.now().isoformat(),
                "action": "close",
                "direction": position.side,
                "intent": position.intent,
                "mode": position.mode,
                "policy": position.policy,
                "confidence": round(position.confidence, 2),
                "leverage": position.leverage,
                "outcome": outcome,
                "gross_pnl": round(gross_pnl, 2),
                "outcome_pnl": round(net_pnl, 2),
                "fee": round(fee, 2),
                "hold_minutes": round(hold_minutes, 1),
                "exit_reason": reason,
                "sl_price": position.sl_price,
                "tp_price": position.tp_price,
                **trade_signal_snapshot,
            }
        )


def build_post_trade_review_prompt(
    position: PositionState,
    exit_price: float,
    exit_reason: str,
    gross_pnl: float,
    net_pnl: float,
    fee: float,
    hold_minutes: float,
    regime: str,
    signal_ctx: dict[str, Any],
) -> str:
    oracle_insight = get_oracle_regime_insight(regime)
    thesis = get_position_thesis_metrics(position, exit_price)
    close_alignment = compute_close_alignment(
        position,
        thesis,
        exit_price,
        signal_ctx=signal_ctx,
        oracle_insight=oracle_insight,
    )
    predictive_setup_score = float(position.entry_predictive_setup_score or 0.0)
    predictive_setup_summary = str(position.entry_predictive_setup_summary or "n/a")
    predictive_expected_edge = float(position.entry_expected_edge or 0.0)
    return f"""
You just closed a trade. Analyze it and extract lessons.

TRADE SUMMARY:
- Side: {position.side.upper()}
- Entry: {position.entry:.0f}
- Exit: {exit_price:.0f}
- Gross PnL: {gross_pnl:+.0f} sats
- Fee: {fee:.0f} sats
- Net PnL: {net_pnl:+.0f} sats
- Hold Time: {hold_minutes:.1f} minutes
- Intent: {position.intent}
- Confidence: {position.confidence:.2f}
- Exit Reason: {exit_reason}
- SL: {f'{position.sl_price:.0f}' if position.sl_price else 'N/A'}
- TP: {f'{position.tp_price:.0f}' if position.tp_price else 'N/A'}
- Regime: {regime}
- Regime Bias: {brain.get('market_regime', {}).get('bias', 'neutral')}
- Regime Flavor: {brain.get('market_regime', {}).get('regime_flavor', regime)}
- Oracle Replay Bias: {oracle_insight.get('dominant_bias', 'neutral')}
- Oracle Replay Flavor: {oracle_insight.get('dominant_flavor', regime)}
- Oracle Replay Drift: {float(oracle_insight.get('avg_directional_drift', 0.0) or 0.0):+.5f}
- Oracle Replay Signed Trend: {float(oracle_insight.get('avg_signed_trend_strength', 0.0) or 0.0):+.6f}
- Oracle Replay MTF Score: {float(oracle_insight.get('avg_mtf_alignment_score', 0.0) or 0.0):+.2f}
- Entry Expected Edge: {predictive_expected_edge:+.2f}
- Predictive Setup Score: {predictive_setup_score:+.2f}
- Predictive Setup Summary: {predictive_setup_summary}
- Parent Allocation Reason: {brain.get('last_trade', {}).get('parent_allocation_reason', 'n/a')}
- Parent Qty Multiplier: {float(brain.get('last_trade', {}).get('parent_qty_multiplier', 1.0) or 1.0):.2f}
- Parent Risk Multiplier: {float(brain.get('last_trade', {}).get('parent_risk_multiplier', 1.0) or 1.0):.2f}
- Lane Allocation Reason: {brain.get('last_trade', {}).get('tuned_allocation_reason', 'n/a')}
- Entry Level: {position.entry_level_summary}
- Entry Feature Health: {position.entry_feature_health_summary}
- Close Alignment: {float(close_alignment.get('score', 0.0) or 0.0):+.2f}
- Close Alignment Summary: {str(close_alignment.get('component_summary', 'n/a'))}
- Momentum: {brain.get('momentum', 0.0):+.5f}
- Volatility: {brain.get('market_regime', {}).get('volatility', 0.0):.5f}
- Funding Momentum: {signal_ctx.get('funding_momentum', 'stable')}
- Funding Bias: {signal_ctx.get('funding_bias', 'neutral')}
- Session: {signal_ctx.get('session_bucket', 'offhours')}
- Session Bias: {signal_ctx.get('session_bias', 'neutral')}
- Spread Shock: {float(signal_ctx.get('spread_shock', 1.0) or 1.0):.2f}x
- Volatility Expansion: {float(signal_ctx.get('volatility_expansion', 1.0) or 1.0):.2f}x
- Volatility State: {signal_ctx.get('volatility_state', 'normal')}
- MTF Alignment: {signal_ctx.get('mtf_alignment', 'mixed')}
- Range Established: {bool(signal_ctx.get('range_established', False))}
- Range Position: {float(signal_ctx.get('range_position', 0.5) or 0.5):.3f} (0=low edge, 1=high edge)
- Range Width: {float(signal_ctx.get('range_width_pct', 0.0) or 0.0):.4f}
- Range High: {float(signal_ctx.get('range_high', 0.0) or 0.0):.0f}
- Range Low: {float(signal_ctx.get('range_low', 0.0) or 0.0):.0f}
- Range Mid: {float(signal_ctx.get('range_mid', 0.0) or 0.0):.0f}
- Range Threshold long_max: {get_range_long_max():.3f}
- Range Threshold short_min: {get_range_short_min():.3f}
- Momentum 1m: {float(signal_ctx.get('momentum_1m', 0.0) or 0.0):+.5f}
- Momentum 5m: {float(signal_ctx.get('momentum_5m', 0.0) or 0.0):+.5f}
- Momentum 15m: {float(signal_ctx.get('momentum_15m', 0.0) or 0.0):+.5f}
- External Bias: {signal_ctx.get('external_bias', 'neutral')}
- External Conviction: {float(signal_ctx.get('external_conviction', 0.0) or 0.0):+.2f}
- External Summary: {signal_ctx.get('external_component_summary', 'n/a')}
- External Source: {signal_ctx.get('external_source', 'none')}
- External Data Quality: {signal_ctx.get('external_data_quality', 'none')}
- Bitget Long Ratio: {float(signal_ctx.get('bitget_account_long_ratio', 0.5) or 0.5):.3f}
- Bitget Position Ratio: {float(signal_ctx.get('bitget_position_long_ratio', 0.5) or 0.5):.3f}
- Deribit Funding 1h: {float(signal_ctx.get('deribit_funding_1h', 0.0) or 0.0):+.5f}
- Deribit Funding 1h: {float(signal_ctx.get('deribit_funding_1h', 0.0) or 0.0):+.6f}
- Deribit Funding 8h: {float(signal_ctx.get('deribit_funding_8h', 0.0) or 0.0):+.6f}
- Adds: {position.add_count}

Focus lessons on whether the entry respected level map, feature health, fee-clear room, parent allocation, tuner drift guards, and deterministic gates; do not recommend weakening exit gates, parent/tuner allocation rails, live caps, or mixed-lane policy clamps.

Return ONLY valid JSON:
{{
  "summary": "one sentence verdict",
  "key_lessons": ["lesson 1", "lesson 2", "lesson 3"],
  "what_to_improve": "specific advice",
  "regime_insight": "how this fits current regime",
  "confidence_calibration": "was confidence too high/low/accurate?",
  "edge_score": 0.0
}}
"""


def build_trade_lesson(
    position: PositionState,
    exit_reason: str,
    gross_pnl: float,
    net_pnl: float,
    fee: float,
    hold_minutes: float,
    regime: str,
    signal_ctx: dict[str, Any],
    oracle_insight: dict[str, Any],
    chop_alignment: dict[str, Any],
    close_alignment: dict[str, Any],
    parsed: dict[str, Any],
    exit_price: float = 0.0,
) -> dict[str, Any]:
    normalize_trade_attribution(position)
    mc = brain.get("market_context", {})
    lesson = {
        "timestamp": datetime.now().isoformat(),
        "side": position.side,
        "intent": position.intent,
        "policy": position.policy,
        "mode": position.mode,
        "gross_pnl": round(gross_pnl, 0),
        "net_pnl": round(net_pnl, 0),
        "fee": round(fee, 2),
        "hold_minutes": round(hold_minutes, 1),
        "regime": regime,
        "exit_reason": exit_reason,
        "exit_type": classify_exit_type(exit_reason),
        "exit_type_normalized": classify_exit_type_normalized(exit_reason, net_pnl, gross_pnl),
        "sl_price": position.sl_price,
        "tp_price": position.tp_price,
        "entry_price": round(float(position.entry or 0.0), 2),
        "close_price": round(float(exit_price or 0.0), 2),
        "tp_bps": int(position.tp_bps) if hasattr(position, 'tp_bps') and position.tp_bps else None,
        "sl_bps": int(position.sl_bps) if hasattr(position, 'sl_bps') and position.sl_bps else None,
        "summary": parsed.get("summary", ""),
        "key_lessons": parsed.get("key_lessons", []),
        "what_to_improve": parsed.get("what_to_improve", ""),
        "regime_insight": parsed.get("regime_insight", ""),
        "edge_score": float(parsed.get("edge_score", 0.0)),
        "entry_expected_edge": round(float(position.entry_expected_edge or 0.0), 4),
        "entry_predictive_setup_score": round(float(position.entry_predictive_setup_score or 0.0), 4),
        "entry_predictive_setup_summary": position.entry_predictive_setup_summary,
        "range_position_at_entry": float(signal_ctx.get("range_position", mc.get("range_position", 0.5)) or 0.5),
        "range_width_pct": float(signal_ctx.get("range_width_pct", mc.get("range_width_pct", 0.0)) or 0.0),
        "range_established": bool(signal_ctx.get("range_established", mc.get("range_established", False))),
        "entry_nearest_support": round(float(position.entry_nearest_support or 0.0), 2),
        "entry_nearest_resistance": round(float(position.entry_nearest_resistance or 0.0), 2),
        "entry_room_to_target_bps": round(float(position.entry_room_to_target_bps or 0.0), 2),
        "entry_level_alignment": position.entry_level_alignment,
        "entry_level_summary": position.entry_level_summary,
        "entry_feature_health_summary": position.entry_feature_health_summary,
    }
    lesson.update(
        build_trade_signal_snapshot(
            regime=regime,
            signal_ctx=signal_ctx,
            oracle_insight=oracle_insight,
            chop_alignment=chop_alignment,
            close_alignment=close_alignment,
        )
    )
    return lesson


async def post_trade_review(client, position: PositionState, exit_price: float, exit_reason: str, fee: float = 0.0):
    try:
        normalize_trade_attribution(position)
        gross_pnl = position.unrealized_pnl(exit_price)
        net_pnl = gross_pnl - fee
        hold_minutes = position.age_minutes
        regime, signal_ctx, oracle_insight, chop_alignment, _ = get_runtime_trade_context()
        thesis = get_position_thesis_metrics(position, exit_price)
        close_alignment = compute_close_alignment(
            position,
            thesis,
            exit_price,
            signal_ctx=signal_ctx,
            oracle_insight=oracle_insight,
            chop_alignment=chop_alignment,
        )
        prompt = build_post_trade_review_prompt(
            position,
            exit_price,
            exit_reason,
            gross_pnl,
            net_pnl,
            fee,
            hold_minutes,
            regime,
            signal_ctx,
        )
        response = await reason(prompt)
        parsed = extract_json(response) if response else None
        if not parsed:
            log("Post-trade review JSON parse failed")
            return

        lesson = build_trade_lesson(
            position,
            exit_reason,
            gross_pnl,
            net_pnl,
            fee,
            hold_minutes,
            regime,
            signal_ctx,
            oracle_insight,
            chop_alignment,
            close_alignment,
            parsed,
            exit_price=exit_price,
        )
        brain.setdefault("trade_lessons", []).append(lesson)
        brain["trade_lessons"] = brain["trade_lessons"][-50:]
        append_review_report("trade_lesson", lesson)
        log(f"Post-trade review saved | net_pnl={net_pnl:+.0f} | edge={lesson['edge_score']:.2f}")
        maybe_save_memory(force=True)
    except Exception as exc:
        log(f"post_trade_review error: {exc}")


async def synthetic_experience_replay():
    """
    Lightweight incremental update: after each exit, nudge policy_fit_adjustments
    based on the most recently resolved shadow trades. Complements the batch
    tune_exploration_thresholds() run by giving fast signal on fresh outcomes.
    """
    recent_shadow = (brain.get("shadow_exploration", {}) or {}).get("recent", [])[-30:]
    resolved = [item for item in recent_shadow if item.get("resolved_at") is not None]
    if len(resolved) < 2:
        return

    et = get_exploration_thresholds()
    adjustments = dict(et.get("policy_fit_adjustments", {}) or {})
    nudged: list[str] = []

    for item in resolved[-6:]:
        policy = str(item.get("policy", "") or "")
        if not policy:
            continue
        fee_cleared = bool(item.get("fee_cleared", False))
        outcome_bps = float(item.get("outcome_bps", 0.0) or 0.0)
        existing = float(adjustments.get(policy, 0.0) or 0.0)
        # Small asymmetric nudge — bad outcomes push harder than good ones
        if fee_cleared and outcome_bps > 0:
            delta = 0.003
        elif outcome_bps < -8.0:
            delta = -0.007
        elif outcome_bps < 0:
            delta = -0.003
        else:
            delta = 0.001
        new_adj = round(clamp(existing + delta, -0.10, 0.08), 4)
        if new_adj != existing:
            adjustments[policy] = new_adj
            nudged.append(f"{policy} {existing:+.3f}→{new_adj:+.3f}")

    if nudged:
        et["policy_fit_adjustments"] = adjustments


def get_risk_mode() -> str:
    snapshot = get_recent_risk_snapshot()
    recent_loss_ratio = float(snapshot.get("recent_loss_ratio", 0.0))
    daily_loss_ratio = float(snapshot.get("daily_loss_ratio", 0.0))
    consecutive_losses = int(get_effective_consecutive_losses())
    streak = get_risk_streak()

    if brain.get("cooldown_until", 0) > time.time():
        brain["risk_mode"] = "protection"
        return "protection"

    if (
        recent_loss_ratio > RISK_CAUTION_RECENT_LOSS_RATIO
        or daily_loss_ratio > RISK_CAUTION_DAILY_LOSS_RATIO
        or consecutive_losses >= RISK_CAUTION_CONSECUTIVE_LOSSES
        or streak <= RISK_CAUTION_STREAK
    ):
        brain["risk_mode"] = "caution"
        return "caution"
    brain["risk_mode"] = "normal"
    return "normal"


def classify_exit_type(reason: str) -> str:
    if reason == "SL_HIT":
        return "stop_loss"
    if reason == "TP_HIT":
        return "take_profit"
    if reason.startswith("MAX_HOLD"):
        return "max_hold"
    if "AI" in reason.upper():
        return "ai_review"
    return "manual"


def classify_exit_type_normalized(reason: str, net_pnl: float, gross_pnl: float) -> str:
    """Collapse every exit into one of: take_profit, trailed_profit, stop_loss, max_hold,
    thesis_break, ai_review, kill_switch, manual.
    Distinguishes a trailed winner (SL_HIT with positive net) from a real stop-loss loss,
    so the post-TP re-entry edge gate does not fail open on trailed profits."""
    reason_upper = (reason or "").upper()
    if "KILL_SWITCH" in reason_upper:
        return "kill_switch"
    if "TP_HIT" in reason_upper:
        return "take_profit"
    if "SL_HIT" in reason_upper:
        # trailed winner — treat as TP for cooldown/edge-gate purposes
        if float(net_pnl or 0.0) > 0.0 or float(gross_pnl or 0.0) > 0.0:
            return "trailed_profit"
        return "stop_loss"
    if "MAX_HOLD" in reason_upper:
        return "max_hold"
    if "DET_THESIS_BREAK" in reason_upper or "DET_CHOP" in reason_upper or "DET_UNKNOWN" in reason_upper:
        return "thesis_break"
    if "AI" in reason_upper:
        # AI-initiated close can itself be trailing profit or thesis break; keep coarse
        if float(net_pnl or 0.0) >= 50.0:
            return "take_profit"
        return "ai_review"
    return "manual"


def update_fee_tracking(estimated_fee: float) -> float:
    global total_fees_paid, total_trades_with_fees
    total_fees_paid += estimated_fee
    total_trades_with_fees += 1
    avg_fee = total_fees_paid / total_trades_with_fees if total_trades_with_fees > 0 else 0.0
    brain["total_fees_paid"] = total_fees_paid
    brain["total_trades_with_fees"] = total_trades_with_fees
    brain["avg_fee"] = round(avg_fee, 2)
    return avg_fee


def update_closed_trade_stats(
    *,
    position: PositionState,
    now: datetime,
    regime: str,
    net_pnl: float,
    reason: str,
    realized_record: dict[str, Any],
) -> bool:
    is_win = net_pnl > 0
    record_legacy_pnl_history(net_pnl)

    brain["trades"] = int(brain.get("trades", 0)) + 1
    if is_win:
        brain["wins"] = int(brain.get("wins", 0)) + 1
        brain["streak"] = max(1, int(brain.get("streak", 0)) + 1)
    else:
        brain["losses"] = int(brain.get("losses", 0)) + 1
        brain["streak"] = min(-1, int(brain.get("streak", 0)) - 1)

    brain["total_pnl"] = float(brain.get("total_pnl", 0.0)) + net_pnl
    brain["last_exit_reason"] = reason
    brain.setdefault("daily_realized", []).append(realized_record)
    update_daily_pnl()

    refresh_legacy_equity_drawdown(net_pnl)

    regime_stats = brain.setdefault("regime_stats", {}).setdefault(regime, {"trades": 0, "wins": 0, "pnl": 0.0})
    regime_stats["trades"] += 1
    regime_stats["pnl"] += net_pnl
    if is_win:
        regime_stats["wins"] = regime_stats.get("wins", 0) + 1

    intent_stats = brain.setdefault("intent_stats", {}).setdefault(position.intent, {"trades": 0, "wins": 0, "pnl": 0.0, "winrate": 0.0})
    intent_stats["trades"] += 1
    intent_stats["pnl"] += net_pnl
    if is_win:
        intent_stats["wins"] += 1
    intent_stats["winrate"] = intent_stats["wins"] / max(intent_stats["trades"], 1)

    conf_bucket = round(float(position.confidence), 1)
    conf_stats = brain.setdefault("confidence_stats", {}).setdefault(conf_bucket, {"trades": 0, "wins": 0, "pnl": 0.0, "winrate": 0.0})
    conf_stats["trades"] += 1
    conf_stats["pnl"] += net_pnl
    if is_win:
        conf_stats["wins"] += 1
    conf_stats["winrate"] = conf_stats["wins"] / max(conf_stats["trades"], 1)
    return is_win


def finalize_exit_learning(
    *,
    client,
    position: PositionState,
    now: datetime,
    regime: str,
    exit_price: float,
    gross_pnl: float,
    net_pnl: float,
    estimated_fee: float,
    reason: str,
    exit_type: str,
    hold_minutes: float,
    exclude_from_risk: bool,
    exclude_from_protection: bool,
):
    normalize_trade_attribution(position)
    learning_snapshot = build_position_learning_snapshot(position)
    thesis = get_position_thesis_metrics(position, exit_price)
    close_alignment = compute_close_alignment(position, thesis, exit_price)
    trade_signal_snapshot = build_trade_signal_snapshot(regime=regime, close_alignment=close_alignment)
    policy_stats = (
        brain.setdefault("exploration", {})
        .setdefault("policies", {})
        .setdefault(
            position.policy,
            {
                "trades": 0,
                "wins": 0,
                "pnl": 0.0,
                "avg_pnl": 0.0,
                "score": 0.0,
                "last_used_at": None,
                "last_regime": None,
                "fee_clear_rate": 0.0,
                "avg_peak_fee_multiple": 0.0,
                "avg_time_to_mfe_minutes": 0.0,
                "timed_mfe_count": 0,
            },
        )
    )
    is_win = net_pnl > 0
    update_policy_learning_stats(policy_stats, net_pnl, is_win, learning_snapshot, now, regime)
    update_winner_fade_stats(position, learning_snapshot, net_pnl)
    append_exploration_recent_record(
        timestamp=now,
        position=position,
        regime=regime,
        pnl=net_pnl,
        reason=reason,
        exit_type=exit_type,
        exclude_from_risk=exclude_from_risk,
        exclude_from_protection=exclude_from_protection,
        learning_snapshot=learning_snapshot,
        trade_signal_snapshot=trade_signal_snapshot,
    )
    update_behavioral_fitness(position, net_pnl, is_win)
    update_outcome_weighted_memory(position, gross_pnl, hold_minutes, reason, estimated_fee)
    trade_id = position.exchange_order_id or f"local_exit_{int(time.time())}"
    record_exit_to_memory(position, exit_price, gross_pnl, reason, estimated_fee)
    _safe_create_task(post_trade_review(client, position, exit_price, reason, estimated_fee))
    _safe_create_task(track_post_exit_prices(trade_id, exit_price, position.side or "long", reason))
    _safe_create_task(synthetic_experience_replay())
    record_trade_activity(position.mode, exit_type, position.qty)
    append_position_event(
        {
            "timestamp": now.isoformat(),
            "event_type": exit_type,
            "reason": reason,
            "side": position.side,
            "closed_qty": round(position.qty, 4),
            "resulting_side": None,
            "resulting_qty": 0.0,
            "gross_pnl": round(gross_pnl, 2),
            "net_pnl": round(net_pnl, 2),
            "fee": round(estimated_fee, 2),
            "exclude_from_risk": exclude_from_risk,
            "exclude_from_protection": exclude_from_protection,
            "policy": position.policy,
            "mode": position.mode,
        }
    )
    exit_type_normalized = classify_exit_type_normalized(reason, net_pnl, gross_pnl)
    last_exit_payload = build_last_exit_record(
        timestamp=now,
        position=position,
        exit_price=exit_price,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        fee=estimated_fee,
        reason=reason,
        exit_type=exit_type,
        exclude_from_risk=exclude_from_risk,
        exclude_from_protection=exclude_from_protection,
        learning_snapshot=learning_snapshot,
        trade_signal_snapshot=trade_signal_snapshot,
        hold_time_minutes=hold_minutes,
    )
    last_exit_payload["exit_type_normalized"] = exit_type_normalized
    brain["last_exit"] = last_exit_payload
    if position.mode == "explore":
        record_exploration_outcome(position.policy, net_pnl, reason, learning_snapshot)


def register_exit_event(client, position: PositionState, exit_price: float, reason: str):
    """Register exit with gross/net PnL, fee tracking, and running average fee"""
    gross_pnl = position.unrealized_pnl(exit_price)
    estimated_fee = estimate_round_trip_fee_from_position(position)
    net_pnl = gross_pnl - estimated_fee
    now = datetime.now()
    hold_minutes = position.age_minutes
    regime = brain.get("market_regime", {}).get("regime", "unknown")
    avg_fee = update_fee_tracking(estimated_fee)
    exit_type = classify_exit_type(reason)
    exit_type_normalized = classify_exit_type_normalized(reason, net_pnl, gross_pnl)
    realized_record = build_realized_record(now, gross_pnl, net_pnl, estimated_fee, reason, exit_type, position)
    realized_record["exit_type_normalized"] = exit_type_normalized
    exclude_from_risk = bool(realized_record["exclude_from_risk"])
    exclude_from_protection = bool(realized_record.get("exclude_from_protection", False))
    update_closed_trade_stats(
        position=position,
        now=now,
        regime=regime,
        net_pnl=net_pnl,
        reason=reason,
        realized_record=realized_record,
    )
    finalize_exit_learning(
        client=client,
        position=position,
        now=now,
        regime=regime,
        exit_price=exit_price,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        estimated_fee=estimated_fee,
        reason=reason,
        exit_type=exit_type,
        hold_minutes=hold_minutes,
        exclude_from_risk=exclude_from_risk,
        exclude_from_protection=exclude_from_protection,
    )

    if exclude_from_risk:
        log(f"⚠️ Excluding exit pnl from risk stats | net={net_pnl:+.0f} | reason={reason}")

    log(
        f"EXIT | {position.side.upper()} | net={net_pnl:+.0f} (gross={gross_pnl:+.0f}) | "
        f"fee≈{estimated_fee:.0f} | avg_fee={avg_fee:.2f} | type={exit_type} | {reason}"
    )
    maybe_save_memory(force=True)


async def handle_ai_close(client, position: PositionState, reason: str):
    exit_price = float(brain.get("last_price") or position.entry or 0)
    thesis = refresh_position_thesis(position, exit_price)
    clearly_broken, broken_reason = is_clearly_broken_exit(position, thesis, exit_price)
    if not is_hard_exit_reason(reason) and not clearly_broken:
        log(f"CLOSE suppressed by strict exit gate | {reason} | {broken_reason}")
        position.pending_close = False
        return

    log(f"Closing position: {reason}")
    snapshot = PositionState(
        side=position.side,
        entry=position.entry,
        qty=position.qty,
        leverage=position.leverage,
        intent=position.intent,
        confidence=position.confidence,
        mode=position.mode,
        policy=position.policy,
        sl_price=position.sl_price,
        tp_price=position.tp_price,
        trail_buffer_pct=position.trail_buffer_pct,
        opened_at=position.opened_at,
        max_hold_minutes=position.max_hold_minutes,
        add_count=position.add_count,
        status="open",
        exchange_order_id=position.exchange_order_id,
        entry_expected_edge=position.entry_expected_edge,
        entry_predictive_setup_score=position.entry_predictive_setup_score,
        entry_predictive_setup_summary=position.entry_predictive_setup_summary,
        entry_tag=position.entry_tag,
        exit_tag=build_exit_tag(reason, position),
        signal_price=position.signal_price,
        evidence_valid=position.evidence_valid,
        evidence_reason=position.evidence_reason,
        roi_schedule_reason=position.roi_schedule_reason,
    )
    snapshot.entry_nearest_support = position.entry_nearest_support
    snapshot.entry_nearest_resistance = position.entry_nearest_resistance
    snapshot.entry_room_to_target_bps = position.entry_room_to_target_bps
    snapshot.entry_level_alignment = position.entry_level_alignment
    snapshot.entry_level_summary = position.entry_level_summary
    snapshot.entry_feature_health_summary = position.entry_feature_health_summary
    await safe_close_position(client)
    register_exit_event(client, snapshot, exit_price, reason)
    position.reset(reason)


async def handle_pyramiding_add(client, position: PositionState):
    cooldown_until = float(brain.get("add_failure_cooldown_until", 0.0) or 0.0)
    if cooldown_until > time.time():
        log(f"ADD blocked: recent add failure cooldown {int(cooldown_until - time.time())}s")
        return

    can_trade, block_reason = check_drawdown_protection()
    if not can_trade:
        log(f"ADD blocked by drawdown protection: {block_reason}")
        return

    usable = await get_usable_margin(client)
    if usable < 950:
        log(f"ADD blocked: low margin ({usable:.0f})")
        return

    price = float(brain.get("last_price") or position.entry or 0)
    pnl = position.unrealized_pnl(price)
    thesis = refresh_position_thesis(position, price)
    thesis_score = float(thesis.get("score", 0.0) or 0.0)
    close_alignment = compute_close_alignment(position, thesis, price)
    close_align_score = float(close_alignment.get("score", 0.0) or 0.0)
    raw_move_bps = get_raw_entry_move_bps(position, price)
    favorable_move_bps = raw_move_bps if position.side == "long" else -raw_move_bps
    adverse_move_bps = max(0.0, -favorable_move_bps)
    reason_text = str(position.last_reason or "")
    recovery_add = "DYN_RECOVERY_ADD" in reason_text
    dynamic_add = "DYN_PYRAMID" in reason_text or recovery_add
    open_position_override = get_open_position_aggression_override(position, thesis)
    attack_mode = str((brain.get("last_strategic_context", {}) or {}).get("mode", "observe") or "observe") == "attack"
    attack_add_window = bool(attack_mode and thesis_score >= 0.02)
    attack_fee_proven_add = bool(
        attack_mode
        and -0.08 <= thesis_score <= 0.02
        and float(thesis.get("peak_fee_multiple", 0.0) or 0.0) >= 0.40
        and close_align_score > 0.08
    )
    attack_intact_winner_add = bool(
        attack_mode
        and thesis.get("intact")
        and (
            thesis_score >= 0.15
            or (thesis_score >= 0.08 and float(thesis.get("peak_fee_multiple", 0.0) or 0.0) >= 0.50)
        )
    )
    if open_position_override:
        position.mode = "exploit"

    if str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown") == "squeeze":
        if recovery_add:
            log(
                f"ADD blocked: recovery adds disabled in squeeze | "
                f"pnl={pnl:+.0f} thesis={thesis_score:+.2f} adverse={adverse_move_bps:.1f}bps"
            )
            return
        estimated_fee = estimate_round_trip_fee_from_position(position)
        peak_fee_multiple = float(thesis.get("peak_fee_multiple", 0.0) or 0.0)
        if (
            pnl <= estimated_fee
            or favorable_move_bps < 12.0
            or thesis_score < 0.20
            or not thesis.get("intact")
            or peak_fee_multiple < 0.75
        ):
            log(
                f"ADD blocked: squeeze winner not fee-cleared | pnl={pnl:+.0f} "
                f"fee≈{estimated_fee:.0f} favorable={favorable_move_bps:+.1f}bps "
                f"thesis={thesis_score:+.2f} peak_fee={peak_fee_multiple:.2f}"
            )
            return

    if pnl <= -50:
        log("ADD blocked: unrealized loss too large")
        return
    if position.age_minutes > ADD_TRUE_STALE_MINUTES:
        log(
            f"ADD blocked: position truly stale | "
            f"age={position.age_minutes:.1f}m limit={ADD_TRUE_STALE_MINUTES:.0f}m "
            f"thesis={thesis_score:+.2f}"
        )
        return
    add_confidence_floor = (
        RECOVERY_ADD_CONFIDENCE_FLOOR
        if recovery_add
        else get_add_confidence_floor(thesis, favorable_move_bps, position.age_minutes)
    )
    if position.confidence < add_confidence_floor:
        log(
            f"ADD blocked: confidence too low ({position.confidence:.2f} "
            f"< {add_confidence_floor:.2f})"
        )
        return
    if recovery_add:
        close_alignment = compute_close_alignment(position, thesis, price)
        close_align_score = float(close_alignment.get("score", 0.0) or 0.0)
        clearly_broken, broken_reason = is_clearly_broken_exit(position, thesis, price)
        if clearly_broken or not thesis.get("intact"):
            log(f"ADD blocked: recovery thesis no longer intact | {broken_reason}")
            return
        if thesis_score < RECOVERY_ADD_MIN_THESIS_SCORE:
            log(f"ADD blocked: recovery thesis score {thesis_score:+.2f} < {RECOVERY_ADD_MIN_THESIS_SCORE:+.2f}")
            return
        if not (RECOVERY_ADD_MIN_ADVERSE_BPS <= adverse_move_bps <= RECOVERY_ADD_MAX_ADVERSE_BPS):
            log(
                f"ADD blocked: recovery adverse move outside ladder | "
                f"adverse={adverse_move_bps:.1f}bps range={RECOVERY_ADD_MIN_ADVERSE_BPS:.1f}-{RECOVERY_ADD_MAX_ADVERSE_BPS:.1f}"
            )
            return
        if close_align_score > RECOVERY_ADD_MAX_CLOSE_ALIGN:
            log(
                f"ADD blocked: recovery close pressure too high | "
                f"close_align={close_align_score:+.2f} max={RECOVERY_ADD_MAX_CLOSE_ALIGN:+.2f}"
            )
            return
    elif (
        thesis_score < 0.02
        and not (thesis_score >= 0.00 and float(thesis.get("peak_fee_multiple", 0.0) or 0.0) >= 0.40)
        and not (thesis_score >= -0.05 and float(thesis.get("peak_fee_multiple", 0.0) or 0.0) > 0.45 and close_align_score > 0.10)
        and not attack_add_window
        and not attack_fee_proven_add
    ):
        log(
            f"ADD blocked: thesis score {thesis_score:+.2f} below winner-add floor | "
            f"floor=+0.02 fee_proven={attack_fee_proven_add}"
        )
        return
    elif (
        favorable_move_bps < get_winner_add_min_move_bps(thesis, position.age_minutes)
        and not (favorable_move_bps > 4.0 or close_align_score > 0.12)
    ):
        log(
            f"ADD blocked: move not strong enough | "
            f"raw_move={raw_move_bps:+.1f}bps favorable={favorable_move_bps:+.1f}bps "
            f"floor={get_winner_add_min_move_bps(thesis, position.age_minutes):.1f}bps"
        )
        return
    aggressive_squeeze_add = bool(
        not dynamic_add
        and str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown") == "squeeze"
        and thesis.get("intact")
        and thesis_score >= 0.04
        and float(thesis.get("fee_ratio", 0.0) or 0.0) >= 0.10
        and float(thesis.get("peak_fee_multiple", 0.0) or 0.0) >= 0.10
        and float(thesis.get("predictive_align", 0.0) or 0.0) >= 0.10
    )
    if (
        not aggressive_squeeze_add
        and not dynamic_add
        and str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown") == "squeeze"
        and thesis.get("intact")
        and thesis_score >= 0.02
        and close_align_score > 0.10
        and float(thesis.get("peak_fee_multiple", 0.0) or 0.0) > 0.30
    ):
        aggressive_squeeze_add = True
    if not aggressive_squeeze_add and attack_fee_proven_add:
        aggressive_squeeze_add = True
    aggressive_squeeze_add = bool(aggressive_squeeze_add or open_position_override)
    if not dynamic_add and not thesis.get("add_ready") and not aggressive_squeeze_add and not attack_intact_winner_add:
        log(
            f"ADD blocked: thesis not improved enough | "
            f"score={thesis.get('score', 0.0):+.2f} fee_ratio={thesis.get('fee_ratio', 0.0):+.2f}"
        )
        return
    max_add_count = get_max_add_count(position, thesis)
    if position.add_count >= max_add_count:
        log("ADD blocked: max adds reached")
        return
    available_add_qty = int(max(0.0, float(MAX_QTY) - float(position.qty or 0.0)))
    if available_add_qty < 1:
        log(f"ADD blocked: position already at max qty {MAX_QTY}")
        return
    margin_add_cap = min(available_add_qty, estimate_add_margin_capped_qty(usable, int(position.leverage or DEFAULT_LEVERAGE)))
    if margin_add_cap < 1:
        log(
            f"ADD blocked: insufficient add margin | usable={usable:.0f} "
            f"reserve={ADD_MARGIN_RESERVE_SATS:.0f} qty={position.qty:.2f}"
        )
        brain["add_failure_cooldown_until"] = time.time() + ADD_FAILURE_COOLDOWN_SECONDS
        return

    momentum = float(brain.get("momentum", 0.0))
    if position.side == "long" and momentum < -0.0005:
        log("ADD blocked: strong bearish momentum for long")
        return
    if position.side == "short" and momentum > 0.0005:
        log("ADD blocked: strong bullish momentum for short")
        return

    risk_probe = EntrySignal(
        action="add",
        direction=position.side or "",
        intent=position.intent,
        mode=position.mode,
        policy=position.policy,
        confidence=position.confidence,
        sl_bps=120,
        tp_bps=240,
        trail_bps=0,
        leverage=int(position.leverage or DEFAULT_LEVERAGE),
        max_hold_minutes=int(position.max_hold_minutes or 60),
        risk_per_trade=float(brain.get("current_risk_per_trade", RISK_PER_TRADE) or RISK_PER_TRADE),
        reason=position.last_reason or "dynamic_pyramid",
    )
    risk_probe.add_winner_override = bool(
        thesis.get("intact")
        and (
            bool(thesis.get("add_ready"))
            or float(thesis.get("peak_fee_multiple", 0.0) or 0.0) >= 0.35
        )
        and float(thesis.get("fee_ratio", 0.0) or 0.0) > 0.0
    )
    risk_probe.base_risk_per_trade = risk_probe.risk_per_trade
    risk_probe.effective_risk_per_trade = risk_probe.risk_per_trade
    allowed, gate_reason = risk_gate(risk_probe, usable)
    if (
        not allowed
        and bool(getattr(risk_probe, "add_winner_override", False))
        and isinstance(gate_reason, str)
        and gate_reason.startswith("Consecutive loss guard active")
    ):
        allowed = True
    if not allowed:
        log(f"ADD blocked by risk gate: {gate_reason}")
        return

    original_qty = max(1.0, float(position.original_qty or position.qty or 1.0))
    min_add = max(1, int(original_qty * 0.75))
    max_add = max(min_add, int(original_qty * 1.25))
    requested_size = int(position.pending_add_qty or 0)
    if recovery_add:
        recovery_cap = max(1, int(original_qty * max(0.20, 0.34 - position.add_count * 0.07)))
        size = min(requested_size or recovery_cap, recovery_cap)
    elif requested_size > 0:
        # Re-score the requested size against current thesis strength before accepting it
        if thesis_score >= 0.40 and favorable_move_bps >= ADD_MOVE_BPS_THRESHOLD * 1.4:
            size = min(max(requested_size, min_add), max_add)   # strong runner: honour full request
        elif thesis_score >= 0.20 and favorable_move_bps >= ADD_MOVE_BPS_THRESHOLD:
            size = min(requested_size, max(1, int(original_qty * 0.75)))  # decent winner: press harder
        else:
            size = 1   # marginal thesis: clamp to 1 regardless of request
    else:
        if thesis_score >= 0.40 and favorable_move_bps >= ADD_MOVE_BPS_THRESHOLD * 1.4:
            size = max_add
        elif thesis_score >= 0.20 and favorable_move_bps >= ADD_MOVE_BPS_THRESHOLD:
            size = max(1, int(original_qty * 0.75))
        else:
            size = 1
    if size > margin_add_cap:
        log(
            f"ADD size capped by margin | requested={size} cap={margin_add_cap} "
            f"usable={usable:.0f} qty={position.qty:.2f}"
        )
    size = min(size, margin_add_cap)
    if size < 1:
        log(f"ADD blocked: margin cap below 1 | usable={usable:.0f} qty={position.qty:.2f}")
        brain["add_failure_cooldown_until"] = time.time() + ADD_FAILURE_COOLDOWN_SECONDS
        return
    side = "buy" if position.side == "long" else "sell"
    try:
        order_payload = {
            "type": "market",
            "side": side,
            "quantity": size,
            "client_id": f"pyramid-add-{int(time.time() * 1000)}-{random.randint(1000, 9999)}",
        }
        log(
            f"ADD ORDER | side={side} qty={size} "
            f"lev={int(position.leverage or DEFAULT_LEVERAGE)} client_id={order_payload['client_id']}"
        )
        await client.futures.cross.new_order(order_payload)

        await asyncio.sleep(2.0)
        await verify_position_with_exchange(client, position)

        position.add_count += 1
        position.last_scale_action_at = datetime.now()
        position.last_add_at = datetime.now()

        # Fix 3: back off trail SL by one buffer-width so the expanded position
        # isn't immediately sitting on the wire after the add.
        if position.trail_buffer_pct and position.sl_price and position.entry:
            sl_relief = float(position.entry) * float(position.trail_buffer_pct)
            if position.side == "long":
                position.sl_price = max(0.0, position.sl_price - sl_relief)
            else:
                position.sl_price = position.sl_price + sl_relief
            log(f"ADD: SL backed off by {sl_relief:.0f} → {position.sl_price:.0f}")

        brain.setdefault("adds", []).append({
            "timestamp": datetime.now().isoformat(),
            "size": size,
            "price": price,
            "pnl_at_add": round(pnl, 0),
            "thesis_score": round(thesis_score, 3),
            "raw_move_bps": round(raw_move_bps, 2),
            "synced_qty": round(position.qty, 4),
            "synced_entry": round(position.entry or 0.0, 2),
        })
        brain["adds"] = brain["adds"][-100:]
        append_position_event(
            {
                "timestamp": datetime.now().isoformat(),
                "event_type": "add",
                "reason": position.last_reason or "main_loop_add",
                "side": position.side,
                "added_qty": round(size, 4),
                "resulting_side": position.side,
                "resulting_qty": round(position.qty, 4),
                "entry_price": round(position.entry or 0.0, 2),
                "thesis_score": round(thesis_score, 3),
                "raw_move_bps": round(raw_move_bps, 2),
                "policy": position.policy,
                "mode": position.mode,
            }
        )
        append_memory_history(
            {
                "id": f"add_{int(time.time())}",
                "time": datetime.now().isoformat(),
                "event_type": "add",
                "side": position.side,
                "added_qty": round(size, 4),
                "resulting_side": position.side,
                "resulting_qty": round(position.qty, 4),
                "entry_price": round(position.entry or 0.0, 2),
                "reason": position.last_reason or "main_loop_add",
                "intent": position.intent,
                "mode": position.mode,
                "policy": position.policy,
                "confidence": round(position.confidence, 2),
                "leverage": position.leverage,
                "source": "position_adjustment",
            }
        )
        record_trade_activity(position.mode, "add", size)
        append_decision_event(
            action="add",
            direction=position.side,
            quantity=size,
            intent=position.intent,
            mode=position.mode,
            policy=position.policy,
            confidence=position.confidence,
            leverage=position.leverage,
            reason=position.last_reason or "main_loop_add",
            extra={
                "resulting_side": position.side,
                "resulting_qty": round(position.qty, 4),
                "entry_price": round(position.entry or 0.0, 2),
            },
        )
        brain["last_decision"] = {
            "timestamp": datetime.now().isoformat(),
            "action": "add",
            "direction": position.side,
            "intent": position.intent,
            "mode": position.mode,
            "policy": position.policy,
            "confidence": position.confidence,
            "leverage": position.leverage,
            "tp_bps": None,
            "sl_bps": None,
            "trail_bps": None,
            "max_hold": position.max_hold_minutes,
            "reason": position.last_reason or "main_loop_add",
        }
        persist_open_position_plan(position)
        maybe_save_memory(force=True)

        log(
            f"ADD executed | size={size} | total adds={position.add_count} | "
            f"synced_qty={position.qty:.2f} | synced_entry={position.entry or 0:.1f} | pnl_at_add={pnl:+.0f}"
        )

    except Exception as exc:
        log(f"ADD failed: {exc}")
        brain["add_failure_cooldown_until"] = time.time() + ADD_FAILURE_COOLDOWN_SECONDS
        maybe_save_memory(force=True)


async def handle_reduce_or_reverse(
    client,
    position: PositionState,
    action: str,
    direction: str,
    quantity: float,
    reason: str,
):
    if not position.is_open:
        log(f"{action.upper()} blocked: no open position")
        return

    if direction == position.side:
        log(
            f"{action.upper()} blocked: direction must oppose current position | "
            f"signal={direction} position={position.side}"
        )
        return

    size = max(1, int(quantity))
    current_qty = max(1, int(position.qty))
    current_price = float(brain.get("last_price") or position.entry or 0.0)
    current_gross_pnl = position.unrealized_pnl(current_price)
    thesis = refresh_position_thesis(position, current_price)
    clearly_broken, broken_reason = is_clearly_broken_exit(position, thesis, current_price)
    scale_out_profit_lock = bool(
        action == "reduce"
        and "DYN_SCALE_OUT" in str(reason)
        and current_gross_pnl >= estimate_round_trip_fee_from_position(position) * SCALE_OUT_MIN_FEE_RATIO
    )
    rebound_scale_out_lock = bool(
        action == "reduce"
        and "DYN_REBOUND_SCALE_OUT" in str(reason)
        and current_gross_pnl >= estimate_round_trip_fee_from_position(position) * REBOUND_SCALE_OUT_MIN_FEE_RATIO
    )
    early_scale_out_lock = bool(
        action == "reduce"
        and "DYN_EARLY_PARTIAL_SCALE_OUT" in str(reason)
        and current_gross_pnl >= estimate_round_trip_fee_from_position(position) * EARLY_PARTIAL_SCALE_OUT_FEE_RATIO
    )
    rebalance_reduce_lock = bool(
        action == "reduce"
        and "DYN_REBALANCE_REDUCE" in str(reason)
    )
    rebalance_reverse_lock = bool(
        action == "reverse"
        and "DYN_REBALANCE_CROSS" in str(reason)
    )

    if action == "reduce" and size > current_qty:
        log(f"REDUCE blocked: qty {size} exceeds current position {current_qty}")
        return

    if action == "reverse" and size <= current_qty:
        log(f"REVERSE blocked: qty {size} must exceed current position {current_qty}")
        return

    if action == "reverse" and not rebalance_reverse_lock:
        log(f"REVERSE suppressed: only deterministic net-rebalance cross may reverse while open | {reason}")
        return

    if action == "reduce" and not clearly_broken and not scale_out_profit_lock and not rebound_scale_out_lock and not early_scale_out_lock and not rebalance_reduce_lock:
        log(
            f"REDUCE suppressed by strict exit gate | qty={size} current_qty={current_qty} "
            f"gross={current_gross_pnl:+.0f} | {broken_reason} | "
            f"{format_strict_exit_requirement()} | {reason}"
        )
        position.last_scale_action_at = datetime.now()
        persist_open_position_plan(position)
        return

    if action == "reduce" and size >= current_qty:
        if should_block_fee_dominated_reduce(position, current_gross_pnl, size):
            log(
                f"REDUCE->CLOSE suppressed: fee-dominated | qty={size} current_qty={current_qty} "
                f"gross={current_gross_pnl:+.0f} | {reason}"
            )
            position.last_scale_action_at = datetime.now()
            persist_open_position_plan(position)
            return
        log(f"REDUCE qty={size} equals/exceeds current qty={current_qty}; converting to full close")
        await handle_ai_close(client, position, f"{reason} | reduce->close")
        return

    if (
        action == "reduce"
        and not scale_out_profit_lock
        and not rebound_scale_out_lock
        and not early_scale_out_lock
        and should_block_fee_dominated_reduce(position, current_gross_pnl, size)
    ):
        log(
            f"REDUCE suppressed: fee-dominated | qty={size} current_qty={current_qty} "
            f"gross={current_gross_pnl:+.0f} | {reason}"
        )
        position.last_scale_action_at = datetime.now()
        persist_open_position_plan(position)
        return

    side = "buy" if direction == "long" else "sell"

    try:
        exit_price = float(brain.get("last_price") or position.entry or 0.0)
        order_qty = int(size)
        order_lev = int(position.leverage or DEFAULT_LEVERAGE)
        snapshot = PositionState(
            side=position.side,
            entry=position.entry,
            qty=position.qty,
            leverage=position.leverage,
            intent=position.intent,
            confidence=position.confidence,
            mode=position.mode,
            policy=position.policy,
            sl_price=position.sl_price,
            tp_price=position.tp_price,
            trail_buffer_pct=position.trail_buffer_pct,
            opened_at=position.opened_at,
            max_hold_minutes=position.max_hold_minutes,
            add_count=position.add_count,
            status="open",
            exchange_order_id=position.exchange_order_id,
            entry_expected_edge=position.entry_expected_edge,
            entry_predictive_setup_score=position.entry_predictive_setup_score,
            entry_predictive_setup_summary=position.entry_predictive_setup_summary,
        )
        log(f"{action.upper()} ORDER | side={side} qty={order_qty} lev={order_lev}")
        await client.futures.cross.new_order(
            {
                "type": "market",
                "side": side,
                "quantity": order_qty,
                "leverage": order_lev,
            }
        )

        await asyncio.sleep(2.0)
        was_side = position.side
        was_qty = position.qty
        await verify_position_with_exchange(client, position)

        closed_qty = min(float(size), float(was_qty))
        resulting_side = position.side if position.is_open else None
        resulting_qty = position.qty if position.is_open else 0.0
        crossed_net = bool(action == "reverse" and resulting_side and resulting_side != was_side)

        if not position.is_open:
            register_exit_event(client, snapshot, exit_price, reason)
        else:
            register_partial_realization(
                snapshot,
                exit_price,
                reason,
                closed_qty=closed_qty,
                event_type=action,
                resulting_side=resulting_side,
                resulting_qty=resulting_qty,
            )
            if action == "reduce":
                position.scale_out_count += 1
                position.last_scale_action_at = datetime.now()
                if "DYN_REBALANCE_REDUCE" in str(reason):
                    position.add_count = 0
                persist_open_position_plan(position)
            elif crossed_net:
                structure = brain.get("broader_structure") or {}
                new_intent, new_policy = get_structure_trade_identity(str(resulting_side), structure)
                position.intent = new_intent
                position.policy = new_policy
                position.mode = "exploit"
                position.confidence = float(structure.get("confidence", position.confidence) or position.confidence)
                position.original_qty = float(resulting_qty or position.qty or 0.0)
                position.add_count = 0
                position.scale_out_count = 0
                position.opened_at = datetime.now()
                position.best_price = position.entry
                position.worst_price = position.entry
                position.max_unrealized_pnl = 0.0
                position.min_unrealized_pnl = 0.0
                position.time_to_mfe_minutes = None
                position.time_to_mae_minutes = None
                position.last_scale_action_at = datetime.now()
                position.last_reason = reason
                log(
                    f"NET REBALANCE CROSSED | old={was_side}/{was_qty:.2f} "
                    f"new={position.side}/{position.qty:.2f} intent={new_intent} policy={new_policy}"
                )
                persist_open_position_plan(position)
        append_decision_event(
            action=action,
            direction=direction,
            quantity=size,
            intent=snapshot.intent,
            mode=snapshot.mode,
            policy=snapshot.policy,
            confidence=snapshot.confidence,
            leverage=snapshot.leverage,
            reason=reason,
            extra={
                "before_side": was_side,
                "before_qty": round(was_qty, 4),
                "resulting_side": resulting_side,
                "resulting_qty": round(resulting_qty, 4),
            },
        )
        brain["last_decision"] = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "direction": direction,
            "intent": snapshot.intent,
            "mode": snapshot.mode,
            "policy": snapshot.policy,
            "confidence": snapshot.confidence,
            "leverage": snapshot.leverage,
            "tp_bps": None,
            "sl_bps": None,
            "trail_bps": None,
            "max_hold": snapshot.max_hold_minutes,
            "reason": reason,
        }

        log(
            f"{action.upper()} executed | qty={size} | "
            f"before={was_side}/{was_qty:.2f} after={position.side or 'flat'}/{position.qty:.2f} | "
            f"{reason}"
        )
    except Exception as exc:
        log(f"{action.upper()} failed: {exc}")


async def monitor_position(client, position: PositionState):
    log("monitor_position started")
    try:
        while position.is_open:
            price = float(brain.get("last_price") or 0)
            if not price:
                await asyncio.sleep(2)
                continue

            thesis = refresh_position_thesis(position, price)

            if position.pending_close:
                await handle_ai_close(client, position, f"AI_REVIEW: {position.last_reason}")
                return
            if position.pending_add:
                position.pending_add = False
                await handle_pyramiding_add(client, position)
                position.pending_add_qty = 0.0
            if position.pending_reduce:
                qty = position.pending_reduce_qty
                position.pending_reduce = False
                position.pending_reduce_qty = 0.0
                await handle_reduce_or_reverse(client, position, "reduce", "long" if position.side == "short" else "short", qty, position.last_reason)
            if position.pending_reverse:
                qty = position.pending_reverse_qty
                direction = position.pending_reverse_direction
                position.pending_reverse = False
                position.pending_reverse_qty = 0.0
                position.pending_reverse_direction = None
                await handle_reduce_or_reverse(client, position, "reverse", direction or "", qty, position.last_reason)
                continue

            previous_sl = position.sl_price
            previous_tp = position.tp_price
            position.update_trail(price)
            winner_lock_reason = apply_fee_clear_winner_protection(position, thesis, price)
            if winner_lock_reason:
                log(f"🔒 WINNER PROTECTION: {winner_lock_reason}")
            if position.sl_price != previous_sl or position.tp_price != previous_tp:
                persist_open_position_plan(position)
                maybe_save_memory(force=True)

            deterministic_action = deterministic_position_action(position, price)
            if deterministic_action:
                reason = deterministic_action.get("reason", "DET_POSITION_RULE")
                secs_since_add = (
                    (datetime.now() - position.last_add_at).total_seconds()
                    if position.last_add_at else float("inf")
                )
                if (
                    secs_since_add < POST_ADD_GRACE_SECONDS
                    and "DET_THESIS_BREAK" in reason
                ):
                    log(
                        f"POST-ADD GRACE: {reason} suppressed | "
                        f"{secs_since_add:.0f}s since last add (grace={POST_ADD_GRACE_SECONDS}s)"
                    )
                else:
                    close_alignment = deterministic_action.get("close_alignment") or compute_close_alignment(position, thesis, price)
                    log(
                        f"Deterministic position rule triggered | {reason} | "
                        f"close_align={float(close_alignment.get('score', 0.0) or 0.0):+.2f} | "
                        f"{str(close_alignment.get('component_summary', 'n/a'))}"
                    )
                    if deterministic_action.get("action") == "close":
                        await handle_ai_close(client, position, reason)
                        return

            confirmed_exit, exit_reason = confirm_live_exit(position, thesis, price, "DET_THESIS_BREAK")
            if confirmed_exit:
                secs_since_add = (
                    (datetime.now() - position.last_add_at).total_seconds()
                    if position.last_add_at else float("inf")
                )
                if secs_since_add < POST_ADD_GRACE_SECONDS:
                    log(
                        f"POST-ADD GRACE: {exit_reason} suppressed | "
                        f"{secs_since_add:.0f}s since last add (grace={POST_ADD_GRACE_SECONDS}s)"
                    )
                else:
                    cross_action = get_net_rebalance_action(position, thesis, price, allow_cross=True)
                    if cross_action and cross_action.get("action") == "reverse":
                        target_direction = str(cross_action.get("direction") or "")
                        target_qty = int(cross_action.get("target_qty") or 1)
                        structure = dict(cross_action.get("structure") or brain.get("broader_structure") or {})
                        usable = await get_usable_margin(client)
                        probe = build_net_rebalance_entry_probe(target_direction, structure, target_qty)
                        level_block = get_candidate_level_block_reason(probe.direction, probe.intent, probe.policy)
                        entry_ok, entry_reason = confirm_live_entry(probe, usable)
                        risk_ok, risk_reason = risk_gate(probe, usable)
                        if level_block:
                            log(f"Net rebalance cross blocked by level gate | {level_block}")
                        elif not entry_ok:
                            log(f"Net rebalance cross blocked by entry confirm | {entry_reason}")
                        elif not risk_ok:
                            log(f"Net rebalance cross blocked by risk gate | {risk_reason}")
                        else:
                            position.pending_reverse = True
                            position.pending_reverse_direction = target_direction
                            position.pending_reverse_qty = float(cross_action.get("quantity") or 0.0)
                            position.last_reason = str(cross_action.get("reason") or f"DYN_REBALANCE_CROSS | {exit_reason}")
                            log(
                                f"Net rebalance cross queued | direction={target_direction} "
                                f"order_qty={position.pending_reverse_qty:.0f} target_qty={target_qty} | "
                                f"{entry_reason}"
                            )
                            continue
                    log(f"Confirmed strict exit | {exit_reason}")
                    await handle_ai_close(client, position, exit_reason)
                    return
            elif "DET_THESIS_BREAK observed" in exit_reason:
                log(f"Strict exit watch | {exit_reason}")

            rebalance_action = get_net_rebalance_action(position, thesis, price, allow_cross=False)
            if rebalance_action and rebalance_action.get("action") == "reduce":
                position.pending_reduce = True
                position.pending_reduce_qty = float(rebalance_action.get("quantity") or 0.0)
                position.last_reason = str(rebalance_action.get("reason") or "DYN_REBALANCE_REDUCE")
                log(
                    f"Net rebalance reduce queued | qty={position.pending_reduce_qty:.0f} | "
                    f"{position.last_reason}"
                )
                await asyncio.sleep(2)
                continue

            dynamic_action = get_dynamic_position_management_action(position, thesis, price)
            if dynamic_action and dynamic_action.get("action") == "add":
                cooldown_until = float(brain.get("add_failure_cooldown_until", 0.0) or 0.0)
                if cooldown_until > time.time():
                    log(f"Dynamic pyramid suppressed | add_failure_cooldown={int(cooldown_until - time.time())}s")
                else:
                    position.pending_add = True
                    position.pending_add_qty = float(dynamic_action.get("quantity") or 0.0)
                    position.last_reason = str(dynamic_action.get("reason") or "DYN_PYRAMID")
                    log(
                        f"Dynamic pyramid queued | qty={position.pending_add_qty:.0f} | "
                        f"{position.last_reason}"
                    )
            elif dynamic_action and dynamic_action.get("action") == "reduce":
                position.pending_reduce = True
                position.pending_reduce_qty = float(dynamic_action.get("quantity") or 0.0)
                position.last_reason = str(dynamic_action.get("reason") or "DYN_SCALE_OUT")
                log(
                    f"Dynamic scale-out queued | qty={position.pending_reduce_qty:.0f} | "
                    f"{position.last_reason}"
                )

            if position.sl_price:
                sl_hit = (position.side == "long" and price <= position.sl_price) or (position.side == "short" and price >= position.sl_price)
                if sl_hit:
                    await handle_ai_close(client, position, "SL_HIT")
                    return

            if position.tp_price:
                tp_hit = (position.side == "long" and price >= position.tp_price) or (position.side == "short" and price <= position.tp_price)
                if tp_hit:
                    await handle_ai_close(client, position, "TP_HIT")
                    return

            if position.max_hold_minutes and position.age_minutes >= position.max_hold_minutes:
                should_close, hold_reason = should_close_on_max_hold(position, thesis, price)
                if should_close:
                    await handle_ai_close(client, position, hold_reason)
                    return

            if int(time.time() / 30) != int((time.time() - 2.0) / 30):
                close_alignment = compute_close_alignment(position, thesis, price)
                raw_move_bps = get_raw_entry_move_bps(position, price)
                add_status = str(thesis["add_ready"]).lower()
                if str((brain.get("last_strategic_context", {}) or {}).get("mode", "observe") or "observe") == "attack" and thesis["add_ready"]:
                    add_status = "ready_attack"
                log(
                    f"THESIS | score={thesis['score']:+.2f} intact={thesis['intact']} add_ready={add_status} "
                    f"move={thesis['entry_move_bps']:+.1f}bps raw={raw_move_bps:+.1f}bps "
                    f"mfe={thesis['mfe_bps']:.1f} mae={thesis['mae_bps']:.1f} "
                    f"q_now={thesis['quality_now']:.2f} dq={thesis['quality_delta']:+.2f} fee_ratio={thesis['fee_ratio']:+.2f} "
                    f"peak_fee={thesis.get('peak_fee_multiple', 0.0):+.2f} "
                    f"close_align={float(close_alignment.get('score', 0.0) or 0.0):+.2f} "
                    f"adds={position.add_count}/{get_max_add_count(position, thesis)} scales={position.scale_out_count}/{MAX_SCALE_OUT_COUNT} "
                    f"t_mfe={thesis.get('time_to_mfe_minutes', 0.0) or 0.0:.1f}m "
                    f"mom_d={thesis.get('momentum_turn', 0.0):+.2f} imb_d={thesis.get('imbalance_turn', 0.0):+.2f}"
                )

            await asyncio.sleep(2)
    except asyncio.CancelledError:
        log("monitor_position cancelled")
    except Exception as exc:
        log(f"monitor_position error: {exc}")
        brain["last_monitor_error"] = {"error": str(exc), "timestamp": datetime.now().isoformat()}


def _build_active_gates_section(regime: str) -> str:
    # Fee-kill status
    recent_chop = [t for t in brain.get("trade_lessons", [])[-12:] if str(t.get("regime", "")) == "chop"][-8:]
    if len(recent_chop) >= 5:
        fee_only = sum(1 for t in recent_chop if float(t.get("net_pnl", 0) or 0) < -80 and abs(float(t.get("gross_pnl", 0) or 0)) < 10)
        fee_kill_active = fee_only / len(recent_chop) >= get_fee_kill_ratio()
        fee_kill_str = f"ACTIVE — {fee_only}/{len(recent_chop)} recent chop trades are fee-only losses" if fee_kill_active else f"inactive ({fee_only}/{len(recent_chop)} fee-only)"
    else:
        fee_kill_active = False
        fee_kill_str = f"inactive (insufficient data: {len(recent_chop)} chop lessons)"

    # Oracle score
    oracle = get_oracle_regime_insight(regime)
    oracle_score = float(oracle.get("score", 0.0) or 0.0)
    oracle_samples = int(oracle.get("samples", 0) or 0)
    oracle_fcr = float(oracle.get("fee_clear_rate", 0.0) or 0.0)
    oracle_gate = ORACLE_SCORE_HARD_BLOCK
    oracle_str = f"{oracle_score:.3f} (gate={oracle_gate:.2f}, samples={oracle_samples}, fcr={oracle_fcr:.2f}) — {'PASS' if oracle_score >= oracle_gate else 'BLOCK'}"

    # Regime stability
    recent_regimes = [x.get("regime") for x in brain.get("regime_history", [])[-5:] if isinstance(x, dict)]
    last_3 = recent_regimes[-3:] if len(recent_regimes) >= 3 else recent_regimes
    stable = len(last_3) >= 3 and all(r == regime for r in last_3)
    stability_str = f"STABLE (last 3: {last_3})" if stable else f"UNSTABLE (last 3: {last_3}) — bot will wait for stability"

    range_note = (
        f"Range-edge override available: long if range_pos < {get_range_long_max():.2f}, short if range_pos > {get_range_short_min():.2f} with strong alignment."
        if fee_kill_active else ""
    )
    exploration_thresholds = get_exploration_thresholds()
    allocation_caps = exploration_thresholds.get("allocation_caps", {}) or {}
    top_lane = exploration_thresholds.get("top_lane", {}) or {}
    top_lane_drift_reason = get_top_lane_drift_guard_reason(top_lane)
    top_lane_note = (
        f"frozen {top_lane.get('lane_key')} ({top_lane_drift_reason})"
        if top_lane and top_lane_drift_reason
        else f"active {get_best_exploration_lane().get('lane_key')}" if get_best_exploration_lane() else "none"
    )

    return f"""Fee-kill: {fee_kill_str}
Oracle score: {oracle_str}
Regime stability: {stability_str}
Fee per trade est: ~20bps round-trip — TP must be at least 50bps to be viable.
Strategic mandate: default aggressive toward account growth, daily profit, and leaderboard climb when risk_mode is normal and broader structure supports action; do not let one tactical win/loss override the strategic market view.
Tuner gate: obey learned min_score={float(exploration_thresholds.get('min_score', 0.0) or 0.0):.2f}, min_edge={float(exploration_thresholds.get('min_edge', 0.0) or 0.0):.2f}, qty/risk caps={float(allocation_caps.get('qty_multiplier_max', 1.0) or 1.0):.2f}x/{float(allocation_caps.get('risk_multiplier_max', 1.0) or 1.0):.2f}x; top lane={top_lane_note}.
Leverage gate: deterministic leverage is chosen by setup quality, alignment, regime, and risk mode. Excellent aligned setups can reach 18-20x, good aligned setups 10-15x, normal setups 5-8x, and caution/protection stays 1-3x.
Exposure budget: final quantity is capped by snapped sizing balance, deterministic exposure_budget, and margin buffer; do not request manual quantity/leverage to bypass this.
Feature warmup: after restart, entries wait until price/momentum/oracle/market-context data are warmed and current.
Stuck positions: unstuck/reduce logic is report-only unless strict exit/reduce gates separately authorize action.
Recovery ladder: deterministic management may add small size into a moderate adverse move only when thesis_intact, close pressure is low, and all risk/margin rails still pass; it may then scale out partial size faster on rebound.
Net-position rebalance: opposite-side orders are allowed as deterministic exposure steering. They may reduce wrong-side exposure before full exit, but crossing through zero requires strict thesis break plus fresh level/entry/risk confirmation.
Tuner drift guard: frozen top lanes, mixed-lane policy clamps, and level/threshold freeze are hard gates; do not use narrative conviction to bypass them.
Post-win gate: breakeven/small exits in ({POST_WIN_BREAKEVEN_EXEMPT_MIN:.0f},{POST_WIN_BREAKEVEN_EXEMPT_MAX:.0f}) sats are exempt; otherwise wait {POST_WIN_COOLDOWN_MINUTES:.0f}m after small wins, {POST_WIN_MEDIUM_COOLDOWN_MINUTES:.0f}m after wins >={POST_WIN_MEDIUM_THRESHOLD:.0f} sats, and {POST_WIN_LARGE_COOLDOWN_MINUTES:.0f}m after wins >={POST_WIN_LARGE_THRESHOLD:.0f} sats; after TP, re-entry inside {POST_WIN_REENTRY_EDGE_WINDOW_MINUTES:.0f}m requires edge_score/expected_edge >= {POST_WIN_REENTRY_EDGE_MIN:.2f}.
Weak squeeze gate: if squeeze lacks range_established or replay_mtf < 0.50, do not choose trend_follow; use mean_revert_reclaim only at a range edge, otherwise HOLD.
Level gate: live entries require level_map_ready, the correct support/resistance or reclaim side, and enough room to the next target level.
Shadow bias: when recent same-regime same-direction shadow trades are fee-cleared and profitable, treat that as a bounded live edge boost, not a standalone signal. In squeeze + attack with positive shadow, favor a probe or pullback entry over passive HOLD if live levels and structure are acceptable.
Feature health gate: orderbook-dependent entries are blocked when orderbook/spread is stale.
Calibration gate: proven weak policies and unproven directional lanes stay in shadow until live/shadow stats support them.
Winner protection: deterministic SL tightening protects fee-cleared winners; do not override it with narrative exits.
{range_note}
NOTE: If fee-kill is ACTIVE, only recommend open for confirmed range-edge setups. Do NOT recommend mid-range chop entries."""


def build_entry_prompt(usable: float, position: PositionState) -> str:
    stats = get_performance_stats()
    market = brain.get("market_context", {})
    regime = brain.get("market_regime", {}).get("regime", "unknown")
    regime_edge = brain.get("regime_weights", {}).get(regime, 0.0)
    transition = brain.get("regime_transition", {})
    regime_stats = brain.get("regime_stats", {}).get(regime, {})
    regime_trades = regime_stats.get("trades", 0)
    regime_wins = regime_stats.get("wins", 0)
    regime_winrate = regime_wins / regime_trades if regime_trades else 0.0
    cb_history = list(brain.get("confidence_bias_history", []))[-6:]

    past_decisions = sorted(
        brain.get("past_ai_decisions", [])[-25:],
        key=lambda item: float(item.get("outcome_pnl") or 0),
        reverse=True,
    )[:12]

    past_summary = "\n".join(
        f"- {item.get('timestamp', '')[:16]}: {item.get('action', '').upper()} {item.get('direction', '')} "
        f"L{item.get('leverage', '?')}x TP={item.get('tp_bps', '?')} SL={item.get('sl_bps', '?')} | "
        f"PnL={item.get('outcome_pnl', '?')} | {item.get('exit_reason', '')}"
        for item in past_decisions
    ) or "No previous decisions."

    thesis = get_position_thesis_metrics(position) if position.is_open else None
    pos_section = (
        "No open position."
        if not position.is_open
        else f"OPEN {position.side.upper()} | Entry={position.entry:.0f} | Qty={position.qty:.2f} | "
             f"Age={position.age_minutes:.1f}m | SL={position.sl_price or 'N/A'} | TP={position.tp_price or 'N/A'} | "
             f"ThesisScore={thesis['score']:+.2f} | AddReady={thesis['add_ready']} | "
             f"Move={thesis['entry_move_bps']:+.1f}bps | MFE={thesis['mfe_bps']:.1f} | MAE={thesis['mae_bps']:.1f} | "
             f"QDelta={thesis['quality_delta']:+.2f} | FeeRatio={thesis['fee_ratio']:+.2f} | "
             f"PeakFee={thesis.get('peak_fee_multiple', 0.0):+.2f} | "
             f"TtMFE={thesis.get('time_to_mfe_minutes', 0.0) or 0.0:.1f}m | "
             f"MomTurn={thesis.get('momentum_turn', 0.0):+.2f} | ImbTurn={thesis.get('imbalance_turn', 0.0):+.2f} | "
             f"PredAlign={thesis.get('predictive_align', 0.0):+.2f} | PredBreak={thesis.get('predictive_break_align', 0.0):+.2f} | "
             f"PredBias={thesis.get('predictive_bias', 'neutral')}"
    )

    # Recent add summary
    recent_adds = brain.get("adds", [])[-4:]
    add_summary = f"Recent adds: {len(recent_adds)}" if recent_adds else "No adds yet"

    return f"""
You are an elite BTC futures trader on LN Markets.

Your response must be a single raw JSON object.
Do not include markdown, prose, commentary, headings, bullets, code fences, or any text before or after the JSON.
If support/resistance or reclaim is clear and thesis/predictive edge is at least decent, do not hide behind HOLD. Choose the actionable setup when the measurable edge is there.

CRITICAL PLATFORM RULE:
- LN Markets uses one net position only.
- You cannot hold simultaneous long and short positions.
- Opposite-direction orders reduce, close, or reverse the current net position depending on quantity.
- Deterministic net-rebalance may steer exposure toward broader thesis; do not fight it with narrative hold/reverse instructions.
- Do not suggest an immediate flip/reverse after a win or TP; deterministic cooldown and edge gates control re-entry.

Rules:
- Use "open" only when flat.
- "add" only in same-direction positions, and "direction" must match the current position side.
- Use "reduce" only when a position is open, and "direction" must be the opposite order side that reduces the current position.
- Avoid "reverse"; wait for the strict exit gate to close the old thesis and post-win/TP gates to allow a fresh entry.
- "close" fully exits.
- "hold" means no action.
- Include "quantity" for "add", "reduce", and "reverse" whenever possible.
- If current position qty is 1, a "reduce" of 1 is effectively a full close.
- Any close or reduce requires ThesisScore <= {BROKEN_EXIT_THESIS_SCORE:.2f} AND adverse Entry Move >= {BROKEN_EXIT_ADVERSE_MOVE_BPS:.1f} bps unless SL/TP/kill-switch has fired.
- Avoid tiny fee-dominated reductions or closes. If the likely realized move is smaller than fees, keep the trade or look for a valid add, not a passive fee burn.
- Minimum stop-loss distance is {int(MIN_SL_PCT * 10000)} bps.
- Target at least 1.5x the SL distance for TP.
- Leverage is deterministic: caution/protection or 3+ consecutive losses stays 1-3x, normal setups 5-8x, good aligned setups 10-15x, and excellent aligned support/resistance setups 18-20x.
- If market quality is low or regime is unknown, still act on clear support/resistance or reclaim setups when thesis/predictive edge is >= 0.35 and fee clearance is realistic.
- For exploit entries, require strong measurable edge; after TP inside {POST_WIN_REENTRY_EDGE_WINDOW_MINUTES:.0f}m require edge_score/expected_edge >= {POST_WIN_REENTRY_EDGE_MIN:.2f}.
- In caution mode, still take high-alignment setups when support/resistance or reclaim is clear and thesis/predictive edge is >= 0.35; reduce size only, do not auto-HOLD.
- In squeeze, clear level-backed reclaims and range-edge reactions are actionable. Do not say "insufficient edge" or "wait for clearer signals" when alignment is good and the setup is already at the level.
- In squeeze + strategy=attack, if recent shadow in the same direction is profitable/fee-cleared, bias toward a small probe or pullback entry rather than default HOLD when live structure and level context are acceptable.
- Live entries must respect the level map: longs need support/reclaim and room up; shorts need resistance/reclaim and room down; do not enter mid-range or into the next opposing level.
- Do not use orderbook-dependent policies when Feature Health says orderbook/spread is stale.
- Do not fight edge calibration or shadow proof gates; reject only truly weak or mid-range setups, not clear level-backed aligned trades.
- Do not fight tuner drift guards: frozen top lanes, mixed-lane policy clamps, and level/threshold freezes mean HOLD or a lower-risk range-edge reclaim only.
- Do not fight parent allocation: broader structure may press or trim final qty/risk/leverage, but tuner, margin, and risk rails remain authoritative.
- In weak squeeze (no range_established or replay_mtf < 0.50), do not choose trend_follow; prefer mean_revert_reclaim at a clear range edge or reclaim and only stay flat when no level-backed setup exists.
- If a position is open, treat "thesis intact" as a measurable claim supported by ThesisScore, excursion metrics, and quality delta.
- Same-direction adds can be winner adds or recovery-ladder adds: winner adds need improved post-entry metrics; recovery adds need intact thesis, moderate adverse excursion, low close pressure, and deterministic risk/margin approval.
- First predict the most likely move over the next 15-60 minutes. Use the forward-looking section to decide whether continuation, failed break, or mean reversion is more probable.
- Only open or add when that 15-60m forecast implies enough edge, level room, and fee clearance potential to justify aggression.
- When support/resistance is clear, alignment is good, and thesis/predictive edge >= 0.35, bias toward taking the trade instead of defaulting to HOLD.

CLOSING GUIDELINES:
- Do NOT close just because the position is slightly negative or flat.
- Only close/reduce if the original thesis is clearly broken by score and adverse price movement.
- Be mindful of trading fees — closing small/unprofitable positions can be very expensive due to round-trip fees.
- Prefer "hold" or "add" over closing/reducing for minor losses.
- Use "reduce" only after the strict exit gate is met, or when deterministic rebound/profit scale-out logic has already queued a partial scale-out.
- Do not use narrative conviction to flip; wait for deterministic exit and re-entry gates.
- Fee-cleared winners are protected by deterministic stop tightening; do not recommend closing/reducing just to protect profit unless the strict exit gate is met.
- In attack mode on an open position, be constructive rather than passive: if thesis is intact but not yet add_ready, prefer guidance like "consider adding on pullback to support" instead of default HOLD language.

{get_common_prompt_context()}

==================== RISK ====================
Usable: {usable:.0f} sats

==================== MARKET ====================
Price: {brain.get('last_price', 73000):.0f}
Volatility: {brain.get('market_regime', {}).get('volatility', 0.0):.5f}
Funding: {brain.get('funding_rate_pct', 0):.4f}%
Bid: {market.get('bid', 0):.0f} | Ask: {market.get('ask', 0):.0f}
Spread: {market.get('spread_pct', 0):.4f}% | Imbalance: {market.get('imbalance', 0):.2f}

==================== REGIME ====================
Regime: {regime}
Bias: {brain.get('market_regime', {}).get('bias', 'neutral')}
Flavor: {brain.get('market_regime', {}).get('regime_flavor', regime)}
Edge: {regime_edge:.3f} | Scalar: {get_regime_risk_scalar():.2f}
Winrate: {regime_winrate:.2f}
Risk Mode: {brain.get('risk_mode', 'normal')}
Instability: {transition.get('instability', 0):.2f}

==================== CURRENT POSITION ====================
{pos_section}
{add_summary}

==================== PERFORMANCE ====================
Trades: {stats['total_trades']} | WR: {stats['win_rate']}% | Streak: {stats['streak']}
{get_historical_summary()}
Confidence Bias (recent): {cb_history}

==================== LAST EXIT ====================
{get_last_exit_summary()}

==================== INTENT PERFORMANCE ====================
{get_intent_bias_summary()}

==================== PAST DECISIONS ====================
{past_summary}

==================== ACTIVE GATES ====================
{_build_active_gates_section(regime)}

Return ONLY valid JSON:
{{
  "action": "open" | "add" | "reduce" | "reverse" | "close" | "hold",
  "direction": "long" | "short",
  "intent": "trend_follow" | "mean_revert" | "breakout" | "scalp",
  "confidence": 0.0-1.0,
  "setup_probability_15_60m": 0.0-1.0,
  "predicted_edge_15_60m": -1.0-1.0,
  "quantity": int | null,
  "tp_bps": int,
  "sl_bps": int,
  "trail_bps": int,
  "max_hold_minutes": int,
  "leverage": int,
  "reason": "short explanation"
}}
	"""


def suppress_weak_squeeze_trend_follow_signal(signal: EntrySignal) -> Optional[EntrySignal]:
    if signal.action != "open" or signal.intent != "trend_follow":
        return signal
    if str(brain.get("market_regime", {}).get("regime", "unknown")) != "squeeze":
        return signal
    market = brain.get("market_context", {})
    range_established = bool(market.get("range_established", False))
    replay_mtf = float(get_oracle_regime_insight("squeeze").get("avg_mtf_alignment_score", 0.0) or 0.0)
    if range_established and replay_mtf >= 0.50:
        emit_gate_event_if_changed("weak_squeeze", "pass", {"replay_mtf": round(replay_mtf, 3)})
        return signal

    # Bad squeeze trend-follow has been fee-heavy; require a real range before reclaiming.
    if not range_established:
        emit_gate_event_if_changed(
            "weak_squeeze",
            "suppress",
            {"range_established": False, "replay_mtf": round(replay_mtf, 3)},
        )
        log(
            "AI squeeze trend_follow suppressed: "
            f"range_est={range_established} replay_mtf={replay_mtf:+.2f}"
        )
        return None

    rpos = float(market.get("range_position", 0.5) or 0.5)
    emit_gate_event_if_changed(
        "weak_squeeze",
        "downgrade",
        {"range_established": True, "replay_mtf": round(replay_mtf, 3), "rpos": round(rpos, 3)},
    )
    signal.intent = "mean_revert"
    signal.policy = "mean_revert_reclaim"
    signal.direction = "long" if rpos < 0.50 else "short"
    signal.leverage = int(clamp(int(signal.leverage or DEFAULT_LEVERAGE), MIN_LEVERAGE, MAX_LEVERAGE))
    signal.max_hold_minutes = min(int(signal.max_hold_minutes or 36), 36)
    signal.reason = (
        f"{signal.reason} | squeeze trend_follow downgraded: "
        f"range_est={range_established} replay_mtf={replay_mtf:+.2f}"
    )[:240]
    log(f"AI squeeze trend_follow downgraded to mean_revert_reclaim | rpos={rpos:.2f} replay_mtf={replay_mtf:+.2f}")
    return signal


async def get_ai_entry_signal(client, position: PositionState, usable: Optional[float] = None, max_retries: int = 3) -> Optional[EntrySignal]:
    if usable is None:
        usable = await get_usable_margin(client)

    def _min_open_confidence(signal: EntrySignal) -> tuple[float, dict[str, Any]]:
        regime = str(brain.get("market_regime", {}).get("regime", "unknown") or "unknown")
        risk_mode = str(brain.get("risk_mode", "normal") or "normal")
        flat_minutes = get_flat_duration_minutes()
        gate_state = brain.get("last_entry_gate_state", {}) or {}
        signal_ctx = get_signal_context()
        align_score = float((gate_state.get("chop_alignment") or {}).get("score", 0.0) or 0.0)
        level_edge = bool(
            (signal.direction == "long" and (signal_ctx.get("at_support", False) or signal_ctx.get("sweep_reclaim_long", False)))
            or (signal.direction == "short" and (signal_ctx.get("at_resistance", False) or signal_ctx.get("sweep_reclaim_short", False)))
        )
        setup_edge = max(
            float(getattr(signal, "predictive_setup_score", 0.0) or 0.0),
            float(getattr(signal, "expected_edge", 0.0) or 0.0),
        )
        min_conf = {"chop": 0.70, "squeeze": AI_SQUEEZE_MIN_CONFIDENCE, "trend": 0.60}.get(regime, 0.65)
        if regime == "squeeze" and flat_minutes >= CAUTION_DECAY_START_MINUTES:
            progress = min(
                (flat_minutes - CAUTION_DECAY_START_MINUTES)
                / max(CAUTION_DECAY_FULL_MINUTES - CAUTION_DECAY_START_MINUTES, 1.0),
                1.0,
            )
            min_conf -= progress * (AI_SQUEEZE_MIN_CONFIDENCE - AI_SQUEEZE_FLAT_MIN_CONFIDENCE)
        if regime == "squeeze" and risk_mode == "caution" and level_edge and align_score >= AI_SQUEEZE_ALIGNMENT_OVERRIDE:
            min_conf = min(min_conf, AI_SQUEEZE_FLAT_MIN_CONFIDENCE)
        if regime == "squeeze" and risk_mode == "caution" and level_edge and setup_edge >= 0.32:
            min_conf = min(min_conf, 0.32)
        return clamp(min_conf, 0.32, 0.70), {
            "regime": regime,
            "risk_mode": risk_mode,
            "flat_minutes": round(flat_minutes, 1),
            "align_score": round(align_score, 2),
            "level_edge": level_edge,
            "setup_edge": round(setup_edge, 2),
        }

    base_prompt = build_entry_prompt(usable, position)
    for attempt in range(1, max_retries + 1):
        strict = (
            "\n\nCRITICAL: Return exactly one JSON object and nothing else. "
            "No markdown, no explanation, no headings, no code fences."
            if attempt > 1 else
            "\n\nFINAL OUTPUT FORMAT: exactly one raw JSON object and nothing else."
        )
        response = await reason(base_prompt + strict)
        if not response:
            continue
        parsed = extract_json(response)
        if parsed:
            signal = clamp_signal(parsed)
            llm_setup_prob = clamp(coerce_float(parsed.get("setup_probability_15_60m", 0.5), 0.5), 0.0, 1.0)
            llm_predicted_edge = clamp(coerce_float(parsed.get("predicted_edge_15_60m", 0.0), 0.0), -1.0, 1.0)
            if signal and signal.action in {"open", "add"}:
                regime = str(brain.get("market_regime", {}).get("regime", "unknown"))
                fingerprint = get_exploration_context_fingerprint(regime)
                oracle_insight = get_oracle_regime_insight(regime)
                predictive_runtime = compute_predictive_setup_score(
                    regime=regime,
                    intent=signal.intent,
                    direction=signal.direction,
                    context_stats=get_context_policy_stats(fingerprint).get(signal.policy, {}),
                    shadow_context_stats=get_shadow_context_policy_stats(fingerprint).get(signal.policy, {}),
                    shadow_direction_stats=get_shadow_policy_direction_stats(fingerprint, signal.policy, signal.direction),
                    oracle_insight=oracle_insight,
                    llm_predictive_prob=llm_setup_prob,
                )
                signal.predictive_setup_score = float(predictive_runtime.get("score", 0.0) or 0.0)
                signal.predictive_setup_summary = str(
                    f"{predictive_runtime.get('component_summary', 'n/a')} | "
                    f"llm={llm_setup_prob:.2f} edge15_60={llm_predicted_edge:+.2f}"
                )[:240]
                signal.predictive_setup_edge_bonus = float(predictive_runtime.get("edge_bonus", 0.0) or 0.0)
                signal.llm_predictive_prob = llm_setup_prob
                signal.llm_predictive_edge = llm_predicted_edge
            if signal and signal.action == "hold":
                log(f"AI HOLD signal | {signal.reason or 'no reason provided'}")
                return None
            if signal and signal.action == "open":
                signal = suppress_weak_squeeze_trend_follow_signal(signal)
                if not signal:
                    return None
                min_conf, conf_meta = _min_open_confidence(signal)
                if signal.confidence < min_conf:
                    log(
                        f"AI signal confidence {signal.confidence:.2f} < {min_conf:.2f} "
                        f"for {conf_meta['regime']} — treating as hold | "
                        f"risk={conf_meta['risk_mode']} flat={conf_meta['flat_minutes']:.1f}m "
                        f"align={conf_meta['align_score']:.2f} level_edge={conf_meta['level_edge']} "
                        f"setup_edge={conf_meta['setup_edge']:.2f}"
                    )
                    return None
                pred = float(getattr(signal, "predictive_setup_score", 0.0) or 0.0)
                if pred < 0.35:
                    log(
                        f"AI open blocked: pred={pred:.2f} < 0.35 floor | "
                        f"intent={signal.intent} dir={signal.direction} conf={signal.confidence:.2f}"
                    )
                    return None
            return signal
        log(f"JSON parse failed on attempt {attempt}, trying repair")
        repaired = await repair_json(response)
        signal = clamp_signal(repaired) if repaired else None
        if repaired:
            log("JSON repair successful")
            llm_setup_prob = clamp(coerce_float(repaired.get("setup_probability_15_60m", 0.5), 0.5), 0.0, 1.0)
            llm_predicted_edge = clamp(coerce_float(repaired.get("predicted_edge_15_60m", 0.0), 0.0), -1.0, 1.0)
            if signal and signal.action in {"open", "add"}:
                regime = str(brain.get("market_regime", {}).get("regime", "unknown"))
                fingerprint = get_exploration_context_fingerprint(regime)
                oracle_insight = get_oracle_regime_insight(regime)
                predictive_runtime = compute_predictive_setup_score(
                    regime=regime,
                    intent=signal.intent,
                    direction=signal.direction,
                    context_stats=get_context_policy_stats(fingerprint).get(signal.policy, {}),
                    shadow_context_stats=get_shadow_context_policy_stats(fingerprint).get(signal.policy, {}),
                    shadow_direction_stats=get_shadow_policy_direction_stats(fingerprint, signal.policy, signal.direction),
                    oracle_insight=oracle_insight,
                    llm_predictive_prob=llm_setup_prob,
                )
                signal.predictive_setup_score = float(predictive_runtime.get("score", 0.0) or 0.0)
                signal.predictive_setup_summary = str(
                    f"{predictive_runtime.get('component_summary', 'n/a')} | "
                    f"llm={llm_setup_prob:.2f} edge15_60={llm_predicted_edge:+.2f}"
                )[:240]
                signal.predictive_setup_edge_bonus = float(predictive_runtime.get("edge_bonus", 0.0) or 0.0)
                signal.llm_predictive_prob = llm_setup_prob
                signal.llm_predictive_edge = llm_predicted_edge
            if signal and signal.action == "hold":
                log(f"AI HOLD signal | {signal.reason or 'no reason provided'}")
                return None
            if signal and signal.action == "open":
                signal = suppress_weak_squeeze_trend_follow_signal(signal)
                if not signal:
                    return None
                min_conf, conf_meta = _min_open_confidence(signal)
                if signal.confidence < min_conf:
                    log(
                        f"AI signal confidence {signal.confidence:.2f} < {min_conf:.2f} "
                        f"for {conf_meta['regime']} — treating as hold | "
                        f"risk={conf_meta['risk_mode']} flat={conf_meta['flat_minutes']:.1f}m "
                        f"align={conf_meta['align_score']:.2f} level_edge={conf_meta['level_edge']} "
                        f"setup_edge={conf_meta['setup_edge']:.2f}"
                    )
                    return None
                pred = float(getattr(signal, "predictive_setup_score", 0.0) or 0.0)
                if pred < 0.35:
                    log(
                        f"AI open blocked: pred={pred:.2f} < 0.35 floor | "
                        f"intent={signal.intent} dir={signal.direction} conf={signal.confidence:.2f}"
                    )
                    return None
            return signal
    log("AI entry signal failed after retries")
    return None


async def ai_review_position(client, position: PositionState):
    try:
        price = float(brain.get("last_price") or position.entry or 0)
        pnl = position.unrealized_pnl(price)
        thesis = refresh_position_thesis(position, price)
        cb_history = list(brain.get("confidence_bias_history", []))[-8:]
        recent_adds = brain.get("adds", [])[-5:]
        add_summary = f"Previous adds: {len(recent_adds)} | Last add PnL: {recent_adds[-1].get('pnl_at_add', 'N/A') if recent_adds else 'None'}"

        prompt = f"""
You are managing an open BTC futures position. Respond with JSON ONLY.

CRITICAL PLATFORM RULE:
- LN Markets uses one net position only.
- You cannot hold long and short simultaneously.
- AI review must not reverse an open position.
- Opposite-direction orders may only reduce the current net position.
- Deterministic net-rebalance may use opposite-side orders to steer exposure toward the broader thesis; crossing through zero is not an AI-review decision.

CURRENT POSITION:
Price: {price:.0f}
Entry: {position.entry:.0f}
Side: {position.side}
Unrealized PnL: {pnl:+.0f} sats
Age: {position.age_minutes:.1f} min
Intent: {position.intent}
Confidence: {position.confidence:.2f}
SL: {f'{position.sl_price:.0f}' if position.sl_price else 'N/A'}
TP: {f'{position.tp_price:.0f}' if position.tp_price else 'N/A'}
Adds done: {position.add_count}
{add_summary}
Trade Thesis: {get_position_plan_summary(position)}
Thesis Score: {thesis['score']:+.2f}
Thesis Intact: {thesis['intact']}
Add Ready: {thesis['add_ready']}
Entry Move: {thesis['entry_move_bps']:+.1f} bps
MFE: {thesis['mfe_bps']:.1f} bps | MAE: {thesis['mae_bps']:.1f} bps
Time to MFE: {thesis.get('time_to_mfe_minutes', 0.0) or 0.0:.1f}m | Time to MAE: {thesis.get('time_to_mae_minutes', 0.0) or 0.0:.1f}m
Entry Quality: {thesis['entry_quality']:.2f} | Quality Now: {thesis['quality_now']:.2f} | Delta: {thesis['quality_delta']:+.2f}
PnL/Fee Ratio: {thesis['fee_ratio']:+.2f}
Peak Fee Multiple: {thesis.get('peak_fee_multiple', 0.0):+.2f}
Momentum Turn: {thesis.get('momentum_turn', 0.0):+.2f} | Imbalance Turn: {thesis.get('imbalance_turn', 0.0):+.2f}
Momentum Persistence: {thesis.get('momentum_persistence', 0.0):+.2f} | Imbalance Persistence: {thesis.get('imbalance_persistence', 0.0):+.2f}
Predictive Bias: {thesis.get('predictive_bias', 'neutral')} | Predictive Align: {thesis.get('predictive_align', 0.0):+.2f} | Predictive Break Align: {thesis.get('predictive_break_align', 0.0):+.2f}
Predictive Summary: {thesis.get('predictive_summary', 'n/a')}

{get_common_prompt_context()}

REGIME & RISK:
Regime: {brain.get('market_regime', {}).get('regime', 'unknown')}
Strength: {brain.get('market_regime', {}).get('confidence', 0.0):.2f}
Risk Mode: {brain.get('risk_mode', 'normal')}
Volatility: {brain.get('market_regime', {}).get('volatility', 0.0):.5f}

HISTORY & BIAS:
Streak: {get_risk_streak()} | Risk Drawdown: {get_recent_risk_snapshot().get('daily_loss_ratio', 0.0):.3f}
Confidence Bias (recent): {cb_history}

CLOSING GUIDELINES:
- Do NOT close just because the position is slightly negative or flat.
- Do not default to HOLD while a position is open. If thesis is intact and a clear same-direction add is valid, choose ADD; if the thesis is broken and the strict exit gate is met, choose REDUCE or CLOSE.
- In squeeze + attack mode, when the position is intact and levels still support the trade, use constructive language such as "consider adding on pullback to support" rather than passive HOLD wording.
- In squeeze + attack mode, if thesis is modest but intact, or slightly negative while peak_fee_multiple >= 0.40 and close_align > 0.08, prefer constructive add language like "consider adding on pullback to support" instead of a generic HOLD.
- For open squeeze positions with intact thesis, positive predictive alignment, stable/improving quality, and clear level support/resistance, treat the trade as actively exploitable even in caution mode. Caution should reduce size, not force passive HOLD.
- Never recommend "reverse" from AI review; wait for a separate flat-entry decision after exit.
- Only recommend "close" when Thesis Score <= -0.30 AND Entry Move <= -20.0 bps.
- Only recommend "reduce" when the same close rule is met, or when deterministic rebound/profit scale-out logic has already queued a partial scale-out.
- Do not close on bullish/bearish market narrative, squeeze dynamics, or regime bias alone.
- Be mindful of trading fees — closing small/unprofitable positions can be very expensive due to round-trip fees.
- Prefer "hold" or "add" over closing/reducing for minor losses.
- In squeeze/caution, high-alignment support/resistance or reclaim setups remain actionable. Do not answer with "low conviction", "insufficient edge", or "wait for clearer signals" when the level is clear and thesis/predictive edge is >= 0.35.
- If a position is already open and thesis is intact, use HOLD only when there is genuinely no add or reduce signal. Do not frame intact squeeze positions as lacking conviction when the measurable thesis is still positive.
- For intact squeeze winners, prefer action-oriented reasoning such as "consider adding on pullback to support" when Thesis Score is positive and level/fee alignment is good, instead of default passive HOLD language.
- Never recommend flipping direction after a win or TP; wait for a flat-cycle re-entry that passes cooldown and edge gates.
- Fee-cleared winners are protected by deterministic SL tightening; do not close/reduce for profit protection unless the strict close rule is met.
- Do not weaken or override level, feature health, calibration, shadow proof, post-win, or weak-squeeze gates from AI review.
- Treat tuner drift guards as hard gates: frozen top lanes, mixed-lane policy clamps, and live leverage/allocation caps cannot be overridden from AI review.
- Treat parent allocation as deterministic: open-entry qty/leverage is finalized outside the prompt from broader structure, edge, replay/oracle, level room, risk mode, margin, and tuner caps. AI review must not force larger size or leverage.
- For "add", direction must match the current position side.
- For "reduce", direction must be the opposite order side that shrinks the current position.
- If position qty is 1, then "reduce" with quantity 1 is effectively a full close and must satisfy the close rule.
- Avoid recommending fee-dominated reductions unless the thesis is clearly broken or risk has materially worsened.
- Only describe the thesis as intact when the measurable thesis score and excursion metrics support that claim.
- Same-direction adds can be winner adds or recovery-ladder adds. Winner adds need Add Ready or clear improvement; recovery adds need Thesis Intact, moderate adverse excursion, low close pressure, and deterministic risk/margin approval.
- Before choosing hold/add/reduce/close, explicitly predict the most likely path over the next 15-60 minutes and use that forecast to judge whether the trade should keep running.
- Do not close a trade whose measurable thesis remains intact and whose 15-60m forecast still favors the current side unless the strict deterministic exit gate is met.
- In caution mode, be selective but still action-oriented: reduce size, not conviction, on clear high-alignment setups.

Return ONLY:
{{
  "action": "hold" | "close" | "add" | "reduce",
  "direction": "long" | "short" | "",
  "setup_probability_15_60m": 0.0-1.0,
  "predicted_edge_15_60m": -1.0-1.0,
  "quantity": int | null,
  "reason": "one short sentence"
}}
"""
        response = await reason(prompt)
        parsed = extract_json(response) if response else None
        if not parsed:
            log("AI review parse failed")
            return
        review = build_review_signal(parsed)
        normalized_action, normalized_direction, normalization_note = normalize_position_action(
            review["action"],
            review.get("direction"),
            position.side,
        )
        if normalization_note:
            log(normalization_note)
        review["action"] = normalized_action
        if normalized_direction:
            review["direction"] = normalized_direction
        review = align_review_with_thesis(review, position, thesis, pnl)
        if (
            bool(thesis.get("add_ready"))
            and str((brain.get("last_strategic_context", {}) or {}).get("mode", "observe") or "observe") == "attack"
            and review["action"] == "hold"
        ):
            review["reason"] = "Consider adding on pullback to support; thesis is intact and attack mode is active."
        brain["last_review_action"] = review["action"]
        brain["last_review_reason"] = review["reason"]
        brain.setdefault("ai_reviews", []).append(
            {
                "timestamp": datetime.now().isoformat(),
                "action": review["action"],
                "direction": review.get("direction"),
                "quantity": review.get("quantity"),
                "reason": review["reason"],
                "pnl": round(pnl, 2),
            }
        )
        brain["ai_reviews"] = brain["ai_reviews"][-100:]
        log(
            f"AI review -> {review['action'].upper()} | pnl={pnl:+.0f} | "
            f"thesis={thesis['score']:+.2f} add_ready={thesis['add_ready']} | {review['reason']}"
        )

        if review["action"] in {"close", "reverse"} and position.last_thesis_score > 0.10:
            log(
                f"AI {review['action']} blocked: thesis still positive ({position.last_thesis_score:+.2f}) | "
                f"reason={review['reason']}"
            )
            review["action"] = "hold"

        if review["action"] == "close":
            price = float(brain.get("last_price") or position.entry or 0.0)
            close_gate, thesis_score, move_bps = ai_review_close_gate(position, thesis, price)
            if not close_gate:
                log(
                    f"AI close blocked by hard review gate | thesis={thesis_score:+.2f} "
                    f"raw_move={move_bps:+.1f}bps | reason={review['reason']}"
                )
                review["action"] = "hold"
                review["reason"] = "hard review close gate failed"
            elif should_block_fee_dominated_ai_close(position, pnl):
                est_fee = estimate_round_trip_fee_from_position(position)
                log(
                    f"AI close suppressed | pnl={pnl:+.0f} | est_fee≈{est_fee:.0f} | "
                    f"reason={review['reason']}"
                )
                review["action"] = "hold"
                review["reason"] = "fee-dominated close suppressed"
            else:
                position.pending_close = True
                position.last_reason = review["reason"]
        elif review["action"] == "add" and position.add_count < get_max_add_count(position, thesis):
            position.pending_add = True
            position.pending_add_qty = float(review.get("quantity") or 0)
            position.last_reason = review["reason"]
        elif review["action"] == "reduce":
            review_direction = review.get("direction") or ("long" if position.side == "short" else "short")
            qty = float(review.get("quantity") or max(1, int(position.qty * 0.5)))
            if review_direction == position.side:
                log(f"AI reduce blocked: direction must oppose current position | signal={review_direction} position={position.side}")
            else:
                price = float(brain.get("last_price") or position.entry or 0.0)
                close_gate, thesis_score, move_bps = ai_review_close_gate(position, thesis, price)
                if not close_gate:
                    log(
                        f"AI reduce blocked by strict exit gate | thesis={thesis_score:+.2f} "
                        f"raw_move={move_bps:+.1f}bps qty={qty:.0f} | {format_strict_exit_requirement()}"
                    )
                    return
                position.pending_reduce = True
                position.pending_reduce_qty = qty
                position.last_reason = review["reason"]
        elif review["action"] == "reverse":
            log(f"AI reverse suppressed after thesis alignment | {review['reason']}")
    except Exception as exc:
        log(f"ai_review_position error: {exc}")


async def execute_trade(client, signal: EntrySignal, position: PositionState):
    can_trade, block_reason = check_drawdown_protection()
    if not can_trade:
        log(f"Drawdown protection: {block_reason}")
        return

    usable = await get_usable_margin(client)
    if usable < 950:
        log(f"Low margin ({usable:.0f})")
        return

    if position.is_open:
        log("execute_trade called with open position, skipping")
        return

    predictive_setup_score = float(getattr(signal, "predictive_setup_score", 0.0) or 0.0)
    predictive_setup_summary = str(getattr(signal, "predictive_setup_summary", "n/a") or "n/a")
    if predictive_setup_score <= 0.0 or predictive_setup_summary == "n/a":
        regime = str(brain.get("market_regime", {}).get("regime", "unknown"))
        fingerprint = get_exploration_context_fingerprint(regime)
        oracle_insight = get_oracle_regime_insight(regime)
        predictive_runtime = compute_predictive_setup_score(
            regime=regime,
            intent=signal.intent,
            direction=signal.direction,
            context_stats=get_context_policy_stats(fingerprint).get(signal.policy, {}),
            shadow_context_stats=get_shadow_context_policy_stats(fingerprint).get(signal.policy, {}),
            shadow_direction_stats=get_shadow_policy_direction_stats(fingerprint, signal.policy, signal.direction),
            oracle_insight=oracle_insight,
            llm_predictive_prob=float(getattr(signal, "llm_predictive_prob", 0.5) or 0.5),
        )
        predictive_setup_score = float(predictive_runtime.get("score", 0.0) or 0.0)
        predictive_setup_summary = str(predictive_runtime.get("component_summary", "n/a"))
        signal.predictive_setup_score = predictive_setup_score
        signal.predictive_setup_summary = predictive_setup_summary
        signal.predictive_setup_edge_bonus = float(predictive_runtime.get("edge_bonus", 0.0) or 0.0)

    base_risk = float(
        getattr(signal, "base_risk_per_trade", signal.risk_per_trade) or RISK_PER_TRADE
    )
    final_risk = float(
        getattr(signal, "effective_risk_per_trade", signal.risk_per_trade) or RISK_PER_TRADE
    )

    final_risk = min(final_risk, MAX_RISK_PER_TRADE)
    final_risk = max(0.0015, final_risk)

    signal.base_risk_per_trade = base_risk
    signal.effective_risk_per_trade = final_risk
    signal.risk_per_trade = final_risk
    signal.leverage = int(clamp(int(signal.leverage or DEFAULT_LEVERAGE), MIN_LEVERAGE, MAX_LEVERAGE))
    gate_state = dict(getattr(signal, "entry_gate_state_snapshot", None) or brain.get("last_entry_gate_state", {}) or {})
    gate_state["chop_learner_lane_active"] = bool(getattr(signal, "chop_learner_lane_active", False))
    brain["last_entry_gate_state"] = safe_serialize(gate_state)

    quantity = calculate_quantity(usable, final_risk, signal.sl_bps, signal.leverage, signal)

    log(
        f"📏 POSITION SIZING | usable={usable:.0f} "
        f"base_risk={base_risk:.4f} effective_risk={final_risk:.4f} "
        f"sl_bps={signal.sl_bps} lev={signal.leverage} qty={quantity}"
    )

    if quantity < 1:
        log("❌ Quantity too small, skipping")
        return

    squeeze_structure_block = get_squeeze_structure_block_reason(signal.direction, signal.intent)
    if squeeze_structure_block:
        bypass_final_block, bypass_final_reason = should_aggressive_learning_bypass_block(
            squeeze_structure_block,
            brain.get("last_entry_gate_state", {}) or {},
        )
        if not bypass_final_block:
            log(f"🚫 ENTRY FINAL BLOCK: {squeeze_structure_block}")
            append_review_report(
                "entry_final_squeeze_structure_block",
                {
                    "entry_tag": signal.entry_tag,
                    "direction": signal.direction,
                    "intent": signal.intent,
                    "policy": signal.policy,
                    "reason": squeeze_structure_block,
                },
            )
            return
        log(f"⚡ ENTRY FINAL SQUEEZE BYPASS: {squeeze_structure_block} | {bypass_final_reason}")

    price_ok, price_reason = confirm_entry_price_deviation(signal)
    if not price_ok:
        log(f"🚫 ENTRY PRICE CONFIRM BLOCK: {price_reason}")
        append_review_report(
            "entry_price_deviation_block",
            {
                "entry_tag": signal.entry_tag,
                "direction": signal.direction,
                "policy": signal.policy,
                "signal_price": round(float(signal.signal_price or 0.0), 2),
                "current_price": round(float(brain.get("last_price") or 0.0), 2),
                "reason": price_reason,
            },
        )
        return
    log(f"✅ ENTRY PRICE CONFIRM PASS: {price_reason}")

    set_leverage_result = await set_cross_leverage(client, signal.leverage)
    if set_leverage_result is None:
        log(f"❌ Aborting trade: unable to set cross leverage to {signal.leverage}x")
        brain["trade_failures"] = int(brain.get("trade_failures", 0)) + 1
        return

    if abs(float(set_leverage_result) - float(signal.leverage)) > 0.01:
        log(
            f"❌ Aborting trade: cross leverage mismatch before entry | "
            f"requested={signal.leverage}x exchange={float(set_leverage_result):.2f}x"
        )
        brain["trade_failures"] = int(brain.get("trade_failures", 0)) + 1
        return

    side = "buy" if signal.direction == "long" else "sell"
    order_id = None

    _regime = str(brain.get("market_regime", {}).get("regime", "unknown"))
    _fee_est_bps = 20.0
    _rr = round(signal.tp_bps / max(signal.sl_bps, 1), 2)
    _quality = round(float(gate_state.get("quality", 0.0) or 0.0), 2)
    _align = round(float((gate_state.get("chop_alignment") or {}).get("score", 0.0) or 0.0), 2)
    _oracle = round(float((gate_state.get("oracle_insight") or {}).get("score", 0.0) or 0.0), 3)
    _ev = round(float(getattr(signal, "expected_edge", 0.0) or 0.0), 3)
    _pred = round(float(predictive_setup_score or 0.0), 3)
    log(
        f"[ENTRY] regime={_regime} side={side} tp={signal.tp_bps}bps sl={signal.sl_bps}bps "
        f"fee_est={_fee_est_bps:.1f}bps R:R={_rr:.2f} quality={_quality:.2f} "
        f"ev={_ev:.3f} pred={_pred:.3f} align={_align:.2f} oracle_score={_oracle:.3f}"
    )

    try:
        log(
            f"📤 SENDING ORDER | side={side} qty={quantity} lev={signal.leverage} "
            f"mode={signal.mode} policy={signal.policy}"
        )

        order_response = await client.futures.cross.new_order(
            {
                "type": "market",
                "side": side,
                "quantity": quantity,
                "leverage": signal.leverage,
            }
        )

        log(f"📥 ORDER RESPONSE | {safe_serialize(order_response)}")

        order_id = str(
            _safe_get(order_response, "id", "")
            or _safe_get(order_response, "order_id", "")
            or ""
        )

    except Exception as exc:
        log(f"❌ Order placement failed: {exc}")
        brain["trade_failures"] = int(brain.get("trade_failures", 0)) + 1
        return

    confirmed_side, confirmed_qty, confirmed_entry, initial_margin, running_margin, total_pl = await confirm_position_fill(client)

    if confirmed_qty <= 0 or not confirmed_side:
        log("⚠️ Position not confirmed — attempting exchange sync")

        await verify_position_with_exchange(client, position)

        if not position.is_open:
            log("❌ No position found after sync — treating as failed")
            return

        confirmed_side = position.side
        confirmed_qty = position.qty
        confirmed_entry = position.entry or 0.0

        if confirmed_qty <= 0 or not confirmed_side or confirmed_entry <= 0:
            log("❌ Sync failed to recover full position data")
            return

        log(
            f"✅ Recovered position via sync | "
            f"side={confirmed_side} qty={confirmed_qty:.2f} entry={confirmed_entry:.1f}"
        )

    sl_pct = max(signal.sl_bps / 10000.0, MIN_SL_PCT)
    tp_pct = max(signal.tp_bps / 10000.0, sl_pct * MIN_TP_TO_SL)
    # Never arm a zero-distance trail; fallback to half the stop distance for malformed signals.
    trail_pct = max(signal.trail_bps / 10000.0, sl_pct * 0.5)

    if signal.direction == "long":
        sl_price = confirmed_entry * (1 - sl_pct)
        tp_price = confirmed_entry * (1 + tp_pct)
    else:
        sl_price = confirmed_entry * (1 + sl_pct)
        tp_price = confirmed_entry * (1 - tp_pct)

    exchange_leverage = position.leverage
    try:
        pos_after_fill = await client.futures.cross.get_position()
        exchange_leverage = float(_safe_get(pos_after_fill, "leverage") or signal.leverage)
    except Exception as exc:
        log(f"Leverage verification fetch failed after fill: {exc}")
        exchange_leverage = float(signal.leverage)

    if abs(float(exchange_leverage) - float(signal.leverage)) > 0.01:
        log(
            f"❌ Closing position due to leverage mismatch after fill | "
            f"requested={signal.leverage}x exchange={exchange_leverage:.2f}x"
        )
        await safe_close_position(client)
        brain["trade_failures"] = int(brain.get("trade_failures", 0)) + 1
        return

    position.open(
        side=confirmed_side,
        entry=confirmed_entry,
        qty=confirmed_qty,
        leverage=exchange_leverage,
        sl_price=sl_price,
        tp_price=tp_price,
        trail_buffer_pct=trail_pct,
        max_hold_minutes=signal.max_hold_minutes,
        intent=signal.intent,
        confidence=signal.confidence,
        reason=signal.reason,
        mode=signal.mode,
        policy=signal.policy,
        exchange_order_id=order_id,
        initial_margin=initial_margin,
        running_margin=running_margin,
        total_pl=total_pl,
        entry_expected_edge=float(getattr(signal, "expected_edge", 0.0) or 0.0),
        entry_predictive_setup_score=predictive_setup_score,
        entry_predictive_setup_summary=predictive_setup_summary,
        entry_chop_learner_lane_active=bool(getattr(signal, "chop_learner_lane_active", False)),
        entry_tag=signal.entry_tag,
        signal_price=float(signal.signal_price or 0.0),
        evidence_valid=bool(signal.evidence_valid),
        evidence_reason=signal.evidence_reason,
        roi_schedule_reason=signal.roi_schedule_reason,
    )

    brain["last_trade"] = {
        "timestamp": datetime.now().isoformat(),
        "entry": confirmed_entry,
        "side": confirmed_side,
        "qty": confirmed_qty,
        "leverage": exchange_leverage,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "trail_buffer_pct": trail_pct,
        "intent": signal.intent,
        "confidence": round(signal.confidence, 3),
        "reason": signal.reason,
        "max_hold_minutes": signal.max_hold_minutes,
        "expected_edge": round(float(getattr(signal, "expected_edge", 0.0) or 0.0), 4),
        "predictive_setup_score": round(predictive_setup_score, 4),
        "predictive_setup_summary": predictive_setup_summary,
        "chop_learner_lane_active": bool(getattr(signal, "chop_learner_lane_active", False)),
        "base_risk_per_trade": round(base_risk, 5),
        "effective_risk_per_trade": round(final_risk, 5),
        "risk_per_trade": round(final_risk, 5),
        "parent_qty_multiplier": round(float(getattr(signal, "parent_qty_multiplier", 1.0) or 1.0), 4),
        "parent_risk_multiplier": round(float(getattr(signal, "parent_risk_multiplier", 1.0) or 1.0), 4),
        "parent_leverage_target": int(getattr(signal, "parent_leverage_target", 0) or signal.leverage),
        "parent_allocation_reason": getattr(signal, "parent_allocation_reason", "") or "n/a",
        "exposure_budget": safe_serialize(brain.get("last_exposure_budget", {})),
        "tuned_qty_multiplier": round(float(getattr(signal, "tuned_qty_multiplier", 1.0) or 1.0), 4),
        "tuned_risk_multiplier": round(float(getattr(signal, "tuned_risk_multiplier", 1.0) or 1.0), 4),
        "tuned_allocation_reason": getattr(signal, "tuned_allocation_reason", "") or "n/a",
        "entry_tag": signal.entry_tag,
        "signal_price": round(float(signal.signal_price or 0.0), 2),
        "evidence_valid": bool(signal.evidence_valid),
        "evidence_reason": signal.evidence_reason,
        "roi_schedule_reason": signal.roi_schedule_reason,
        "order_id": order_id,
        "mode": signal.mode,
        "policy": signal.policy,
        "entry_nearest_support": position.entry_nearest_support,
        "entry_nearest_resistance": position.entry_nearest_resistance,
        "entry_room_to_target_bps": position.entry_room_to_target_bps,
        "entry_level_alignment": position.entry_level_alignment,
        "entry_level_summary": position.entry_level_summary,
        "entry_feature_health_summary": position.entry_feature_health_summary,
    }

    append_past_ai_decision(
        {
            "timestamp": datetime.now().isoformat(),
            "action": "open",
            "direction": confirmed_side,
            "quantity": confirmed_qty,
            "intent": signal.intent,
            "mode": signal.mode,
            "policy": signal.policy,
            "confidence": signal.confidence,
            "leverage": exchange_leverage,
            "tp_bps": signal.tp_bps,
            "sl_bps": signal.sl_bps,
            "trail_bps": signal.trail_bps,
            "expected_edge": round(float(getattr(signal, "expected_edge", 0.0) or 0.0), 4),
            "predictive_setup_score": round(predictive_setup_score, 4),
            "predictive_setup_summary": predictive_setup_summary,
            "chop_learner_lane_active": bool(getattr(signal, "chop_learner_lane_active", False)),
            "base_risk_per_trade": round(base_risk, 5),
            "effective_risk_per_trade": round(final_risk, 5),
            "risk_per_trade": round(final_risk, 5),
            "parent_qty_multiplier": round(float(getattr(signal, "parent_qty_multiplier", 1.0) or 1.0), 4),
            "parent_risk_multiplier": round(float(getattr(signal, "parent_risk_multiplier", 1.0) or 1.0), 4),
            "parent_leverage_target": int(getattr(signal, "parent_leverage_target", 0) or signal.leverage),
            "parent_allocation_reason": getattr(signal, "parent_allocation_reason", "") or "n/a",
            "exposure_budget": safe_serialize(brain.get("last_exposure_budget", {})),
            "tuned_qty_multiplier": round(float(getattr(signal, "tuned_qty_multiplier", 1.0) or 1.0), 4),
            "tuned_risk_multiplier": round(float(getattr(signal, "tuned_risk_multiplier", 1.0) or 1.0), 4),
            "tuned_allocation_reason": getattr(signal, "tuned_allocation_reason", "") or "n/a",
            "entry_tag": signal.entry_tag,
            "signal_price": round(float(signal.signal_price or 0.0), 2),
            "evidence_valid": bool(signal.evidence_valid),
            "evidence_reason": signal.evidence_reason,
            "roi_schedule_reason": signal.roi_schedule_reason,
            "reason": signal.reason,
            "outcome": "pending",
            "exchange_order_id": order_id,
        }
    )
    record_trade_activity(signal.mode, "open", confirmed_qty)
    brain["last_decision"] = {
        "timestamp": datetime.now().isoformat(),
        "action": "open",
        "direction": confirmed_side,
        "intent": signal.intent,
        "mode": signal.mode,
        "policy": signal.policy,
        "confidence": signal.confidence,
        "leverage": exchange_leverage,
        "tp_bps": signal.tp_bps,
        "sl_bps": signal.sl_bps,
        "trail_bps": signal.trail_bps,
        "max_hold": signal.max_hold_minutes,
        "expected_edge": round(float(getattr(signal, "expected_edge", 0.0) or 0.0), 4),
        "predictive_setup_score": round(predictive_setup_score, 4),
        "predictive_setup_summary": predictive_setup_summary,
        "chop_learner_lane_active": bool(getattr(signal, "chop_learner_lane_active", False)),
        "parent_allocation_reason": getattr(signal, "parent_allocation_reason", "") or "n/a",
        "parent_qty_multiplier": round(float(getattr(signal, "parent_qty_multiplier", 1.0) or 1.0), 4),
        "parent_risk_multiplier": round(float(getattr(signal, "parent_risk_multiplier", 1.0) or 1.0), 4),
        "exposure_budget": safe_serialize(brain.get("last_exposure_budget", {})),
        "tuned_allocation_reason": getattr(signal, "tuned_allocation_reason", "") or "n/a",
        "entry_tag": signal.entry_tag,
        "signal_price": round(float(signal.signal_price or 0.0), 2),
        "evidence_valid": bool(signal.evidence_valid),
        "evidence_reason": signal.evidence_reason,
        "roi_schedule_reason": signal.roi_schedule_reason,
        "reason": signal.reason,
    }

    log(
        f"🚀 EXECUTED {signal.mode.upper()} TRADE | {signal.policy} | "
        f"base={base_risk:.4f} effective={final_risk:.4f} "
        f"qty={confirmed_qty:.2f} lev={exchange_leverage:.2f}x | "
        f"parent={getattr(signal, 'parent_allocation_reason', '') or 'n/a'}"
    )

    on_position_filled(signal, position)
    maybe_save_memory(force=True)


async def ingest_closed_trades(client):
    """Ingest closed trades and use EXACT fees from exchange"""
    if bool(brain.get("closed_trade_ingest_disabled", False)):
        return
    try:
        closed_trades = await client.futures.cross.get_filled_orders()
        if not closed_trades:
            return

        processed = set(brain.get("processed_trade_ids", []))
        added = 0

        for trade in closed_trades:
            trade_id = str(_safe_get(trade, "id", "") or _safe_get(trade, "order_id", "") or "")
            if not trade_id or trade_id in processed:
                continue

            gross_pnl = float(_safe_get(trade, "pl", 0) or _safe_get(trade, "pnl", 0) or 0)
            trading_fee = float(_safe_get(trade, "trading_fee", 0) or _safe_get(trade, "fee", 0) or 0)
            funding_fee = float(_safe_get(trade, "funding_fee", 0) or 0)

            net_pnl = gross_pnl - trading_fee - funding_fee

            if abs(net_pnl) < 1:
                processed.add(trade_id)
                continue

            fee_dominated = abs(gross_pnl) < max(abs(trading_fee + funding_fee) * 0.5, 10.0)

            recent_pnls.append(net_pnl)
            brain.setdefault("last_pnls", []).append(net_pnl)
            brain["last_pnls"] = brain["last_pnls"][-80:]

            append_memory_history(
                {
                    "id": trade_id,
                    "time": datetime.now().isoformat(),
                    "gross_pnl": round(gross_pnl, 2),
                    "net_pnl": round(net_pnl, 2),
                    "trading_fee": round(trading_fee, 2),
                    "funding_fee": round(funding_fee, 2),
                    "fee_dominated": fee_dominated,
                    "source": "exchange_ingest",
                }
            )

            processed.add(trade_id)
            added += 1

        if added:
            brain["processed_trade_ids"] = list(processed)[-1000:]
            log(f"Ingested {added} closed trades with exact fees")
            maybe_save_memory(force=True)

    except Exception as exc:
        message = str(exc)
        if "404" in message:
            brain["closed_trade_ingest_disabled"] = True
            brain["closed_trade_ingest_disabled_reason"] = (
                f"{datetime.now().isoformat()} stale get_filled_orders endpoint returned 404"
            )
            log("ingest_closed_trades disabled: stale get_filled_orders endpoint returned 404")
            maybe_save_memory(force=True)
            return
        log(f"ingest_closed_trades error: {exc}")


async def ingest_leaderboard(client):
    try:
        lb_obj = await client.futures.get_leaderboard()
        if not lb_obj:
            return
        if hasattr(lb_obj, "model_dump"):
            leaderboard_data = lb_obj.model_dump()
        else:
            leaderboard_data = {k: _safe_get(lb_obj, k) for k in ("daily", "weekly", "day", "week") if _safe_get(lb_obj, k)}
        daily = leaderboard_data.get("daily") or leaderboard_data.get("day") or []
        weekly = leaderboard_data.get("weekly") or leaderboard_data.get("week") or []
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "top_daily_pnl": 0.0,
            "top_weekly_pnl": 0.0,
            "biggest_winner": "N/A",
            "market_sentiment": "neutral",
            "your_pnl": float(brain.get("lifetime_total_pnl", 0.0)) + float(brain.get("total_pnl", 0.0)),
            "gap_to_top": 0.0,
            "relative_strength": "neutral",
            "is_ahead": False,
        }
        if daily:
            top = daily[0]
            snapshot["top_daily_pnl"] = float(_safe_get(top, "pl", 0) or _safe_get(top, "pnl", 0) or 0)
            snapshot["biggest_winner"] = _safe_get(top, "username", "Anonymous") or "Anonymous"
        if weekly:
            snapshot["top_weekly_pnl"] = float(_safe_get(weekly[0], "pl", 0) or _safe_get(weekly[0], "pnl", 0) or 0)
        top_pnl = snapshot["top_daily_pnl"]
        your_pnl = snapshot["your_pnl"]
        snapshot["gap_to_top"] = float(top_pnl - your_pnl)
        snapshot["is_ahead"] = your_pnl > top_pnl
        if top_pnl > 250000:
            snapshot["market_sentiment"] = "strongly_bullish"
        elif top_pnl > 75000:
            snapshot["market_sentiment"] = "bullish"
        elif top_pnl < -75000:
            snapshot["market_sentiment"] = "bearish"
        if top_pnl == 0:
            snapshot["relative_strength"] = "unknown"
        elif your_pnl >= top_pnl * 0.8:
            snapshot["relative_strength"] = "leading"
        elif your_pnl >= top_pnl * 0.4:
            snapshot["relative_strength"] = "competitive"
        else:
            snapshot["relative_strength"] = "behind"
        brain.setdefault("leaderboard_history", []).append(snapshot)
        brain["leaderboard_history"] = brain["leaderboard_history"][-12:]
        brain["leaderboard"] = snapshot
        log(
            f"LB | Top={top_pnl:,.0f} | You={your_pnl:,.0f} | "
            f"Gap={snapshot['gap_to_top']:,.0f} | {snapshot['relative_strength']}"
        )
        maybe_save_memory(force=True)
    except Exception as exc:
        log(f"ingest_leaderboard error: {exc}")


async def seed_brain_from_history(client):
    """Seed brain stats using ONLY trades on or after 2026-04-16 14:00 UTC"""

    if brain.get("learning_epoch") == LEARNING_EPOCH and brain.get("trades", 0) > 0:
        log(f"✅ Epoch {LEARNING_EPOCH} already has data — loading from memory only")
        return

    log(f"🌱 First run of new epoch {LEARNING_EPOCH} — seeding historical trades from 2026-04-16 14:00 UTC onwards")

    try:
        trades = await client.futures.cross.get_filled_orders()
        if not trades:
            log("No historical trades found from exchange")
            return

        pnls = []
        processed = set(brain.get("processed_trade_ids", []))
        used_trades = 0

        for trade in trades:
            trade_id = str(_safe_get(trade, "id", "") or _safe_get(trade, "order_id", "") or "")
            if not trade_id or trade_id in processed:
                continue

            ts_str = _safe_get(trade, "time") or _safe_get(trade, "created_at") or _safe_get(trade, "timestamp")
            trade_time = parse_exchange_dt(ts_str)
            if not trade_time:
                continue
            if trade_time < EPOCH_CUTOFF_UTC:
                processed.add(trade_id)
                continue

            try:
                pnl = float(_safe_get(trade, "pl", 0) or _safe_get(trade, "pnl", 0) or _safe_get(trade, "realized_pnl", 0) or 0)
            except Exception:
                continue

            fee = float(_safe_get(trade, "trading_fee", 0) or _safe_get(trade, "fees", 0) or _safe_get(trade, "fee", 0) or 0)
            net_pnl = pnl - fee

            if abs(net_pnl) < 1:
                processed.add(trade_id)
                continue

            pnls.append(net_pnl)
            processed.add(trade_id)
            used_trades += 1

        if pnls:
            total = len(pnls)
            wins = sum(1 for p in pnls if p > 0)

            abs_pnls = [abs(p) for p in pnls if abs(p) > 0]
            if abs_pnls:
                avg_abs_pnl = sum(abs_pnls) / len(abs_pnls)
                pnl_reference = max(avg_abs_pnl * 2.5, 200)
                log(f"Smart PnL scaling: avg |PnL| = {avg_abs_pnl:.1f} sats → reference = {pnl_reference:.0f} sats")
            else:
                pnl_reference = 800

            for net_pnl in pnls:
                confidence = min(1.0, max(0.3, abs(net_pnl) / pnl_reference))

                intent = "scalp" if abs(net_pnl) < 150 else "mean_revert" if abs(net_pnl) < 400 else "trend_follow"
                intent_stats = brain.setdefault("intent_stats", {}).setdefault(intent, {"trades": 0, "wins": 0, "pnl": 0.0, "winrate": 0.0})
                intent_stats["trades"] += 1
                intent_stats["pnl"] += net_pnl
                if net_pnl > 0:
                    intent_stats["wins"] += 1
                intent_stats["winrate"] = intent_stats["wins"] / max(intent_stats["trades"], 1)

                conf_bucket = round(confidence, 1)
                conf_stats = brain.setdefault("confidence_stats", {}).setdefault(conf_bucket, {"trades": 0, "wins": 0, "pnl": 0.0, "winrate": 0.0})
                conf_stats["trades"] += 1
                conf_stats["pnl"] += net_pnl
                if net_pnl > 0:
                    conf_stats["wins"] += 1
                conf_stats["winrate"] = conf_stats["wins"] / max(conf_stats["trades"], 1)

            brain["last_pnls"] = pnls[-14:]

            brain["trades"] = max(int(brain.get("trades", 0)), total)
            brain["wins"] = max(int(brain.get("wins", 0)), wins)
            brain["losses"] = max(int(brain.get("losses", 0)), total - wins)
            brain["total_pnl"] = float(brain.get("total_pnl", 0.0)) if brain.get("session_start") else sum(pnls)

            brain["historical_stats"] = {
                "trades": total,
                "wins": wins,
                "losses": total - wins,
                "win_rate": round(wins / max(total, 1) * 100, 1),
                "avg_pnl": round(sum(pnls) / max(total, 1), 4),
            }

            log(f"✅ Seeded {used_trades} trades into new epoch | last_pnls={len(brain['last_pnls'])}")

        brain["processed_trade_ids"] = list(processed)[-1000:]
        maybe_save_memory(force=True)

    except Exception as exc:
        log(f"seed_brain_from_history error: {exc}")


async def seed_regime_from_history():
    """Seed regime weights using ONLY trades on or after 2026-04-16 14:00 UTC"""

    if brain.get("regime_weights") and len(brain.get("regime_weights", {})) > 0:
        log("Regime weights already populated — skipping seeding")
        return

    log("🌱 Seeding regime performance using trades from 2026-04-16 14:00 UTC onwards")

    try:
        regime_stats = brain.setdefault("regime_stats", {})
        for regime in ("trend", "chop", "volatile", "squeeze"):
            regime_stats[regime] = {"trades": 0, "wins": 0, "pnl": 0.0}

        history = MEMORY.get("history", [])
        if not history:
            log("No history available for regime seeding")
            return

        used_trades = 0
        for item in history:
            ts_str = item.get("time") or item.get("timestamp")
            trade_time = parse_exchange_dt(ts_str)
            if not trade_time:
                continue
            if trade_time < EPOCH_CUTOFF_UTC:
                continue

            regime = item.get("regime", "unknown")
            pnl = float(item.get("net_pnl", 0.0))
            is_win = pnl > 0

            regime_stats.setdefault(regime, {"trades": 0, "wins": 0, "pnl": 0.0})
            regime_stats[regime]["trades"] += 1
            regime_stats[regime]["pnl"] += pnl
            if is_win:
                regime_stats[regime]["wins"] += 1

            used_trades += 1

        if used_trades == 0:
            log("No trades found after cutoff — skipping regime seeding")
            return

        regime_weights = {}
        for regime, stats in regime_stats.items():
            if stats["trades"] < 5:
                regime_weights[regime] = 0.0
                continue
            winrate = stats["wins"] / stats["trades"]
            avg_pnl = stats["pnl"] / stats["trades"]
            regime_weights[regime] = (winrate - 0.5) * avg_pnl

        brain["regime_weights"] = regime_weights

        best = max(regime_weights.items(), key=lambda x: x[1], default=("none", 0))
        log(f"✅ Regime edges seeded from {used_trades} trades | best={best[0]} edge={best[1]:.4f}")

        maybe_save_memory(force=True)

    except Exception as exc:
        log(f"seed_regime_from_history error: {exc}")


async def fetch_oracle_index_history() -> list[dict[str, Any]]:
    now_utc = datetime.now(timezone.utc)
    from_dt = datetime.fromtimestamp(now_utc.timestamp() - ORACLE_REPLAY_LOOKBACK_HOURS * 3600, tz=timezone.utc)
    session = await get_ai_session()
    url = f"{ORACLE_API_BASE.rstrip('/')}/oracle/index"
    rows: list[dict[str, Any]] = []
    seen_times: set[str] = set()
    page_to = now_utc

    for _ in range(ORACLE_REPLAY_MAX_PAGES):
        params = {
            "from": from_dt.isoformat().replace("+00:00", "Z"),
            "to": page_to.isoformat().replace("+00:00", "Z"),
            "limit": ORACLE_REPLAY_LIMIT,
        }
        async with session.get(url, params=params) as response:
            response.raise_for_status()
            payload = await response.json()
        if not isinstance(payload, list) or not payload:
            break

        page_rows = []
        for item in payload:
            try:
                ts = str(item.get("time") or "")
                idx = float(item.get("index", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if not ts or idx <= 0 or ts in seen_times:
                continue
            seen_times.add(ts)
            page_rows.append({"time": ts, "index": idx})
        if not page_rows:
            break
        rows.extend(page_rows)

        oldest = min(page_rows, key=lambda item: item["time"])
        oldest_dt = parse_iso_dt(oldest["time"])
        if oldest_dt is None or oldest_dt <= from_dt or len(page_rows) < ORACLE_REPLAY_LIMIT:
            break
        page_to = oldest_dt

    rows.sort(key=lambda item: item.get("time", ""))
    return rows


def compute_replay_regime(window_prices: list[float]) -> dict[str, float | str]:
    if len(window_prices) < 20:
        return {"regime": "unknown", "bias": "neutral", "regime_flavor": "unknown", "volatility": 0.0, "trend_strength": 0.0, "compression": 0.0}
    returns = np.diff(np.array(window_prices, dtype=float)) / np.array(window_prices, dtype=float)[:-1]
    volatility = float(np.std(returns))
    slope = float(np.polyfit(np.arange(len(window_prices), dtype=float), np.array(window_prices, dtype=float), 1)[0])
    normalized_slope = slope / max(float(np.mean(window_prices)), 1.0)
    signed_trend_strength = float(normalized_slope)
    compression = max(0.0, 1.0 - ((max(window_prices) - min(window_prices)) / max(float(np.mean(window_prices)), 1.0)))
    trend_strength = abs(signed_trend_strength)
    short_prices = np.array(window_prices[-20:], dtype=float)
    medium_prices = np.array(window_prices[-60:] if len(window_prices) >= 60 else window_prices, dtype=float)
    long_prices = np.array(window_prices[-180:] if len(window_prices) >= 180 else window_prices, dtype=float)
    mtf_slopes = []
    for segment in (short_prices, medium_prices, long_prices):
        seg_slope = float(np.polyfit(np.arange(len(segment), dtype=float), segment, 1)[0]) if len(segment) >= 8 else 0.0
        mtf_slopes.append(seg_slope / max(float(np.mean(segment)), 1.0))
    mtf_signs = [1 if val > 0 else -1 if val < 0 else 0 for val in mtf_slopes]
    mtf_alignment_score = sum(mtf_signs)
    drift_20 = ((window_prices[-1] / window_prices[-20]) - 1.0) if len(window_prices) >= 20 else 0.0
    drift_60 = ((window_prices[-1] / window_prices[-60]) - 1.0) if len(window_prices) >= 60 else drift_20
    directional_drift = max(abs(drift_20), abs(drift_60))
    if mtf_alignment_score >= 2 and (signed_trend_strength > 0 or drift_20 > 0):
        bias = "bullish"
    elif mtf_alignment_score <= -2 and (signed_trend_strength < 0 or drift_20 < 0):
        bias = "bearish"
    else:
        bias = "neutral"
    regime = "chop"
    if volatility > 0.004:
        regime = "volatile"
    if (
        trend_strength > 0.0011
        and volatility < 0.0045
        and directional_drift > 0.0035
        and abs(mtf_alignment_score) >= 2
    ):
        regime = "trend"
    elif compression > 0.997 and volatility < 0.0025:
        regime = "squeeze"
    if volatility < 0.002 and trend_strength < 0.0008 and abs(mtf_alignment_score) < 2:
        regime = "chop"
    return {
        "regime": regime,
        "bias": bias,
        "regime_flavor": regime if bias == "neutral" else f"{bias}_{regime}",
        "volatility": volatility,
        "trend_strength": trend_strength,
        "signed_trend_strength": signed_trend_strength,
        "compression": compression,
        "mtf_alignment_score": float(mtf_alignment_score),
        "directional_drift": float(directional_drift),
    }


def simulate_oracle_shadow_replay(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) < ORACLE_REPLAY_MIN_POINTS:
        return {}

    prices = [float(r["index"]) for r in rows]
    window_size = min(200, len(prices) // 4)
    stride = 4

    regime_scores: dict[str, dict] = {}
    regime_stats: dict[str, dict] = {}
    regime_context_raw: dict[str, dict] = {}

    for i in range(window_size, len(prices) - ORACLE_REPLAY_HOLD_STEPS - 1, stride):
        window = prices[i - window_size:i]
        entry_price = prices[i]
        if entry_price <= 0:
            continue
        future = prices[i + 1:i + 1 + ORACLE_REPLAY_HOLD_STEPS]
        if len(future) < ORACLE_REPLAY_HOLD_STEPS // 2:
            continue

        rr = compute_replay_regime(window)
        regime = str(rr.get("regime", "chop"))
        bias = str(rr.get("bias", "neutral"))

        max_future = max(future)
        min_future = min(future)
        long_peak_bps = (max_future - entry_price) / entry_price * 10000
        long_adverse_bps = max(0.0, (entry_price - min_future) / entry_price * 10000)
        short_peak_bps = max(0.0, (entry_price - min_future) / entry_price * 10000)
        short_adverse_bps = (max_future - entry_price) / entry_price * 10000

        if bias == "bullish":
            peak_bps, adverse_bps = long_peak_bps, long_adverse_bps
        elif bias == "bearish":
            peak_bps, adverse_bps = short_peak_bps, short_adverse_bps
        else:
            if long_peak_bps >= short_peak_bps:
                peak_bps, adverse_bps, bias = long_peak_bps, long_adverse_bps, "bullish"
            else:
                peak_bps, adverse_bps, bias = short_peak_bps, short_adverse_bps, "bearish"

        fee_clear = peak_bps >= ORACLE_REPLAY_FEE_PROXY_BPS
        score = peak_bps / max(peak_bps + adverse_bps, 0.01)

        rs = regime_scores.setdefault(regime, {"samples": 0, "score_sum": 0.0})
        rs["samples"] += 1
        rs["score_sum"] += score

        st = regime_stats.setdefault(regime, {
            "trades": 0, "fee_clears": 0,
            "peak_bps_sum": 0.0, "adverse_bps_sum": 0.0,
            "fee_clear_timed_count": 0, "time_to_fee_clear_sum": 0.0,
            "fee_clear_before_half_count": 0,
            "fade_after_peak_sum": 0.0, "degrade_after_peak_count": 0,
        })
        st["trades"] += 1
        st["peak_bps_sum"] += peak_bps
        st["adverse_bps_sum"] += adverse_bps

        if fee_clear:
            st["fee_clears"] += 1
            for t_idx, fp in enumerate(future):
                fp_bps = ((fp - entry_price) if bias == "bullish" else (entry_price - fp)) / entry_price * 10000
                if fp_bps >= ORACLE_REPLAY_FEE_PROXY_BPS:
                    st["fee_clear_timed_count"] += 1
                    st["time_to_fee_clear_sum"] += t_idx + 1
                    if t_idx + 1 <= ORACLE_REPLAY_HOLD_STEPS // 2:
                        st["fee_clear_before_half_count"] += 1
                    break

        if bias == "bearish":
            peak_price = min_future
            fade_bps = (future[-1] - peak_price) / entry_price * 10000
        else:
            peak_price = max_future
            fade_bps = (peak_price - future[-1]) / entry_price * 10000
        st["fade_after_peak_sum"] += max(0.0, fade_bps)
        if fade_bps > 0.5:
            st["degrade_after_peak_count"] += 1

        ctx = regime_context_raw.setdefault(regime, {
            "bias_counts": {"bullish": 0, "bearish": 0, "neutral": 0},
            "flavor_counts": {},
            "signed_trend_sum": 0.0, "directional_drift_sum": 0.0,
            "mtf_alignment_sum": 0.0, "count": 0,
        })
        ctx["bias_counts"][bias] = ctx["bias_counts"].get(bias, 0) + 1
        flavor = str(rr.get("regime_flavor", regime))
        ctx["flavor_counts"][flavor] = ctx["flavor_counts"].get(flavor, 0) + 1
        ctx["signed_trend_sum"] += float(rr.get("signed_trend_strength", 0.0) or 0.0)
        ctx["directional_drift_sum"] += float(rr.get("directional_drift", 0.0) or 0.0)
        ctx["mtf_alignment_sum"] += float(rr.get("mtf_alignment_score", 0.0) or 0.0)
        ctx["count"] += 1

    if not regime_scores:
        return {}

    regime_context: dict[str, dict] = {}
    for reg, ctx in regime_context_raw.items():
        count = max(ctx["count"], 1)
        bias_counts = ctx["bias_counts"]
        total_biases = max(sum(bias_counts.values()), 1)
        dominant_bias = max(bias_counts, key=lambda k: bias_counts[k])
        flavor_counts = ctx["flavor_counts"]
        dominant_flavor = max(flavor_counts, key=lambda k: flavor_counts[k]) if flavor_counts else reg
        regime_context[reg] = {
            "dominant_bias": dominant_bias,
            "dominant_flavor": dominant_flavor,
            "bullish_bias_rate": bias_counts.get("bullish", 0) / total_biases,
            "bearish_bias_rate": bias_counts.get("bearish", 0) / total_biases,
            "neutral_bias_rate": bias_counts.get("neutral", 0) / total_biases,
            "avg_signed_trend_strength": ctx["signed_trend_sum"] / count,
            "avg_directional_drift": ctx["directional_drift_sum"] / count,
            "avg_mtf_alignment_score": ctx["mtf_alignment_sum"] / count,
        }

    regime_weights: dict[str, float] = {}
    for reg, rs in regime_scores.items():
        samples = rs["samples"]
        if samples < 10:
            continue
        avg_score = rs["score_sum"] / samples
        st = regime_stats.get(reg, {})
        trades = st.get("trades", 0)
        fcr = st.get("fee_clears", 0) / max(trades, 1) if trades else 0.0
        regime_weights[reg] = float(np.clip((avg_score - 0.5) * 2.0 + (fcr - 0.5) * 1.0, -1.0, 1.0))

    return {
        "regime_scores": regime_scores,
        "regime_stats": regime_stats,
        "regime_context": regime_context,
        "regime_weights": regime_weights,
        "points": len(prices),
    }


def get_flat_entry_skip_reason(position: PositionState, usable: float) -> Optional[str]:
    if position.is_open:
        return None
    gate_state = get_entry_gate_state(usable)
    if brain.get("risk_mode") == "protection":
        return "protection mode"
    return get_common_entry_block_reason(usable, gate_state)


async def run_oracle_shadow_replay_once():
    try:
        rows = await fetch_oracle_index_history()
        if len(rows) < ORACLE_REPLAY_MIN_POINTS:
            brain.setdefault("oracle_replay", {})["last_status"] = f"insufficient ({len(rows)} pts)"
            log(f"Oracle replay skipped: {len(rows)} pts (need {ORACLE_REPLAY_MIN_POINTS})")
            return
        result = simulate_oracle_shadow_replay(rows)
        if not result:
            brain.setdefault("oracle_replay", {})["last_status"] = "empty_result"
            return
        oracle = brain.setdefault("oracle_replay", {})
        oracle.update({
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_status": "ok",
            "points": result["points"],
            "regime_scores": result["regime_scores"],
            "regime_stats": result["regime_stats"],
            "regime_context": result["regime_context"],
            "regime_weights": result["regime_weights"],
        })
        regime_summary = {
            r: {
                "samples": v.get("samples", 0),
                "fcr": round(result["regime_stats"].get(r, {}).get("fee_clears", 0) / max(result["regime_stats"].get(r, {}).get("trades", 1), 1), 2),
                "bias": result["regime_context"].get(r, {}).get("dominant_bias", "?"),
            }
            for r, v in result["regime_scores"].items()
        }
        log(f"Oracle replay updated | pts={result['points']} {regime_summary}")
    except Exception as exc:
        brain.setdefault("oracle_replay", {})["last_status"] = f"error: {exc}"
        log(f"Oracle replay error: {exc}")


async def oracle_shadow_loop():
    await asyncio.sleep(90)
    while True:
        try:
            await run_oracle_shadow_replay_once()
        except Exception as exc:
            log(f"Oracle loop error: {exc}")
        await asyncio.sleep(ORACLE_REPLAY_INTERVAL_SECONDS)


async def fast_market_loop(client):
    log("Fast market loop started")
    consecutive_failures = 0
    last_saved_price = None
    last_momentum_bucket = None
    last_minute = None
    context_counter = 0

    while True:
        try:
            ticker = await client.futures.get_ticker()
            price = extract_price_lnm(ticker)
            if price <= 0:
                consecutive_failures += 1
                await asyncio.sleep(min(1.5 * consecutive_failures, 15))
                continue

            consecutive_failures = 0
            update_price(price)
            prev = float(market_state.get("last_price", 0.0))
            market_state["last_price"] = price

            if prev > 0:
                momentum = (price - prev) / prev
                market_state["momentum"] = momentum
                if len(PRICE_WINDOW) >= 20:
                    returns = np.diff(np.array(PRICE_WINDOW, dtype=float)) / np.array(PRICE_WINDOW, dtype=float)[:-1]
                    market_state["volatility"] = float(max(np.std(returns), 0.0002))
                market_state["micro_trend"] = "bullish" if momentum > 0.0005 else "bearish" if momentum < -0.0005 else "neutral"

            brain["last_price"] = price
            brain["momentum"] = market_state["momentum"]
            brain["volatility"] = market_state["volatility"]
            brain["regime_hint"] = market_state["micro_trend"]
            update_shadow_exploration_pending(price)

            if context_counter % 4 == 0:
                await get_market_context(client)
            context_counter += 1
            if context_counter >= 10:
                context_counter = 0

            imbalance = float(brain.get("market_context", {}).get("imbalance", 0.0))
            funding = float(brain.get("funding_rate_pct", 0.0))
            brain["momentum_history"].append(market_state["momentum"])
            brain["imbalance_history"].append(imbalance)
            brain["funding_history"].append(funding)
            brain["confidence_bias_history"].append(round(float(brain.get("confidence_bias", 0.0)), 4))

            regime_state = compute_regime()
            brain["market_regime"] = regime_state
            brain["regime_vol_history"].append(float(regime_state.get("volatility", 0.0) or 0.0))
            brain.setdefault("regime_history", []).append({"time": datetime.now().isoformat(), **regime_state})
            brain["regime_history"] = brain["regime_history"][-200:]
            brain["regime_transition"] = detect_regime_transition()
            if isinstance(brain.get("market_context"), dict):
                refresh_market_signal_context()

            if len(PRICE_WINDOW) >= 25:
                recent_prices = list(PRICE_WINDOW)[-15:]
                recent_max = max(recent_prices)
                recent_min = min(recent_prices)
                recent_mean = float(np.mean(recent_prices))
                if price > recent_max * 1.0005:
                    brain["price_action_summary"] = "bullish_breakout"
                elif price < recent_min * 0.9995:
                    brain["price_action_summary"] = "bearish_breakdown"
                elif price > recent_mean:
                    brain["price_action_summary"] = "higher_highs"
                else:
                    brain["price_action_summary"] = "range_bound"

            range_state = compute_range_state()
            mc = brain.setdefault("market_context", {})
            mc["range_position"] = range_state["range_position"]
            mc["range_width_pct"] = range_state["range_width_pct"]
            mc["range_high"] = range_state["range_high"]
            mc["range_low"] = range_state["range_low"]
            mc["range_mid"] = range_state["range_mid"]
            mc["range_established"] = range_state["range_established"]
            mc["micro_range_established"] = range_state["micro_range_established"]
            mc["micro_range_reason"] = range_state["micro_range_reason"]
            structure = compute_broader_structure_context(refresh_market_signal_context())

            price_moved = last_saved_price is None or abs(price - last_saved_price) / price > 0.0015
            bucket = "up" if market_state["momentum"] > 0.001 else "down" if market_state["momentum"] < -0.001 else "flat"
            momentum_shift = last_momentum_bucket is None or bucket != last_momentum_bucket
            if price_moved or momentum_shift:
                log(
                    f"{price:.0f} | mom={market_state['momentum']:+.5f} | {market_state['micro_trend']} | "
                    f"regime={brain['market_regime']['regime']} bias={brain['market_regime'].get('bias', 'neutral')} | "
                    f"pa={brain.get('price_action_summary')} | structure={structure.get('action', 'wait')}/"
                    f"{float(structure.get('confidence', 0.0) or 0.0):.2f} | "
                    f"session={brain.get('market_context', {}).get('session_bucket', 'n/a')} | "
                    f"volx={brain.get('market_context', {}).get('volatility_expansion', 1.0):.2f} | "
                    f"mtf={brain.get('market_context', {}).get('mtf_alignment', 'mixed')} | "
                    f"ext={brain.get('market_context', {}).get('external_bias', 'neutral')}/"
                    f"{float(brain.get('market_context', {}).get('external_conviction', 0.0) or 0.0):.2f}/"
                    f"{brain.get('market_context', {}).get('external_data_quality', 'none')}"
                )
                last_saved_price = price
                last_momentum_bucket = bucket
                maybe_save_memory()

            current_minute = int(time.time() // 60)
            if current_minute != last_minute:
                maybe_save_memory(force=True)
                last_minute = current_minute
        except Exception as exc:
            consecutive_failures += 1
            brain["last_monitor_error"] = {"error": str(exc), "timestamp": datetime.now().isoformat()}
            log(f"Fast loop error: {exc}")
            await asyncio.sleep(min(2 * consecutive_failures, 10))
        await asyncio.sleep(FAST_SLEEP)


def refresh_flat_state(position: PositionState):
    if position.is_open:
        brain["flat_started_at"] = None
    elif not brain.get("flat_started_at"):
        brain["flat_started_at"] = datetime.now().isoformat()


def should_skip_slow_cycle() -> bool:
    brain["risk_mode"] = get_risk_mode()
    refresh_risk_persistence_fields()
    if brain["risk_mode"] == "protection":
        cooldown_remaining = max(0, int(brain.get("cooldown_until", 0) - time.time()))
        risk_snapshot = brain.get("recent_risk_snapshot", {})
        log(
            "Protection mode active, skipping trades | "
            f"streak={brain.get('streak', 0)} "
            f"recent_loss_ratio={float(risk_snapshot.get('recent_loss_ratio', 0.0)):.4f} "
            f"daily_loss_ratio={float(risk_snapshot.get('daily_loss_ratio', 0.0)):.4f} "
            f"legacy_drawdown={float(risk_snapshot.get('legacy_drawdown', 0.0)):.4f} "
            f"cooldown_remaining={cooldown_remaining}s"
        )
        return True
    if brain.get("regime_transition", {}).get("instability", 0.0) > 0.7:
        log("High regime instability, skipping cycle")
        return True
    return False


async def handle_flat_cycle(client, position: PositionState, usable: float):
    adaptive = get_adaptive_trade_parameters()
    strategic = get_strategic_aggression_context()
    brain["last_strategic_context"] = safe_serialize(strategic)
    effective_mix_rate = get_effective_explore_rate()
    get_recent_risk_snapshot()
    log(
        f"🧠 MODE CHECK | explore_rate={effective_mix_rate:.2f} "
        f"mode={brain.get('risk_mode')} regime={brain.get('market_regime', {}).get('regime')} "
        f"strategy={strategic.get('mode', 'observe')} "
        f"reason={describe_risk_mode()}"
    )

    pre_ai_skip_reason = get_flat_entry_skip_reason(position, usable)
    brain["last_entry_gate_state"] = safe_serialize(get_entry_gate_state(usable))
    brain["last_flat_entry_block_reason"] = pre_ai_skip_reason
    maybe_log_gate_snapshot(usable, brain["last_entry_gate_state"], pre_ai_skip_reason)
    flat_entry_blocked = bool(pre_ai_skip_reason)
    bypass_flat_block, bypass_flat_reason = should_aggressive_learning_bypass_block(
        pre_ai_skip_reason,
        brain.get("last_entry_gate_state", {}) or {},
    )
    _hold_cooldown_remaining = AI_ENTRY_COOLDOWN_SECONDS - (time.time() - float(brain.get("last_ai_hold_signal_time", 0)))
    if pre_ai_skip_reason and not bypass_flat_block:
        log(f"🚫 AI ENTRY SKIPPED: {pre_ai_skip_reason}")
        maybe_record_shadow_exploration(adaptive, usable, pre_ai_skip_reason)
        signal = None
    elif pre_ai_skip_reason and bypass_flat_block:
        flat_entry_blocked = False
        log(f"⚡ AGGRESSIVE LEARNING BYPASS: {pre_ai_skip_reason} | {bypass_flat_reason}")
        signal = await get_ai_entry_signal(client, position, usable=usable)
        if signal is None or signal.action == "hold":
            brain["last_ai_hold_signal_time"] = time.time()
        else:
            brain["last_ai_hold_signal_time"] = 0
    elif _hold_cooldown_remaining > 0:
        log(f"⏳ AI ENTRY COOLDOWN: {_hold_cooldown_remaining:.0f}s remaining after last hold signal")
        signal = None
    else:
        signal = await get_ai_entry_signal(client, position, usable=usable)
        if signal is None or signal.action == "hold":
            brain["last_ai_hold_signal_time"] = time.time()
        else:
            brain["last_ai_hold_signal_time"] = 0
    chosen_signal = None

    if signal:
        normalized_action, normalized_direction, normalization_note = normalize_position_action(
            signal.action,
            signal.direction,
            position.side if position.is_open else None,
        )
        if normalization_note:
            log(normalization_note)
        signal.action = normalized_action
        if normalized_direction:
            signal.direction = normalized_direction
        signal.leverage = int(clamp(signal.leverage, MIN_LEVERAGE, MAX_LEVERAGE))
        signal.risk_per_trade = adaptive.get("risk_per_trade", RISK_PER_TRADE)
        signal.base_risk_per_trade = signal.risk_per_trade
        signal.effective_risk_per_trade = signal.risk_per_trade
        allowed_strategy, strategy_reason = is_strategy_allowed_for_regime(
            signal,
            adaptive.get("regime", "unknown"),
            position_open=position.is_open,
        )
        if not allowed_strategy:
            log(f"Strategy blocked: {strategy_reason}")
            signal = None

    if signal and signal.action == "open":
        gate_state = dict(brain.get("last_entry_gate_state", {}) or {})
        align_score = float((gate_state.get("chop_alignment") or {}).get("score", 0.0) or 0.0)
        expected_edge = float(getattr(signal, "expected_edge", 0.0) or 0.0)
        predictive_score = float(getattr(signal, "predictive_setup_score", 0.0) or 0.0)
        aggression_override = bool(
            str(brain.get("risk_mode", "normal") or "normal") == "caution"
            and (
                (expected_edge >= 0.55 and predictive_score >= 0.48)
                or (align_score >= 0.65 and expected_edge >= 0.24 and predictive_score >= 0.48)
            )
        )
        flat_minutes = get_flat_duration_minutes()
        dynamic_conf_floor = float(adaptive.get("confidence_threshold", 0.6) or 0.6)
        if str(adaptive.get("regime", "unknown") or "unknown") == "squeeze":
            dynamic_conf_floor = AI_SQUEEZE_MIN_CONFIDENCE
            if flat_minutes >= CAUTION_DECAY_START_MINUTES:
                dynamic_conf_floor = AI_SQUEEZE_FLAT_MIN_CONFIDENCE
            if aggression_override:
                dynamic_conf_floor = min(dynamic_conf_floor, 0.32)
        if not adaptive.get("risk_permission", True) and not aggression_override:
            log(f"Risk permission denied: regime={adaptive.get('regime')}")
        elif signal.confidence < dynamic_conf_floor:
            log(
                f"Primary signal blocked: confidence {signal.confidence:.2f} "
                f"< threshold {dynamic_conf_floor:.2f}"
            )
        else:
            if aggression_override:
                signal.mode = "exploit"
            chosen_signal = signal

    primary_said_hold = signal is None or signal.action == "hold"
    if chosen_signal is None and primary_said_hold and not flat_entry_blocked:
        explore_signal = choose_exploration_signal(adaptive, usable)
        if explore_signal:
            log(
                f"🧪 Shadow-backed live override | policy={explore_signal.policy} "
                f"dir={explore_signal.direction} conf={explore_signal.confidence:.2f} "
                f"edge={float(getattr(explore_signal, 'expected_edge', 0.0) or 0.0):.2f}"
            )
            explore_signal.base_risk_per_trade = float(
                getattr(explore_signal, "risk_per_trade", RISK_PER_TRADE) or RISK_PER_TRADE
            )
            explore_signal.effective_risk_per_trade = explore_signal.base_risk_per_trade
            chosen_signal = explore_signal
        elif bypass_flat_block:
            fallback_signal = build_aggressive_learning_fallback_signal(adaptive)
            if fallback_signal:
                log(
                    f"⚡ Aggressive fallback entry | policy={fallback_signal.policy} "
                    f"dir={fallback_signal.direction} conf={fallback_signal.confidence:.2f} "
                    f"edge={float(getattr(fallback_signal, 'expected_edge', 0.0) or 0.0):.2f}"
                )
                fallback_signal.base_risk_per_trade = float(
                    getattr(fallback_signal, "risk_per_trade", RISK_PER_TRADE) or RISK_PER_TRADE
                )
                fallback_signal.effective_risk_per_trade = fallback_signal.base_risk_per_trade
                chosen_signal = fallback_signal

    if not chosen_signal:
        return

    post_win_edge_block = get_post_win_reentry_block_reason(chosen_signal)
    if post_win_edge_block:
        log(f"🚫 ENTRY SKIPPED: {post_win_edge_block}")
        return

    level_block = get_level_entry_block_reason(chosen_signal)
    if level_block:
        bypass_level_block, bypass_level_reason = should_aggressive_learning_bypass_block(
            level_block,
            brain.get("last_entry_gate_state", {}) or {},
        )
        if not bypass_level_block:
            log(f"🚫 ENTRY SKIPPED: {level_block}")
            maybe_record_shadow_exploration(adaptive, usable, level_block)
            return
        log(f"⚡ ENTRY LEVEL BYPASS: {level_block} | {bypass_level_reason}")

    if not chosen_signal.entry_tag:
        chosen_signal.entry_tag = build_entry_tag(chosen_signal)
    if not chosen_signal.signal_price:
        chosen_signal.signal_price = float(brain.get("last_price") or market_state.get("last_price") or 0.0)
    apply_parent_allocation_plan(chosen_signal, adaptive, usable)
    signal_ctx = get_signal_context()
    broader_alignment = get_broader_structure_alignment(
        chosen_signal.direction,
        chosen_signal.intent,
        brain.get("broader_structure") or compute_broader_structure_context(signal_ctx),
    )
    level_edge = bool(
        (chosen_signal.direction == "long" and (signal_ctx.get("at_support", False) or signal_ctx.get("sweep_reclaim_long", False)))
        or (chosen_signal.direction == "short" and (signal_ctx.get("at_resistance", False) or signal_ctx.get("sweep_reclaim_short", False)))
    )
    leverage_alignment = "excellent" if broader_alignment == "aligned" and level_edge else "good" if broader_alignment == "aligned" else "supportive" if broader_alignment == "supportive" else "neutral"
    chosen_signal.leverage = get_dynamic_leverage(
        max(
            float(getattr(chosen_signal, "predictive_setup_score", 0.0) or 0.0),
            float(getattr(chosen_signal, "expected_edge", 0.0) or 0.0),
        ),
        leverage_alignment,
        str(adaptive.get("regime", "unknown") or "unknown"),
        str(brain.get("risk_mode", "normal") or "normal"),
    )
    chosen_signal.entry_tag = build_entry_tag(chosen_signal)
    apply_custom_roi_plan(chosen_signal)

    confirmed, confirm_reason = confirm_live_entry(chosen_signal, usable)
    if not confirmed:
        log(f"🚫 ENTRY CONFIRM BLOCK: {confirm_reason}")
        maybe_record_shadow_exploration(adaptive, usable, confirm_reason)
        return
    log(f"✅ ENTRY CONFIRM PASS: {confirm_reason}")

    squeeze_structure_block = get_squeeze_structure_block_reason(chosen_signal.direction, chosen_signal.intent)
    if squeeze_structure_block:
        bypass_squeeze_block, bypass_squeeze_reason = should_aggressive_learning_bypass_block(
            squeeze_structure_block,
            brain.get("last_entry_gate_state", {}) or {},
        )
        if not bypass_squeeze_block:
            log(f"🚫 ENTRY CONFIRM BLOCK: {squeeze_structure_block}")
            maybe_record_shadow_exploration(adaptive, usable, squeeze_structure_block)
            return
        log(f"⚡ SQUEEZE STRUCTURE BYPASS: {squeeze_structure_block} | {bypass_squeeze_reason}")

    allowed, gate_reason = risk_gate(chosen_signal, usable)
    if not allowed:
        log(f"Risk gate blocked: {gate_reason}")
        return

    chosen_signal.effective_risk_per_trade = float(
        getattr(chosen_signal, "risk_per_trade", RISK_PER_TRADE) or RISK_PER_TRADE
    )
    brain["current_risk_per_trade"] = chosen_signal.effective_risk_per_trade
    log(
        f"🧾 FINAL SIGNAL | action={chosen_signal.action} mode={chosen_signal.mode} "
        f"policy={chosen_signal.policy} "
        f"base_risk={chosen_signal.base_risk_per_trade:.4f} "
        f"effective_risk={chosen_signal.effective_risk_per_trade:.4f} "
        f"lev={chosen_signal.leverage} conf={chosen_signal.confidence:.2f} "
        f"parent={chosen_signal.parent_allocation_reason or 'n/a'}"
    )
    await execute_trade(client, chosen_signal, position)


async def handle_open_position_cycle(client, position: PositionState, usable: float):
    adaptive = get_adaptive_trade_parameters()
    strategic = get_strategic_aggression_context()
    brain["last_strategic_context"] = safe_serialize(strategic)
    effective_mix_rate = get_effective_explore_rate()
    get_recent_risk_snapshot()
    log(
        f"🧠 MODE CHECK | explore_rate={effective_mix_rate:.2f} "
        f"mode={brain.get('risk_mode')} regime={brain.get('market_regime', {}).get('regime')} "
        f"strategy={strategic.get('mode', 'observe')} "
        f"reason={describe_risk_mode()}"
    )
    _hold_cooldown_remaining = AI_OPEN_POS_COOLDOWN_SECONDS - (time.time() - float(brain.get("last_ai_hold_signal_time", 0)))
    if _hold_cooldown_remaining > 0:
        log(f"⏳ AI CYCLE COOLDOWN: {_hold_cooldown_remaining:.0f}s remaining after last hold signal")
        signal = None
    else:
        signal = await get_ai_entry_signal(client, position, usable=usable)
        if signal is None or signal.action == "hold":
            brain["last_ai_hold_signal_time"] = time.time()
        else:
            brain["last_ai_hold_signal_time"] = 0
    if signal:
        normalized_action, normalized_direction, normalization_note = normalize_position_action(
            signal.action,
            signal.direction,
            position.side if position.is_open else None,
        )
        if normalization_note:
            log(normalization_note)
        signal.action = normalized_action
        if normalized_direction:
            signal.direction = normalized_direction
        signal.leverage = int(clamp(signal.leverage, MIN_LEVERAGE, MAX_LEVERAGE))
        signal.risk_per_trade = adaptive.get("risk_per_trade", RISK_PER_TRADE)
        signal.base_risk_per_trade = signal.risk_per_trade
        signal.effective_risk_per_trade = signal.risk_per_trade
        allowed_strategy, strategy_reason = is_strategy_allowed_for_regime(
            signal,
            adaptive.get("regime", "unknown"),
            position_open=position.is_open,
        )
        if not allowed_strategy:
            log(f"Strategy blocked: {strategy_reason}")
            signal = None

    if signal and signal.action == "open":
        log("Open signal ignored: position already open")
    elif signal and signal.action == "close":
        price = float(brain.get("last_price") or position.entry or 0)
        thesis = refresh_position_thesis(position, price)
        _pre_thesis = float(thesis.get("score", 0.0) or 0.0)
        _pre_raw = get_raw_entry_move_bps(position, price)
        _pre_adverse = max(0.0, -_pre_raw if position.side == "long" else _pre_raw)
        if _pre_thesis > -0.25 and _pre_adverse < 15.0:
            log(
                f"CLOSE ignored: thesis/move well within position | "
                f"thesis={_pre_thesis:+.2f} adverse={_pre_adverse:.1f}bps"
            )
        else:
            close_gate, thesis_score, move_bps = ai_review_close_gate(position, thesis, price)
            if not close_gate:
                brain["last_ai_hold_signal_time"] = time.time()
                log(
                    f"Main loop CLOSE blocked by strict exit gate | thesis={thesis_score:+.2f} "
                    f"raw_move={move_bps:+.1f}bps | {format_strict_exit_requirement()} | "
                    f"{signal.reason or 'main_loop_close'}"
                )
            else:
                position.pending_close = True
                position.last_reason = signal.reason or "main_loop_close"
                log(f"Main loop requested CLOSE | {position.last_reason}")
    elif signal and signal.action == "add":
        price = float(brain.get("last_price") or position.entry or 0)
        thesis = refresh_position_thesis(position, price)
        raw_move_bps = get_raw_entry_move_bps(position, price)
        favorable_move_bps = raw_move_bps if position.side == "long" else -raw_move_bps
        thesis_score = float(thesis.get("score", 0.0) or 0.0)
        if signal.direction != position.side:
            if (
                bool(thesis.get("intact", False))
                and thesis_score >= 0.20
                and favorable_move_bps >= ADD_MOVE_BPS_THRESHOLD
            ):
                log(
                    f"Opposite ADD ignored: current winner still intact | "
                    f"signal={signal.direction} position={position.side} "
                    f"thesis={thesis_score:+.2f} move={favorable_move_bps:+.1f}bps"
                )
                return
            close_gate, gate_thesis_score, gate_move_bps = ai_review_close_gate(position, thesis, price)
            if not close_gate:
                brain["last_ai_hold_signal_time"] = time.time()
                log(
                    f"Opposite ADD->REDUCE blocked by strict exit gate | "
                    f"thesis={gate_thesis_score:+.2f} raw_move={gate_move_bps:+.1f}bps | "
                    f"{format_strict_exit_requirement()} | {signal.reason or f'opposite_add_reduce_{signal.direction}'}"
                )
                return
            qty = signal.quantity or max(1, int(position.qty))
            position.pending_reduce = True
            position.pending_reduce_qty = float(qty)
            position.last_reason = signal.reason or f"opposite_add_reduce_{signal.direction}"
            log(
                f"Main loop converted opposite-direction ADD into REDUCE | "
                f"signal={signal.direction} position={position.side} qty={qty} | "
                f"{position.last_reason}"
            )
        elif signal.confidence < min(
            adaptive.get("confidence_threshold", 0.6),
            get_add_confidence_floor(thesis, favorable_move_bps, position.age_minutes),
        ):
            log(
                f"Add blocked: confidence {signal.confidence:.2f} "
                f"< threshold {min(adaptive.get('confidence_threshold', 0.6), get_add_confidence_floor(thesis, favorable_move_bps, position.age_minutes)):.2f}"
            )
        else:
            allowed, gate_reason = risk_gate(signal, usable)
            if not allowed:
                log(f"Main-loop add blocked: {gate_reason}")
            else:
                brain["current_risk_per_trade"] = float(
                    getattr(signal, "risk_per_trade", RISK_PER_TRADE) or RISK_PER_TRADE
                )
                signal_ctx = get_signal_context()
                broader_alignment = get_broader_structure_alignment(
                    signal.direction,
                    signal.intent,
                    brain.get("broader_structure") or compute_broader_structure_context(signal_ctx),
                )
                level_edge = bool(
                    (signal.direction == "long" and (signal_ctx.get("at_support", False) or signal_ctx.get("sweep_reclaim_long", False)))
                    or (signal.direction == "short" and (signal_ctx.get("at_resistance", False) or signal_ctx.get("sweep_reclaim_short", False)))
                )
                leverage_alignment = "excellent" if broader_alignment == "aligned" and level_edge else "good" if broader_alignment == "aligned" else "supportive" if broader_alignment == "supportive" else "neutral"
                signal.leverage = get_dynamic_leverage(
                    max(
                        float(getattr(signal, "predictive_setup_score", 0.0) or 0.0),
                        float(getattr(signal, "expected_edge", 0.0) or 0.0),
                        float(thesis_score or 0.0),
                    ),
                    leverage_alignment,
                    str(adaptive.get("regime", "unknown") or "unknown"),
                    str(brain.get("risk_mode", "normal") or "normal"),
                )
                position.confidence = signal.confidence
                position.last_reason = signal.reason or "main_loop_add"
                position.pending_add = True
                position.pending_add_qty = float(signal.quantity or 0)
                log(
                    f"🧾 FINAL SIGNAL | action=add mode={signal.mode} "
                    f"policy={signal.policy} base_risk={signal.base_risk_per_trade:.4f} "
                    f"effective_risk={signal.effective_risk_per_trade:.4f} "
                    f"lev={signal.leverage} conf={signal.confidence:.2f} qty={signal.quantity or 'auto'}"
                )
    elif signal and signal.action == "reduce":
        if signal.direction == position.side:
            log(
                f"Reduce blocked: direction must oppose current position | "
                f"signal={signal.direction} position={position.side}"
            )
        else:
            price = float(brain.get("last_price") or position.entry or 0)
            thesis = refresh_position_thesis(position, price)
            raw_move_bps = get_raw_entry_move_bps(position, price)
            favorable_move_bps = raw_move_bps if position.side == "long" else -raw_move_bps
            thesis_score = float(thesis.get("score", 0.0) or 0.0)
            if (
                bool(thesis.get("intact", False))
                and thesis_score > 0.0
            ):
                log(
                    f"REDUCE ignored: thesis positive, exit gate would block | "
                    f"thesis={thesis_score:+.2f} move={favorable_move_bps:+.1f}bps "
                    f"conf={signal.confidence:.2f}"
                )
                return
            close_gate, gate_thesis_score, gate_move_bps = ai_review_close_gate(position, thesis, price)
            if not close_gate:
                log(
                    f"Main loop REDUCE blocked by strict exit gate | thesis={gate_thesis_score:+.2f} "
                    f"raw_move={gate_move_bps:+.1f}bps | {format_strict_exit_requirement()} | "
                    f"{signal.reason or 'main_loop_reduce'}"
                )
                return
            qty = signal.quantity or max(1, int(position.qty * 0.5))
            position.last_reason = signal.reason or "main_loop_reduce"
            position.pending_reduce = True
            position.pending_reduce_qty = float(qty)
            log(
                f"🧾 FINAL SIGNAL | action=reduce mode={signal.mode} "
                f"policy={signal.policy} qty={qty} conf={signal.confidence:.2f} | "
                f"{position.last_reason}"
            )
    elif signal and signal.action == "reverse":
        log(
            f"🧾 FINAL SIGNAL | reverse ignored while open | "
            f"policy={signal.policy} conf={signal.confidence:.2f} | {signal.reason}"
        )


async def run_position_followups(client, position: PositionState, monitor_task, last_review: float) -> tuple[Any, float]:
    if position.is_open:
        if time.time() - last_review > AI_REVIEW_INTERVAL_SECONDS:
            await ai_review_position(client, position)
            last_review = time.time()

        if monitor_task is None or monitor_task.done():
            monitor_task = asyncio.create_task(monitor_position(client, position))

        reconcile_open_position_context(position)
    return monitor_task, last_review


def emit_heartbeat(position: PositionState):
    price = float(brain.get("last_price") or 0)
    upnl = position.unrealized_pnl(price) if position.is_open else 0.0
    current_equity = float(brain.get("current_equity", 0.0)) + upnl
    total_pnl = float(brain.get("total_pnl", 0.0))
    thesis = refresh_position_thesis(position, price) if position.is_open else {"score": 0.0, "add_ready": False}
    close_alignment = compute_close_alignment(position, thesis, price) if position.is_open else get_default_close_alignment()
    signal_ctx = get_signal_context()
    blocker = brain.get("last_flat_entry_block_reason", "n/a") if not position.is_open else "n/a"
    effective_mix_rate = get_effective_explore_rate()
    strategic_mode = str((brain.get("last_strategic_context", {}) or {}).get("mode", "observe") or "observe")
    add_status = str(thesis["add_ready"]).lower()
    if position.is_open and strategic_mode == "attack" and thesis["add_ready"]:
        add_status = "ready_attack"
    pred = (
        float(position.entry_predictive_setup_score or 0.0)
        if position.is_open
        else float(brain.get("last_decision", {}).get("predictive_setup_score", 0.0) or 0.0)
    )

    log(
        f"HB | price={price:.0f} regime={brain.get('market_regime', {}).get('regime', 'unknown')} "
        f"open={position.is_open} side={position.side or 'flat'} "
        f"upnl={upnl:+.0f} equity={current_equity:+.0f} realized={total_pnl:+.0f} "
        f"risk_mode={brain.get('risk_mode', 'unknown')} "
        f"mode={position.mode if position.is_open else 'flat'} "
        f"policy={position.policy if position.is_open else brain.get('exploration', {}).get('last_policy', 'none')} "
        f"mix={effective_mix_rate:.2f} "
        f"risk={brain.get('current_risk_per_trade', 0):.4f} "
        f"pred={pred:.2f} ext={signal_ctx.get('external_bias', 'neutral')}/{float(signal_ctx.get('external_conviction', 0.0) or 0.0):.2f}/{signal_ctx.get('external_data_quality', 'none')} "
        f"thesis={thesis['score']:+.2f} add_ready={add_status} "
        f"close_align={float(close_alignment.get('score', 0.0) or 0.0):+.2f} "
        f"peak_fee={thesis.get('peak_fee_multiple', 0.0):+.2f} trades={brain.get('trades', 0)} "
        f"blocker={blocker}"
    )


async def slow_trading_loop(client):
    log("🧠 Slow trading loop started (ADAPTIVE + REGIME ENGINE)")

    position = PositionState()
    monitor_task = None
    last_review = 0.0
    last_heartbeat = time.time()

    while True:
        try:
            if KILL_FILE.exists():
                log("Kill switch detected")
                if position.is_open:
                    await handle_ai_close(client, position, "KILL_SWITCH")
                brain["cooldown_until"] = time.time() + 86400
                await asyncio.sleep(300)
                continue

            await verify_position_with_exchange(client, position)
            refresh_flat_state(position)
            if should_skip_slow_cycle():
                await asyncio.sleep(SLOW_SLEEP)
                continue

            usable = await get_usable_margin(client)

            if not position.is_open:
                if monitor_task and not monitor_task.done():
                    monitor_task.cancel()
                    monitor_task = None

            if time.time() - float(brain.get("last_entry_attempt", 0)) > 30:
                brain["last_entry_attempt"] = time.time()
                if not position.is_open:
                    await handle_flat_cycle(client, position, usable)
                else:
                    await handle_open_position_cycle(client, position, usable)

            # === Position monitoring & AI review ===
            monitor_task, last_review = await run_position_followups(client, position, monitor_task, last_review)
            maybe_log_shadow_report()

            maybe_save_memory(force=True)

            # Heartbeat log
            if time.time() - last_heartbeat > 60:
                emit_heartbeat(position)
                last_heartbeat = time.time()

        except Exception as exc:
            log(f"slow loop error: {exc}")
            traceback.print_exc()
            brain["last_trade_error"] = {
                "error": str(exc),
                "timestamp": datetime.now().isoformat(),
            }
            await asyncio.sleep(10)

        await asyncio.sleep(SLOW_SLEEP)


async def periodic_ingest(client):
    while True:
        await ingest_closed_trades(client)
        await ingest_leaderboard(client)
        await get_funding_rate(client)
        await refresh_external_market_data()
        await asyncio.sleep(900)


async def main():
    log("Agent v3.2 starting")
    APP_DIR.mkdir(parents=True, exist_ok=True)
    validate_startup()
    load_memory()
    initialize_brain_deques()

    if brain.get("daily_start_time") is None:
        brain["daily_start_time"] = datetime.now().date().isoformat()
        brain["daily_pnl"] = 0.0
    if brain.get("session_start") is None:
        brain["session_start"] = datetime.now().isoformat()

    log(
        f"Boot | trades={brain.get('trades', 0)} total_pnl={brain.get('total_pnl', 0):.0f} "
        f"streak={brain.get('streak', 0)}"
    )

    config = APIClientConfig(
        authentication=APIAuthContext(key=LNM_API_KEY, secret=LNM_API_SECRET, passphrase=LNM_API_PASSPHRASE),
        network="mainnet",
        timeout=60.0,
    )

    async with LNMClient(config) as client:
        await seed_brain_from_history(client)
        await seed_regime_from_history()
        await get_funding_rate(client)
        try:
            await refresh_external_market_data()
        except Exception as exc:
            brain.setdefault("external_market", {})["status"] = f"error: {exc}"
            log(f"Initial external market refresh failed: {exc}")
        try:
            await run_oracle_shadow_replay_once()
        except Exception as exc:
            brain.setdefault("oracle_replay", {})["last_status"] = f"error: {exc}"
            log(f"Initial oracle replay failed: {exc}")
        try:
            compute_entry_quality_bias()
            compute_exit_quality_bias()
        except Exception as exc:
            log(f"Quality bias init failed: {exc}")
        initialize_brain_deques()
        log(
            f"Limits | max daily loss={MAX_DAILY_LOSS_SATS:,} sats "
            f"max drawdown={MAX_SESSION_DRAWDOWN_PCT:.0%}"
        )
        try:
            await asyncio.gather(
                fast_market_loop(client),
                slow_trading_loop(client),
                periodic_ingest(client),
                oracle_shadow_loop(),
            )
        finally:
            await close_ai_session()


def print_dry_run_report():
    """Read-only operator helper: print the latest stored flat-entry gate report and exit."""
    load_memory()
    initialize_brain_deques()
    usable = float(brain.get("last_margin", {}).get("usable", 0.0) or 0.0)
    gate_state = brain.get("last_entry_gate_state") or get_entry_gate_state(usable)
    dry_report = brain.get("dry_run_entry_report") or build_dry_run_entry_report(usable, gate_state)
    report = {
        "dry_run_entry_report": dry_report,
        "last_entry_gate_state": gate_state,
        "last_flat_entry_block_reason": brain.get("last_flat_entry_block_reason"),
        "shadow_report": brain.get("shadow_report", {}),
        "level_thresholds": brain.get("level_thresholds", {}),
        "exploration_thresholds": get_exploration_thresholds(),
        "winner_fade_stats": brain.get("winner_fade_stats", {}),
    }
    print(json.dumps(safe_serialize(report), indent=2, sort_keys=True))


def print_daily_metrics_report():
    """Read-only: roll up agent_review_reports.jsonl + brain trade_lessons into per-day metrics.
    Does not mutate memory. Use this for leaderboard progress tracking and offline tuning."""
    load_memory()
    initialize_brain_deques()

    daily: dict[str, dict[str, Any]] = {}

    def day(record: dict) -> Optional[str]:
        ts = record.get("timestamp") or record.get("time") or record.get("date")
        if not ts:
            return None
        try:
            return str(ts)[:10]
        except Exception:
            return None

    # Trade lessons (closed trades)
    for lesson in brain.get("trade_lessons", []) or []:
        d = day(lesson)
        if not d:
            continue
        bucket = daily.setdefault(d, {"trades": 0, "wins": 0, "net_pnl": 0.0,
                                      "fee_total": 0.0, "fee_dominated": 0,
                                      "by_policy": {}, "by_regime": {}, "by_exit_type": {},
                                      "post_tp_reentries": 0, "post_tp_reentries_blocked": 0})
        bucket["trades"] += 1
        net_pnl = float(lesson.get("net_pnl", 0.0) or 0.0)
        gross_pnl = float(lesson.get("gross_pnl", 0.0) or 0.0)
        fee = abs(gross_pnl - net_pnl)
        bucket["net_pnl"] += net_pnl
        bucket["fee_total"] += fee
        if net_pnl > 0:
            bucket["wins"] += 1
        if abs(gross_pnl) < max(fee * 0.5, 10.0):
            bucket["fee_dominated"] += 1
        policy = str(lesson.get("policy") or "unknown")
        bucket["by_policy"][policy] = bucket["by_policy"].get(policy, 0) + 1
        regime = str(lesson.get("regime") or "unknown")
        bucket["by_regime"][regime] = bucket["by_regime"].get(regime, 0) + 1
        exit_t = str(lesson.get("exit_type_normalized") or lesson.get("exit_type") or "manual")
        bucket["by_exit_type"][exit_t] = bucket["by_exit_type"].get(exit_t, 0) + 1

    # JSONL events for post-TP gate outcomes and chop_recycle would-fires
    try:
        review_files = iter_review_report_files()
        if review_files:
            chop_recycle_obs: dict[str, int] = {}
            gate_transitions: dict[str, int] = {}
            for report_file in review_files:
                with report_file.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            rec = json.loads(line)
                        except Exception:
                            continue
                        rtype = rec.get("type")
                        d = day(rec)
                        if not d:
                            continue
                        bucket = daily.setdefault(d, {"trades": 0, "wins": 0, "net_pnl": 0.0,
                                                      "fee_total": 0.0, "fee_dominated": 0,
                                                      "by_policy": {}, "by_regime": {}, "by_exit_type": {},
                                                      "post_tp_reentries": 0, "post_tp_reentries_blocked": 0})
                        payload = rec.get("payload", {}) or {}
                        if rtype == "post_tp_edge_gate_eval":
                            bucket["post_tp_reentries"] += 1
                            if payload.get("blocked"):
                                bucket["post_tp_reentries_blocked"] += 1
                        elif rtype == "chop_recycle_would_fire":
                            v = str(payload.get("variant", "unknown"))
                            chop_recycle_obs[f"{d}::{v}"] = chop_recycle_obs.get(f"{d}::{v}", 0) + 1
                        elif rtype == "gate_event":
                            gate = str(rec.get("payload", {}).get("gate") or payload.get("gate") or "unknown")
                            to_state = str(rec.get("payload", {}).get("to_state") or payload.get("to_state") or "unknown")
                            gate_transitions[f"{d}::{gate}::{to_state}"] = gate_transitions.get(f"{d}::{gate}::{to_state}", 0) + 1
    except Exception as exc:
        log(f"daily metrics event scan failed: {exc}")
        chop_recycle_obs = {}
        gate_transitions = {}

    # Finalize derived metrics
    for d, bucket in daily.items():
        trades = max(bucket["trades"], 1)
        bucket["win_rate"] = round(bucket["wins"] / trades, 4)
        bucket["avg_net_pnl"] = round(bucket["net_pnl"] / trades, 2)
        bucket["fee_ratio"] = round(bucket["fee_total"] / max(abs(bucket["net_pnl"]) + bucket["fee_total"], 1.0), 4)
        bucket["net_pnl"] = round(bucket["net_pnl"], 2)
        bucket["fee_total"] = round(bucket["fee_total"], 2)

    report = {
        "generated_at": datetime.now().isoformat(),
        "days": dict(sorted(daily.items())),
        "chop_recycle_would_fire_counts": chop_recycle_obs,
        "gate_transitions": gate_transitions,
        "leaderboard_snapshot": brain.get("leaderboard", {}),
    }
    print(json.dumps(safe_serialize(report), indent=2, sort_keys=True))


def print_tuner_report():
    """Operator helper for profit-tuner state and lane rankings."""
    load_memory()
    initialize_brain_deques()
    if (
        not (brain.get("exploration_thresholds", {}) or {}).get("lane_stats")
        or "initial" in str(((brain.get("exploration_thresholds", {}) or {}).get("allocation_caps", {}) or {}).get("last_reason", ""))
    ):
        tune_exploration_thresholds()
    thresholds = get_exploration_thresholds()
    lane_stats = thresholds.get("lane_stats", {}) or {}
    top_lane = thresholds.get("top_lane", {}) or {}
    top_lane_drift_reason = get_top_lane_drift_guard_reason(top_lane)
    ranked = sorted(
        lane_stats.values(),
        key=lambda item: float(item.get("profit_score", 0.0) or 0.0),
        reverse=True,
    )
    report = {
        "generated_at": datetime.now().isoformat(),
        "daily_pnl": round(float(brain.get("daily_pnl", 0.0) or 0.0), 2),
        "total_pnl": round(float(brain.get("total_pnl", 0.0) or 0.0), 2),
        "risk_mode": brain.get("risk_mode", "unknown"),
        "exploration_thresholds": {
            "mix_bias": thresholds.get("mix_bias"),
            "min_score": thresholds.get("min_score"),
            "min_edge": thresholds.get("min_edge"),
            "confidence_floor": thresholds.get("confidence_floor"),
            "cooldown_seconds": thresholds.get("cooldown_seconds"),
            "risk_floor": thresholds.get("risk_floor"),
            "risk_ceiling": thresholds.get("risk_ceiling"),
            "allocation_caps": thresholds.get("allocation_caps", {}),
            "policy_fit_adjustments": thresholds.get("policy_fit_adjustments", {}),
            "last_reason": thresholds.get("last_reason"),
            "last_tuned": thresholds.get("last_tuned"),
        },
        "top_lane": top_lane,
        "top_lane_active": bool(get_best_exploration_lane()),
        "top_lane_drift_guard": top_lane_drift_reason or "",
        "effective_breakout_min_room_bps": get_level_breakout_min_room_bps(),
        "top_lanes": ranked[:8],
        "weak_lanes": sorted(
            lane_stats.values(),
            key=lambda item: float(item.get("profit_score", 0.0) or 0.0),
        )[:8],
        "level_thresholds": brain.get("level_thresholds", {}),
        "shadow_report": brain.get("shadow_report", {}),
    }
    print(json.dumps(safe_serialize(report), indent=2, sort_keys=True))


if __name__ == "__main__":
    if "--daily-metrics" in sys.argv[1:]:
        print_daily_metrics_report()
    elif "--tuner-report" in sys.argv[1:]:
        print_tuner_report()
    elif any(arg in {"--dry-run-report", "--gate-report"} for arg in sys.argv[1:]):
        print_dry_run_report()
    else:
        try:
            asyncio.run(main())
        except (KeyboardInterrupt, asyncio.CancelledError):
            log("Agent shutdown requested")
