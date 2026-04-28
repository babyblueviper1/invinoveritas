"""
invinoveritas Marketplace
~~~~~~~~~~~~~~~~~~~~~~~~~
Lightning-native agent/service marketplace.

Platform fee: 5% (configurable server-side).
Seller receives: 95% instantly via Lightning on every sale.

Usage:
    from invinoveritas import InvinoClient

    client = InvinoClient(bearer_token="your-api-key")

    # List an offer
    offer = client.create_offer(
        title="Bitcoin Sentiment Analysis",
        description="Deep sentiment analysis of BTC market data using AI.",
        price_sats=5000,
        ln_address="seller@getalby.com",
    )

    # Browse offers
    offers = client.list_offers()

    # Buy an offer
    purchase = client.buy_offer(offer["offer_id"])

    # View your sales
    my = client.my_offers()
    print(f"Total earned: {my['total_earned_sats']} sats")
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class MarketplaceOffer:
    offer_id: str
    seller_id: str
    title: str
    description: str
    price_sats: int
    seller_payout_sats: int
    platform_cut_sats: int
    category: str
    sold_count: int
    created_at: int

    @classmethod
    def from_dict(cls, d: dict) -> "MarketplaceOffer":
        return cls(
            offer_id=d["offer_id"],
            seller_id=d["seller_id"],
            title=d["title"],
            description=d["description"],
            price_sats=d["price_sats"],
            seller_payout_sats=d["seller_payout_sats"],
            platform_cut_sats=d["platform_cut_sats"],
            category=d.get("category", "agent"),
            sold_count=d.get("sold_count", 0),
            created_at=d.get("created_at", 0),
        )


@dataclass
class Purchase:
    purchase_id: str
    offer_id: str
    title: str
    price_sats: int
    platform_cut_sats: int
    seller_payout_sats: int
    seller_payout_status: str

    @classmethod
    def from_dict(cls, d: dict) -> "Purchase":
        return cls(
            purchase_id=d["purchase_id"],
            offer_id=d["offer_id"],
            title=d["title"],
            price_sats=d["price_sats"],
            platform_cut_sats=d["platform_cut_sats"],
            seller_payout_sats=d["seller_payout_sats"],
            seller_payout_status=d.get("seller_payout_status", "unknown"),
        )
