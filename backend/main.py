"""
main.py — FastAPI WebSocket server

Single-consumer design
──────────────────────
receive_loop() is the ONLY task that calls websocket.receive_text().
It pushes every incoming message onto command_queue (asyncio.Queue).

All other readers — the outer command dispatcher and _pause_for_human()
inside run_agent_loop — read from command_queue. This guarantees exactly
one consumer per message, eliminating the race condition that would occur
if both the abort-listener and _pause_for_human tried to read from the
WebSocket stream concurrently.

Message flow:
  Client WebSocket → receive_loop → command_queue
                                          │
                      ┌───────────────────┼──────────────────────┐
                      │                   │                        │
              outer while loop     _drain_abort()        _pause_for_human()
              (start_agent cmd)   (between tool calls)   (blocking wait)
"""
import json
import sys
import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from browser import BrowserSession
from agent import run_agent_loop, _WS_CLOSED
from dotenv import load_dotenv

load_dotenv()

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI(title="Real Estate Agent Backend")


def get_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.websocket("/ws/agent")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    browser_session = BrowserSession()

    # Shared state for this connection
    abort_event   = asyncio.Event()
    command_queue: asyncio.Queue = asyncio.Queue()

    # ── Single WebSocket receive loop ─────────────────────────────────────────
    # This is the ONLY place in the entire application that calls
    # websocket.receive_text(). Every incoming message is pushed onto
    # command_queue for whichever reader needs it.
    async def receive_loop():
        try:
            while True:
                raw = await websocket.receive_text()
                cmd = json.loads(raw)
                await command_queue.put(cmd)
                # Fast path: set abort_event immediately so the agent loop's
                # next _drain_abort() check exits within one poll cycle.
                if cmd.get("action") in ("abort", "_ws_closed"):
                    abort_event.set()
        except (WebSocketDisconnect, Exception):
            # WebSocket closed (client disconnected or server error).
            # Push the sentinel so any blocking queue.get() in _pause_for_human
            # sees it and exits cleanly rather than hanging indefinitely.
            await command_queue.put(_WS_CLOSED)
            abort_event.set()

    receive_task = asyncio.create_task(receive_loop())

    try:
        # We wait for the user to explicitly send 'start_agent' before doing anything.

        # ── Outer command dispatcher ──────────────────────────────────────────
        # Reads from command_queue (NOT from the WebSocket directly).
        # Handles start_agent and abort before any agent task has started.
        while True:
            cmd = await command_queue.get()
            action = cmd.get("action")

            if action == "start_agent":
                goal = cmd.get("goal", "navigate to Redfin and search Richardson TX")

                await websocket.send_json({
                    "type": "thought",
                    "payload": f"Starting agent with goal: {goal}",
                    "timestamp": get_timestamp()
                })

                await websocket.send_json({
                    "type": "thought",
                    "payload": "Initializing browser session...",
                    "timestamp": get_timestamp()
                })
                
                await browser_session.start()

                # run_agent_loop blocks until done, aborted, or error.
                # It reads further client messages through command_queue only.
                await run_agent_loop(
                    goal,
                    browser_session,
                    websocket,
                    get_timestamp,
                    abort_event,
                    command_queue,
                )

                # ── Post-run cleanup ──────────────────────────────────────────
                # 1. Reset abort_event for the next run.
                abort_event.clear()

                # 2. Drain any stale "abort" messages that receive_loop enqueued
                #    while the agent was running. If we don't do this, the outer
                #    dispatcher reads the leftover abort on the next iteration,
                #    hits the `elif action in ("abort", ...)` branch, and breaks —
                #    which closes the WebSocket and causes "Not connected to server"
                #    when the user tries to start a new query.
                while not command_queue.empty():
                    try:
                        stale = command_queue.get_nowait()
                        print(f"[Dispatcher] Drained stale post-run command: {stale.get('action')}")
                    except asyncio.QueueEmpty:
                        break

                # 3. Close the Playwright browser from the completed/aborted run
                #    and create a fresh BrowserSession for the next query.
                #    Without this, the next start_agent would call browser_session.start()
                #    on an already-started (possibly broken) session.
                await browser_session.close()
                print("Browser session closed after run. Ready for next query.")
                browser_session = BrowserSession()

            elif action in ("abort", "_ws_closed"):
                # Abort before any agent task started
                abort_event.set()
                try:
                    await websocket.send_json({
                        "type": "aborted",
                        "payload": "Aborted before agent started.",
                        "timestamp": get_timestamp()
                    })
                except Exception:
                    pass
                break

            # Any other unexpected action: discard and keep waiting

    except WebSocketDisconnect:
        print("Client disconnected.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            await websocket.send_json({
                "type": "error",
                "payload": str(e),
                "timestamp": get_timestamp()
            })
        except Exception:
            pass
    finally:
        # Signal all consumers to exit, then clean up
        abort_event.set()
        receive_task.cancel()
        try:
            await receive_task
        except asyncio.CancelledError:
            pass
        await browser_session.close()
        print("Browser session closed.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8006)
