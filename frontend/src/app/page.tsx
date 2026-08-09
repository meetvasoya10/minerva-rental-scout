'use client';

import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search,
  Loader2,
  StopCircle,
  ArrowRight,
  Home,
  Bed,
  Bath,
  Square,
  Lightbulb,
  CheckCircle2,
  AlertTriangle,
  Play,
  Settings2,
  User,
  Globe2,
  X,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Maximize2,
  MapPin,
  Car,
  ScanSearch,
} from 'lucide-react';
import { useAgent, AppState, AgentEvent, AmenityGroup, DisplayEvent } from '@/hooks/useAgent';
import ReactMarkdown from 'react-markdown';

/**
 * Normalize a raw `category` value from the backend into a fixed display label.
 *
 * The LLM sometimes passes a full landmark name as the `category` argument to
 * get_nearby_amenities (e.g. "Plano West Senior High School" instead of "schools").
 * places.py already resolves the correct OSM tag using the same keyword check, so
 * we mirror that logic here to always show the canonical UI label.
 */
function canonicalizeCategoryLabel(raw: string): string {
  const s = (raw || '').toLowerCase();
  if (s.includes('school')) return 'Schools';
  if (s.includes('store') || s.includes('grocer') || s.includes('supermarket')) return 'Grocery Stores';
  if (s.includes('gym') || s.includes('fitness')) return 'Gyms';
  // Unknown category — title-case the raw value as a safe fallback
  return raw ? raw.charAt(0).toUpperCase() + raw.slice(1) : 'Nearby';
}

