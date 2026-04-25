import os

VERSION = "1.1.1"

# ======================
# OpenAI Configuration
# ======================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    print("⚠️  WARNING: OPENAI_API_KEY is not set!")

# ======================
# Lightning Bridge (VPS)
# ======================
NODE_URL = os.getenv("NODE_URL")

if not NODE_URL:
    print("⚠️  WARNING: NODE_URL is not set! "
          "Please set the NODE_URL environment variable to your Lightning bridge address "
          "(e.g. http://127.0.0.1:8081)")

NOSTR_NSEC = os.getenv("NOSTR_NSEC")  # hex format, optional but recommended

# ======================
# NWC (Nostr Wallet Connect) — recommended default wallet
# ======================
NWC_CONNECTION_URI = os.getenv("NWC_CONNECTION_URI", "")
# Get your NWC URI from: https://app.getalby.com/apps/new
# Format: nostr+walletconnect://<pubkey>?relay=<relay>&secret=<secret>

# ======================
# Pricing Configuration
# ======================
REASONING_PRICE_SATS = int(os.getenv("REASONING_PRICE_SATS", 500))
DECISION_PRICE_SATS = int(os.getenv("DECISION_PRICE_SATS", 1000))
ORCHESTRATE_PRICE_SATS = int(os.getenv("ORCHESTRATE_PRICE_SATS", 2000))

# Agent pricing (agents pay a small premium)
ENABLE_AGENT_MULTIPLIER = os.getenv("ENABLE_AGENT_MULTIPLIER", "True").lower() in ("true", "1", "yes")
AGENT_PRICE_MULTIPLIER = float(os.getenv("AGENT_PRICE_MULTIPLIER", 1.2))

# Minimum price floor
MIN_PRICE_SATS = int(os.getenv("MIN_PRICE_SATS", 50))

# Rate limiting
RATE_LIMIT_SECONDS = int(os.getenv("RATE_LIMIT_SECONDS", 5))

# ======================
# Marketplace Configuration
# ======================
# Platform takes a cut of every marketplace sale (paid to platform Lightning address)
PLATFORM_CUT_PERCENT = float(os.getenv("PLATFORM_CUT_PERCENT", "5.0"))  # 5% default
SELLER_PERCENT = 100.0 - PLATFORM_CUT_PERCENT                             # 95% to seller
MARKETPLACE_MIN_PRICE_SATS = int(os.getenv("MARKETPLACE_MIN_PRICE_SATS", "1000"))
MARKETPLACE_MAX_PRICE_SATS = int(os.getenv("MARKETPLACE_MAX_PRICE_SATS", "10000000"))
# Platform Lightning address for receiving the 10% cut
PLATFORM_LN_ADDRESS = os.getenv("PLATFORM_LN_ADDRESS", "")

# ======================
# Data Storage (VPS paths)
# ======================
VPS_DATA_DIR = os.getenv("VPS_DATA_DIR", "/root/invinoveritas/data")

# ======================
# Debug / Startup Info
# ======================
def print_config():
    print("=== invinoveritas v{} Configuration Loaded ===".format(VERSION))
    print(f"OPENAI_API_KEY          : {'✅ Set' if OPENAI_API_KEY else '❌ MISSING'}")
    print(f"NODE_URL                : {NODE_URL or 'NOT SET (required!)'}")
    print(f"NWC_CONNECTION_URI      : {'✅ Set' if NWC_CONNECTION_URI else '⚠️  Not set (optional)'}")
    print(f"REASONING_PRICE         : {REASONING_PRICE_SATS} sats")
    print(f"DECISION_PRICE          : {DECISION_PRICE_SATS} sats")
    print(f"ORCHESTRATE_PRICE       : {ORCHESTRATE_PRICE_SATS} sats")
    print(f"ENABLE_AGENT_MULTIPLIER : {ENABLE_AGENT_MULTIPLIER}")
    print(f"AGENT_PRICE_MULTIPLIER  : {AGENT_PRICE_MULTIPLIER}x")
    print(f"MIN_PRICE_SATS          : {MIN_PRICE_SATS} sats")
    print(f"RATE_LIMIT_SECONDS      : {RATE_LIMIT_SECONDS}s")
    print(f"PLATFORM_CUT_PERCENT    : {PLATFORM_CUT_PERCENT}%")
    print(f"SELLER_PERCENT          : {SELLER_PERCENT}%")
    print(f"MARKETPLACE_MIN_PRICE   : {MARKETPLACE_MIN_PRICE_SATS} sats")
    print(f"VPS_DATA_DIR            : {VPS_DATA_DIR}")
    print("========================================")


print_config()
