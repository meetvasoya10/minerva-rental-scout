import os
import json
import asyncio
from dotenv import load_dotenv
from anthropic import AsyncAnthropic
from browser import BrowserSession
import places

current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, ".env")
load_dotenv(dotenv_path=env_path)

api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    print(f"Warning: ANTHROPIC_API_KEY not found in {env_path}")

client = AsyncAnthropic(api_key=api_key)

MODEL_NAME = "claude-sonnet-4-5-20250929"

# ── Sentinel value ────────────────────────────────────────────────────────────
# Placed on command_queue by receive_loop when the WebSocket closes, so any
# blocking queue.get() in _pause_for_human() sees it and exits cleanly.
_WS_CLOSED = {"action": "_ws_closed"}

# ── Tool schema ───────────────────────────────────────────────────────────────
# These are the actions the LLM can request. The backend decides HOW to execute
# each one (Playwright selectors, waits, parsing). The LLM decides WHICH and WHEN.
TOOLS = [
    {
        "name": "search_and_extract_listings",
        "description": "Mechanically searches Craigslist and PadMapper, extracts all listing URLs, dedupes them, visits them, and returns exactly 3 unique listings combined across sources.",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "e.g., 'houston' or 'dallas'"},
                "query": {"type": "string", "description": "General text keywords ONLY. Do NOT put bed/bath counts or prices here, use the max_* fields. Can be empty."},
                "max_price": {"type": "number"},
                "min_bedrooms": {"type": "number", "description": "Set if user asks for 'at least X' or 'X+'. If they ask for exactly 'X', set BOTH min and max to X."},
                "max_bedrooms": {"type": "number", "description": "Set if user asks for 'under X' or 'max X'. If they ask for exactly 'X', set BOTH min and max to X."},
                "min_bathrooms": {"type": "number", "description": "Set if user asks for 'at least X' or 'X+'. If they ask for exactly 'X', set BOTH min and max to X."},
                "max_bathrooms": {"type": "number", "description": "Set if user asks for 'under X' or 'max X'. If they ask for exactly 'X', set BOTH min and max to X."}
            },
            "required": ["location"]
        }
    },
    {
        "name": "ask_human",
        "description": (
            "Pause the agent and ask the human operator a question. "
            "Use this when: (1) a CAPTCHA or bot-block page appears, "
            "(2) a search returns an error and retrying would not help, "
            "(3) you are genuinely unsure how to proceed. "
            "The agent resumes once the human responds."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Clear description of what you need from the human."
                }
            },
            "required": ["question"]
        }
    },
    {
        "name": "get_nearby_amenities",
        "description": "Checks for nearby amenities (schools, stores, gyms) or calculates distance to a work landmark.",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "The listing address"},
                "category": {"type": "string", "description": "Category of amenity (e.g., 'schools', 'grocery stores', 'gyms'). If measuring distance to a work location, put the work location/landmark string here."}
            },
            "required": ["address", "category"]
        }
    },
    {
        "name": "submit_comparison",
        "description": (
            "Submit the final structured comparison of all properties researched. "
            "Call this exactly once when all extraction is complete. "
            "All numeric fields must be actual numbers, not strings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "listings": {
                    "type": "array",
                    "description": "One entry per property investigated.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source":    {"type": "string", "description": "redfin or craigslist"},
                            "price":     {"type": "number", "description": "Monthly rent in dollars (integer)"},
                            "beds":      {"type": "number"},
                            "baths":     {"type": "number"},
                            "sqft":      {"type": "number"},
                            "address":   {"type": "string"},
                            "amenities": {"type": "string"},
                            "photos": {
                                "type": "array",
                                "items": {"type": "string"}
                            },
                            "floorplan": {"type": "string"},
                            "url":       {"type": "string", "description": "The URL of the actual posting"},
                            "nearby_places": {
                                "type": "array",
                                "description": "Structured data from get_nearby_amenities containing schools, gyms, stores, etc.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "category": {"type": "string"},
                                        "amenities": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "name": {"type": "string"},
                                                    "distance_miles": {"type": "number"}
                                                }
                                            }
                                        },
                                        "error": {"type": "string"},
                                        "data_source": {"type": "string"}
                                    }
                                }
                            },
                            "commute": {
                                "type": "object",
                                "description": "Structured commute distance from get_nearby_amenities when used for work locations.",
                                "properties": {
                                    "to": {"type": "string"},
                                    "distance_miles": {"type": "number"},
                                    "duration_minutes": {"type": "number"},
                                    "error": {"type": "string"},
                                    "data_source": {"type": "string"}
                                }
                            }
                        }
                    }
                },
                "summary": {
                    "type": "string",
                    "description": (
                        "Format this strictly as a scannable ranked list using markdown. "
                        "For each listing, output: '### 1. [Address] - $[Price]/mo', "
                        "followed by a bulleted list containing a $/sqft badge (e.g. '**$1.20/sqft**') if applicable, "
                        "and 2-3 short bullet points of key features or concerns. "
                        "Visually separate each listing. Do NOT write a dense paragraph."
                    )
                }
            },
            "required": ["listings", "summary"]
        }
    }
]

