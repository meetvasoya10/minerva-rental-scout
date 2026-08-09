import base64
import re
import json
import os
import time
from playwright.async_api import async_playwright, Browser, Page, Playwright
from places import resolve_location

class BrowserSession:
    def __init__(self):
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.page: Page | None = None

    async def start(self):
        self.playwright = await async_playwright().start()
        # Default to headless=True for production, but allow HEADLESS=false for local visual debugging
        is_headless = os.getenv("HEADLESS", "true").lower() == "true"
        self.browser = await self.playwright.chromium.launch(headless=is_headless)
        self.page = await self.browser.new_page()
        self.cdp_client = None

    async def start_screencast(self, frame_callback):
        if not self.page:
            return
            
        if self.cdp_client:
            return
            
        import asyncio
        self.cdp_client = await self.page.context.new_cdp_session(self.page)
        
        async def handle_frame(event):
            session_id = event.get("sessionId")
            data = event.get("data")
            
            if frame_callback:
                asyncio.create_task(frame_callback(data))
                
            await self.cdp_client.send("Page.screencastFrameAck", {"sessionId": session_id})
            
        self.cdp_client.on("Page.screencastFrame", handle_frame)
        await self.cdp_client.send("Page.startScreencast", {
            "format": "jpeg",
            "quality": 75,
            "everyNthFrame": 1
        })

    async def navigate(self, url: str):
        if not self.page:
            raise RuntimeError("Browser session not started")
        await self.page.goto(url, wait_until="domcontentloaded")

    async def get_screenshot_base64(self) -> str:
        if not self.page:
            raise RuntimeError("Browser session not started")
        # Lower quality JPEG for faster WebSocket transmission
        screenshot_bytes = await self.page.screenshot(type="jpeg", quality=60)
        return base64.b64encode(screenshot_bytes).decode("utf-8")

    async def close(self):
        try:
            if self.page:
                await self.page.close()
        except Exception:
            pass
            
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
            
        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass

    async def execute_redfin_search(self, query: str) -> str:
        if not self.page:
            return "Error: Browser session not started"
            
        try:
            # Robust locators for search input (avoids fragile CSS class names)
            search_box = self.page.locator("input[type='search'], input[title*='City'], input[placeholder*='City']").first
            await search_box.fill(query)
            await search_box.press("Enter")
            
            # Wait for either: results container OR Redfin's own error banner.
            # This prevents clicking on a still-loading or broken page.
            try:
                await self.page.wait_for_selector(
                    ".HomeCardsContainer, .homes.summary.row, [data-rf-test-id='homes-description'], .errorMessage, .Alert--error",
                    timeout=12000
                )
            except Exception:
                # Selector didn't appear within 12s — fall back to network idle
                await self.page.wait_for_load_state("networkidle", timeout=15000)
            
            # Check if Redfin returned an error page
            error_el = self.page.locator(".errorMessage, .Alert--error, :text('error occurred'), :text('try again')")
            try:
                error_count = await error_el.count()
                if error_count > 0:
                    error_text = await error_el.first.text_content(timeout=2000)
                    return f"Search returned an error from Redfin: '{error_text.strip()}'. The site may be rate-limiting. Use ask_human to pause."
            except Exception:
                pass
            
            return f"Successfully typed '{query}' into search bar and pressed Enter. Results page has loaded."
        except Exception as e:
            return f"Search failed: {str(e)}"

    async def extract_redfin_details(self) -> dict:
        if not self.page:
            return {"error": "Browser session not started"}
            
        # Graceful degradation pattern: default to "not found"
        data = {
            "price": "not found",
            "beds": "not found",
            "baths": "not found",
            "sqft": "not found",
            "address": "not found",
            "amenities": "not found",
            "photos": [],
            "floorplan": "not found"
        }
        
        # Helper to safely extract text with a short timeout
        async def safe_extract(locator) -> str:
            try:
                text = await locator.text_content(timeout=1000)
                return " ".join(text.split()) if text else "not found"
            except:
                return "not found"
                
        try:
            # Price
            data["price"] = await safe_extract(self.page.locator("[data-rf-test-id='abp-price']"))
            if data["price"] == "not found":
                data["price"] = await safe_extract(self.page.locator("div:has-text('Price') + div, .statsValue").first)

            # Beds/Baths/Sqft
            data["beds"] = await safe_extract(self.page.locator("[data-rf-test-id='abp-beds']"))
            data["baths"] = await safe_extract(self.page.locator("[data-rf-test-id='abp-baths']"))
            data["sqft"] = await safe_extract(self.page.locator("[data-rf-test-id='abp-sqFt']"))

            # Address (usually the main H1 on the page)
            data["address"] = await safe_extract(self.page.locator("h1").first)
            
            # Amenities (often in a container or list)
            amenities = await safe_extract(self.page.locator(".amenities-container, [data-rf-test-id='amenities']").first)
            if amenities != "not found":
                data["amenities"] = amenities[:150] + "..." # truncate for brevity

            # Photos
            try:
                imgs = await self.page.locator("img").all()
                photos = []
                for img in imgs:
                    src = await img.get_attribute("src")
                    if src and src not in photos:
                        photos.append(src)
                data["photos"] = photos[:10] if photos else []
            except: pass
            
            # Floorplan explicitly checked
            try:
                has_floorplan = await self.page.locator("text='Floorplan', text='Floor Plan'").count()
                data["floorplan"] = "found" if has_floorplan > 0 else "not found"
            except: pass

        except Exception as e:
            # If the entire extraction process hits a critical error, we still return what we got
            print(f"Critical extraction error: {e}")
            
        return self._normalize_listing_data(data)

    async def execute_craigslist_search(self, query: str) -> str:
        if not self.page:
            return "Error: Browser session not started"
            
        try:
            search_box = self.page.locator("input#query, input[name='query']").first
            await search_box.fill(query)
            await search_box.press("Enter")
            await self.page.wait_for_load_state("domcontentloaded")
            return f"Successfully typed '{query}' into Craigslist search bar and pressed Enter."
        except Exception as e:
            return f"Search failed: {str(e)}"

    async def extract_craigslist_details(self) -> dict:
        if not self.page:
            return {"error": "Browser session not started"}
            
        # Ensure identical normalized schema shape
        data = {
            "price": "not found",
            "beds": "not found",
            "baths": "not found",
            "sqft": "not found",
            "address": "not found",
            "amenities": "not found",
            "photos": [],
            "floorplan": "not found",
            "url": self.page.url if self.page else "not found"
        }
        
        async def safe_extract(locator) -> str:
            try:
                text = await locator.text_content(timeout=1000)
                return " ".join(text.split()) if text else "not found"
            except:
                return "not found"
                
        try:
            # Price
            data["price"] = await safe_extract(self.page.locator(".price").first)
            
            # Attributes (Beds, Baths, Sqft are bundled in .attrgroup)
            try:
                attrgroups = await self.page.locator(".attrgroup span").all_text_contents()
                amenities_list = []
                for attr in attrgroups:
                    attr_lower = attr.lower()
                    if "br " in attr_lower or "ba " in attr_lower:
                        parts = attr.split("/")
                        for part in parts:
                            p = part.strip().lower()
                            if "br" in p: data["beds"] = part.strip()
                            elif "ba" in p: data["baths"] = part.strip()
                    elif "ft2" in attr_lower or "sqft" in attr_lower:
                        data["sqft"] = attr.strip()
                    else:
                        amenities_list.append(attr.strip())
                
                if amenities_list:
                    data["amenities"] = ", ".join(amenities_list)[:150] + ("..." if len(", ".join(amenities_list)) > 150 else "")
            except: pass
            
            # Address
            data["address"] = await safe_extract(self.page.locator("div.mapaddress").first)
            if data["address"] == "not found":
                data["address"] = await safe_extract(self.page.locator(".postingtitletext small").first)
                
            # Photos
            try:
                imgs = await self.page.locator("#thumbs a, .swipe-wrap img").all()
                photos = []
                for img in imgs:
                    src = await img.get_attribute("href") or await img.get_attribute("src")
                    if src and src not in photos:
                        photos.append(src)
                if not photos:
                    first_img = await self.page.locator("img").first.get_attribute("src", timeout=1000)
                    if first_img: photos.append(first_img)
                data["photos"] = photos if photos else []
            except: pass
            
            # Floorplan
            try:
                body_text = await self.page.locator("#postingbody").text_content(timeout=1000)
                if body_text and "floorplan" in body_text.lower():
                    data["floorplan"] = "mentioned in description"
            except: pass

        except Exception as e:
            print(f"Critical extraction error (Craigslist): {e}")
            
        return self._normalize_listing_data(data)

    async def extract_padmapper_details(self) -> dict:
        if not self.page:
            return {"error": "Browser session not started"}
            
        data = {
            "price": "not found",
            "beds": "not found",
            "baths": "not found",
            "sqft": "not found",
            "address": "not found",
            "amenities": "not found",
            "photos": [],
            "floorplan": "not found",
            "url": self.page.url if self.page else "not found"
        }
        
        async def safe_extract(locator) -> str:
            try:
                text = await locator.text_content(timeout=1000)
                return " ".join(text.split()) if text else "not found"
            except:
                return "not found"
                
        try:
            body_text = await safe_extract(self.page.locator("body"))
            # Address
            data["address"] = await safe_extract(self.page.locator("h1, h2, [class*='Address']").first)
            if data["address"] == "not found":
                # fallback for padmapper address
                match_addr = re.search(r'([0-9]+\s+[a-zA-Z\s]+(?:Avenue|Ave|Street|St|Boulevard|Blvd|Drive|Dr|Road|Rd|Lane|Ln|Court|Ct|Circle|Cir))', body_text)
                if match_addr: data["address"] = match_addr.group(1).strip()
            
            # Clean junk from address
            if data["address"] != "not found":
                for sep in ['·', '|', 'Apartment for Rent', '→', '\u2192']:
                    data["address"] = data["address"].split(sep)[0].strip()
                data["address"] = data["address"].strip(' -')
            
            # Price
            data["price"] = await safe_extract(self.page.locator("span:has-text('$'), [class*='Price']").first)
            
            # Beds/Baths/Sqft
            match_beds = re.search(r'\b(\d{1,2})\s*Bed(?:room)?s?\b', body_text, re.IGNORECASE)
            if match_beds: data["beds"] = match_beds.group(1)
            else:
                if "Studio" in body_text: data["beds"] = "0"
            
            match_baths = re.search(r'\b(\d{1,2}(?:\.\d+)?)\s*Bath(?:room)?s?\b', body_text, re.IGNORECASE)
            if match_baths: data["baths"] = match_baths.group(1)
            
            match_sqft = re.search(r'(\d+(?:,\d+)?)\s*Sq(?:uare)?\s*Ft', body_text, re.IGNORECASE)
            if match_sqft: data["sqft"] = match_sqft.group(1)
            
            # Photos
            try:
                imgs = await self.page.locator("img").all()
                photos = []
                for img in imgs:
                    src = await img.get_attribute("src")
                    if src and src not in photos:
                        photos.append(src)
                data["photos"] = photos[:10] if photos else []
            except: pass
            
        except Exception as e:
            print(f"Critical extraction error (PadMapper): {e}")
            
        return self._normalize_listing_data(data)

    async def _fetch_padmapper_urls(self, city_slug: str, state_slug: str, max_price: int=None, min_beds: int=None, max_beds: int=None, min_baths: int=None, max_baths: int=None, query: str="") -> list:
        if not self.page: return []
        
        try:
            url = f"https://www.padmapper.com/apartments/{city_slug}-{state_slug}"
            
            params = []
            if min_beds and not max_beds:
                params.append(f"beds={','.join(str(i) for i in range(min_beds, 8))}")
            elif min_beds and max_beds:
                params.append(f"beds={','.join(str(i) for i in range(min_beds, max_beds + 1))}")
            elif max_beds:
                params.append(f"beds={','.join(str(i) for i in range(0, max_beds + 1))}")
            
            if min_baths: params.append(f"baths={min_baths}")
            if max_price: params.append(f"price=0-{max_price}")
            
            if params:
                url += "?" + "&".join(params)
                
            import time
            t0 = time.time()
            print(f"[Timing] Navigating to PadMapper search: {url}")
            await self.navigate(url)
            t_nav = time.time() - t0
            print(f"[Timing] PadMapper navigation took {t_nav:.2f}s")
            
            # Explicit sleep for dynamic content
            t0_sleep = time.time()
            await self.page.wait_for_timeout(4000)
            print(f"[Timing] PadMapper explicit wait took {time.time() - t0_sleep:.2f}s")
            
            hrefs = []
            listings = await self.page.locator("div[itemtype*='Apartment']").all()
            for listing in listings:
                try:
                    link = listing.locator("a").first
                    href = await link.get_attribute("href", timeout=1000)
                    if href and href not in hrefs:
                        hrefs.append(href)
                except:
                    pass
                    
            print(f"DEBUG: Found {len(hrefs)} PadMapper urls.")
            full_urls = []
            for href in hrefs:
                if href.startswith("http"):
                    full_urls.append(href)
                else:
                    full_urls.append(f"https://www.padmapper.com{href}")
            return full_urls
        except Exception as e:
            print(f"Error gathering padmapper urls: {e}")
            return []

    async def _fetch_craigslist_urls(self, city_slug: str, raw_city: str, max_price: int=None, min_beds: int=None, max_beds: int=None, min_baths: int=None, max_baths: int=None, query: str="") -> tuple[list, str]:
        if not self.page: return [], ""
        try:
            CRAIGSLIST_METRO_MAPPING = {
                "houston": "houston", "katy": "houston", "woodlands": "houston",
                "dallas": "dallas", "richardson": "dallas", "plano": "dallas", "frisco": "dallas",
                "austin": "austin", "sanantonio": "sanantonio", "san antonio": "sanantonio",
                "denver": "denver", "aurora": "denver", "boulder": "boulder", "coloradosprings": "cosprings",
                "losangeles": "losangeles"
            }
            clean_city = city_slug.replace("-", "")
            domain = CRAIGSLIST_METRO_MAPPING.get(clean_city)
            if not domain:
                print(f"DEBUG: City '{clean_city}' not in Craigslist mapping, skipping CL.")
                return [], ""
            
            if not query:
                # Use the raw city name as the search query if none is provided
                query = raw_city
            
            url = f"https://{domain}.craigslist.org/search/apa?query={query}"
            if max_price: url += f"&max_price={max_price}"
            if min_beds: url += f"&min_bedrooms={min_beds}"
            if max_beds: url += f"&max_bedrooms={max_beds}"
            if min_baths: url += f"&min_bathrooms={min_baths}"
            if max_baths: url += f"&max_bathrooms={max_baths}"
            
            import time
            t0 = time.time()
            print(f"[Timing] Navigating to Craigslist search: {url}")
            await self.navigate(url)
            t_nav = time.time() - t0
            print(f"[Timing] Craigslist navigation took {t_nav:.2f}s")
            
            # Explicit sleep for dynamic content
            t0_sleep = time.time()
            await self.page.wait_for_timeout(4000)
            print(f"[Timing] Craigslist explicit wait took {time.time() - t0_sleep:.2f}s")
            
            hrefs = []
            links = await self.page.locator("a").all()
            for link in links:
                href = await link.get_attribute("href")
                if href and "/view/d/" in href and href not in hrefs:
                    hrefs.append(href)
                    
            full_urls = []
            for href in hrefs:
                if href.startswith("http"): full_urls.append(href)
                else: full_urls.append(f"https://{domain}.craigslist.org{href}")
                
            return full_urls, domain
        except Exception as e:
            print(f"Error gathering craigslist urls: {e}")
            return [], ""

    async def gather_combined_listings(self, location: str, max_price: int=None, min_beds: int=None, max_beds: int=None, min_baths: int=None, max_baths: int=None, query: str="", landmark_hint: str=None) -> str:
        if not self.page:
            return "Error: Browser session not started"

        # ── Landmark proximity guard ──────────────────────────────────────────
        # Geocode the actual landmark (from goal "near X") rather than the LLM's
        # city slug. This gives the true POI coordinates as the filter centroid.
        from places import geocode_address, calculate_distance
        import re as _re
        MAX_LANDMARK_RADIUS_MILES = 15.0

        # Prefer landmark_hint qualified by location for accurate geocoding.
        # e.g. "UTA arlington tx" rather than just "UTA" which resolves to Utah.
        centroid_source = f"{landmark_hint} {location}" if landmark_hint else location
        landmark_lat, landmark_lng = geocode_address(centroid_source)
        landmark_centroid = (landmark_lat, landmark_lng) if landmark_lat and landmark_lng else None
        if landmark_centroid:
            print(f"[GeoFilter] Centroid for '{centroid_source}': {landmark_centroid}")

        import time
        t_start_all = time.time()
        
        try:
            city_slug, state_slug, raw_city = resolve_location(location)
            if not city_slug or not state_slug:
                return f"Error: Could not determine valid city and state from location '{location}'."

            t0_pm = time.time()
            pm_urls = await self._fetch_padmapper_urls(city_slug, state_slug, max_price, min_beds, max_beds, min_baths, max_baths, query)
            print(f"[Timing] Total PadMapper fetch urls took {time.time() - t0_pm:.2f}s (Found {len(pm_urls)})")
            
            t0_cl = time.time()
            cl_urls, cl_domain = await self._fetch_craigslist_urls(city_slug, raw_city, max_price, min_beds, max_beds, min_baths, max_baths, query)
            print(f"[Timing] Total Craigslist fetch urls took {time.time() - t0_cl:.2f}s (Found {len(cl_urls)})")

            if not pm_urls and not cl_urls:
                return "Error: Could not find any listing URLs on PadMapper or Craigslist."

            combined_queue = []
            max_len = max(len(pm_urls), len(cl_urls))
            for i in range(max_len):
                if i < len(pm_urls): combined_queue.append((pm_urls[i], "padmapper"))
                if i < len(cl_urls): combined_queue.append((cl_urls[i], "craigslist"))

            results = []
            seen_addresses = set()

            for url, source in combined_queue:
                if len(results) >= 3:
                    break

                print(f"[Timing] Extracting {url} from {source}")
                t0_nav = time.time()
                await self.navigate(url)
                print(f"[Timing]   -> Page load took {time.time() - t0_nav:.2f}s")
                
                t0_sleep = time.time()
                await self.page.wait_for_timeout(2000)
                print(f"[Timing]   -> Explicit wait took {time.time() - t0_sleep:.2f}s")

                t0_ext = time.time()
                try:
                    if source == "padmapper":
                        details = await self.extract_padmapper_details()
                    else:
                        details = await self.extract_craigslist_details()

                    details["source"] = source
                    address = details.get("address", "")

                    if address != "not found" and address in seen_addresses:
                        continue

                    if address != "not found":
                        seen_addresses.add(address)

                    # ── Standard filter: beds / baths / price ─────────────────
                    valid = True
                    b = details.get("beds")
                    if isinstance(b, (int, float)):
                        if min_beds and b < min_beds: valid = False
                        if max_beds and b > max_beds: valid = False
                    else:
                        if min_beds or max_beds: valid = False

                    ba = details.get("baths")
                    if isinstance(ba, (int, float)):
                        if min_baths and ba < min_baths: valid = False
                        if max_baths and ba > max_baths: valid = False
                    else:
                        if min_baths or max_baths: valid = False

                    p = details.get("price")
                    if isinstance(p, (int, float)):
                        if max_price and p > max_price: valid = False

                    if address == "not found" or not address:
                        valid = False

                    if not valid:
                        print(f"Skipping {url} (violates search filters or missing address)")
                        continue

                    # ── Geographic proximity filter ───────────────────────────
                    # Only applied when we have a usable landmark centroid.
                    # Fail-open: if we cannot geocode the listing address, keep it.
                    if landmark_centroid and address and address != "not found":
                        qualified_address = f"{address} {location}"
                        listing_lat, listing_lng = geocode_address(qualified_address)
                        safe_addr = qualified_address.encode('ascii', 'replace').decode('ascii')
                        if listing_lat and listing_lng:
                            dist = calculate_distance(
                                landmark_centroid[0], landmark_centroid[1],
                                listing_lat, listing_lng
                            )
                            details["_distance_to_landmark_miles"] = round(dist, 2)
                            print(f"[GeoFilter] {safe_addr} -> {dist:.2f} mi from landmark")
                            if dist > MAX_LANDMARK_RADIUS_MILES:
                                print(f"[GeoFilter] REJECTING {url}: {dist:.2f} mi > {MAX_LANDMARK_RADIUS_MILES} mi radius")
                                continue
                        else:
                            print(f"[GeoFilter] Could not geocode listing address '{safe_addr}' — keeping (fail-open)")

                    results.append(details)
                except Exception as e:
                    print(f"Error extracting {url}: {e}")

            print(f"[Timing] gather_combined_listings total execution took {time.time() - t_start_all:.2f}s. Returning {len(results)} results.")
            
            # Park the browser on a blank page to kill active trackers/ads 
            # and reclaim memory/renderer processes while the agent thinks.
            try:
                await self.page.goto("about:blank")
            except Exception:
                pass
                
            return json.dumps(results, indent=2)

        except Exception as e:
            return f"Error gathering combined listings: {str(e)}"

    def _normalize_listing_data(self, data: dict) -> dict:
        """Parse raw string values into clean numeric types for the LLM."""
        norm = data.copy()
        
        # Clean Price (prefer monthly rent if present, e.g. "$925k Est. $6,862/mo" -> 6862)
        if norm.get("price") and norm["price"] != "not found":
            # Look for a number near "/mo", "mo", or "month"
            match_mo = re.search(r'\$?([\d,]+)\s*(?:/mo|mo\b|per month)', norm["price"], re.IGNORECASE)
            if match_mo:
                norm["price"] = int(match_mo.group(1).replace(",", ""))
            else:
                # Fallback to the first number found
                match = re.search(r'\$?([\d,]+)', norm["price"])
                if match:
                    norm["price"] = int(match.group(1).replace(",", ""))
                
        # Clean Beds (e.g. "3BR", "4bd" -> 3, 4)
        if norm.get("beds") and norm["beds"] != "not found":
            match = re.search(r'([\d\.]+)', norm["beds"])
            if match:
                beds = float(match.group(1))
                norm["beds"] = int(beds) if beds.is_integer() else beds
                
        # Clean Baths (e.g. "2Ba", "3.5 ba" -> 2.0, 3.5)
        if norm.get("baths") and norm["baths"] != "not found":
            match = re.search(r'([\d\.]+)', norm["baths"])
            if match:
                norm["baths"] = float(match.group(1))
                
        # Clean Sqft (e.g. "1168ft2", "3,352sq ft" -> 1168, 3352)
        if norm.get("sqft") and norm["sqft"] != "not found":
            match = re.search(r'([\d,]+)', norm["sqft"])
            if match:
                norm["sqft"] = int(match.group(1).replace(",", ""))
                
        return norm
