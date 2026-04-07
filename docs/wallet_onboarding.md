# ⚡ invinoveritas — Wallet Onboarding Guide

This guide helps developers and autonomous agents quickly set up Lightning wallets to pay for invinoveritas services.

---

## 1. Choose Your Wallet Type

| Type                  | Recommended Wallets       | Best For                          | Node Required |
|-----------------------|---------------------------|-----------------------------------|---------------|
| **NWC (Easiest)**     | Alby, Zeus, Mutiny        | Quick setup, autonomous agents    | No            |
| **Full Node**         | LND                       | High volume, maximum control      | Yes           |

---

## 2. Install the Python SDK

```bash
# Basic installation
pip install invinoveritas

# For LangChain + agent support
pip install "invinoveritas[langchain]"

# For NWC wallet support
pip install "invinoveritas[nwc]"
```

---

## 3. Configure Your Wallet

### Option A: NWC Wallet (Recommended for most agents)

```python
from invinoveritas.providers import NWCProvider
from invinoveritas.langchain import InvinoCallbackHandler, create_invinoveritas_tools

handler = InvinoCallbackHandler(
    provider=NWCProvider(
        uri="nostr+walletconnect://YOUR_WALLET_CONNECT_URI_HERE"
    )
)

tools = create_invinoveritas_tools(handler)
```

> Replace `YOUR_WALLET_CONNECT_URI_HERE` with the NWC URI from Alby, Zeus, or Mutiny.

### Option B: LND Node (Full control)

```python
from invinoveritas.providers import LNDProvider
from invinoveritas.langchain import InvinoCallbackHandler, create_invinoveritas_tools

handler = InvinoCallbackHandler(
    provider=LNDProvider(
        macaroon_path="/root/.lnd/data/chain/bitcoin/mainnet/admin.macaroon",
        cert_path="/root/.lnd/tls.cert",
        # rpcserver="localhost:10009"   # optional if not default
    )
)

tools = create_invinoveritas_tools(handler)
```

---

## 4. Test Your Agent

```python
result = agent.run(
    "Should I increase my BTC exposure in 2026?", 
    callbacks=[handler]
)

print(f"Total spent: {handler.total_spent_sats} sats")
print(f"Answer: {result}")
```

The handler automatically handles Lightning payments (L402 or credit system) and tracks spending.

---

## 5. Best Practices for Agents

- Start with small test queries using `/reason` or `/decide`
- Ensure your wallet always has sufficient sats
- NWC is fastest for onboarding new agents
- All payments are atomic and fully verifiable
- No KYC or accounts required (though credit accounts are optional)
- Keep your LND macaroon and TLS cert secure

---

## 6. Official Resources

- **LND Documentation**: [https://docs.lightning.engineering](https://docs.lightning.engineering)
- **NWC / WalletConnect**: [https://walletconnect.com](https://walletconnect.com)
- **invinoveritas GitHub**: [https://github.com/babyblueviper1/invinoveritas](https://github.com/babyblueviper1/invinoveritas)

---

**Tip**: Use the **Credit Account system** (`/register` + `/topup`) if you prefer pre-funding instead of paying per request.

---
