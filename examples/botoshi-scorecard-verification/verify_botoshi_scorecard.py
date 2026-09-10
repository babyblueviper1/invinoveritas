#!/usr/bin/env python3
"""Independent recompute: does the EIP-712 signature on a real Botoshi/BOTCOIN scorecard actually
recover to the claimed signer (0x69747C4Ce6185d21A33b3BcdBa980d659600aC7b)? Real miner address
(0x39484e5fdEedaf0916c53d9C3Bf380d3F307eB5d) found live on-chain on the V3 rig contract, not
guessed or taken from documentation."""
import json
import sys

import rfc8785
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak, to_checksum_address

SCORECARD = json.loads(sys.stdin.read())
CLAIMED_SIGNER = "0x69747C4Ce6185d21A33b3BcdBa980d659600aC7b"

stats_obj = {
    "miner": SCORECARD["miner"],
    "agentId": SCORECARD["agentId"],
    "agentRegistry": SCORECARD["agentRegistry"],
    "asOf": SCORECARD["asOf"],
    "perDomain": SCORECARD["perDomain"],
    "lifetime": SCORECARD["lifetime"],
}
stats_bytes = rfc8785.dumps(stats_obj)
stats_hash = keccak(stats_bytes)
print("statsHash (recomputed):", stats_hash.hex())

typed_data = {
    "types": {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
            {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"},
        ],
        "Scorecard": [
            {"name": "miner", "type": "address"},
            {"name": "agentId", "type": "uint256"},
            {"name": "agentRegistry", "type": "address"},
            {"name": "asOf", "type": "uint256"},
            {"name": "issuedAt", "type": "uint256"},
            {"name": "validUntil", "type": "uint256"},
            {"name": "statsHash", "type": "bytes32"},
        ],
    },
    "primaryType": "Scorecard",
    "domain": {
        "name": "BotcoinScorecard",
        "version": "1",
        "chainId": 8453,
    },
    "message": {
        "miner": to_checksum_address(SCORECARD["miner"]),
        "agentId": int(SCORECARD["agentId"]),
        "agentRegistry": to_checksum_address(SCORECARD["agentRegistry"]),
        "asOf": int(SCORECARD["asOf"]),
        "issuedAt": int(SCORECARD["issuedAt"]),
        "validUntil": int(SCORECARD["validUntil"]),
        "statsHash": stats_hash,
    },
}

sig = SCORECARD["signature"]
sig_bytes = bytes.fromhex(sig[2:] if sig.startswith("0x") else sig)
print("signature length (bytes):", len(sig_bytes))

encoded = encode_typed_data(full_message=typed_data)
recovered = Account.recover_message(encoded, signature=sig_bytes)
print("recovered signer:", recovered)
print("claimed  signer:", CLAIMED_SIGNER)
print("MATCH:", recovered.lower() == CLAIMED_SIGNER.lower())
