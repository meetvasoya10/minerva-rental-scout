import os
import requests
import json
import time
import math
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(current_dir, ".env"))

LOCATIONIQ_API_KEY = os.getenv("LOCATIONIQ_API_KEY")

_GEOCODE_CACHE = {}
_AMENITY_CACHE = {}
LAST_API_CALL = 0

def _rate_limit():
    global LAST_API_CALL
    now = time.time()
    elapsed = now - LAST_API_CALL
    if elapsed < 2.0:
        time.sleep(2.0 - elapsed)
    LAST_API_CALL = time.time()

def geocode_address(address: str) -> tuple[float, float]:
    """Geocode an address to lat/lng using LocationIQ exclusively."""
    if address in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[address]

    if not LOCATIONIQ_API_KEY:
        print("Error: LOCATIONIQ_API_KEY is not set.")
        return None, None

    import urllib.parse
    _rate_limit()
    quoted_addr = urllib.parse.quote(address)
    url = f"https://us1.locationiq.com/v1/search?key={LOCATIONIQ_API_KEY}&q={quoted_addr}&format=json"
    
    for attempt in range(2):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if data:
                        res = float(data[0]["lat"]), float(data[0]["lon"])
                        _GEOCODE_CACHE[address] = res
                        return res
                except Exception as e:
                    print(f"LocationIQ geocode JSON error: {e}. Status: {resp.status_code}, Body: {resp.text[:200]}")
            else:
                print(f"LocationIQ blocked/failed (attempt {attempt+1}): HTTP {resp.status_code} - {resp.text[:100]}")
                if resp.status_code == 429 and attempt == 0:
                    time.sleep(2.0)
                    continue
        except Exception as e:
            print(f"LocationIQ error (attempt {attempt+1}): {e}")
            if attempt == 0:
                time.sleep(2.0)
                continue
        break
        
    return None, None

US_STATES = {
    'alabama': 'al', 'alaska': 'ak', 'arizona': 'az', 'arkansas': 'ar', 'california': 'ca', 
    'colorado': 'co', 'connecticut': 'ct', 'delaware': 'de', 'florida': 'fl', 'georgia': 'ga', 
    'hawaii': 'hi', 'idaho': 'id', 'illinois': 'il', 'indiana': 'in', 'iowa': 'ia', 
    'kansas': 'ks', 'kentucky': 'ky', 'louisiana': 'la', 'maine': 'me', 'maryland': 'md', 
    'massachusetts': 'ma', 'michigan': 'mi', 'minnesota': 'mn', 'mississippi': 'ms', 'missouri': 'mo', 
    'montana': 'mt', 'nebraska': 'ne', 'nevada': 'nv', 'new hampshire': 'nh', 'new jersey': 'nj', 
    'new mexico': 'nm', 'new york': 'ny', 'north carolina': 'nc', 'north dakota': 'nd', 'ohio': 'oh', 
    'oklahoma': 'ok', 'oregon': 'or', 'pennsylvania': 'pa', 'rhode island': 'ri', 'south carolina': 'sc', 
    'south dakota': 'sd', 'tennessee': 'tn', 'texas': 'tx', 'utah': 'ut', 'vermont': 'vt', 
    'virginia': 'va', 'washington': 'wa', 'west virginia': 'wv', 'wisconsin': 'wi', 'wyoming': 'wy',
    'district of columbia': 'dc'
}

