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
                "User-Agent": "invinoveritas-dify/0.0.1",
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

    def reason(self, question: str, style: str = "normal") -> dict:
        return self.request("/reason", {"question": question, "style": style})

    def decision(self, goal: str, question: str, context: str = "") -> dict:
        return self.request("/decision", {"goal": goal, "question": question, "context": context})

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

    def growth_attack_plan(self, objective: str, context: str = "", budget_sats: int | None = None) -> dict:
        prompt = (
            "budget limits, and clear risk controls. Produce concrete next actions that drive registrations, "
            "funded accounts, paid reasoning, marketplace purchases, Premium Spawn Kit conversion, referrals, "
            "seller withdrawals, or Sovereign Earner support.\n\n"
            f"Objective: {objective}\nContext: {context}\nBudget sats: {budget_sats or 'not specified'}"
        )
        return self.decision(
            goal="Maximize invinoveritas growth and daily sats PNL with default-aggressive execution.",
            question=prompt,
            context=context,
        )

    def sovereign_status(self) -> dict:
        stats = urllib.request.urlopen(f"{self.base_url}/stats", timeout=20).read()
        return json.loads(stats.decode("utf-8"))

    def sovereign_execute(
        self,
        fee_sats: int = 1000,
        direction: str = "auto",
        leverage: int = 3,
        duration_hours: float = 2.0,
        stop_loss_pct: float = 0.35,
        take_profit_pct: float = 0.70,
        thesis: str = "",
    ) -> dict:
        return self.request("/sovereign/execute", {
            "fee_sats": fee_sats,
            "direction": direction,
            "leverage": leverage,
            "duration_hours": duration_hours,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "thesis": thesis,
            "agent_id": "dify",
        })
