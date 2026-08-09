"""
test_client.py — Step 6 verification harness

Supports:
  - Sending start_agent goals
  - Printing all event types (thought / action / observation / screenshot / done / error / aborted)
  - Handling waiting_for_user: prompts terminal for input, sends user_response back
  - Sending abort at any time via Ctrl+C (mapped to a clean abort message)
"""
import asyncio
import json
import sys
import websockets


URI = "ws://localhost:8006/ws/agent"


async def run_session(goal: str, label: str = ""):
    """
    Open one WebSocket session, run the agent to completion (or abort).
    Returns True if the session finished cleanly (done / aborted),
    False on connection error.
    """
    print(f"\n{'='*64}")
    print(f"SESSION: {label or goal[:60]}")
    print(f"{'='*64}\n")

    try:
        async with websockets.connect(URI, open_timeout=10) as ws:
            # No initial message expected; just start


            import time
            start_time = time.time()
            
            # Send the goal
            await ws.send(json.dumps({"action": "start_agent", "goal": goal}))
            print(f"[GOAL SENT]\n  {goal}\n")

            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=120)
                except asyncio.TimeoutError:
                    print("  [TIMEOUT] No event received for 120s — aborting.")
                    await ws.send(json.dumps({"action": "abort"}))
                    continue

                data = json.loads(raw)
                event_type = data.get("type")
                payload    = data.get("payload")

                if event_type == "screenshot":
                    print(f"  [SCREENSHOT] {len(payload)} bytes")

                elif event_type == "thought":
                    print(f"  [THOUGHT]   {payload}")

                elif event_type == "action":
                    print(f"  [ACTION]    {payload}")

                elif event_type == "observation":
                    # Truncate long extraction dumps for readability
                    display = payload if len(payload) < 400 else payload[:400] + "…"
                    print(f"  [OBS]       {display}")

                elif event_type == "waiting_for_user":
                    print(f"\n  [PAUSE] AGENT PAUSED — needs human input:")
                    print(f"     {payload}")
                    # Read from terminal synchronously (blocks the event loop briefly,
                    # acceptable for a CLI test harness)
                    human_text = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: input("  >> Your response (or 'abort'): ").strip()
                    )
                    if human_text.lower() == "abort":
                        await ws.send(json.dumps({"action": "abort"}))
                    else:
                        await ws.send(json.dumps({
                            "action": "user_response",
                            "response": human_text
                        }))
                    print()

                elif event_type == "done":
                    end_time = time.time()
                    print(f"\n  ✅ DONE (Total run time: {end_time - start_time:.2f}s)")
                    if isinstance(payload, dict) and "listings" in payload:
                        for i, lst in enumerate(payload["listings"], 1):
                            print(f"\n  Listing {i}:")
                            for k, v in lst.items():
                                print(f"    {k:12s} = {v!r}")
                        print(f"\n  SUMMARY:\n  {payload.get('summary', '')}")
                    else:
                        print(f"  {payload}")
                    return True

                elif event_type == "aborted":
                    end_time = time.time()
                    print(f"\n  [ABORTED] {payload} (Total run time: {end_time - start_time:.2f}s)")
                    return True

                elif event_type == "error":
                    print(f"\n  ❌ ERROR: {payload}")
                    return False

    except ConnectionRefusedError:
        print(f"  [ERROR] Could not connect to {URI} — is the server running?")
        return False
    except KeyboardInterrupt:
        print("\n  [CTRL+C] Sending abort to server...")
        # Re-connect briefly just to send abort; server will clean up
        try:
            async with websockets.connect(URI, open_timeout=5) as ws:
                await ws.send(json.dumps({"action": "abort"}))
        except Exception:
            pass
        return False


async def main():
    # ── Test plan ────────────────────────────────────────────────────────────
    # 1. Real search goal — exercises navigate → search → click → extract → submit
    # 2. Craigslist search — exercises the other source path
    # Both hit the full pipeline; Redfin rate-limit will surface as ask_human.

    goals = [
        (
            "Find me a 3 bedroom 3 bathroom in Richardson, TX under $3500. Use Craigslist. I work at 'University of Texas at Dallas', and I also want to know about nearby schools and gyms.",
            "E2E Test: Amenities and Distance"
        )
    ]

    for goal, label in goals:
        ok = await run_session(goal, label)
        if not ok:
            print(f"\n[Session ended with error — stopping.]\n")
            sys.exit(1)
        await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
