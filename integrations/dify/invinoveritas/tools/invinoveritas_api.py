import json
import urllib.error
import urllib.request

BASE_URL = "https://api.babyblueviper.com"


class InvinoveritasApi:
    """Small dependency-free helper for Dify tool actions."""

    def __init__(self, api_key: str, base_url: str = BASE_URL):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def request(self, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "invinoveritas-dify/0.1.0",
                "X-Invino-Integration": "dify",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return {"ok": False, "status": exc.code, "error": detail}

    def get(self, path: str, x402: bool = False) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "invinoveritas-dify/0.2.0",
            "X-Invino-Integration": "dify",
        }
        if x402:
            headers["X-Payment-Scheme"] = "x402"
        req = urllib.request.Request(f"{self.base_url}{path}", headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return {"ok": False, "status": exc.code, "error": detail}

    def reason(self, question: str, style: str = "normal") -> dict:
        return self.request("/reason", {"question": question, "style": style})

    def decision(self, goal: str, question: str, context: str = "") -> dict:
        return self.request("/decision", {"goal": goal, "question": question, "context": context})

    def review(
        self,
        artifact: str,
        artifact_type: str = "general",
        context: str = "",
        severity_threshold: str = "medium",
        include_trading_state: bool = False,
        sign: bool = False,
    ) -> dict:
        """Capital-scale-aware structured review — the proven front door (/review). sign=True → portable verdict proof on `proof`."""
        return self.request("/review", {
            "artifact": artifact,
            "artifact_type": artifact_type,
            "context": context,
            "severity_threshold": severity_threshold,
            "include_trading_state": include_trading_state,
            "sign": sign,
        })

    def verify_proof(self, event: dict | None = None, proof_id: str | None = None,
                     expect_artifact_hash: str | None = None) -> dict:
        """Verify a counterparty's invinoveritas proof — agent-to-agent trust handshake (FREE, no auth).
        Pass the signed `event` another agent attached to its output; confirms invinoveritas issued the
        verdict WITHOUT trusting them or us. expect_artifact_hash binds it to the exact output received."""
        payload: dict = {}
        if event is not None:
            payload["event"] = event
        if proof_id:
            payload["proof_id"] = proof_id
        if expect_artifact_hash:
            payload["expect_artifact_hash"] = expect_artifact_hash
        return self.request("/verify-proof", payload)

    def residence_act(
        self,
        intent: str,
        artifact: str = "",
        artifact_type: str = "general",
        require_review: bool = True,
        remember: bool = True,
        max_spend_sats: int | None = None,
    ) -> dict:
        """The home reasons + governs + remembers in one governed call (/residence/act)."""
        payload: dict = {
            "intent": intent,
            "artifact_type": artifact_type,
            "policy": {
                "require_review": require_review,
                "remember": remember,
                "max_spend_sats": max_spend_sats,
            },
        }
        if artifact:
            payload["artifact"] = artifact
        return self.request("/residence/act", payload)

    # ---- Markets / trading intelligence (facts-only, never P&L/advice) ----

    def regime(self, x402: bool = False) -> dict:
        """Macro risk-off DATA feed (/regime) — the methodology behind our own risk-sizing research."""
        return self.get("/regime", x402=x402)

    def signals_teaser(self) -> dict:
        """Free shop-window: BTC vol-expansion regime read (/signals) — the gate our earner enters on."""
        return self.get("/signals")

    def signals(self, x402: bool = False) -> dict:
        """Full live Hyperliquid derivatives set (/signals/full): funding + 24h delta, basis, OI, regime, realized vol, DVOL."""
        return self.get("/signals/full", x402=x402)

    def markets_act(
        self,
        artifact: str = "",
        artifact_type: str = "general",
        context: str = "",
    ) -> dict:
        """The Markets Bundle (/markets/act): regime + live signals + brief + optional governance review."""
        payload: dict = {"artifact_type": artifact_type}
        if artifact:
            payload["artifact"] = artifact
        if context:
            payload["context"] = context
        return self.request("/markets/act", payload)

    def marketplace_buy(self, offer_id: str) -> dict:
        return self.request("/offers/buy", {"offer_id": offer_id})

    def memory_store(self, agent_id: str, key: str, value: str) -> dict:
        return self.request("/memory/store", {"agent_id": agent_id, "key": key, "value": value})

    def memory_get(self, agent_id: str, key: str) -> dict:
        return self.request("/memory/get", {"agent_id": agent_id, "key": key})

    def a2a_delegate(self, operation: str, task_json: str = "{}") -> dict:
        try:
            task = json.loads(task_json or "{}")
        except json.JSONDecodeError:
            task = {"description": task_json}
        return self.request("/a2a", {"operation": operation, "task": task})