function ListingCard({ listing }: { listing: any }) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [currentPhotoIndex, setCurrentPhotoIndex] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [activeTab, setActiveTab] = useState<'details' | 'nearby'>('details');

  const isAddressMissing = !listing.address || listing.address.toLowerCase() === 'not found';
  const displayAddress = isAddressMissing ? 'Address not provided' : listing.address;
  const validUrl = listing.url && listing.url !== 'not found' ? listing.url : '#';

  // Whitelist-only photo filter: only keep URLs from known listing-photo CDNs.
  // PadMapper serves real photos via img.zumpercdn.com; Craigslist via images.craigslist.org.
  // Everything else (cloudfront icons, data URIs, relative paths) is rejected.
  const PHOTO_HOSTNAMES = ['img.zumpercdn.com', 'images.craigslist.org'];
  const isRealPhoto = (url: string): boolean => {
    if (!url || !url.startsWith('http')) return false;
    try {
      const host = new URL(url).hostname;
      return PHOTO_HOSTNAMES.some(allowed => host === allowed || host.endsWith('.' + allowed));
    } catch { return false; }
  };
  const photosArray = Array.isArray(listing.photos)
    ? listing.photos.filter(isRealPhoto)
    : (listing.photos && listing.photos !== 'not found' && isRealPhoto(listing.photos) ? [listing.photos] : []);
  const coverPhoto = photosArray.length > 0 ? photosArray[0] : null;
  const hasMultiplePhotos = photosArray.length > 1;

  const nextPhoto = (e: any) => { e.stopPropagation(); setCurrentPhotoIndex((prev) => (prev + 1) % photosArray.length); };
  const prevPhoto = (e: any) => { e.stopPropagation(); setCurrentPhotoIndex((prev) => (prev - 1 + photosArray.length) % photosArray.length); };

  const hasNearby = (listing.nearby_places && listing.nearby_places.length > 0)
    || (listing.commute && listing.commute.data_source !== 'fallback_unavailable');

  return (
    <>
      <div
        onClick={() => { setCurrentPhotoIndex(0); setActiveTab('details'); setIsModalOpen(true); }}
        className="bg-panel border border-neutral-100 dark:border-neutral-800/50 rounded-[24px] overflow-hidden shadow-[0_4px_20px_rgba(0,0,0,0.03)] hover:shadow-[0_12px_40px_rgba(0,0,0,0.08)] transition-all duration-500 flex flex-col h-full hover:-translate-y-1 cursor-pointer group"
      >
        <div className="aspect-[4/3] bg-neutral-50 dark:bg-neutral-900 relative overflow-hidden">
          {coverPhoto ? (
            <img
              src={coverPhoto}
              alt="Property"
              referrerPolicy="no-referrer"
              className="w-full h-full object-cover transition-transform duration-700 ease-out group-hover:scale-105"
              onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-neutral-300">
              <Home className="w-10 h-10 stroke-[1]" />
            </div>
          )}
          {listing.price && (
            <div className="absolute top-5 left-5 px-4 py-2 bg-white/90 dark:bg-black/90 backdrop-blur-md rounded-full text-sm font-bold shadow-[0_4px_12px_rgba(0,0,0,0.1)]">
              ${listing.price.toLocaleString()}<span className="text-neutral-500 font-medium">/mo</span>
            </div>
          )}
        </div>

        <div className="p-8 flex flex-col flex-1 group-hover:bg-neutral-50/50 dark:group-hover:bg-white/[0.02] transition-colors">
          <h3 className={`font-semibold text-xl leading-tight mb-6 h-14 line-clamp-2 ${isAddressMissing ? 'text-neutral-400 font-medium italic' : 'text-neutral-900 dark:text-neutral-100 group-hover:text-emerald-700 dark:group-hover:text-emerald-400 transition-colors'}`}>
            {displayAddress}
          </h3>

          <div className="flex items-center justify-between text-sm text-neutral-500 mb-8 pb-8 border-b border-neutral-100 dark:border-neutral-800">
            <div className="flex items-center gap-2"><Bed className="w-4 h-4" /><span className="font-semibold text-neutral-900 dark:text-neutral-100">{listing.beds || '-'}</span> bd</div>
            <div className="flex items-center gap-2"><Bath className="w-4 h-4" /><span className="font-semibold text-neutral-900 dark:text-neutral-100">{listing.baths || '-'}</span> ba</div>
            <div className="flex items-center gap-2"><Square className="w-4 h-4" /><span className="font-semibold text-neutral-900 dark:text-neutral-100">{listing.sqft && listing.sqft !== 'not found' ? listing.sqft : '-'}</span> sqft</div>
          </div>

          <div className="space-y-6 flex-1 flex flex-col justify-end">
            {listing.amenities && listing.amenities !== 'not found' && (
              <div>
                <span className="text-[11px] font-bold text-neutral-400 uppercase tracking-[0.08em] block mb-2">Amenities</span>
                <span className="text-sm text-neutral-700 dark:text-neutral-300 line-clamp-2 leading-relaxed">
                  {listing.amenities}
                </span>
              </div>
            )}
            <div className="flex items-center justify-between pt-2 mt-auto">
              <span className="text-[11px] font-bold text-neutral-400 uppercase tracking-[0.08em]">Source</span>
              <span className="text-[10px] font-bold bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-300 px-3 py-1.5 rounded-full uppercase tracking-widest">
                {listing.source || 'unknown'}
              </span>
            </div>
          </div>
        </div>
      </div>

      <AnimatePresence>
        {isModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6" onClick={() => setIsModalOpen(false)}>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              transition={{ type: 'spring', damping: 25, stiffness: 300 }}
              onClick={(e) => e.stopPropagation()}
              className="relative w-full max-w-4xl max-h-[90vh] bg-white dark:bg-neutral-900 rounded-[32px] shadow-2xl overflow-hidden flex flex-col md:flex-row border border-neutral-200 dark:border-neutral-800"
            >
              <button
                onClick={() => setIsModalOpen(false)}
                className="absolute top-6 right-6 z-10 p-2 bg-black/50 hover:bg-black/70 text-white rounded-full backdrop-blur-md transition-colors"
              >
                <X className="w-5 h-5" />
              </button>

              <div className="w-full md:w-1/2 h-64 md:h-auto bg-neutral-100 dark:bg-neutral-800 relative group/gallery">
                {photosArray.length > 0 ? (
                  <>
                    <img
                      src={photosArray[currentPhotoIndex]}
                      alt="Property"
                      referrerPolicy="no-referrer"
                      className="w-full h-full object-cover"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                    />
                    {hasMultiplePhotos && (
                      <>
                        <button onClick={prevPhoto} className="absolute left-4 top-1/2 -translate-y-1/2 p-2 bg-black/50 hover:bg-black/80 text-white rounded-full backdrop-blur-sm opacity-0 group-hover/gallery:opacity-100 transition-opacity">
                          <ChevronLeft className="w-5 h-5" />
                        </button>
                        <button onClick={nextPhoto} className="absolute right-4 top-1/2 -translate-y-1/2 p-2 bg-black/50 hover:bg-black/80 text-white rounded-full backdrop-blur-sm opacity-0 group-hover/gallery:opacity-100 transition-opacity">
                          <ChevronRight className="w-5 h-5" />
                        </button>
                        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-2 bg-black/50 px-3 py-1.5 rounded-full backdrop-blur-sm text-xs font-medium text-white shadow-lg">
                          {currentPhotoIndex + 1} / {photosArray.length}
                        </div>
                      </>
                    )}
                    <button onClick={() => setIsFullscreen(true)} className="absolute bottom-4 right-4 p-2 bg-black/50 hover:bg-black/80 text-white rounded-full backdrop-blur-sm opacity-0 group-hover/gallery:opacity-100 transition-opacity">
                      <Maximize2 className="w-4 h-4" />
                    </button>
                  </>
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-neutral-300">
                    <Home className="w-16 h-16 stroke-[1]" />
                  </div>
                )}
                {listing.price && (
                  <div className="absolute top-6 left-6 px-5 py-2.5 bg-white/95 dark:bg-black/95 backdrop-blur-md rounded-full text-lg font-bold shadow-lg text-neutral-900 dark:text-white">
                    ${listing.price.toLocaleString()}<span className="text-neutral-500 font-medium">/mo</span>
                  </div>
                )}
              </div>

              <div className="w-full md:w-1/2 p-6 md:p-10 overflow-y-auto flex flex-col">
                <h2 className={`text-xl md:text-2xl font-bold leading-tight mb-5 ${isAddressMissing ? 'text-neutral-400 italic' : 'text-neutral-900 dark:text-white'}`}>
                  {displayAddress}
                </h2>

                <div className="flex flex-wrap items-center gap-5 text-sm text-neutral-600 dark:text-neutral-400 mb-6 pb-6 border-b border-neutral-100 dark:border-neutral-800/60">
                  <div className="flex items-center gap-2"><Bed className="w-4 h-4" /><span className="font-semibold text-neutral-900 dark:text-white">{listing.beds || '-'}</span> beds</div>
                  <div className="flex items-center gap-2"><Bath className="w-4 h-4" /><span className="font-semibold text-neutral-900 dark:text-white">{listing.baths || '-'}</span> baths</div>
                  <div className="flex items-center gap-2"><Square className="w-4 h-4" /><span className="font-semibold text-neutral-900 dark:text-white">{listing.sqft && listing.sqft !== 'not found' ? listing.sqft : '-'}</span> sqft</div>
                </div>

                {/* ── Tab bar ── */}
                <div className="flex gap-1 mb-6 p-1 bg-neutral-100 dark:bg-neutral-800/60 rounded-[14px]">
                  {(['details', 'nearby'] as const).map(tab => (
                    <button
                      key={tab}
                      onClick={() => setActiveTab(tab)}
                      className={`flex-1 flex items-center justify-center gap-1.5 py-2 px-3 rounded-[10px] text-[12px] font-semibold transition-all ${activeTab === tab
                        ? 'bg-white dark:bg-neutral-700 text-neutral-900 dark:text-white shadow-sm'
                        : 'text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300'
                        }`}
                    >
                      {tab === 'details' ? 'Details' : 'Nearby'}
                      {tab === 'nearby' && hasNearby && (
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0" />
                      )}
                    </button>
                  ))}
                </div>

                {/* ── Tab: Details ── */}
                <div className={`flex-1 ${activeTab === 'details' ? 'block' : 'hidden'}`}>
                  <h4 className="text-[11px] font-bold text-neutral-400 uppercase tracking-[0.1em] mb-3">Features &amp; Amenities</h4>
                  {(() => {
                    const amenityText = listing.amenities && listing.amenities !== 'not found'
                      ? listing.amenities
                      : listing.amenity_text && listing.amenity_text !== 'not found'
                        ? listing.amenity_text
                        : null;
                    return amenityText ? (
                      <div className="flex flex-wrap gap-2">
                        {amenityText.split(',').map((a: string, i: number) => (
                          <span key={i} className="px-3 py-1.5 bg-neutral-100 dark:bg-neutral-800 text-neutral-700 dark:text-neutral-300 rounded-xl text-xs font-medium">
                            {a.trim()}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <p className="text-neutral-400 italic text-sm">No listing amenity details available.</p>
                    );
                  })()}
                </div>

                {/* ── Tab: Nearby ── */}
                <div className={`flex-1 ${activeTab === 'nearby' ? 'block' : 'hidden'}`}>
                  {!hasNearby ? (
                    <p className="text-neutral-400 italic text-sm">No location data available for this listing.</p>
                  ) : (
                    <>
                      {/* Commute card */}
                      {listing.commute && listing.commute.data_source !== 'fallback_unavailable' && (
                        <div className="mb-5 p-4 bg-emerald-50 dark:bg-emerald-900/10 rounded-2xl border border-emerald-100 dark:border-emerald-900/50">
                          <div className="flex items-center gap-2 mb-1 text-emerald-800 dark:text-emerald-400">
                            <Car className="w-4 h-4" />
                            <h4 className="text-[11px] font-bold uppercase tracking-[0.1em]">Commute to {listing.commute.to}</h4>
                          </div>
                          <p className="text-base font-semibold text-emerald-950 dark:text-emerald-200">
                            {listing.commute.distance_miles} mi{listing.commute.duration_minutes ? ` · ${listing.commute.duration_minutes} min` : ''}
                          </p>
                        </div>
                      )}

                      {/* Nearby categories */}
                      {listing.nearby_places && listing.nearby_places.length > 0 && (
                        <div>
                          {listing.nearby_places.map((place: any, i: number) => (
                            <div
                              key={i}
                              className={`py-4 ${i > 0 ? 'border-t border-neutral-100 dark:border-neutral-800/60' : ''}`}
                            >
                              <div className="flex items-center gap-2 mb-3">
                                <MapPin className="w-3 h-3 text-neutral-400 shrink-0" />
                                <h4 className="text-[11px] font-bold text-neutral-500 dark:text-neutral-400 uppercase tracking-[0.1em]">
                                  {canonicalizeCategoryLabel(place.category)}
                                </h4>
                              </div>
                              {place.error || place.data_source === 'fallback_unavailable' ? (
                                <p className="text-rose-500 text-xs italic">Data unavailable</p>
                              ) : place.amenities && place.amenities.length > 0 ? (
                                <ul className="space-y-2.5">
                                  {place.amenities.map((am: any, j: number) => {
                                    console.log(`[DEBUG-DISTANCE-FRONTEND] Rendering amenity: ${am.name}, distance=${am.distance_miles}`);
                                    return (
                                      <li key={j} className="flex items-center gap-3">
                                        <span className="w-1.5 h-1.5 rounded-full bg-neutral-300 dark:bg-neutral-600 shrink-0" />
                                        <span className="text-sm font-medium text-neutral-800 dark:text-neutral-200 flex-1 leading-snug truncate">
                                          {am.name}
                                        </span>
                                        <span className="shrink-0 text-[11px] font-semibold tabular-nums text-neutral-500 dark:text-neutral-400 bg-neutral-100 dark:bg-neutral-800 px-2 py-0.5 rounded-full">
                                          {am.distance_miles} mi
                                        </span>
                                      </li>
                                    );
                                  })}
                                </ul>
                              ) : (
                                <p className="text-neutral-400 italic text-xs">None found nearby.</p>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>

                <div className="mt-8 pt-6 border-t border-neutral-100 dark:border-neutral-800/60">
                  {validUrl !== '#' ? (
                    <a
                      href={validUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="w-full flex items-center justify-center gap-3 py-3.5 px-6 bg-emerald-600 hover:bg-emerald-700 text-white rounded-2xl font-semibold transition-colors"
                    >
                      View original posting
                      <ExternalLink className="w-4 h-4" />
                    </a>
                  ) : (
                    <button disabled className="w-full py-3.5 px-6 bg-neutral-100 dark:bg-neutral-800 text-neutral-400 rounded-2xl font-semibold cursor-not-allowed">
                      Source link unavailable
                    </button>
                  )}
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {isFullscreen && (
          <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/95" onClick={() => setIsFullscreen(false)}>
            <button
              onClick={() => setIsFullscreen(false)}
              className="absolute top-6 right-6 z-10 p-3 bg-white/10 hover:bg-white/20 text-white rounded-full backdrop-blur-md transition-colors"
            >
              <X className="w-6 h-6" />
            </button>
            <img src={photosArray[currentPhotoIndex]} alt="Fullscreen" className="max-w-full max-h-[90vh] object-contain" onClick={(e) => e.stopPropagation()} />
            {hasMultiplePhotos && (
              <>
                <button onClick={prevPhoto} className="absolute left-6 top-1/2 -translate-y-1/2 p-4 bg-white/10 hover:bg-white/20 text-white rounded-full backdrop-blur-sm transition-colors">
                  <ChevronLeft className="w-8 h-8" />
                </button>
                <button onClick={nextPhoto} className="absolute right-6 top-1/2 -translate-y-1/2 p-4 bg-white/10 hover:bg-white/20 text-white rounded-full backdrop-blur-sm transition-colors">
                  <ChevronRight className="w-8 h-8" />
                </button>
                <div className="absolute bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-2 bg-white/10 px-4 py-2 rounded-full backdrop-blur-sm text-sm font-medium text-white">
                  {currentPhotoIndex + 1} / {photosArray.length}
                </div>
              </>
            )}
          </div>
        )}
      </AnimatePresence>
    </>
  );
}

const STATUS_CONFIG: Record<AppState, { label: string; dot: string }> = {
  IDLE: { label: 'Ready', dot: 'bg-neutral-300 dark:bg-neutral-600' },
  STARTING: { label: 'Starting', dot: 'bg-emerald-600 animate-pulse' },
  RUNNING: { label: 'Agent running', dot: 'bg-emerald-600' },
  PAUSED: { label: 'Waiting for input', dot: 'bg-amber-500' },
  COMPLETED: { label: 'Completed', dot: 'bg-emerald-600' },
  ERROR: { label: 'Error', dot: 'bg-rose-500' },
};

function formatPayload(type: string, payload: any) {
  if (type === 'action' && typeof payload === 'string' && payload.startsWith('Tool call:')) {
    try {
      const match = payload.match(/Tool call: (.*?) with input: (.*)/);
      if (match) {
        const toolName = match[1];
        const inputStr = match[2];
        const inputJson = inputStr ? JSON.parse(inputStr) : {};

        if (toolName === 'search_and_extract_listings' || toolName === 'search_and_extract_craigslist') {
          let desc = `Searching ${inputJson.location || 'unknown'}`;
          let reqs = [];
          if (inputJson.min_bedrooms) reqs.push(`${inputJson.min_bedrooms}BR`);
          if (inputJson.min_bathrooms) reqs.push(`${inputJson.min_bathrooms}BA`);
          if (reqs.length > 0) desc += ` for ${reqs.join('/')} listings`;
          else desc += ` for listings`;

          if (inputJson.max_price) desc += ` under $${inputJson.max_price}`;
          if (inputJson.query) desc += ` matching "${inputJson.query}"`;
          return desc;
        }

        if (toolName === 'navigate') {
          try {
            const hostname = new URL(inputJson.url).hostname.replace('www.', '');
            return `Navigating to ${hostname}`;
          } catch (e) {
            return `Navigating to ${inputJson.url}`;
          }
        }
        if (toolName === 'search') return `Searching for "${inputJson.query}"`;
        if (toolName === 'click') return `Clicking "${inputJson.text}"`;
        if (toolName === 'extract_listing_details') return `Extracting listing details`;
        if (toolName === 'ask_human') return `Pausing for human input`;
        if (toolName === 'submit_comparison') return `Submitting final results`;
        if (toolName === 'get_nearby_amenities') {
          return `Querying OSM for ${inputJson.category} near ${inputJson.address}`;
        }

        // Sane default fallback for any unhandled or future tools
        const keys = Object.keys(inputJson);
        if (keys.length > 0) {
          const summary = keys.map(k => `${k}: ${inputJson[k]}`).join(', ');
          return `Running ${toolName} (${summary})`;
        }
        return `Running ${toolName}`;
      }
    } catch (e) {
      // Fallback if parsing fails
    }
  }

  if (type === 'observation' && typeof payload === 'string') {
    if (payload.includes('"data_source": "fallback_unavailable"')) {
      return (
        <span className="text-rose-600 dark:text-rose-400 font-semibold bg-rose-50 dark:bg-rose-950/30 px-2 py-1 rounded">
          Amenity data unavailable (API Blocked)
        </span>
      );
    }
    if (payload.startsWith('[\n  {')) {
      return `Successfully extracted mechanical listing results.`;
    }
    if (payload.includes('"distance_miles":') || payload.includes('"amenities":')) {
      return `OSM data retrieved successfully.`;
    }
  }

  return payload;
}

function EventCard({ event }: { event: AgentEvent }) {
  // Mapping the backend event types to the user requested visual styles
  let bgClass = 'bg-neutral-50 border-neutral-200 text-neutral-800';
  let label = event.type;
  let Icon = ArrowRight;
  let iconClass = 'text-neutral-500';

  if (event.type === 'thought') {
    bgClass = 'bg-emerald-50/70 border-emerald-100 text-emerald-950 dark:bg-emerald-950/20 dark:border-emerald-900/50 dark:text-emerald-300';
    label = 'Thought';
    Icon = Lightbulb;
    iconClass = 'text-emerald-700 dark:text-emerald-400';
  } else if (event.type === 'action') { // Tool calls from backend
    bgClass = 'bg-amber-50/70 border-amber-100 text-amber-950 dark:bg-amber-950/20 dark:border-amber-900/50 dark:text-amber-300';
    label = 'Tool Call';
    Icon = Settings2;
    iconClass = 'text-amber-700 dark:text-amber-400';
  } else if (event.type === 'observation') { // Action results
    bgClass = 'bg-blue-50/70 border-blue-100 text-blue-950 dark:bg-blue-950/20 dark:border-blue-900/50 dark:text-blue-300';
    label = 'Action';
    Icon = CheckCircle2;
    iconClass = 'text-blue-700 dark:text-blue-400';
  } else if (event.type === 'error' || event.type === 'aborted' || event.type === 'waiting_for_user') {
    bgClass = 'bg-rose-50/70 border-rose-100 text-rose-950 dark:bg-rose-950/20 dark:border-rose-900/50 dark:text-rose-300';
    label = event.type === 'waiting_for_user' ? 'Needs Input' : 'Error';
    Icon = AlertTriangle;
    iconClass = 'text-rose-700 dark:text-rose-400';
  } else if (event.type === 'done') {
    bgClass = 'bg-emerald-50/70 border-emerald-100 text-emerald-950 dark:bg-emerald-950/20 dark:border-emerald-900/50 dark:text-emerald-300';
    label = 'Completed';
    Icon = CheckCircle2;
    iconClass = 'text-emerald-700 dark:text-emerald-400';
  }

  let formattedPayload: React.ReactNode = null;

  if (event.type === 'done' && event.payload && typeof event.payload === 'object') {
    formattedPayload = (
      <div className="flex flex-col mt-1">
        <p className="text-sm font-medium">Comparison complete — see results below.</p>
      </div>
    );
  } else {
    formattedPayload = formatPayload(event.type, event.payload);
  }

  return (
    <div className={`p-4 rounded-[16px] border ${bgClass} flex items-start gap-4 shadow-[0_1px_2px_rgba(0,0,0,0.02)]`}>
      <div className={`mt-0.5 p-1.5 rounded-full bg-white dark:bg-black/20 shadow-sm ${iconClass}`}>
        <Icon className="w-4 h-4 stroke-[2.5]" />
      </div>
      <div className="flex-1 min-w-0 pt-0.5">
        <div className="flex items-center gap-2 mb-1.5">
          <span className="text-[11px] font-bold tracking-widest uppercase opacity-70">
            {label}
          </span>
          <span className="text-[10px] opacity-40 font-medium">
            {new Date(event.timestamp).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </span>
        </div>
        <div className="text-[14px] leading-relaxed break-words font-medium opacity-90">
          {formattedPayload}
        </div>
      </div>
    </div>
  );
}

// ── AmenityGroupCard ─────────────────────────────────────────────────────────
// Collapsible trace entry that groups all get_nearby_amenities calls for one address
function AmenityGroupCard({ group }: { group: AmenityGroup }) {
  const [isOpen, setIsOpen] = useState(false);
  const categoryCount = group.categories.length;
  const totalResults = group.categories.reduce((s, c) => s + (c.results?.length ?? 0), 0);

  // Trim long addresses for the one-liner
  const shortAddr = group.displayAddress.length > 48
    ? group.displayAddress.slice(0, 45) + '…'
    : group.displayAddress;

  return (
    <div className="rounded-[16px] border border-violet-100 dark:border-violet-900/50 bg-violet-50/70 dark:bg-violet-950/20 shadow-[0_1px_2px_rgba(0,0,0,0.02)] overflow-hidden">
      {/* ── Header (always visible) ── */}
      <button
        onClick={() => setIsOpen(o => !o)}
        disabled={group.inProgress && categoryCount === 0}
        className="w-full flex items-center gap-3 p-4 text-left transition-colors hover:bg-violet-100/50 dark:hover:bg-violet-900/20 disabled:cursor-default"
      >
        {/* Icon */}
        <div className="shrink-0 p-1.5 rounded-full bg-white dark:bg-black/20 shadow-sm text-violet-600 dark:text-violet-400">
          {group.inProgress
            ? <Loader2 className="w-4 h-4 animate-spin" />
            : <ScanSearch className="w-4 h-4 stroke-[2.5]" />}
        </div>

        {/* Label */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-[11px] font-bold tracking-widest uppercase opacity-70 text-violet-900 dark:text-violet-300">
              Amenity Search
            </span>
            <span className="text-[10px] opacity-40 font-medium text-violet-900 dark:text-violet-300">
              {new Date(group.timestamp).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
          </div>
          <p className="text-[13px] font-semibold text-violet-900 dark:text-violet-200 leading-snug truncate">
            {shortAddr}
          </p>
          {!group.inProgress && categoryCount > 0 && (
            <p className="text-[11px] text-violet-600 dark:text-violet-400 mt-0.5">
              {categoryCount} {categoryCount === 1 ? 'category' : 'categories'} · {totalResults} places found
            </p>
          )}
          {group.inProgress && (
            <p className="text-[11px] text-violet-500 dark:text-violet-500 mt-0.5 animate-pulse">
              {categoryCount > 0 ? `${categoryCount} of 3 complete…` : 'Querying nearby places…'}
            </p>
          )}
        </div>

        {/* Chevron */}
        {!group.inProgress && categoryCount > 0 && (
          <ChevronDown
            className={`shrink-0 w-4 h-4 text-violet-500 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}
          />
        )}
      </button>

      {/* ── Expanded detail ── */}
      <AnimatePresence initial={false}>
        {isOpen && categoryCount > 0 && (
          <motion.div
            key="amenity-detail"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 pt-1 border-t border-violet-100 dark:border-violet-900/40 space-y-4">
              {group.categories.map((cat, i) => (
                <div key={i}>
                  <h4 className="text-[11px] font-bold text-violet-400 dark:text-violet-500 uppercase tracking-[0.08em] mb-2">
                    {canonicalizeCategoryLabel(cat.category)}
                  </h4>
                  {cat.error || cat.data_source === 'fallback_unavailable' ? (
                    <p className="text-[12px] text-rose-500 italic">Data unavailable</p>
                  ) : cat.results.length === 0 ? (
                    <p className="text-[12px] text-violet-500 italic">None found nearby</p>
                  ) : (
                    <ul className="space-y-1.5">
                      {cat.results.map((r, j) => (
                        <li key={j} className="flex items-center gap-2 text-[13px] text-violet-900 dark:text-violet-200">
                          <MapPin className="w-3.5 h-3.5 text-violet-400 shrink-0" />
                          <span className="font-medium truncate">{r.name}</span>
                          <span className="text-violet-400 shrink-0 ml-auto pl-2">{r.distance_miles} mi</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function HomeView() {
  const wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8006/ws/agent';
  const {
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
  } = useAgent(wsUrl);

  const [goal, setGoal] = useState('Find me a 2BR under $3000/month in Huston, TX');
  const [userReply, setUserReply] = useState('');

  const EXAMPLE_PROMPTS = [
    'Find a 1BR near UTA',
    'Pet-friendly apartments under $1,800',
    'Homes with a garage in Plano',
    'Find a 1BR near UT Dallas'
  ];

  const REFINEMENT_CHIPS = [
    { label: 'Cheaper', prompt: 'Find cheaper options than these' },
    { label: 'Pet friendly', prompt: 'Show me pet-friendly options' },
    { label: 'More bedrooms', prompt: 'Show options with more bedrooms' },
    { label: 'Show me the best 3', prompt: 'Show me the best 3 matches' },
  ];

  const traceEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll trace
  useEffect(() => {
    if (traceEndRef.current) {
      traceEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [events]);

  const handleStart = (e: React.FormEvent) => {
    e.preventDefault();
    if (!goal.trim()) return;
    if (appState === 'IDLE' || appState === 'COMPLETED' || appState === 'ERROR') {
      startAgent(goal);
    }
  };

  const handleHumanReply = (e: React.FormEvent) => {
    e.preventDefault();
    if (!userReply.trim()) return;
    sendHumanResponse(userReply);
    setUserReply('');
  };

  const isInputDisabled = appState === 'STARTING' || appState === 'RUNNING' || appState === 'PAUSED';

  return (
    <main className="min-h-screen bg-background text-foreground flex flex-col pt-6 pb-24 px-6 md:px-12 w-full max-w-[1800px] mx-auto font-sans">
      
      {/* ── TOP BRANDING ── */}
      <div className="flex items-center mb-6 pl-2">
        <span className="text-xl font-bold tracking-tight text-emerald-800 dark:text-emerald-400">
          Minerva <span className="font-normal text-neutral-400 dark:text-neutral-500">Rental Scout</span>
        </span>
      </div>

      {/* ── HEADER ── */}
      <header className="flex flex-col gap-8 mb-12 p-8 md:p-12 bg-gradient-to-b from-sky-50 to-transparent dark:from-sky-950/30 dark:to-transparent border border-neutral-100 dark:border-neutral-800/50 rounded-[32px] shadow-[0_2px_8px_rgba(0,0,0,0.02)]">
        <div className="flex flex-col items-center justify-center text-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1 bg-transparent border border-neutral-200 dark:border-neutral-800 rounded-full text-xs font-semibold tracking-wide text-neutral-500 dark:text-neutral-400">
            <div className={`w-2 h-2 rounded-full ${isConnected ? STATUS_CONFIG[appState].dot : 'bg-rose-500'}`} />
            {!isConnected ? 'Disconnected' : STATUS_CONFIG[appState].label}
          </div>
          <h1 className="text-[42px] leading-tight font-semibold tracking-[-0.03em] text-neutral-900 dark:text-white">
            Find Your Next Place
          </h1>
          <p className="text-base text-neutral-500 dark:text-neutral-400 max-w-md">
            Search and compare the right place with an AI-powered real estate agent.
          </p>
        </div>

        {/* ── SEARCH INPUT ── */}
        <div className="max-w-3xl w-full mx-auto">
          <form onSubmit={handleStart} className="relative group">
            <div className="absolute inset-y-0 left-6 flex items-center pointer-events-none text-neutral-400">
              <Search className="w-5 h-5 stroke-[2]" />
            </div>
            <input
              id="main-search-input"
              type="text"
              className="w-full pl-14 pr-36 py-5 bg-white dark:bg-[#111] border border-neutral-200 dark:border-neutral-800 rounded-[20px] shadow-[0_4px_20px_rgba(0,0,0,0.04)] focus:outline-none focus:ring-2 focus:ring-emerald-600/30 focus:border-emerald-600 transition-all text-lg placeholder:text-neutral-400 disabled:opacity-60 disabled:bg-neutral-50 dark:disabled:bg-neutral-900/50"
              placeholder="Find me a 2BR under $2000/month in Huston, TX"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              disabled={isInputDisabled}
            />
            <button
              id="start-agent-btn"
              type="submit"
              disabled={isInputDisabled || !goal.trim()}
              className="absolute right-3 top-3 bottom-3 px-8 bg-emerald-700 dark:bg-emerald-600 text-white rounded-[14px] font-medium hover:bg-emerald-800 dark:hover:bg-emerald-700 transition-colors flex items-center gap-2 disabled:opacity-40 shadow-sm"
            >
              {isInputDisabled ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4 fill-current" />}
              Start
            </button>
          </form>

          {/* Example prompts — only show when idle or error, NOT on completed (refinement chips handle that state) */}
          {(appState === 'IDLE' || appState === 'ERROR') && (
            <div className="flex flex-wrap gap-2 mt-3">
              {EXAMPLE_PROMPTS.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setGoal(p)}
                  className="text-xs px-3 py-1.5 rounded-full border border-neutral-200 dark:border-neutral-700 text-neutral-500 dark:text-neutral-400 bg-white dark:bg-neutral-900 hover:border-emerald-500 hover:text-emerald-700 transition-colors"
                >
                  {p}
                </button>
              ))}
            </div>
          )}
        </div>
      </header>

      {/* ── MAIN TWO-COLUMN PANELS ── */}
      <div className={`grid grid-cols-1 lg:grid-cols-[1.1fr_0.9fr] gap-8 ${appState === 'COMPLETED' && finalResult ? 'lg:h-[360px] min-h-[280px]' : 'lg:h-[640px] min-h-[320px]'}`}>

        {/* LEFT COLUMN: Agent Trace */}
        <div className="flex flex-col bg-panel rounded-[24px] overflow-hidden shadow-[0_2px_8px_rgba(0,0,0,0.02),0_12px_40px_rgba(0,0,0,0.04)] border border-neutral-100 dark:border-neutral-800/50 h-full relative">

          <div className="flex items-center justify-between px-8 py-5 border-b border-neutral-100 dark:border-neutral-800/50 bg-white/50 dark:bg-black/20 backdrop-blur-md absolute top-0 left-0 right-0 z-10">
            <h2 className="text-[11px] font-bold text-neutral-400 uppercase tracking-[0.08em]">Agent Trace</h2>
            {(appState === 'STARTING' || appState === 'RUNNING' || appState === 'PAUSED') && (
              <button onClick={abortAgent} className="text-neutral-400 hover:text-rose-600 text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5 transition-colors">
                <StopCircle className="w-3.5 h-3.5" /> Abort
              </button>
            )}
          </div>

          <div className="flex-1 overflow-y-auto pt-20 pb-6 px-6 flex flex-col gap-4 relative">

            {appState === 'IDLE' && events.length === 0 && (
              <div className="flex flex-col gap-3 px-2 py-6">
                <p className="text-sm font-semibold text-neutral-500">Ready to search</p>
                <p className="text-xs text-neutral-400">I'll:</p>
                <ul className="space-y-2">
                  {['Search rental listings', 'Compare price + bedrooms', 'Check availability', 'Rank the best matches'].map((step) => (
                    <li key={step} className="flex items-center gap-2 text-sm text-neutral-500">
                      <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" />
                      {step}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {displayEvents.map((evt, idx) => {
              // Type-guard: amenity group sentinel
              if ('_type' in evt && evt._type === 'amenity_group') {
                return (
                  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} key={`ag-${evt.address}`}>
                    <AmenityGroupCard group={evt as AmenityGroup} />
                  </motion.div>
                );
              }
              // Normal event
              return (
                <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} key={idx}>
                  <EventCard event={evt as AgentEvent} />
                </motion.div>
              );
            })}

            {(appState === 'STARTING' || appState === 'RUNNING') && (
              <div className="flex items-center gap-3 text-neutral-400 mt-2 ml-2">
                <Loader2 className="w-4 h-4 animate-spin text-emerald-600" />
                <span className="text-sm font-medium">Agent is thinking...</span>
              </div>
            )}

            <div ref={traceEndRef} className="h-4" />
          </div>

          <AnimatePresence>
            {appState === 'PAUSED' && (
              <motion.div
                initial={{ opacity: 0, y: '100%' }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: '100%' }}
                transition={{ type: 'spring', damping: 25, stiffness: 200 }}
                className="absolute bottom-4 left-4 right-4 p-5 bg-white dark:bg-neutral-900 border border-rose-100 dark:border-rose-900/50 rounded-[20px] shadow-[0_8px_30px_rgba(0,0,0,0.12)] z-20"
              >
                <div className="flex items-start gap-4 mb-4">
                  <div className="p-2 bg-rose-100 dark:bg-rose-900/50 rounded-full text-rose-600 dark:text-rose-500 shrink-0">
                    <User className="w-5 h-5" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-rose-900 dark:text-rose-400">Human Input Required</h3>
                    <p className="text-sm text-rose-700 dark:text-rose-300 mt-1 leading-relaxed">{humanPrompt}</p>
                  </div>
                </div>
                <form onSubmit={handleHumanReply} className="flex gap-2">
                  <input
                    type="text"
                    className="flex-1 px-4 py-3 bg-neutral-50 dark:bg-black border border-neutral-200 dark:border-neutral-800 rounded-xl focus:outline-none focus:ring-2 focus:ring-rose-500/30 focus:border-rose-500 transition-all text-sm"
                    placeholder="Type your response..."
                    value={userReply}
                    onChange={(e) => setUserReply(e.target.value)}
                    autoFocus
                  />
                  <button type="submit" className="px-6 py-3 bg-rose-600 hover:bg-rose-700 text-white rounded-xl text-sm font-semibold transition-colors">
                    Reply
                  </button>
                </form>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* RIGHT COLUMN: Live View */}
        <div className="flex flex-col bg-panel rounded-[24px] overflow-hidden shadow-[0_2px_8px_rgba(0,0,0,0.02),0_12px_40px_rgba(0,0,0,0.04)] border border-neutral-100 dark:border-neutral-800/50 h-full relative">
          <div className="flex items-center justify-between px-8 py-5 border-b border-neutral-100 dark:border-neutral-800/50 bg-white/50 dark:bg-black/20 backdrop-blur-md absolute top-0 left-0 right-0 z-10">
            <h2 className="text-[11px] font-bold text-neutral-400 uppercase tracking-[0.08em]">Live View</h2>
            {appState === 'RUNNING' && (
              <div className="flex items-center gap-2 text-rose-500">
                <div className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse" />
                <span className="text-[10px] font-bold tracking-[0.1em] uppercase">Live</span>
              </div>
            )}
          </div>

          <div className="flex-1 bg-[#F9F9F9] dark:bg-[#0A0A0A] relative flex items-center justify-center p-4 pt-20">
            <AnimatePresence mode="wait">
              {appState === 'IDLE' && !latestScreenshot ? (
                <motion.div key="idle" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex flex-col items-center justify-center text-neutral-400 gap-4 text-center max-w-xs">
                  <Globe2 className="w-10 h-10 stroke-[1.5] text-neutral-300" />
                  <div>
                    <p className="text-sm font-semibold text-neutral-500">Your search will appear here</p>
                    <p className="text-xs text-neutral-400 mt-1 leading-relaxed">The agent will browse listings and compare properties for you.</p>
                  </div>
                </motion.div>
              ) : appState === 'STARTING' && !latestScreenshot ? (
                <motion.div key="starting" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex flex-col items-center justify-center text-emerald-600 gap-5">
                  <Loader2 className="w-10 h-10 animate-spin stroke-[1.5]" />
                  <p className="text-sm font-medium">Launching browser...</p>
                </motion.div>
              ) : appState === 'ERROR' && !latestScreenshot ? (
                <motion.div key="error" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex flex-col items-center justify-center text-rose-400 gap-5 p-8 text-center max-w-sm">
                  <AlertTriangle className="w-12 h-12 stroke-[1.5]" />
                  <div>
                    <p className="text-base font-semibold text-rose-600 dark:text-rose-400 mb-2">Browser unavailable</p>
                    <p className="text-sm opacity-80 leading-relaxed">{errorMessage}</p>
                  </div>
                </motion.div>
              ) : latestScreenshot ? (
                <img
                  key="live-screencast"
                  src={latestScreenshot}
                  alt="Live browser state"
                  className="w-full h-full object-contain rounded-lg shadow-[0_4px_24px_rgba(0,0,0,0.06)] border border-black/5 dark:border-white/5 bg-white dark:bg-neutral-900"
                />
              ) : null}
            </AnimatePresence>
          </div>
        </div>
      </div>

      {/* ── FINAL RESULTS ── */}
      <AnimatePresence>
        {appState === 'COMPLETED' && finalResult && (
          <motion.div
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
            className="mt-10"
          >
            {/* Results header + count */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-5 pl-1">
              <div>
                <p className="text-xs font-bold text-neutral-400 uppercase tracking-[0.08em] mb-1">Results</p>
                <h2 className="text-[26px] font-semibold tracking-[-0.02em] text-neutral-900 dark:text-white">
                  {finalResult.listings.length > 0
                    ? `Found ${finalResult.listings.length} strong match${finalResult.listings.length === 1 ? '' : 'es'}.`
                    : 'Search complete.'}
                </h2>
              </div>
            </div>

            {/* Refinement chips */}
            {finalResult.listings.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-6">
                {REFINEMENT_CHIPS.map((chip) => (
                  <button
                    key={chip.label}
                    type="button"
                    onClick={() => setGoal(chip.prompt)}
                    className="text-xs px-4 py-2 rounded-full border border-neutral-200 dark:border-neutral-700 text-neutral-600 dark:text-neutral-300 bg-white dark:bg-neutral-900 hover:border-violet-400 hover:text-violet-700 dark:hover:text-violet-300 transition-colors font-medium"
                  >
                    {chip.label}
                  </button>
                ))}
              </div>
            )}

            {/* AI summary (collapsible, closed by default) */}
            {finalResult.summary && (
              <details className="mb-8 bg-panel rounded-[20px] border border-neutral-100 dark:border-neutral-800/50 shadow-[0_2px_12px_rgba(0,0,0,0.03)] group">
                <summary className="flex items-center justify-between px-8 py-5 cursor-pointer list-none">
                  <div className="flex items-center gap-3">
                    <div className="p-1.5 bg-emerald-100 dark:bg-emerald-900/40 rounded-full text-emerald-600">
                      <CheckCircle2 className="w-4 h-4" />
                    </div>
                    <span className="text-sm font-semibold text-neutral-700 dark:text-neutral-300">Agent Summary</span>
                  </div>
                  <ChevronDown className="w-4 h-4 text-neutral-400 group-open:rotate-180 transition-transform" />
                </summary>
                <div className="px-8 pb-8 text-base leading-relaxed border-t border-neutral-100 dark:border-neutral-800/50 pt-6">
                  <ReactMarkdown
                    components={{
                      h3: ({ node, children, ...props }) => {
                        const text = String(children);
                        const badgeMatch = text.match(/\b(Best Value|Best Pick|Top Pick|Highest Price|Budget Pick|Recommended|Most Space|Lowest Price)\b/i);
                        const cleanTitle = badgeMatch ? text.replace(badgeMatch[0], '').replace(/[-–—·|]\s*$/, '').trim() : text;
                        return (
                          <div className="flex flex-wrap items-baseline gap-3 mt-8 mb-3 first:mt-0 pb-3 border-b border-neutral-100 dark:border-neutral-800/60">
                            <h3 className="text-base font-bold text-neutral-900 dark:text-white leading-snug">{cleanTitle}</h3>
                            {badgeMatch && (
                              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-bold tracking-wide bg-emerald-100 dark:bg-emerald-900/40 text-emerald-800 dark:text-emerald-300 uppercase">
                                {badgeMatch[0]}
                              </span>
                            )}
                          </div>
                        );
                      },
                      h2: ({ node, ...props }) => <h2 className="text-lg font-bold text-neutral-900 dark:text-white mt-8 mb-3 first:mt-0" {...props} />,
                      strong: ({ node, ...props }) => <strong className="font-semibold text-neutral-900 dark:text-white" {...props} />,
                      p: ({ node, children, ...props }) => {
                        const text = String(children);
                        if (/^[òò•·\-–—*]\s/.test(text.trim())) {
                          const content = text.trim().replace(/^[òò•·\-–—*]\s*/, '');
                          return (
                            <li className="flex items-start gap-2 text-sm text-neutral-600 dark:text-neutral-400 leading-relaxed">
                              <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-neutral-300 dark:bg-neutral-600 shrink-0" />
                              <span>{content}</span>
                            </li>
                          );
                        }
                        return <p className="text-sm text-neutral-600 dark:text-neutral-400 mb-3 last:mb-0" {...props} />;
                      },
                      ul: ({ node, ...props }) => <ul className="space-y-2 mb-4" {...props} />,
                      ol: ({ node, ...props }) => <ol className="space-y-2 mb-4 list-decimal pl-4" {...props} />,
                      li: ({ node, ...props }) => (
                        <li className="flex items-start gap-2 text-sm text-neutral-600 dark:text-neutral-400 leading-relaxed">
                          <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-neutral-300 dark:bg-neutral-600 shrink-0" />
                          <span {...props} />
                        </li>
                      ),
                      hr: () => null,
                    }}
                  >
                    {finalResult.summary
                      .replace(/^\s*[òò•]\s+/gm, '- ')
                      .replace(/^\s*---\s*$/gm, '')
                    }
                  </ReactMarkdown>
                </div>
              </details>
            )}

            {/* Property cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {finalResult.listings.map((listing: any, idx: number) => (
                <motion.div
                  key={idx}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: idx * 0.1, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
                  className="flex flex-col"
                >
                  <ListingCard listing={listing} />
                  {/* Why this property — only when we have enough real fields to say something meaningful */}
                  {(() => {
                    const parts: string[] = [];
                    if (listing.beds) parts.push(`${listing.beds}-bedroom`);
                    if (listing.price) parts.push(`$${listing.price.toLocaleString()}/mo`);
                    if (listing.address && listing.address.toLowerCase() !== 'not found') {
                      const cityMatch = listing.address.match(/,\s*([^,]+),\s*[A-Z]{2}/);
                      if (cityMatch) parts.push(`in ${cityMatch[1].trim()}`);
                    }
                    if (parts.length < 2) return null;
                    return (
                      <div className="mt-3 px-4 py-3 bg-white dark:bg-neutral-900 border border-neutral-100 dark:border-neutral-800/50 rounded-[14px] text-xs text-neutral-500 leading-relaxed">
                        <span className="font-semibold text-neutral-600 dark:text-neutral-400">Why this property? </span>
                        {`${parts.join(' · ')} listing.`}
                      </div>
                    );
                  })()}
                </motion.div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </main>
  );
}