SYSTEM_PROMPT = (
    "You are an autonomous browser-automation agent for real estate research. "
    "Follow these rules:\n"
    "1. Always use a tool — never end your turn with only text. Plain text completion is invalid.\n"
    "2. If a search returns an error or a CAPTCHA appears, call ask_human immediately.\n"
    "3. When all required listings have been extracted via search_and_extract_listings, you MUST call get_nearby_amenities for each listing to check for schools, grocery stores, and gyms, plus calculate distance to any mentioned work location/landmark.\n"
    "4. When all listings and their amenities are gathered, evaluate them and call submit_comparison exactly once.\n"
    "5. Calling submit_comparison is the ONLY valid way to end a run.\n"
    "6. BEDROOM/BATHROOM PARSING RULES:\n"
    "   - EXACT matches (e.g. '3 bedroom', '3 bed 3 bath'): You MUST set BOTH min_bedrooms and max_bedrooms to 3.\n"
    "   - MINIMUM matches (e.g. 'at least 2 bed', '3+ baths'): You MUST set min_bedrooms only.\n"
    "   - MAXIMUM matches (e.g. 'under 3 bed', 'max 2 baths'): You MUST set max_bedrooms only.\n"
    "7. Craigslist search queries: DO NOT put bed/bath numbers in the 'query' text parameter. Use the min/max fields exclusively."
)

# ── Stuck-state detector ──────────────────────────────────────────────────────
# Safety net under the LLM's judgment: if the same (tool, failure-text) pair
# appears CONSECUTIVE_FAILURE_THRESHOLD times in a row, auto-escalate to
# ask_human rather than letting the agent spin indefinitely.
CONSECUTIVE_FAILURE_THRESHOLD = 2

class StuckDetector:
    def __init__(self):
        self._last_key: str | None = None
        self._count: int = 0

    def record(self, tool_name: str, observation: str) -> bool:
        """Return True if this should trigger an automatic ask_human escalation."""
        is_failure = (
            observation.startswith("Failed to click")
            or observation.startswith("Error:")
            or "rate-limiting" in observation.lower()
            or "error occurred" in observation.lower()
        )
        if not is_failure:
            self._last_key = None
            self._count = 0
            return False

        key = f"{tool_name}:{observation[:80]}"
        if key == self._last_key:
            self._count += 1
        else:
            self._last_key = key
            self._count = 1

        return self._count >= CONSECUTIVE_FAILURE_THRESHOLD

    def reset(self):
        self._last_key = None
        self._count = 0

