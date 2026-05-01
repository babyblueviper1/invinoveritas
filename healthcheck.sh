#!/bin/bash
# ==============================
# Invinoveritas Node Healthcheck
# ==============================

echo "=== Invinoveritas Node Healthcheck ==="
echo ""

# ------------------------------
# 1️⃣ Check bitcoind
# ------------------------------
echo "1. bitcoind status:"
if command -v bitcoin-cli >/dev/null 2>&1; then
    BLOCKS=$(bitcoin-cli getblockcount 2>/dev/null)
    if [[ $? -eq 0 && "$BLOCKS" =~ ^[0-9]+$ ]]; then
        echo "✅ Synced: $BLOCKS blocks"
    else
        echo "⚠️  bitcoind not responding"
    fi
else
    echo "❌ bitcoin-cli not found"
fi
echo ""

# ------------------------------
# 2️⃣ Check LND
# ------------------------------
echo "2. LND status:"
if command -v lncli >/dev/null 2>&1; then
    LND_INFO=$(lncli getinfo 2>/dev/null)
    if [[ $? -eq 0 ]]; then
        PUBKEY=$(echo "$LND_INFO" | jq -r '.identity_pubkey // empty')
        SYNC_CHAIN=$(echo "$LND_INFO" | jq -r '.synced_to_chain // false')
        if [[ "$SYNC_CHAIN" == "true" ]]; then
            echo "✅ LND synced (pubkey: $PUBKEY)"
        else
            echo "⚠️  LND not synced"
        fi
    else
        echo "⚠️  lncli not responding"
    fi
else
    echo "❌ lncli not found"
fi
echo ""

# ------------------------------
# 3️⃣ Check bridge service
# ------------------------------
echo "3. Bridge service:"
BRIDGE_RESP=$(curl -s -X GET http://127.0.0.1:8081/health || echo "")
if [[ -n "$BRIDGE_RESP" && "$BRIDGE_RESP" == *'"status":"ok"'* ]]; then
    echo "✅ Bridge running: $BRIDGE_RESP"
else
    echo "⚠️  Bridge not responding or wrong code"
fi
echo ""

echo "=== Healthcheck complete ==="