def resolve_location(address: str) -> tuple[str, str, str]:
    """Geocode a location string to get a clean city and state slug for URLs.
    Returns (city_slug, state_slug, raw_city). E.g. ('los-angeles', 'ca', 'Los Angeles').
    Returns (None, None, None) if resolution fails.
    """
    if not LOCATIONIQ_API_KEY:
        print("Error: LOCATIONIQ_API_KEY is not set.")
        return None, None, None

    _rate_limit()
    url = f"https://us1.locationiq.com/v1/search?key={LOCATIONIQ_API_KEY}&q={address}&format=json&addressdetails=1"
    try:
        resp = requests.get(url)
        if resp.status_code == 200:
            try:
                data = resp.json()
                if data and len(data) > 0:
                    addr_details = data[0].get("address", {})
                    # Try city, then town, then village
                    city = addr_details.get("city") or addr_details.get("town") or addr_details.get("village")
                    state = addr_details.get("state")
                    
                    if not city or not state:
                        return None, None, None
                        
                    city_slug = city.lower().replace(" ", "-")
                    state_slug = US_STATES.get(state.lower(), "")
                    
                    if not state_slug:
                        return None, None, None
                        
                    return city_slug, state_slug, city
            except Exception as e:
                print(f"LocationIQ geocode JSON error: {e}")
        else:
            print(f"LocationIQ blocked/failed: HTTP {resp.status_code}")
    except Exception as e:
        print(f"LocationIQ error: {e}")
        
    return None, None, None

