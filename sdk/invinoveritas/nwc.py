"""
invinoveritas NWC Provider
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nostr Wallet Connect (NIP-47) payment provider for the invinoveritas SDK.

Allows any NWC-compatible wallet (Alby, Mutiny, Zeus, etc.) to autonomously
pay Lightning invoices without a local LND node.

Install:
    pip install "invinoveritas[nwc]"

Usage:
    from invinoveritas.providers import NWCProvider
    from invinoveritas.langchain import InvinoCallbackHandler

    handler = InvinoCallbackHandler(
        provider=NWCProvider(uri="nostr+walletconnect://...")
    )

NWC URI format:
    nostr+walletconnect://<wallet_pubkey>?relay=<relay_url>&secret=<client_secret>

Get your NWC URI from:
    - Alby: https://app.getalby.com/apps/new
    - Zeus: Settings → Nostr Wallet Connect
    - Any NIP-47 compatible wallet
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import struct
import time
from typing import Optional
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("invinoveritas.nwc")


# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------

def _check_deps():
    missing = []
    try:
        import websockets
    except ImportError:
        missing.append("websockets")
    try:
        import coincurve
    except ImportError:
        missing.append("coincurve")
    if missing:
        raise ImportError(
            f"NWC provider requires: {', '.join(missing)}\n"
            f"Install with: pip install 'invinoveritas[nwc]'"
        )


# ---------------------------------------------------------------------------
# NWC URI Parser
# ---------------------------------------------------------------------------

class NWCUri:
    """
    Parse a nostr+walletconnect:// URI.

    Format:
        nostr+walletconnect://<wallet_pubkey>?relay=<relay_url>&secret=<secret>

    Attributes:
        wallet_pubkey: Hex pubkey of the wallet service
        relay:         WebSocket relay URL (wss://...)
        secret:        Hex secret key for this connection
    """

    def __init__(self, uri: str):
        if not uri.startswith("nostr+walletconnect://"):
            raise ValueError(f"Invalid NWC URI — must start with nostr+walletconnect://")

        # Replace scheme for urlparse
        parsed = urlparse(uri.replace("nostr+walletconnect://", "https://"))
        params = parse_qs(parsed.query)

        self.wallet_pubkey = parsed.hostname
        if not self.wallet_pubkey:
            raise ValueError("NWC URI missing wallet pubkey")

        relay_list = params.get("relay", [])
        if not relay_list:
            raise ValueError("NWC URI missing relay parameter")
        self.relay = relay_list[0]

        secret_list = params.get("secret", [])
        if not secret_list:
            raise ValueError("NWC URI missing secret parameter")
        self.secret = secret_list[0]

    def __repr__(self):
        return f"NWCUri(wallet={self.wallet_pubkey[:8]}..., relay={self.relay})"


# ---------------------------------------------------------------------------
# Crypto helpers (NIP-44 v2 + secp256k1)
# ---------------------------------------------------------------------------

class NIP44:
    """
    NIP-44 v2 encryption/decryption.

    Uses ECDH shared secret + HKDF + ChaCha20-Poly1305.
    """

    VERSION = 2

    @staticmethod
    def _get_shared_secret(privkey_hex: str, pubkey_hex: str) -> bytes:
        """Compute ECDH shared secret."""
        import coincurve

        privkey_bytes = bytes.fromhex(privkey_hex)
        # Ensure pubkey is 33-byte compressed form
        pubkey_hex_full = "02" + pubkey_hex if len(pubkey_hex) == 64 else pubkey_hex
        pubkey_bytes = bytes.fromhex(pubkey_hex_full)

        privkey = coincurve.PrivateKey(privkey_bytes)
        pubkey = coincurve.PublicKey(pubkey_bytes)
        shared = pubkey.multiply(privkey.secret)
        # Return x-coordinate only (32 bytes)
        return shared.format(compressed=True)[1:]

    @staticmethod
    def _hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
        """HKDF-Expand (SHA256)."""
        t = b""
        okm = b""
        for i in range(1, (length + 31) // 32 + 1):
            t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
            okm += t
        return okm[:length]

    @staticmethod
    def _hkdf(secret: bytes, salt: bytes) -> bytes:
        """HKDF (SHA256) — extract + expand."""
        prk = hmac.new(salt, secret, hashlib.sha256).digest()
        return NIP44._hkdf_expand(prk, b"nip44-v2", 76)

    @classmethod
    def encrypt(cls, plaintext: str, privkey_hex: str, pubkey_hex: str) -> str:
        """
        Encrypt plaintext using NIP-44 v2.
        Returns base64-encoded ciphertext with version byte and nonce.
        """
        import base64
        try:
            from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
        except ImportError:
            raise ImportError("cryptography package required: pip install cryptography")

        shared_secret = cls._get_shared_secret(privkey_hex, pubkey_hex)
        nonce = os.urandom(32)
        keys = cls._hkdf(shared_secret, nonce)

        chacha_key = keys[:32]
        chacha_nonce = keys[32:44]
        # padding
        pad_len = cls._calc_padding(len(plaintext.encode()))
        padded = struct.pack(">H", len(plaintext.encode())) + plaintext.encode().ljust(pad_len, b"\x00")

        aead = ChaCha20Poly1305(chacha_key)
        ciphertext = aead.encrypt(chacha_nonce, padded, None)

        payload = bytes([cls.VERSION]) + nonce + ciphertext
        return base64.b64encode(payload).decode()

    @classmethod
    def decrypt(cls, payload_b64: str, privkey_hex: str, pubkey_hex: str) -> str:
        """Decrypt NIP-44 v2 payload."""
        import base64
        try:
            from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
        except ImportError:
            raise ImportError("cryptography package required: pip install cryptography")

        payload = base64.b64decode(payload_b64)
        version = payload[0]
        if version != cls.VERSION:
            raise ValueError(f"Unsupported NIP-44 version: {version}")

        nonce = payload[1:33]
        ciphertext = payload[33:]

        shared_secret = cls._get_shared_secret(privkey_hex, pubkey_hex)
        keys = cls._hkdf(shared_secret, nonce)
        chacha_key = keys[:32]
        chacha_nonce = keys[32:44]

        aead = ChaCha20Poly1305(chacha_key)
        padded = aead.decrypt(chacha_nonce, ciphertext, None)

        msg_len = struct.unpack(">H", padded[:2])[0]
        return padded[2:2 + msg_len].decode()

    @staticmethod
    def _calc_padding(msg_len: int) -> int:
        """Calculate NIP-44 padding to next power of 2 boundary."""
        if msg_len <= 32:
            return 32
        next_pow2 = 1 << (msg_len - 1).bit_length()
        return min(next_pow2, 65536)


class NostrKey:
    """Nostr key operations (secp256k1)."""

    @staticmethod
    def privkey_to_pubkey(privkey_hex: str) -> str:
        """Derive x-only pubkey from private key."""
        import coincurve
        privkey = coincurve.PrivateKey(bytes.fromhex(privkey_hex))
        pubkey = privkey.public_key.format(compressed=True)
        return pubkey[1:].hex()  # x-only (32 bytes)

    @staticmethod
    def sign_event(event: dict, privkey_hex: str) -> str:
        """Sign a Nostr event, return signature hex."""
        import coincurve
        event_id = NostrKey.compute_event_id(event)
        privkey = coincurve.PrivateKey(bytes.fromhex(privkey_hex))
        sig = privkey.sign_recoverable(bytes.fromhex(event_id), hasher="sha256")
        return sig[:64].hex()

    @staticmethod
    def compute_event_id(event: dict) -> str:
        """Compute Nostr event ID (SHA256 of canonical serialization)."""
        serialized = json.dumps(
            [
                0,
                event["pubkey"],
                event["created_at"],
                event["kind"],
                event["tags"],
                event["content"],
            ],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(serialized.encode()).hexdigest()

    @staticmethod
    def build_event(kind: int, content: str, pubkey: str, tags: list) -> dict:
        """Build an unsigned Nostr event."""
        event = {
            "pubkey": pubkey,
            "created_at": int(time.time()),
            "kind": kind,
            "tags": tags,
            "content": content,
        }
        event["id"] = NostrKey.compute_event_id(event)
        return event


# ---------------------------------------------------------------------------
# NWC Client
# ---------------------------------------------------------------------------

class NWCClient:
    """
    Nostr Wallet Connect client (NIP-47).

    Connects to a Nostr relay via WebSocket and sends/receives
    encrypted payment requests.

    Args:
        uri:        nostr+walletconnect:// connection string
        timeout:    Seconds to wait for payment response (default: 30)
    """

    NWC_REQUEST_KIND = 23194
    NWC_RESPONSE_KIND = 23195

    def __init__(self, uri: str, timeout: int = 30):
        _check_deps()
        self.nwc_uri = NWCUri(uri)
        self.timeout = timeout
        self._client_privkey = self.nwc_uri.secret
        self._client_pubkey = NostrKey.privkey_to_pubkey(self._client_privkey)

    async def pay_invoice(self, invoice: str) -> str:
        """
        Pay a Lightning invoice via NWC.

        Sends a pay_invoice request to the wallet service via Nostr relay
        and waits for the payment preimage response.

        Args:
            invoice: bolt11 Lightning invoice string

        Returns:
            Payment preimage (hex string)

        Raises:
            PaymentFailed: If payment fails or times out
        """
        import websockets

        request_id = secrets.token_hex(16)
        request_payload = json.dumps({
            "method": "pay_invoice",
            "params": {"invoice": invoice}
        })

        # Encrypt request with NIP-44
        encrypted = NIP44.encrypt(
            request_payload,
            self._client_privkey,
            self.nwc_uri.wallet_pubkey
        )

        # Build and sign the request event
        tags = [["p", self.nwc_uri.wallet_pubkey]]
        event = NostrKey.build_event(
            kind=self.NWC_REQUEST_KIND,
            content=encrypted,
            pubkey=self._client_pubkey,
            tags=tags,
        )
        event["sig"] = NostrKey.sign_event(event, self._client_privkey)

        # Subscribe to responses before sending request
        sub_id = secrets.token_hex(8)
        subscribe_msg = json.dumps([
            "REQ",
            sub_id,
            {
                "kinds": [self.NWC_RESPONSE_KIND],
                "authors": [self.nwc_uri.wallet_pubkey],
                "#p": [self._client_pubkey],
                "since": int(time.time()) - 5,
            }
        ])

        send_msg = json.dumps(["EVENT", event])

        logger.info(f"NWC | connecting to relay: {self.nwc_uri.relay}")

        try:
            async with websockets.connect(
                self.nwc_uri.relay,
                ping_interval=20,
                ping_timeout=10,
            ) as ws:
                # Subscribe first
                await ws.send(subscribe_msg)
                logger.info(f"NWC | subscribed | sub_id={sub_id}")

                # Send payment request
                await ws.send(send_msg)
                logger.info(f"NWC | payment request sent | invoice={invoice[:20]}...")

                # Wait for response
                deadline = asyncio.get_event_loop().time() + self.timeout
                while asyncio.get_event_loop().time() < deadline:
                    remaining = deadline - asyncio.get_event_loop().time()
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=min(5.0, remaining))
                    except asyncio.TimeoutError:
                        continue

                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if not isinstance(msg, list) or len(msg) < 3:
                        continue

                    msg_type = msg[0]
                    if msg_type != "EVENT":
                        continue

                    received_event = msg[2]
                    if received_event.get("kind") != self.NWC_RESPONSE_KIND:
                        continue

                    # Decrypt response
                    try:
                        decrypted = NIP44.decrypt(
                            received_event["content"],
                            self._client_privkey,
                            self.nwc_uri.wallet_pubkey,
                        )
                        response = json.loads(decrypted)
                    except Exception as e:
                        # Try NIP-04 fallback
                        try:
                            decrypted = self._decrypt_nip04(
                                received_event["content"],
                                self._client_privkey,
                                self.nwc_uri.wallet_pubkey,
                            )
                            response = json.loads(decrypted)
                        except Exception:
                            logger.warning(f"NWC | failed to decrypt response: {e}")
                            continue

                    logger.info(f"NWC | response received: {response.get('result_type')}")

                    # Check for error
                    if response.get("error"):
                        error = response["error"]
                        raise PaymentFailed(
                            f"NWC payment failed: {error.get('message', error)}"
                        )

                    # Extract preimage
                    result = response.get("result", {})
                    preimage = result.get("preimage")
                    if preimage:
                        logger.info(f"NWC | payment successful | preimage obtained")
                        return preimage

                raise PaymentFailed(
                    f"NWC payment timed out after {self.timeout}s — "
                    f"wallet did not respond. Check wallet is online and has sufficient balance."
                )

        except Exception as e:
            if isinstance(e, PaymentFailed):
                raise
            raise PaymentFailed(f"NWC connection error: {e}") from e

    def _decrypt_nip04(self, content: str, privkey_hex: str, pubkey_hex: str) -> str:
        """NIP-04 fallback decryption (deprecated but some wallets still use it)."""
        import base64
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        shared = NIP44._get_shared_secret(privkey_hex, pubkey_hex)

        parts = content.split("?iv=")
        if len(parts) != 2:
            raise ValueError("Invalid NIP-04 content format")

        ciphertext = base64.b64decode(parts[0])
        iv = base64.b64decode(parts[1])

        cipher = Cipher(algorithms.AES(shared), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()

        # Remove PKCS7 padding
        pad_len = padded[-1]
        return padded[:-pad_len].decode()


# ---------------------------------------------------------------------------
# PaymentFailed exception (local to this module)
# ---------------------------------------------------------------------------

class PaymentFailed(Exception):
    """Raised when NWC payment fails."""


# ---------------------------------------------------------------------------
# NWCProvider — BaseProvider implementation
# ---------------------------------------------------------------------------

class NWCProvider:
    """
    Lightning payment provider using Nostr Wallet Connect (NIP-47).

    Works with any NWC-compatible wallet:
    - Alby (https://app.getalby.com/apps/new)
    - Zeus (Settings → Nostr Wallet Connect)
    - Mutiny Wallet
    - Any NIP-47 compatible wallet

    No Lightning node required — payments go through your wallet app.

    Args:
        uri:     nostr+walletconnect:// connection string from your wallet
        timeout: Seconds to wait for payment (default: 30)

    Example::

        from invinoveritas.providers import NWCProvider
        from invinoveritas.langchain import InvinoCallbackHandler

        handler = InvinoCallbackHandler(
            provider=NWCProvider(
                uri="nostr+walletconnect://abc123...?relay=wss://relay.getalby.com/v1&secret=def456..."
            )
        )
    """

    def __init__(self, uri: str, timeout: int = 30):
        self._uri = uri
        self._timeout = timeout
        self._client: Optional[NWCClient] = None

    def _get_client(self) -> NWCClient:
        if self._client is None:
            self._client = NWCClient(self._uri, timeout=self._timeout)
        return self._client

    def is_available(self) -> bool:
        return bool(self._uri)

    async def pay_invoice(self, invoice: str):
        """Pay invoice via NWC, return PaymentResult."""
        # Import here to avoid circular
        from invinoveritas.providers import PaymentResult

        client = self._get_client()
        preimage = await client.pay_invoice(invoice)

        return PaymentResult(
            payment_hash="",  # NWC response doesn't always include hash
            preimage=preimage,
            amount_sats=0,
        )

    async def get_balance(self) -> int:
        """Get wallet balance in sats (useful for checking before agent runs)."""
        import websockets

        client = self._get_client()
        request_payload = json.dumps({"method": "get_balance", "params": {}})
        encrypted = NIP44.encrypt(
            request_payload,
            client._client_privkey,
            client.nwc_uri.wallet_pubkey,
        )

        sub_id = secrets.token_hex(8)
        tags = [["p", client.nwc_uri.wallet_pubkey]]
        event = NostrKey.build_event(
            kind=NWCClient.NWC_REQUEST_KIND,
            content=encrypted,
            pubkey=client._client_pubkey,
            tags=tags,
        )
        event["sig"] = NostrKey.sign_event(event, client._client_privkey)

        subscribe_msg = json.dumps([
            "REQ", sub_id,
            {
                "kinds": [NWCClient.NWC_RESPONSE_KIND],
                "authors": [client.nwc_uri.wallet_pubkey],
                "#p": [client._client_pubkey],
                "since": int(time.time()) - 5,
            }
        ])

        async with websockets.connect(client.nwc_uri.relay) as ws:
            await ws.send(subscribe_msg)
            await ws.send(json.dumps(["EVENT", event]))

            for _ in range(20):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    msg = json.loads(raw)
                    if isinstance(msg, list) and msg[0] == "EVENT":
                        received = msg[2]
                        if received.get("kind") == NWCClient.NWC_RESPONSE_KIND:
                            decrypted = NIP44.decrypt(
                                received["content"],
                                client._client_privkey,
                                client.nwc_uri.wallet_pubkey,
                            )
                            response = json.loads(decrypted)
                            balance_msat = response.get("result", {}).get("balance", 0)
                            return balance_msat // 1000
                except asyncio.TimeoutError:
                    continue
        return 0
