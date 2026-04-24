"""
Agent Revenue Demo — invinoveritas Marketplace
================================================
Shows the complete marketplace lifecycle:
  1. Seller lists an AI agent service
  2. Buyer discovers and purchases it
  3. Seller receives 90% instantly via Lightning
  4. Both parties view analytics

Setup:
    pip install invinoveritas
    export INVINO_API_KEY="your-bearer-token"
    export BUYER_API_KEY="buyer-bearer-token"      # can be same for demo
    python agent_revenue_demo.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../sdk"))

from invinoveritas import InvinoClient

BASE_URL = "https://api.babyblueviper.com"

SELLER_API_KEY = os.getenv("INVINO_API_KEY", "")
BUYER_API_KEY  = os.getenv("BUYER_API_KEY", SELLER_API_KEY)
SELLER_LN_ADDRESS = os.getenv("SELLER_LN_ADDRESS", "seller@getalby.com")

if not SELLER_API_KEY:
    print("❌ Set INVINO_API_KEY to your Bearer token")
    print("   Register at: https://api.babyblueviper.com/register")
    sys.exit(1)


def separator(title=""):
    print(f"\n{'─'*55}")
    if title:
        print(f"  {title}")
        print(f"{'─'*55}")


def main():
    seller = InvinoClient(base_url=BASE_URL, bearer_token=SELLER_API_KEY)
    buyer  = InvinoClient(base_url=BASE_URL, bearer_token=BUYER_API_KEY)

    # ─── 1. Seller lists an offer ────────────────────────────────
    separator("STEP 1: Seller lists an offer")

    offer_result = seller.create_offer(
        title="Bitcoin Market Intelligence",
        description=(
            "AI-powered Bitcoin market analysis: trend detection, support/resistance levels, "
            "sentiment scoring, and actionable trade signals. Updated every 15 minutes. "
            "Powered by invinoveritas deep reasoning."
        ),
        price_sats=5000,
        ln_address=SELLER_LN_ADDRESS,
        category="trading",
        seller_id=SELLER_API_KEY[:16],
    )

    offer_id = offer_result["offer_id"]
    print(f"✅ Offer created: {offer_result['title']}")
    print(f"   Offer ID    : {offer_id}")
    print(f"   Price       : {offer_result['price_sats']:,} sats")
    print(f"   Seller gets : {offer_result['seller_payout_sats']:,} sats ({offer_result['seller_percent']}%)")
    print(f"   Platform cut: {offer_result['platform_cut_sats']:,} sats ({offer_result['platform_cut_percent']}%)")
    print(f"   Payout to   : {SELLER_LN_ADDRESS}")

    # ─── 2. Buyer browses the marketplace ────────────────────────
    separator("STEP 2: Buyer browses marketplace")

    offers = buyer.list_offers(category="trading", limit=10)
    print(f"Found {len(offers)} trading offers:")
    for o in offers[:3]:
        print(f"  [{o.offer_id[:8]}...] {o.title} — {o.price_sats:,} sats")
    if not offers:
        print("  (No offers yet — the one you just created should appear)")

    # ─── 3. Buyer purchases the offer ────────────────────────────
    separator("STEP 3: Buyer purchases the offer")
    print(f"Buying offer {offer_id[:8]}...")

    try:
        purchase = buyer.buy_offer(offer_id)
        print(f"✅ Purchase complete!")
        print(f"   Purchase ID        : {purchase.purchase_id}")
        print(f"   Price paid         : {purchase.price_sats:,} sats")
        print(f"   Seller payout      : {purchase.seller_payout_sats:,} sats")
        print(f"   Seller payout status: {purchase.seller_payout_status}")
        print(f"   Platform fee       : {purchase.platform_cut_sats:,} sats")
    except Exception as e:
        print(f"⚠️  Purchase failed (expected if balance is low): {e}")
        print("   Top up your account at: https://api.babyblueviper.com/register")

    # ─── 4. Seller views earnings ────────────────────────────────
    separator("STEP 4: Seller views their offers and earnings")

    try:
        my = seller.my_offers()
        print(f"Total earnings: {my.get('total_earned_sats', 0):,} sats")
        print(f"Platform cut  : {my.get('platform_cut_percent', 10)}%")
        for o in my.get("offers", []):
            print(f"  {o['title'][:40]:40s} | {o['sold_count']} sales | {o['total_earned_sats']:,} sats earned")
    except Exception as e:
        print(f"⚠️  my_offers error: {e}")

    # ─── 5. Analytics ────────────────────────────────────────────
    separator("STEP 5: ROI Analytics")

    try:
        roi = seller.analytics_roi()
        print(f"Lifetime spend      : {roi.get('total_spent_sats', 0):,} sats")
        print(f"Marketplace earnings: {roi.get('marketplace_earnings_sats', 0):,} sats")
        print(f"Net sats            : {roi.get('net_sats', 0):,} sats")
        print(f"Total calls         : {roi.get('total_calls', 0)}")
        profitable = roi.get("net_sats", 0) >= 0
        print(f"Status              : {'✅ Net profitable' if profitable else '📉 Net negative (buy more calls or sell more)'}")
    except Exception as e:
        print(f"⚠️  analytics error: {e}")

    separator("DONE")
    print("Marketplace demo complete.")
    print()
    print("Key takeaways:")
    print(f"  • Platform fee : 10% (configurable via PLATFORM_CUT_PERCENT)")
    print(f"  • Seller payout: 90% — sent INSTANTLY to their Lightning Address")
    print(f"  • No invoices to manage — fully automated Lightning settlement")
    print(f"  • SDK: pip install invinoveritas")
    print(f"  • API: https://api.babyblueviper.com/offers/list")


if __name__ == "__main__":
    main()
