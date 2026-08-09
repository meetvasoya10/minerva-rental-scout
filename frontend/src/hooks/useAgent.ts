import { useState, useEffect, useCallback, useRef, useMemo } from 'react';

export type AgentEvent = {
  type: string;
  payload: any;
  timestamp: string;
};

// One result entry inside an amenity category
export type AmenityResult = { name: string; distance_miles: number };

// A single category inside an amenity group (e.g. 'schools')
export type AmenityCategory = {
  category: string;
  results: AmenityResult[];
  error?: string;
  data_source?: string;
};

// A grouped amenity block for one listing address
export type AmenityGroup = {
  _type: 'amenity_group';
  address: string;          // normalised address used as key
  displayAddress: string;   // original address string for display
  categories: AmenityCategory[];
  inProgress: boolean;      // true while more calls may come in
  timestamp: string;
};

// Union type for the display list
export type DisplayEvent = AgentEvent | AmenityGroup;

export type Listing = {
  source: string;
  price: number;
  beds: number;
  baths: number;
  sqft: number;
  address: string;
  amenities: string;
  photos: string;
  floorplan: string;
};

export type AppState = 'IDLE' | 'STARTING' | 'RUNNING' | 'PAUSED' | 'COMPLETED' | 'ERROR';

export function useAgent(url: string) {
  const [appState, setAppState] = useState<AppState>('IDLE');
  const [isConnected, setIsConnected] = useState(false);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [latestScreenshot, setLatestScreenshot] = useState<string | null>(null);
  const [humanPrompt, setHumanPrompt] = useState('');
  const [finalResult, setFinalResult] = useState<{listings: Listing[], summary: string} | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Mutable ref map: normalised address → AmenityGroup
  // We keep this in a ref (not state) so mutations don't trigger full re-renders;
  // the displayEvents memo below recalculates whenever `events` changes.
  const amenityGroupsRef = useRef<Map<string, AmenityGroup>>(new Map());
  
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => setIsConnected(true);
    ws.onclose = () => {
      setIsConnected(false);
      if (appState === 'RUNNING' || appState === 'STARTING' || appState === 'PAUSED') {
        setAppState('ERROR');
        setErrorMessage('WebSocket connection closed unexpectedly.');
      }
    };

    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        
        if (data.type === 'screenshot') {
          setLatestScreenshot(`data:image/jpeg;base64,${data.payload}`);
          return;
        }

        if (data.type === 'error') {
          setAppState('ERROR');
          setErrorMessage(data.payload);
          return;
        }

        // ── Amenity grouping ──────────────────────────────────────────────
        // Intercept get_nearby_amenities action+observation pairs and merge
        // them into AmenityGroup objects in the amenityGroupsRef map.
        // We still push them into the raw events array for the state machine,
        // but the displayEvents memo will suppress individual action/obs events
        // that belong to an amenity group and replace them with the group entry.

        if (data.type === 'action' && typeof data.payload === 'string'
            && data.payload.startsWith('Tool call: get_nearby_amenities')) {
          try {
            const match = data.payload.match(/Tool call: get_nearby_amenities with input: (.+)/);
            if (match) {
              const input = JSON.parse(match[1]);
              const addr: string = (input.address || '').trim();
              const normKey = addr.toLowerCase();
              if (addr && !amenityGroupsRef.current.has(normKey)) {
                amenityGroupsRef.current.set(normKey, {
                  _type: 'amenity_group',
                  address: normKey,
                  displayAddress: addr,
                  categories: [],
                  inProgress: true,
                  timestamp: data.timestamp,
                });
              }
            }
          } catch { /* ignore parse failures */ }
        }

        if (data.type === 'observation') {
          // Try to match this observation to the most recent pending amenity group
          // by looking backwards through events for the most recent get_nearby_amenities action
          try {
            const parsed = JSON.parse(data.payload);
            if (parsed && typeof parsed === 'object' && parsed.address) {
              const normKey = (parsed.address as string).toLowerCase();
              const group = amenityGroupsRef.current.get(normKey);
              if (group) {
                // ── Canonical key for dedup ───────────────────────────────
                // The LLM sometimes calls get_nearby_amenities with a full
                // landmark name (e.g. "Plano West Senior High School") AND
                // separately with "schools". Both must map to the same slot.
                const canonKey = (raw: string): string => {
                  const s = (raw || '').toLowerCase();
                  if (s === 'school' || s === 'schools') return 'schools';
                  if (['grocery', 'grocery store', 'grocery stores', 'store', 'stores',
                       'supermarket', 'grocer', 'groceries'].includes(s)) return 'grocery stores';
                  if (['gym', 'gyms', 'fitness', 'fitness centre', 'fitness center'].includes(s)) return 'gyms';
                  // Named landmark / commute — don't add as a display category
                  return '__commute__';
                };

                const incomingKey = canonKey(parsed.category || '');

                // Skip landmark/commute observations — they don't belong in the
                // category list (they render as commute cards via a separate path)
                if (incomingKey === '__commute__') {
                  // still push the raw event so the rest of the pipeline sees it
                } else {
                  const cat: AmenityCategory = {
                    category: incomingKey,      // always store the canonical form
                    results: Array.isArray(parsed.amenities)
                      ? parsed.amenities.map((a: any) => ({ name: a.name, distance_miles: a.distance_miles }))
                      : [],
                    error: parsed.error,
                    data_source: parsed.data_source,
                  };
                  const idx = group.categories.findIndex(c => c.category === incomingKey);
                  if (idx >= 0) group.categories[idx] = cat;   // update existing slot
                  else group.categories.push(cat);             // new canonical category
                }

                // Mark complete once all 3 standard categories have arrived
                if (group.categories.length >= 3) {
                  group.inProgress = false;
                }
              }
            }
          } catch { /* not an amenity observation */ }
        }

        // Handle side-effects (other state updates) before the main state transition
        if (data.type === 'waiting_for_user') {
          setHumanPrompt(data.payload);
        } else if (data.type === 'done') {
          console.log("== DONE EVENT RECEIVED ==");
          console.log("Payload:", data.payload);
          console.log("Type of payload:", typeof data.payload);
          if (typeof data.payload === 'object' && data.payload.listings) {
            console.log("Setting final result!");
            setFinalResult(data.payload);
          } else {
            console.warn("Payload is missing listings!", data.payload);
          }
        }

        // Trim massive payloads before storing in the events array to prevent memory leaks
        let eventToStore = data;
        if (data.type === 'observation' && typeof data.payload === 'string' && data.payload.length > 500) {
          try {
            const parsed = JSON.parse(data.payload);
            if (parsed && typeof parsed === 'object' && parsed.address) {
              // Preserve enough fields so `displayEvents` suppression and `EventCard` formatting still work
              eventToStore = { 
                ...data, 
                payload: JSON.stringify({ 
                  address: parsed.address,
                  data_source: parsed.data_source,
                  distance_miles: parsed.distance_miles,
                  amenities: [], // Empty the heavy arrays
                  trimmed: true 
                }) 
              };
            } else if (data.payload.startsWith('[\n  {')) {
              // Preserve start for formatPayload matching
              eventToStore = { ...data, payload: '[\n  {\n    "trimmed": true\n  }\n]' };
            } else {
              eventToStore = { ...data, payload: data.payload.substring(0, 500) + '... [trimmed]' };
            }
          } catch {
            eventToStore = { ...data, payload: data.payload.substring(0, 500) + '... [trimmed]' };
          }
        } else if (data.type === 'done' && typeof data.payload === 'object') {
          // finalResult already holds the full payload, so we don't need it in the trace events list
          eventToStore = { ...data, payload: { trimmed: true } };
        }

        if (eventToStore !== data) {
          const originalLen = typeof data.payload === 'string' ? data.payload.length : JSON.stringify(data.payload).length;
          const trimmedLen = typeof eventToStore.payload === 'string' ? eventToStore.payload.length : JSON.stringify(eventToStore.payload).length;
          console.log(`[TRIMMED] Type: ${data.type} | Original Length: ${originalLen} -> Trimmed Length: ${trimmedLen}`);
        }

        setEvents((prev) => [...prev, eventToStore]);

        // Transition states based on events
        setAppState((current) => {
          if (data.type === 'thought' && current === 'STARTING') {
            return 'RUNNING';
          }
          if (data.type === 'waiting_for_user') {
            return 'PAUSED';
          }
          if (data.type === 'done') {
            return 'COMPLETED';
          }
          if (data.type === 'aborted') {
            // User aborted. Let's go to IDLE so they can start again.
            return 'IDLE';
          }
          return current;
        });

      } catch (e) {
        console.error('Failed to parse WS message', e);
      }
    };

    return () => {
      ws.close();
    };
  }, [url]);

  // ── Display events ────────────────────────────────────────────────────────
  // Build a de-noised event list:
  //  • get_nearby_amenities action events → suppressed (rolled into group)
  //  • observation events that are amenity JSON → suppressed (rolled into group)
  //  • The first action event for a new address inserts the AmenityGroup sentinel
  //  • All other events pass through unchanged
  const displayEvents: DisplayEvent[] = useMemo(() => {
    const result: DisplayEvent[] = [];
    const insertedGroups = new Set<string>();

    for (const evt of events) {
      // Amenity action — swap for (or insert) the group entry
      if (evt.type === 'action' && typeof evt.payload === 'string'
          && evt.payload.startsWith('Tool call: get_nearby_amenities')) {
        try {
          const match = evt.payload.match(/Tool call: get_nearby_amenities with input: (.+)/);
          if (match) {
            const input = JSON.parse(match[1]);
            const normKey = (input.address || '').trim().toLowerCase();
            const group = amenityGroupsRef.current.get(normKey);
            if (group && !insertedGroups.has(normKey)) {
              result.push(group);
              insertedGroups.add(normKey);
            }
            // Always skip the raw action event itself
            continue;
          }
        } catch { /* fall through and keep event */ }
      }

      // Amenity observation (JSON with address field) — suppress
      if (evt.type === 'observation' && typeof evt.payload === 'string') {
        try {
          const parsed = JSON.parse(evt.payload);
          if (parsed && typeof parsed === 'object' && parsed.address) {
            const normKey = (parsed.address as string).toLowerCase();
            if (amenityGroupsRef.current.has(normKey)) {
              continue; // suppress — it's already reflected in the group
            }
          }
        } catch { /* not JSON, keep event */ }
      }

      result.push(evt);
    }

    // Mark any remaining in-progress groups as complete once the run has
    // no further get_nearby_amenities actions outstanding (belt-and-suspenders
    // for the case where the agent calls fewer than 3 categories).
    const hasRunningAmenityAction = events.some(
      e => e.type === 'action' && typeof e.payload === 'string'
        && e.payload.startsWith('Tool call: get_nearby_amenities')
    );
    // Only mark done if a subsequent non-amenity event has arrived,
    // meaning the last amenity observation has already been processed.
    const lastEvent = events[events.length - 1];
    const lastIsAmenityObs = lastEvent?.type === 'observation' && (() => {
      try {
        const p = JSON.parse(lastEvent.payload);
        return !!(p?.address);
      } catch { return false; }
    })();
    if (!hasRunningAmenityAction && !lastIsAmenityObs) {
      amenityGroupsRef.current.forEach(g => { g.inProgress = false; });
    }

    return result;
  }, [events]);

  const sendCommand = useCallback((cmd: any) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(cmd));
    } else {
      setAppState('ERROR');
      setErrorMessage('Not connected to server.');
    }
  }, []);

  const startAgent = useCallback((goal: string) => {
    setAppState('STARTING');
    setEvents([]);
    setLatestScreenshot(null);
    setFinalResult(null);
    setErrorMessage(null);
    amenityGroupsRef.current.clear();
    sendCommand({ action: 'start_agent', goal });
  }, [sendCommand]);

  const abortAgent = useCallback(() => {
    // Only send the signal — do NOT flip state here.
    // The backend will send back an "aborted" event once the loop actually
    // exits, and the onmessage handler already maps that to IDLE (line ~184).
    // Flipping early made the UI lie while the backend was still running.
    sendCommand({ action: 'abort' });
  }, [sendCommand]);

  const sendHumanResponse = useCallback((response: string) => {
    sendCommand({ action: 'user_response', response });
    setAppState('RUNNING');
  }, [sendCommand]);

  return {
    appState,
    isConnected,
    events,
    displayEvents,
    latestScreenshot,
    humanPrompt,
    finalResult,
    errorMessage,
    startAgent,
    abortAgent,
    sendHumanResponse,
  };
}
