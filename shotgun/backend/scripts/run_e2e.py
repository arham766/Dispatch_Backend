"""
Fire the seeded incident and print the full SSE stream.
"""
import sys, os, json, time
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding='utf-8')

import httpx

API = "http://localhost:8000"

def main():
    payload = {
        "service": "checkout",
        "symptom": "Checkout returns 500 on pay-submit, 80% error rate",
        "suspect_url": "https://arham766.github.io/app-under-test",
        "repro_flow": "flows/checkout_test.md",
        "recent_diff_hint": "payment.js",
        "source": "manual"
    }

    print("=== Triggering Incident ===")
    r = httpx.post(f"{API}/incidents", json=payload)
    data = r.json()
    run_id = data["run_id"]
    print(f"Run ID: {run_id}")
    print(f"State:  {data['state']}")
    print()

    # Poll state every 3 seconds for 2 minutes
    print("=== Polling Run State ===")
    for i in range(40):
        time.sleep(3)
        try:
            r = httpx.get(f"{API}/incidents/{run_id}")
            state = r.json()
            s = state.get("state", "?")
            att = state.get("attempt", 0)
            awaiting = state.get("awaiting_approval", False)
            pr = state.get("pr_url", "")
            kane = state.get("last_kane")
            kane_str = ""
            if kane:
                kane_str = f" | Kane: {'PASS' if kane.get('passed') else 'FAIL'} - {kane.get('summary', '')[:60]}"
            print(f"  [{i*3:3d}s] state={s:<18s} attempt={att} awaiting={awaiting}{kane_str}")

            if s in ("RESOLVED", "ESCALATE", "STANDBY", "DISMISSED"):
                print(f"\n=== FINAL STATE: {s} ===")
                if pr:
                    print(f"PR: {pr}")
                break

            if awaiting:
                print("  >>> HUMAN GATE reached! Auto-approving...")
                httpx.post(f"{API}/incidents/{run_id}/approve", json={"approve": True})

        except Exception as e:
            print(f"  Error polling: {e}")

    # Final state
    r = httpx.get(f"{API}/incidents/{run_id}")
    print("\n=== Final Run State ===")
    print(json.dumps(r.json(), indent=2, default=str))

if __name__ == "__main__":
    main()
