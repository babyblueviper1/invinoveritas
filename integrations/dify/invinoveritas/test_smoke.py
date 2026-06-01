from pathlib import Path
import yaml

ROOT = Path(__file__).parent
required = [
    "manifest.yaml",
    "provider/invinoveritas.yaml",
    "tools/reason.yaml",
    "tools/decision.yaml",
    "tools/regime.yaml",
    "tools/signals.yaml",
    "tools/signals_teaser.yaml",
    "tools/markets_act.yaml",
    "tools/marketplace_buy.yaml",
    "tools/memory_store.yaml",
    "tools/memory_get.yaml",
    "tools/a2a_delegate.yaml",
    "tools/growth_attack_plan.yaml",
    "tools/sovereign_execute.yaml",
    "tools/sovereign_status.yaml",
    "tools/invinoveritas_api.py",
]

for rel in required:
    path = ROOT / rel
    if not path.exists():
        raise SystemExit(f"missing {rel}")
    if path.suffix in {".yaml", ".yml"}:
        yaml.safe_load(path.read_text())

provider = yaml.safe_load((ROOT / "provider/invinoveritas.yaml").read_text())
tools = provider.get("tools", [])
for rel in ["tools/growth_attack_plan.yaml", "tools/sovereign_execute.yaml"]:
    if rel not in tools:
        raise SystemExit(f"{rel} not registered")

api = (ROOT / "tools/invinoveritas_api.py").read_text()
for token in ["growth_attack_plan", "sovereign_execute", "X-Invino-Integration", "dify",
              "/markets/act", "/signals/full", "/regime", "def markets_act", "def signals"]:
    if token not in api:
        raise SystemExit(f"missing {token}")

print("dify smoke ok")
