import json
import asyncio
from datetime import datetime, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

app = FastAPI(title="Real Estate Agent Mock Server")

def get_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()

# Hardcoded sequence of events to simulate a realistic run,
# including a pause, a few screenshots, and a final listing submission.
MOCK_EVENTS = [
    {"type": "thought", "payload": "Initializing browser session..."},
    {"type": "thought", "payload": "Starting agent with goal: Find me a 2BR under $2000/month in Richardson, TX"},
    {"type": "action", "payload": "Tool call: navigate with input: {\"url\": \"https://www.redfin.com\"}"},
    {"type": "observation", "payload": "Navigated to https://www.redfin.com"},
    # We will simulate screenshots as tiny blank base64s or just skip them for the mock to keep it light, 
    # but the frontend needs to handle them. Let's send a minimal valid base64 transparent gif.
    {"type": "screenshot", "payload": "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"},
    {"type": "thought", "payload": "Thinking about next action..."},
    {"type": "action", "payload": "Tool call: search with input: {\"query\": \"Richardson TX\"}"},
    {"type": "observation", "payload": "Search returned an error from Redfin: 'An error occurred while searching. Please try again later.' The site may be rate-limiting. Use ask_human to pause."},
    {"type": "screenshot", "payload": "R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw=="},
    {"type": "thought", "payload": "Thinking about next action..."},
    {"type": "action", "payload": "Tool call: ask_human with input: {\"question\": \"The site seems to be rate-limiting us. Should I try Craigslist instead?\"}"},
    {"type": "waiting_for_user", "payload": "The site seems to be rate-limiting us. Should I try Craigslist instead?"},
    # The loop will PAUSE here until it receives a user_response.
    {"type": "thought", "payload": "Human responded: Yes, go to Craigslist."},
    {"type": "action", "payload": "Tool call: navigate with input: {\"url\": \"https://dallas.craigslist.org/search/apa?query=richardson\"}"},
    {"type": "observation", "payload": "Navigated to https://dallas.craigslist.org/search/apa?query=richardson"},
    {"type": "screenshot", "payload": "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"},
    {"type": "thought", "payload": "Thinking about next action..."},
    {"type": "action", "payload": "Tool call: extract_listing_details with input: {}"},
    {"type": "observation", "payload": "Extracted (Craigslist):\n{\n  \"price\": 1850,\n  \"beds\": 2,\n  \"baths\": 2.0,\n  \"sqft\": 1100,\n  \"address\": \"123 Main St, Richardson, TX\",\n  \"amenities\": \"Pool, Gym, In-unit Laundry\",\n  \"photos\": \"https://picsum.photos/400/300\",\n  \"floorplan\": \"not found\",\n  \"source\": \"craigslist\"\n}"},
    {"type": "screenshot", "payload": "R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw=="},
    {"type": "thought", "payload": "Thinking about next action..."},
    {"type": "action", "payload": "Tool call: submit_comparison with input: {...}"},
    {"type": "done", "payload": {
        "listings": [
            {
                "source": "craigslist",
                "price": 1850,
                "beds": 2,
                "baths": 2,
                "sqft": 1100,
                "address": "123 Main St, Richardson, TX",
                "amenities": "Pool, Gym, In-unit Laundry",
                "photos": [
                    "https://picsum.photos/800/600?random=1", 
                    "https://picsum.photos/800/600?random=2", 
                    "https://picsum.photos/800/600?random=3"
                ],
                "floorplan": "not found",
                "nearby_places": [
                    {
                        "category": "schools",
                        "amenities": [
                            {"name": "Richardson High", "distance_miles": 0.5}, 
                            {"name": "Richardson Middle", "distance_miles": 0.8}
                        ],
                        "data_source": "live"
                    },
                    {
                        "category": "gyms",
                        "amenities": [
                            {"name": "24 Hour Fitness", "distance_miles": 1.2}
                        ],
                        "data_source": "live"
                    },
                    {
                        "category": "stores",
                        "amenities": [],
                        "error": "Amenity data unavailable",
                        "data_source": "fallback_unavailable"
                    }
                ],
                "commute": {
                    "to": "Downtown Dallas",
                    "distance_miles": 14.5,
                    "duration_minutes": 22,
                    "data_source": "live"
                }
            }
        ],
        "summary": "I found a great 2BR/2BA apartment in Richardson for $1,850/mo. It has 1,100 sqft, making it a solid value at $1.68/sqft. It includes a pool, gym, and in-unit laundry."
    }}
]

@app.websocket("/ws/agent")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("Client connected to mock server.")

    try:
        while True:
            # Wait for goal
            raw = await websocket.receive_text()
            cmd = json.loads(raw)
            
            if cmd.get("action") == "start_agent":
                goal = cmd.get("goal", "Test goal")
                
                # Play back the mocked events with realistic delays
                for event in MOCK_EVENTS:
                    event["timestamp"] = get_timestamp()
                    await websocket.send_json(event)
                    
                    if event["type"] == "waiting_for_user":
                        # Block until we receive a human response
                        print("Waiting for human response...")
                        while True:
                            resp_raw = await websocket.receive_text()
                            resp_cmd = json.loads(resp_raw)
                            if resp_cmd.get("action") == "user_response":
                                print(f"Received from human: {resp_cmd.get('response')}")
                                break
                            elif resp_cmd.get("action") == "abort":
                                await websocket.send_json({"type": "aborted", "payload": "Aborted.", "timestamp": get_timestamp()})
                                return
                    
                    # 1.5s delay between events to simulate thinking/network
                    await asyncio.sleep(1.5)

            elif cmd.get("action") == "abort":
                await websocket.send_json({"type": "aborted", "payload": "Aborted.", "timestamp": get_timestamp()})
                
    except WebSocketDisconnect:
        print("Client disconnected.")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8006)
