import os
from typing import Dict
from lndgrpc import LNDClient
from lndgrpc.common import Macaroon

# =========================
# Config
# =========================
LND_DIR = os.getenv("LND_DIR", "/root/.lnd")

# Your restricted invoice macaroon (the long hex you baked)
MACAROON_HEX = os.getenv("LND_MACAROON_HEX")

if not MACAROON_HEX:
    raise ValueError("LND_MACAROON_HEX is not set in environment variables!")

# Convert hex macaroon to bytes for lndgrpc
macaroon_bytes = bytes.fromhex(MACAROON_HEX)

# =========================
# Initialize LND Client
# =========================
lnd = LNDClient(
    LND_DIR,
    macaroon=Macaroon(macaroon_bytes)   # Use your restricted macaroon
)

# =============================
# Create Lightning Invoice
# =============================
def create_invoice(amount_sats: int, memo: str = "invinoveritas") -> Dict:
    """
    Creates a Lightning invoice using your restricted macaroon.
    """
    try:
        invoice = lnd.add_invoice(
            value=amount_sats,
            memo=memo,
            expiry=3600,          # 1 hour
        )
        return {
            "invoice": invoice.payment_request,
            "payment_hash": invoice.r_hash.hex()   # return as hex string
        }
    except Exception as e:
        return {"error": f"Failed to create invoice: {str(e)}"}


# =============================
# Check if invoice is paid
# =============================
def check_payment(payment_hash: str) -> bool:
    """
    Checks payment status using the restricted macaroon.
    """
    try:
        # payment_hash should be hex
        invoice = lnd.lookup_invoice(r_hash_str=payment_hash)
        return invoice.settled
    except Exception as e:
        print(f"Check payment error: {e}")
        return False


# Optional: Test function
if __name__ == "__main__":
    result = create_invoice(1000, "Test invoice")
    print(result)
