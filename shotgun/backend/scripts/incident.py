"""
Shotgun — CLI trigger script.

Fire a seeded incident from the command line (no frontend needed).
Used in Phase 1 and as the judge-runnable fallback.

Usage:
    python -m scripts.incident examples/checkout-500.json
    python scripts/incident.py examples/checkout-500.json
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx


API_BASE = "http://localhost:8000"


async def main(incident_file: str) -> None:
    """Load an incident JSON file, POST it, and tail the SSE stream."""
    # Load the incident
    with open(incident_file, encoding="utf-8") as f:
        payload = json.load(f)

    print(f"\n🔔 Triggering incident: {payload.get('symptom', 'unknown')}")
    print(f"   Service: {payload.get('service', '?')}")
    print(f"   Flow: {payload.get('repro_flow', '?')}")
    print()

    # POST to /incidents
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(f"{API_BASE}/incidents", json=payload)
        r.raise_for_status()
        data = r.json()

    run_id = data["run_id"]
    print(f"✅ Run created: {run_id}")
    print(f"   State: {data['state']}")
    print(f"\n📡 Streaming events from {API_BASE}/incidents/{run_id}/stream\n")
    print("─" * 60)

    import websockets

    # Tail the WebSocket stream
    ws_url = f"ws://localhost:8000/incidents/{run_id}/ws"
    async with websockets.connect(ws_url) as ws:
        try:
            async for message in ws:
                payload = json.loads(message)
                event_type = payload.get("event", "")
                data_str = payload.get("data", "{}")
                
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                _print_event(event_type, event)

                if event_type == "done":
                    print("─" * 60)
                    final = event.get("final_state", "UNKNOWN")
                    emoji = "✅" if final == "RESOLVED" else "❌"
                    print(f"\n{emoji} Final state: {final}")
                    return

                if event_type == "awaiting_approval":
                    print("\n⏸️  Waiting for approval…")
                    print(f"   Run: curl -X POST {API_BASE}/incidents/{run_id}/approve")
                    # Auto-approve for CLI demo
                    input("\n   Press ENTER to approve (or Ctrl+C to reject): ")
                    async with httpx.AsyncClient() as c:
                        await c.post(
                            f"{API_BASE}/incidents/{run_id}/approve",
                            json={"approve": True},
                        )
                    print("   ✅ Approved!\n")
        except websockets.exceptions.ConnectionClosed:
            print("\n❌ WebSocket connection closed.")


def _print_event(event_type: str, event: dict) -> None:
    """Pretty-print an SSE event to the terminal."""
    state = event.get("state", "")
    icons = {
        "state_change": "🔄",
        "kane_step": "  📋",
        "kane_result": "🎯",
        "patch": "🔧",
        "awaiting_approval": "⏸️ ",
        "pr_opened": "📝",
        "review_result": "🔍",
        "recorded": "💾",
        "escalated": "⚠️ ",
        "done": "🏁",
    }
    icon = icons.get(event_type, "  ")

    if event_type == "state_change":
        msg = event.get("message", "")
        attempt = event.get("attempt")
        att_str = f" [attempt {attempt}]" if attempt else ""
        print(f"{icon} [{state}]{att_str} {msg}")

    elif event_type == "kane_result":
        passed = event.get("passed", False)
        summary = event.get("summary", "")
        duration = event.get("duration", 0)
        emoji = "✅" if passed else "❌"
        print(f"{icon} Kane: {emoji} {summary} ({duration:.1f}s)")

    elif event_type == "kane_step":
        step = event.get("step", "")
        status = event.get("status", "")
        print(f"{icon} {step}: {status}")

    elif event_type == "patch":
        branch = event.get("branch", "")
        files = event.get("changed_files", [])
        print(f"{icon} Patch: branch={branch}, files={files}")

    elif event_type == "pr_opened":
        pr_url = event.get("pr_url", "")
        print(f"{icon} PR opened: {pr_url}")

    elif event_type == "review_result":
        passed = event.get("passed", False)
        emoji = "✅" if passed else "❌"
        flows = event.get("flows_run", [])
        print(f"{icon} Review: {emoji} ({len(flows)} flows)")

    elif event_type == "recorded":
        chain = event.get("chain_length", 0)
        print(f"{icon} Recorded (chain length: {chain})")

    elif event_type == "escalated":
        reason = event.get("reason", "")
        print(f"{icon} ESCALATED: {reason}")

    elif event_type == "done":
        final = event.get("final_state", "")
        print(f"{icon} Done: {final}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/incident.py <incident.json>")
        print("Example: python scripts/incident.py examples/checkout-500.json")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
