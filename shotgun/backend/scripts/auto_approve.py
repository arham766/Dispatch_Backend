import httpx
import time
import sys

API = "http://127.0.0.1:8000"
RUN_ID = "ea7d14a70583"

def main():
    print(f"Waiting for run {RUN_ID} to reach HUMAN GATE...")
    while True:
        try:
            r = httpx.get(f"{API}/incidents/{RUN_ID}")
            if r.status_code == 200:
                data = r.json()
                if data.get("awaiting_approval"):
                    print("HUMAN GATE reached! Approving...")
                    r = httpx.post(f"{API}/incidents/{RUN_ID}/approve", json={"approve": True})
                    print("Approve response:", r.status_code, r.text)
                    break
                elif data.get("pr_url"):
                    print("PR already created! URL:", data["pr_url"])
                    break
                print(f"State: {data.get('state')}, Awaiting: {data.get('awaiting_approval')}")
            else:
                print("Error:", r.status_code)
        except Exception as e:
            print("Connection error:", e)
        time.sleep(5)

if __name__ == "__main__":
    main()
