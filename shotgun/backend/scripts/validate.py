"""Quick config + import validation."""
import sys
import os
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, ".")

from app.config import settings
print("[OK] Config loaded")
print(f"  Kane user   : {settings.LT_USERNAME}")
print(f"  GitHub repo : {settings.GITHUB_REPO}")
print(f"  Kiro mode   : {settings.KIRO_MODE}")
print(f"  Staging URL : {settings.STAGING_BASE_URL}")
print(f"  AgentPhone  : {'ON' if settings.AGENTPHONE_ENABLED else 'OFF'}")
print()

from app.models import Incident, State, RunState, KaneResult
print(f"[OK] Models imported ({len(State)} states)")

from app.store import store
print("[OK] Store imported")

from app.events import EventType
print("[OK] Events imported")

from app import recorder
print("[OK] Recorder imported")

from app.clients.kiro import make_kiro_agent
kiro = make_kiro_agent()
print(f"[OK] Kiro agent: {kiro.__class__.__name__}")

from app.intake.normalize import to_incident
test_payload = {
    "service": "checkout",
    "symptom": "Test incident",
    "suspect_url": "http://localhost:3000",
    "repro_flow": "flows/checkout_test.md",
}
inc = to_incident(test_payload)
print(f"[OK] Normalizer: {inc.service} - {inc.symptom}")

from app.clients import github_pr
print("[OK] GitHub PR client imported")

from app.clients import kane
print("[OK] Kane client imported")

print()
print("All imports valid -- ready to start server!")
