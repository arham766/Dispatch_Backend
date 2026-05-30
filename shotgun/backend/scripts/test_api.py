"""Quick API test — POST an incident and check endpoints."""
import sys, os, json, time
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding='utf-8')

import httpx

API = "http://localhost:8000"

def main():
    # 1. Health check
    print("=== Health Check ===")
    r = httpx.get(f"{API}/healthz")
    data = r.json()
    print(json.dumps(data, indent=2))
    print()

    # 2. POST incident
    print("=== Creating Incident ===")
    payload = {
        "service": "checkout",
        "symptom": "Checkout returns 500 on pay-submit after deploy",
        "suspect_url": "https://arham766.github.io/app-under-test",
        "repro_flow": "flows/checkout_test.md",
        "recent_diff_hint": "payment.js",
        "source": "manual"
    }
    r = httpx.post(f"{API}/incidents", json=payload)
    print(f"Status: {r.status_code}")
    data = r.json()
    print(json.dumps(data, indent=2))
    run_id = data.get("run_id")
    print(f"\nRun ID: {run_id}")
    print()

    # 3. Get run state
    if run_id:
        time.sleep(1)
        print("=== Run State ===")
        r = httpx.get(f"{API}/incidents/{run_id}")
        print(f"Status: {r.status_code}")
        state = r.json()
        print(f"  run_id: {state.get('run_id')}")
        print(f"  state : {state.get('state')}")
        print(f"  attempt: {state.get('attempt')}")
        print()

    # 4. List incidents
    print("=== All Incidents ===")
    r = httpx.get(f"{API}/incidents")
    for inc in r.json():
        print(f"  [{inc['state']}] {inc['run_id']} - {inc['symptom'][:50]}")

    print()
    print("API tests complete!")

if __name__ == "__main__":
    main()