def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate straight-line distance in miles between two coordinates."""
    # Haversine formula
    R = 3958.8  # Radius of earth in miles
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) * math.sin(dlat / 2) + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) * math.sin(dlng / 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def calculate_commute_distance(address1: str, address2: str) -> dict:
    """Calculate driving distance and time between two addresses/landmarks."""
    lat1, lng1 = geocode_address(address1)
    lat2, lng2 = geocode_address(address2)
    
    if not lat1 or not lat2:
        return {
            "from": address1, 
            "to": address2, 
            "error": "Geocoding failed (API block or unavailable)",
            "data_source": "fallback_unavailable"
        }
        
    if not LOCATIONIQ_API_KEY:
        return {
            "from": address1,
            "to": address2,
            "error": "API key not set",
            "data_source": "fallback_unavailable"
        }
        
    _rate_limit()
    url = f"https://us1.locationiq.com/v1/directions/driving/{lng1},{lat1};{lng2},{lat2}?key={LOCATIONIQ_API_KEY}&overview=false"
    
    for attempt in range(2):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                routes = data.get("routes", [])
                if routes:
                    route = routes[0]
                    dist_meters = route.get("distance", 0)
                    dur_seconds = route.get("duration", 0)
                    
                    dist_miles = dist_meters * 0.000621371
                    dur_minutes = dur_seconds / 60.0
                    
                    return {
                        "from": address1,
                        "to": address2,
                        "distance_miles": round(dist_miles, 2),
                        "duration_minutes": int(round(dur_minutes)),
                        "data_source": "live"
                    }
                break # Success but no routes, don't retry
            else:
                print(f"LocationIQ directions blocked/failed (attempt {attempt+1}): HTTP {resp.status_code}")
                if resp.status_code == 429 and attempt == 0:
                    time.sleep(2.0)
                    continue
                break
        except Exception as e:
            print(f"LocationIQ directions error (attempt {attempt+1}): {e}")
            if attempt == 0:
                time.sleep(2.0)
                continue
            break

    # Fallback to haversine if driving directions fail
    dist = calculate_distance(lat1, lng1, lat2, lng2)
    return {
        "from": address1,
        "to": address2,
        "distance_miles": round(dist, 2),
        "duration_minutes": None,
        "data_source": "fallback_haversine"
    }

def get_nearby_amenities(address: str, category: str, radius_meters: int = 2000) -> dict:
    """Find nearby amenities using LocationIQ API.

    Routing:
      - category is a known generic type  → amenity search (schools/stores/gyms)
      - category is a named POI/landmark  → calculate_commute_distance

    The old logic used substring match ("school" in category) which caused
    named landmarks like "Plano West Senior High School" to be misrouted into
    the amenity search path because they happen to contain the word "school".
    Whitelist routing is strictly safer.
    """
    cat_lower = (category or '').lower().strip()

    # ── Whitelist of known generic amenity category keywords ────────────────
    SCHOOL_KEYS  = {'school', 'schools'}
    GROCERY_KEYS = {'grocery', 'grocery store', 'grocery stores', 'store', 'stores',
                    'supermarket', 'supermarkets', 'grocer', 'groceries'}
    GYM_KEYS     = {'gym', 'gyms', 'fitness', 'fitness centre', 'fitness center'}

    is_schools  = cat_lower in SCHOOL_KEYS
    is_grocery  = cat_lower in GROCERY_KEYS
    is_gym      = cat_lower in GYM_KEYS
    is_amenity  = is_schools or is_grocery or is_gym

    if not is_amenity:
        # Named landmark, workplace, or unknown category → commute distance
        print(f"[places] '{category}' is not a generic category — routing to commute distance")
        return calculate_commute_distance(address, category)

    lat, lng = geocode_address(address)
    if not lat or not lng:
        return {
            "address": address,
            "category": category,
            "error": "Geocoding failed (API block or unavailable)",
            "data_source": "fallback_unavailable"
        }

    cache_key = f"{lat},{lng},{cat_lower}"
    if cache_key in _AMENITY_CACHE:
        return _AMENITY_CACHE[cache_key]

    if not LOCATIONIQ_API_KEY:
        print("Error: LOCATIONIQ_API_KEY is not set.")
        return {
            "address": address,
            "category": category,
            "lat": lat,
            "lng": lng,
            "error": "API key not set",
            "data_source": "fallback_unavailable"
        }

    results = []
    _rate_limit()

    # Map to LocationIQ OSM tag
    if is_schools:
        tag = "amenity:school"
    elif is_grocery:
        tag = "shop:supermarket"
    else:  # gym/fitness
        tag = "leisure:fitness_centre"
    
    # The /v1/nearby endpoint params: key, lat, lon, tag, radius, format
    url = f"https://us1.locationiq.com/v1/nearby?key={LOCATIONIQ_API_KEY}&lat={lat}&lon={lng}&tag={tag}&radius={radius_meters}&format=json"
    
    data_source = "live"
    for attempt in range(2):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    for r in data:
                        name = r.get("name")
                        if not name or not name.strip() or name == "Unknown Name":
                            continue
                            
                        # Use LocationIQ's native 'distance' field (in meters) if available
                        raw_dist = r.get("distance")
                        if raw_dist is not None:
                            dist = float(raw_dist) * 0.000621371
                        else:
                            plat = float(r.get("lat", 0))
                            plng = float(r.get("lon", 0))
                            dist = calculate_distance(lat, lng, plat, plng) if plat and plng else 0
                            
                        # LOG FOR DEBUGGING
                        print(f"[DEBUG-DISTANCE] Parsed amenity '{name}': raw_distance={raw_dist}, calculated_dist_miles={dist}")
                        
                        results.append({
                            "name": name,
                            "distance_miles": round(dist, 2) if dist else 0
                        })
                        
                        if len(results) >= 3:
                            break
                    data_source = "live"
                    break # Success, exit retry loop
                except Exception as e:
                    print(f"LocationIQ nearby JSON error: {e}. Status: {resp.status_code}, Body: {resp.text[:200]}")
                    data_source = "fallback_unavailable"
                    break # JSON parse error, no retry
            else:
                print(f"LocationIQ nearby blocked/failed (attempt {attempt+1}): HTTP {resp.status_code} - {resp.text[:100]}")
                data_source = "fallback_unavailable"
                if resp.status_code == 429 and attempt == 0:
                    time.sleep(2.0)
                    continue
                break # other HTTP error, no retry
        except Exception as e:
            print(f"LocationIQ nearby error (attempt {attempt+1}): {e}")
            data_source = "fallback_unavailable"
            if attempt == 0:
                time.sleep(2.0)
                continue
            break
        
    res = {
        "address": address,
        "category": category,
        "lat": lat,
        "lng": lng,
        "amenities": results,
        "data_source": data_source
    }
    _AMENITY_CACHE[cache_key] = res
    return res