def _norm_addr(a: str) -> str:
    """Aggressively normalize an address for fuzzy matching."""
    import re
    a = (a or "").strip().lower()
    # Expand common abbreviations
    a = re.sub(r'\bst\b', 'street', a)
    a = re.sub(r'\bdr\b', 'drive', a)
    a = re.sub(r'\bave\b', 'avenue', a)
    a = re.sub(r'\bblvd\b', 'boulevard', a)
    a = re.sub(r'\brd\b', 'road', a)
    a = re.sub(r'\bln\b', 'lane', a)
    a = re.sub(r'\bct\b', 'court', a)
    # Collapse whitespace and strip punctuation
    a = re.sub(r'[^a-z0-9 ]', ' ', a)
    a = re.sub(r'\s+', ' ', a).strip()
    return a

# ── Core agent loop ───────────────────────────────────────────────────────────
async def run_agent_loop(
    goal: str,
    browser: BrowserSession,
    websocket,
    get_timestamp_fn,
    abort_event: asyncio.Event,
    command_queue: asyncio.Queue,   # ← single-consumer queue; never call ws.receive_text() here
):
    """
    Agentic loop design
    ───────────────────
    • The LLM decides WHICH tool to call and WHEN.
    • The backend executes each tool using hardcoded Playwright logic.
    • All WebSocket messages from the client arrive via command_queue (written
      exclusively by receive_loop in main.py). This function never calls
      websocket.receive_text() directly — that is the key invariant that
      prevents the race condition between concurrent consumers.
    • abort_event can be set from receive_loop (on "abort" message) or from
      within _pause_for_human. Both paths check it before the next action.
    """
    messages = [{"role": "user", "content": f"Your goal is: {goal}"}]
    stuck = StuckDetector()

    # ── Extract landmark from goal for GeoFilter precision ────────────────────
    # If the user says "near X" or "close to X", X is the anchor for distance
    # filtering. We pass this as landmark_hint to gather_combined_listings so
    # GeoFilter geocodes the actual POI (e.g. the school) rather than the city.
    import re as _re
    _landmark_hint: str | None = None
    _near_match = _re.search(
        r'\b(?:near|close to|next to|by|around)\s+([A-Z][^,\.\n]{3,60})',
        goal,
        _re.IGNORECASE
    )
    if _near_match:
        _landmark_hint = _near_match.group(1).strip()
        print(f"[LandmarkHint] Extracted from goal: '{_landmark_hint}'")

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _send(event_type: str, payload):
        """Send a JSON event to the frontend. Swallows disconnect errors."""
        try:
            await websocket.send_json({
                "type": event_type,
                "payload": payload,
                "timestamp": get_timestamp_fn()
            })
        except Exception:
            pass

    async def _send_frame(data):
        await _send("screenshot", data)
        
    await browser.start_screencast(_send_frame)

    def _drain_abort():
        """
        Non-blocking queue drain between tool calls.
        Consumes any queued messages and sets abort_event if "abort" is found.
        Does NOT block — safe to call between any two await points.
        """
        try:
            while True:
                cmd = command_queue.get_nowait()
                if cmd.get("action") in ("abort", "_ws_closed"):
                    abort_event.set()
        except asyncio.QueueEmpty:
            pass

    async def _abortable(coro):
        """
        Race a coroutine against abort_event.

        Polls abort_event every 0.5 s. If abort fires, cancels the running
        task and raises asyncio.CancelledError so the caller can clean up.
        This ensures no blocking LLM call or Playwright scrape runs more than
        ~0.5 s past the moment the user clicks Abort.
        """
        task = asyncio.ensure_future(coro)
        try:
            while not task.done():
                if abort_event.is_set():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    raise asyncio.CancelledError("abort_event set")
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=0.5)
                except asyncio.TimeoutError:
                    pass  # not done yet; loop and check abort again
            return task.result()
        except asyncio.CancelledError:
            if not task.done():
                task.cancel()
            raise

    async def _pause_for_human(question: str) -> str | None:
        """
        Emit waiting_for_user, then block on command_queue until:
          - "user_response" arrives → return the response string
          - "abort" or "_ws_closed" arrives → set abort_event, return None

        This is the ONLY place that does a blocking queue.get(); it is never
        called concurrently with itself. receive_loop() in main.py is the only
        caller of websocket.receive_text(), so there is exactly one consumer
        per message.
        """
        await _send("waiting_for_user", question)
        while True:
            if abort_event.is_set():
                return None
            try:
                cmd = await asyncio.wait_for(command_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # Poll loop — check abort_event and wait again
                continue

            action = cmd.get("action")
            if action == "user_response":
                return cmd.get("response", "(no text provided)")
            elif action in ("abort", "_ws_closed"):
                abort_event.set()
                return None
            # Any other action (e.g. a stale start_agent retransmit): discard during pause

    # Server-side accumulator: we track all valid extracted listings ourselves
    # so we don't rely on the LLM to re-transcribe them into submit_comparison.
    accumulated_listings: list = []

    # ── Main loop ─────────────────────────────────────────────────────────────

    while True:
        # Drain any pending client messages before asking the LLM.
        # This is the non-blocking abort check between iterations.
        _drain_abort()
        if abort_event.is_set():
            await _send("aborted", "Agent stopped by abort signal.")
            return

        try:
            # Generic pre-call thought — replaced after the response arrives.
            await _send("thought", "Thinking...")

            try:
                response = await _abortable(client.messages.create(
                    model=MODEL_NAME,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
                    messages=messages,
                ))
            except asyncio.CancelledError:
                await _send("aborted", "Agent stopped by abort signal.")
                return

            messages.append({"role": "assistant", "content": response.content})

            # ── Extract LLM's own text reasoning and send it to the UI ─────
            # The LLM often includes a text preamble alongside its tool calls.
            # Sending this is far more useful than the generic "Thinking..." label.
            reasoning_text = next(
                (b.text for b in response.content if b.type == "text" and b.text.strip()),
                None
            )
            if reasoning_text:
                # Truncate very long reasoning blocks; the full text is in server logs
                preview = reasoning_text.strip()[:300] + ("…" if len(reasoning_text.strip()) > 300 else "")
                print(f"[LLM-THOUGHT] {reasoning_text.strip()[:500]}")
                await _send("thought", preview)

            # ── Case 1: LLM called a tool ─────────────────────────────────────
            has_tool_use = any(b.type == "tool_use" for b in response.content)
            if has_tool_use:
                tool_results_content = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue  # Skip text preamble blocks

                    tool_name   = block.name
                    tool_input  = block.input
                    tool_use_id = block.id
                    observation_text = ""

                    await _send("action", f"Tool call: {tool_name} with input: {json.dumps(tool_input)}")

                    # Keep track of what we send to the UI vs what we send to the LLM
                    ui_observation_text = None

                    # ── Tool dispatch ─────────────────────────────────────────
                    try:
                        # Abort check before every tool call
                        _drain_abort()
                        if abort_event.is_set():
                            raise asyncio.CancelledError("abort before tool dispatch")

                        if tool_name == "search_and_extract_listings":
                            loc = tool_input.get("location", "")
                            q = tool_input.get("query", "")
                            p = tool_input.get("max_price")
                            min_b = tool_input.get("min_bedrooms")
                            max_b = tool_input.get("max_bedrooms")
                            min_ba = tool_input.get("min_bathrooms")
                            max_ba = tool_input.get("max_bathrooms")
                            observation_text = await _abortable(browser.gather_combined_listings(
                                location=loc, query=q, max_price=p,
                                min_beds=min_b, max_beds=max_b,
                                min_baths=min_ba, max_baths=max_ba,
                                landmark_hint=_landmark_hint
                            ))
                            ui_observation_text = observation_text # keep full payload for UI if needed
                            # Accumulate listings server-side so we don't rely
                            # on the LLM to re-transcribe them into submit_comparison.
                            try:
                                parsed = json.loads(observation_text)
                                if isinstance(parsed, list):
                                    accumulated_listings.extend(parsed)
                                    print(f"[Accumulator] Now holding {len(accumulated_listings)} listing(s).")
                                    # Feed a COMPACT summary back to the LLM — strip photos
                                    # (which can be 10 long URLs each) so the context window
                                    # doesn't balloon and cause slow final LLM calls.
                                    compact = []
                                    for item in parsed:
                                        c = {k: v for k, v in item.items() if k != "photos"}
                                        c["photo_count"] = len(item.get("photos") or [])
                                        compact.append(c)
                                    observation_text = json.dumps(compact, indent=2)
                            except (json.JSONDecodeError, TypeError):
                                pass  # observation was an error string, not JSON

                        elif tool_name == "ask_human":
                            question = tool_input.get("question", "I need help — please advise.")
                            human_reply = await _pause_for_human(question)
                            if human_reply is None:
                                await _send("aborted", "Agent aborted while waiting for human input.")
                                return
                            observation_text = f"Human responded: {human_reply}"
                            ui_observation_text = observation_text
                            stuck.reset()

                        elif tool_name == "get_nearby_amenities":
                            addr = tool_input.get("address")
                            cat = tool_input.get("category")
                            # places.get_nearby_amenities is synchronous (blocking HTTP).
                            # Run it in a thread so _abortable can cancel it promptly.
                            try:
                                res = await _abortable(
                                    asyncio.to_thread(places.get_nearby_amenities, addr, cat)
                                )
                            except asyncio.CancelledError:
                                await _send("aborted", "Agent stopped by abort signal.")
                                return
                            observation_text = json.dumps(res, indent=2)
                            ui_observation_text = observation_text # default UI format is the JSON
                            
                            print(f"[DEBUG-DISTANCE-AGENT] Attaching to UI observation: {json.dumps(res.get('amenities', []))}")
                            
                            # Also attach to the relevant accumulator entry so
                            # submit_comparison can merge by URL (most reliable key)
                            # ── Canonical-category dedup before appending ─────────────────
                            # The LLM sometimes calls get_nearby_amenities twice for schools:
                            # once with the landmark name (e.g. "Plano West Senior High School")
                            # and once with the canonical string ("schools"). Both resolve to
                            # the same OSM tag in places.py, so they return identical data.
                            # We must deduplicate on the canonical type, not the raw string.
                            def _canon_cat(s: str) -> str:
                                s = (s or '').lower()
                                if 'school' in s: return 'schools'
                                if 'store' in s or 'grocer' in s or 'supermarket' in s: return 'grocery stores'
                                if 'gym' in s or 'fitness' in s: return 'gyms'
                                return s

                            input_addr = _norm_addr(addr)
                            for acc in accumulated_listings:
                                acc_addr = _norm_addr(acc.get("address"))
                                if acc_addr and input_addr and (acc_addr in input_addr or input_addr in acc_addr):
                                    acc.setdefault("nearby_places", [])
                                    incoming_canon = _canon_cat(res.get("category", ""))
                                    existing_canons = [_canon_cat(p.get("category", "")) for p in acc["nearby_places"]]
                                    if res.get("category") and incoming_canon not in existing_canons:
                                        # Store the result but overwrite category with the canonical string
                                        # so the frontend always gets a predictable value.
                                        canonical_res = dict(res)
                                        canonical_res["category"] = incoming_canon
                                        acc["nearby_places"].append(canonical_res)
                                        print(f"[NearbyDedup] Appended '{incoming_canon}' for {acc.get('address')}")
                                    elif incoming_canon in existing_canons:
                                        print(f"[NearbyDedup] SKIPPING duplicate '{incoming_canon}' (raw='{res.get('category')}') for {acc.get('address')}")
                                    elif res.get("to"):  # commute result
                                        acc["commute"] = res
                                    break
                            # Feed a compact version to the LLM to keep context small
                            if isinstance(res, dict) and "amenities" in res:
                                names = [a.get("name", "?") for a in (res.get("amenities") or [])]
                                observation_text = (
                                    f"Nearby {res.get('category', 'places')} found near "
                                    f"{res.get('address', addr)}: "
                                    + (', '.join(names) if names else 'none found')
                                    + f" ({len(names)} result(s), data_source={res.get('data_source', 'unknown')})"
                                )
                            elif isinstance(res, dict) and "distance_miles" in res:
                                observation_text = (
                                    f"Commute from {res.get('from', addr)} to {res.get('to', cat)}: "
                                    f"{res.get('distance_miles', '?')} mi"
                                    + (f", {res.get('duration_minutes')} min" if res.get('duration_minutes') else "")
                                )
                            
                        elif tool_name == "submit_comparison":
                            # Use the server-side accumulated listings as the base
                            # (guarantees scraped photos/amenities are always present),
                            # then MERGE the enrichment fields that the LLM added
                            # (nearby_places, commute) from its own submitted listings.
                            summary = tool_input.get("summary", "")
                            llm_listings = tool_input.get("listings", [])

                            # ── Merge strategy (most-reliable-key-first) ──────────
                            # 1. URL match (exact) — URLs are never reformatted by the LLM
                            # 2. Normalized address match (strip/lower) — fallback
                            # Diagnostic logging: print both sides so mismatches are visible.

                            # Build LLM-enrichment lookup: url → entry, then addr → entry
                            llm_by_url: dict = {}
                            llm_by_addr: dict = {}
                            for ll in llm_listings:
                                u = (ll.get("url") or "").strip()
                                if u and u != "not found":
                                    llm_by_url[u] = ll
                                ak = _norm_addr(ll.get("address", ""))
                                if ak:
                                    llm_by_addr[ak] = ll

                            print("\n[Merge] LLM URL keys:", list(llm_by_url.keys()))
                            print("[Merge] LLM addr keys:", list(llm_by_addr.keys()))

                            merged = []
                            for acc in accumulated_listings:
                                acc_url = (acc.get("url") or "").strip()
                                acc_addr_key = _norm_addr(acc.get("address", ""))

                                # The accumulator may already have nearby_places attached
                                # directly by the get_nearby_amenities handler above.
                                # Only try LLM merge if the server-side data is missing.
                                entry = dict(acc)
                                
                                print(f"[DEBUG-DISTANCE-MERGE-BEFORE] entry address={entry.get('address')}, nearby_places={json.dumps(entry.get('nearby_places', []))}")

                                if not entry.get("nearby_places"):
                                    # Try URL match first
                                    enriched = llm_by_url.get(acc_url) or llm_by_addr.get(acc_addr_key) or {}
                                    if enriched:
                                        print(f"[Merge] Matched acc addr='{acc.get('address')}' url='{acc_url}'")
                                    else:
                                        print(f"[Merge] NO MATCH for acc addr='{acc.get('address')}' url='{acc_url}'")
                                        print(f"         norm_addr='{acc_addr_key}'")
                                    for field in ("nearby_places", "commute"):
                                        if enriched.get(field):
                                            print(f"[DEBUG-ASSIGN] Assigning {field} from LLM enriched object!")
                                            print(f"[DEBUG-ASSIGN] Source (enriched[{field}]): {json.dumps(enriched[field])}")
                                            entry[field] = enriched[field]
                                            print(f"[DEBUG-ASSIGN] Result (entry[{field}]): {json.dumps(entry[field])}")
                                            
                                print(f"[DEBUG-DISTANCE-MERGE-AFTER] entry address={entry.get('address')}, nearby_places={json.dumps(entry.get('nearby_places', []))}")

                                merged.append(entry)

                            # If accumulated is empty (shouldn't happen), fall back to LLM list
                            if not merged:
                                merged = llm_listings

                            final_payload = {
                                "listings": merged,
                                "summary": summary,
                            }
                            print(f"\n--- FINAL SUBMIT_COMPARISON PAYLOAD ({len(merged)} listings) ---")
                            print(json.dumps(final_payload, indent=2)[:1200], "...")
                            print(f"----------------------------------------------------------------------\n")
                            await _send("done", final_payload)
                            # We MUST append the tool result before returning to maintain Anthropic block parity!
                            tool_results_content.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": "Submitted successfully."
                            })
                            messages.append({
                                "role": "user",
                                "content": tool_results_content
                            })
                            return

                        else:
                            observation_text = f"Error: unknown tool '{tool_name}'."

                    except asyncio.CancelledError:
                        # abort_event was set — _abortable() raised CancelledError.
                        # asyncio.CancelledError is BaseException (not Exception) so
                        # the generic except below can't catch it, causing an ASGI crash.
                        # Handle it here: send "aborted" and exit the loop cleanly.
                        await _send("aborted", "Agent stopped by abort signal.")
                        return

                    except Exception as e:
                        # Catch any exception during tool execution to guarantee we append a tool_result!
                        observation_text = f"Error executing tool: {e}"
                        print(f"Tool execution exception: {e}")

                    # ── Stuck-state safety net ────────────────────────────────
                    if stuck.record(tool_name, observation_text):
                        stuck_msg = (
                            f"The same action failed {CONSECUTIVE_FAILURE_THRESHOLD} times in a row.\n"
                            f"  Tool: {tool_name}\n"
                            f"  Last result: {observation_text}\n\n"
                            f"Should I try a different approach, or abort?"
                        )
                        await _send("thought", f"[StuckDetector] Auto-escalating after {CONSECUTIVE_FAILURE_THRESHOLD} identical failures.")
                        human_reply = await _pause_for_human(stuck_msg)
                        if human_reply is None:
                            await _send("aborted", "Agent aborted during stuck-state escalation.")
                            return
                        observation_text += f"\n\n[Operator advice]: {human_reply}"
                        stuck.reset()

                    # Feed result back to LLM message history GUARANTEED
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": str(observation_text)
                    })

                    await _send("observation", ui_observation_text if ui_observation_text is not None else observation_text)
                    # Abortable sleep — exits within 0.5 s if abort fires
                    try:
                        await _abortable(asyncio.sleep(2))
                    except asyncio.CancelledError:
                        await _send("aborted", "Agent stopped by abort signal.")
                        messages.append({"role": "user", "content": tool_results_content})
                        return

                    _drain_abort()
                    if abort_event.is_set():
                        await _send("aborted", "Agent stopped mid-turn by abort signal.")
                        messages.append({
                            "role": "user",
                            "content": tool_results_content
                        })
                        return

                messages.append({
                    "role": "user",
                    "content": tool_results_content
                })

            # ── Case 2: LLM ended turn without calling a tool ─────────────────
            # Violation of rule #1 in the system prompt. Nudge it back.
            else:
                text_content = next(
                    (b.text for b in response.content if b.type == "text"),
                    "(no text)"
                )
                messages.append({
                    "role": "user",
                    "content": (
                        "You ended your turn without calling a tool, which violates your instructions. "
                        "You must always call a tool. "
                        "If finished: call submit_comparison. "
                        "If stuck or CAPTCHA: call ask_human. "
                        "Otherwise: continue with the next step."
                    )
                })
                await _send(
                    "thought",
                    f"Agent produced text without a tool call — nudging back. Text: \"{text_content[:120]}\""
                )
                # No sleep — nudge immediately

        except asyncio.CancelledError:
            # Safety net: if CancelledError propagates past inner handlers,
            # catch it here instead of letting ASGI see an unhandled BaseException.
            await _send("aborted", "Agent stopped by abort signal.")
            return

        except Exception as e:
            import traceback
            traceback.print_exc()
            await _send("error", f"Agent loop exception: {e}")
            return
