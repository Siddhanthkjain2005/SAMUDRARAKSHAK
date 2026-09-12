"use client";

import {
  forwardRef, useCallback, useEffect, useId, useImperativeHandle, useMemo,
  useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent,
} from "react";
import type {
  MapCoordinate, MapGeography, MapGeometry, MapPosition, MapVessel,
  OceanMapHandle, OceanMapProps,
} from "../lib/map-types";

type Camera = { latitude: number; longitude: number; zoom: number };
type Pixel = { x: number; y: number };
type MapListener = { remove(): void };
type GoogleMap = {
  moveCamera(options: { center: { lat: number; lng: number }; zoom: number }): void;
  getCenter(): { lat(): number; lng(): number } | undefined;
  getZoom(): number | undefined;
  addListener(event: string, callback: () => void): MapListener;
};
type Map3D = HTMLElement & {
  center: { lat: number; lng: number; altitude?: number };
  range: number;
  flyCameraTo?: (options: Record<string, unknown>) => void;
  flyCameraAround?: (options: Record<string, unknown>) => void;
};
type Map3DMarker = HTMLElement & { position: { lat: number; lng: number; altitude?: number } };
type Maps3DLibrary = {
  Map3DElement?: new (options: Record<string, unknown>) => Map3D;
  Marker3DInteractiveElement?: new (options: Record<string, unknown>) => Map3DMarker;
  Marker3DElement?: new (options: Record<string, unknown>) => Map3DMarker;
  Polyline3DElement?: new (options: Record<string, unknown>) => HTMLElement & { coordinates: { lat: number; lng: number }[] };
};
type MapsRuntime = {
  Map?: new (element: HTMLElement, options: Record<string, unknown>) => GoogleMap;
  importLibrary?: (name: string) => Promise<unknown>;
};
type MapWindow = Window & { google?: { maps?: MapsRuntime }; gm_authFailure?: () => void; __samudraMapsReady?: () => void };

const DEFAULT_CAMERA: Camera = { latitude: 14.35, longitude: 72.8, zoom: 6.65 };
const INDIA_CAMERA: Camera = { latitude: 20.5, longitude: 76.5, zoom: 4.7 };
let hasPlayedMapIntro = false;
const EMPTY: never[] = [];
const MAP_COLORS = { teal: "#56ddc0", blue: "#77b7ec", amber: "#f0bc72", purple: "#c3a9ef" };
const clamp = (n: number, low: number, high: number) => Math.min(high, Math.max(low, n));
const ease = (x: number) => x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
const validPosition = (p: MapPosition) => Number.isFinite(p.latitude) && Number.isFinite(p.longitude) && Math.abs(p.latitude) <= 90 && Math.abs(p.longitude) <= 180;
const routeBearing = (a: MapCoordinate, b: MapCoordinate) => {
  const toRad = Math.PI / 180;
  const longitudeDelta = (b[0] - a[0]) * toRad;
  const y = Math.sin(longitudeDelta) * Math.cos(b[1] * toRad);
  const x = Math.cos(a[1] * toRad) * Math.sin(b[1] * toRad) - Math.sin(a[1] * toRad) * Math.cos(b[1] * toRad) * Math.cos(longitudeDelta);
  return (Math.atan2(y, x) / toRad + 360) % 360;
};

/** Spherical Web Mercator: shared by the cached chart and the standard Google map. */
function worldPoint(longitude: number, latitude: number): Pixel {
  const sine = Math.sin(clamp(latitude, -85, 85) * Math.PI / 180);
  return { x: (longitude + 180) / 360 * 256, y: (0.5 - Math.log((1 + sine) / (1 - sine)) / (4 * Math.PI)) * 256 };
}

function unproject(x: number, y: number): MapPosition {
  return { longitude: x / 256 * 360 - 180, latitude: Math.atan(Math.sinh(Math.PI * (1 - 2 * y / 256))) * 180 / Math.PI };
}

function geometryPath(geography: MapGeography): string {
  const ring = (points: number[][]) => points.filter(p => p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1])).map((p, i) => {
    const q = worldPoint(p[0], p[1]);
    return `${i ? "L" : "M"}${q.x.toFixed(5)},${q.y.toFixed(5)}`;
  }).join("");
  const geometry = (g: MapGeometry | null): string => {
    if (!g) return "";
    if (g.type === "Polygon") return (g.coordinates as number[][][]).map(p => ring(p) + "Z").join("");
    if (g.type === "MultiPolygon") return (g.coordinates as number[][][][]).map(p => p.map(r => ring(r) + "Z").join("")).join("");
    if (g.type === "LineString") return ring(g.coordinates as number[][]);
    if (g.type === "MultiLineString") return (g.coordinates as number[][][]).map(ring).join("");
    if (g.type === "GeometryCollection") return (g.geometries || []).map(geometry).join("");
    return "";
  };
  if (geography.features) return geography.features.map(feature => geometry(feature.geometry)).join("");
  return geometry(geography.geometry || geography as MapGeometry);
}

function geographyBounds(geography: MapGeography | null | undefined) {
  const bounds = { west: 180, east: -180, south: 90, north: -90 };
  const visit = (value: unknown): void => {
    if (!Array.isArray(value)) return;
    if (value.length >= 2 && typeof value[0] === "number" && typeof value[1] === "number") {
      bounds.west = Math.min(bounds.west, value[0]); bounds.east = Math.max(bounds.east, value[0]);
      bounds.south = Math.min(bounds.south, value[1]); bounds.north = Math.max(bounds.north, value[1]);
    } else value.forEach(visit);
  };
  if (geography?.features) geography.features.forEach(feature => visit(feature.geometry?.coordinates));
  else visit(geography?.geometry?.coordinates || geography?.coordinates);
  return bounds.east >= bounds.west ? bounds : null;
}

let mapsScriptPromise: Promise<MapsRuntime> | undefined;
function loadGoogleMaps(key: string): Promise<MapsRuntime> {
  const scope = window as MapWindow;
  if (scope.google?.maps?.Map) return Promise.resolve(scope.google.maps);
  if (mapsScriptPromise) return mapsScriptPromise;
  mapsScriptPromise = new Promise<MapsRuntime>((resolve, reject) => {
    const script = document.createElement("script");
    const timer = window.setTimeout(() => reject(new Error("Google Maps connection timed out")), 14000);
    scope.__samudraMapsReady = () => {
      window.clearTimeout(timer);
      if (scope.google?.maps) resolve(scope.google.maps);
      else reject(new Error("Google Maps unavailable"));
    };
    script.src = `https://maps.googleapis.com/maps/api/js?${new URLSearchParams({ key, loading: "async", callback: "__samudraMapsReady", v: "weekly" })}`;
    script.async = true;
    script.onerror = () => { window.clearTimeout(timer); reject(new Error("Google Maps connection unavailable")); };
    document.head.append(script);
  }).catch(error => { mapsScriptPromise = undefined; throw error; });
  return mapsScriptPromise;
}

const GOOGLE_STYLE = [
  { elementType: "geometry", stylers: [{ color: "#1b3033" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#708e90" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#17282d" }, { weight: 3 }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#091d2b" }] },
  { featureType: "landscape.natural", elementType: "geometry", stylers: [{ color: "#233537" }] },
  { featureType: "administrative", elementType: "geometry.stroke", stylers: [{ color: "#466260" }, { weight: 0.6 }] },
  { featureType: "road", stylers: [{ visibility: "off" }] },
  { featureType: "poi", stylers: [{ visibility: "off" }] },
  { featureType: "transit", stylers: [{ visibility: "off" }] },
  { featureType: "administrative.land_parcel", stylers: [{ visibility: "off" }] },
];

function MapIcon({ kind }: { kind: "plus" | "minus" | "reset" | "globe" | "compass" | "layers" }) {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
    {kind === "plus" && <path d="M12 5v14M5 12h14" />}
    {kind === "minus" && <path d="M5 12h14" />}
    {kind === "reset" && <><circle cx="12" cy="12" r="6" /><path d="M12 2v4m0 12v4M2 12h4m12 0h4" /><circle cx="12" cy="12" r="1" fill="currentColor" /></>}
    {kind === "globe" && <><circle cx="12" cy="12" r="9" /><ellipse cx="12" cy="12" rx="4" ry="9" /><path d="M3 12h18M5 6.5c4 2 10 2 14 0M5 17.5c4-2 10-2 14 0" /></>}
    {kind === "compass" && <><circle cx="12" cy="12" r="9" /><path d="m15.5 8.5-2 5-5 2 2-5z" /><path d="m15.5 8.5-5 2 3 3z" fill="currentColor" /></>}
    {kind === "layers" && <><path d="m3 8 9-5 9 5-9 5zM3 12l9 5 9-5M3 16l9 5 9-5" /></>}
  </svg>;
}

const OceanMap = forwardRef<OceanMapHandle, OceanMapProps>(function OceanMap({
  googleMapsKey, vessels = EMPTY, ports = EMPTY, hotspots = EMPTY, route, marine = EMPTY,
  collectors = EMPTY, mission = "overview", selectedVesselId, onVesselSelect, onHotspotSelect,
  onPortSelect, onCameraChange, focus, layers: layerOverrides, geography, worldGeography, boundaries, protectedAreas, controlInsets, className = "", hideLegend = false, cinematicIntro = true,
}, ref) {
  const uid = useId().replace(/:/g, "");
  const rootRef = useRef<HTMLDivElement>(null);
  const googleContainer = useRef<HTMLDivElement>(null);
  const threeContainer = useRef<HTMLDivElement>(null);
  const mapInstance = useRef<GoogleMap | null>(null);
  const threeMap = useRef<Map3D | null>(null);
  const threeLibrary = useRef<Maps3DLibrary | null>(null);
  const [dimensions, setDimensions] = useState({ width: 1200, height: 800 });
  const [panelInsets, setPanelInsets] = useState({ left: 0, right: 0 });
  const [camera, setCamera] = useState<Camera>(() => cinematicIntro && !hasPlayedMapIntro && !focus ? INDIA_CAMERA : DEFAULT_CAMERA);
  const playIntro = useRef(cinematicIntro && !hasPlayedMapIntro && !focus);
  const cameraRef = useRef(camera);
  const cameraAnimation = useRef(0);
  const introTimer = useRef<number | null>(null);
  const viewGeometryRef = useRef({ dimensions, left: 0, right: 0 });
  viewGeometryRef.current = { dimensions, left: controlInsets?.left ?? panelInsets.left, right: controlInsets?.right ?? panelInsets.right };
  const onCameraChangeRef = useRef(onCameraChange);
  onCameraChangeRef.current = onCameraChange;
  const [localGeography, setLocalGeography] = useState<MapGeography | null>(null);
  const [localWorldGeography, setLocalWorldGeography] = useState<MapGeography | null>(null);
  const [worldStatus, setWorldStatus] = useState<"loading" | "loaded" | "unavailable">("loading");
  const [localBoundaries, setLocalBoundaries] = useState<MapGeography | null>(null);
  const [localProtectedAreas, setLocalProtectedAreas] = useState<MapGeography | null>(null);
  const [engine, setEngine] = useState<"offline" | "google" | "3d">("offline");
  const engineRef = useRef(engine);
  const [googleStatus, setGoogleStatus] = useState("Cached geographic chart");
  const [threeStatus, setThreeStatus] = useState<"idle" | "loading" | "available" | "unavailable">("idle");
  const [chartMode, setChartMode] = useState(false);
  const [internalLayers, setInternalLayers] = useState({ vessels: true, ports: true, currents: true, debris: true, boundaries: true, routes: true, grid: true });
  const [showLayerMenu, setShowLayerMenu] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);
  const [following, setFollowing] = useState<string | null>(null);
  const [positions, setPositions] = useState<Record<string, MapPosition & { heading: number }>>({});
  const [retiredRoutes, setRetiredRoutes] = useState<{ id: string; coordinates: MapCoordinate[] }[]>([]);
  const previousCollectorRoutes = useRef<{ id: string; coordinates: MapCoordinate[] }[]>([]);
  const positionsRef = useRef(positions);
  const [cursorCoordinates, setCursorCoordinates] = useState<MapPosition | null>(null);
  const drag = useRef<{ x: number; y: number; camera: Camera } | null>(null);
  const layers = { ...internalLayers, ...layerOverrides, debris: layerOverrides?.debris ?? layerOverrides?.hotspots ?? internalLayers.debris };
  const validVessels = useMemo(() => vessels.filter(validPosition).slice(0, 700), [vessels]);
  const vesselPositionsKey = validVessels.map(v => `${v.id}:${v.latitude}:${v.longitude}:${v.heading ?? ""}`).join("|");
  const followingVessel = validVessels.find(v => v.id === following);
  const validPorts = useMemo(() => ports.filter(validPosition), [ports]);
  const validHotspots = useMemo(() => hotspots.filter(validPosition).slice(0, 250), [hotspots]);
  const validMarine = useMemo(() => {
    const unique = new Map<string, typeof marine[number]>();
    marine.forEach(sample => {
      if (!validPosition(sample) || sample.current_velocity == null || sample.current_direction == null || !Number.isFinite(sample.current_velocity) || !Number.isFinite(sample.current_direction) || sample.current_velocity < 0) return;
      const key = `${sample.latitude.toFixed(6)},${sample.longitude.toFixed(6)}`;
      const previous = unique.get(key);
      if (!previous || Date.parse(sample.timestamp || "") > Date.parse(previous.timestamp || "")) unique.set(key, sample);
    });
    return [...unique.values()];
  }, [marine]);
  const collectorRoutesKey = collectors.map(c => `${c.id}:${JSON.stringify(c.route || [])}`).join("|");
  const landPath = useMemo(() => {
    try { return (geography || localGeography) ? geometryPath((geography || localGeography)!) : ""; }
    catch { return ""; }
  }, [geography, localGeography]);
  const regionBounds = useMemo(() => geographyBounds(geography || localGeography), [geography, localGeography]);
  const worldLandPath = useMemo(() => {
    try { return (worldGeography || localWorldGeography) ? geometryPath((worldGeography || localWorldGeography)!) : ""; }
    catch { return ""; }
  }, [worldGeography, localWorldGeography]);
  const boundaryPaths = useMemo(() => {
    const features = (boundaries || localBoundaries)?.features || [];
    return features.flatMap((feature, index) => {
      if (!feature.geometry) return [];
      try { return [{ id: String(feature.properties?.id || index), path: geometryPath({ type: "Feature", geometry: feature.geometry }), name: String(feature.properties?.name || feature.properties?.geoname || "Marine boundary"), kind: String(feature.properties?.kind || "eez") }]; }
      catch { return []; }
    });
  }, [boundaries, localBoundaries]);
  const protectedPath = useMemo(() => {
    try { return (protectedAreas || localProtectedAreas) ? geometryPath((protectedAreas || localProtectedAreas)!) : ""; }
    catch { return ""; }
  }, [protectedAreas, localProtectedAreas]);
  const worldScale = Math.pow(2, camera.zoom);
  const center = worldPoint(camera.longitude, camera.latitude);
  const project = useCallback((latitude: number, longitude: number): Pixel => {
    const p = worldPoint(longitude, latitude);
    return { x: (p.x - center.x) * worldScale + dimensions.width / 2, y: (p.y - center.y) * worldScale + dimensions.height / 2 };
  }, [center.x, center.y, worldScale, dimensions]);
  const pathFromCoordinates = (coordinates: MapCoordinate[] = []) => coordinates.filter(p => Number.isFinite(p[0]) && Number.isFinite(p[1])).map(([lon, lat], index) => {
    const point = project(lat, lon); return `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`;
  }).join(" ");
  const inView = (p: Pixel, margin = 90) => p.x > -margin && p.x < dimensions.width + margin && p.y > -margin && p.y < dimensions.height + margin;
  const visibleMarine = validMarine.filter(sample => inView(project(sample.latitude, sample.longitude), 50)).slice(0, 200);

  useEffect(() => {
    engineRef.current = engine;
  }, [engine]);

  useEffect(() => {
    if (!rootRef.current) return;
    const host = rootRef.current.closest(".operations");
    const leftPanel = host?.querySelector(".left-panel");
    const rightPanel = host?.querySelector(".right-panel");
    const measure = () => {
      if (!rootRef.current) return;
      const rect = rootRef.current.getBoundingClientRect();
      if (rect.width && rect.height) setDimensions(previous => previous.width === rect.width && previous.height === rect.height ? previous : { width: rect.width, height: rect.height });
      const left = leftPanel?.getBoundingClientRect();
      const right = rightPanel?.getBoundingClientRect();
      const overlaps = (r?: DOMRect) => r && r.top < rect.bottom - 40 && r.bottom > rect.top + 40;
      const next = { left: overlaps(left) ? Math.max(0, left!.right - rect.left) : 0, right: overlaps(right) ? Math.max(0, rect.right - right!.left) : 0 };
      setPanelInsets(previous => previous.left === next.left && previous.right === next.right ? previous : next);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(rootRef.current);
    if (leftPanel) observer.observe(leftPanel);
    if (rightPanel) observer.observe(rightPanel);
    measure();
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (geography) return;
    const controller = new AbortController();
    (async () => {
      for (const url of ["/api/map/land", "/data/land.geojson"]) {
        try {
          const response = await fetch(url, { signal: controller.signal });
          if (!response.ok) continue;
          const result = await response.json();
          if (result.type && (result.features || result.coordinates || result.geometry)) { setLocalGeography(result); break; }
        } catch { if (controller.signal.aborted) break; }
      }
    })();
    return () => controller.abort();
  }, [geography]);

  useEffect(() => {
    if (worldGeography) { setWorldStatus("loaded"); return; }
    const controller = new AbortController();
    (async () => {
      for (const url of ["/api/map/land_world", "/data/land_world.geojson"]) {
        try {
          const response = await fetch(url, { signal: controller.signal });
          if (!response.ok) continue;
          const result = await response.json();
          if (result.type === "FeatureCollection" && Array.isArray(result.features)) { setLocalWorldGeography(result); setWorldStatus("loaded"); return; }
        } catch { if (controller.signal.aborted) return; }
      }
      setWorldStatus("unavailable");
    })();
    return () => controller.abort();
  }, [worldGeography]);

  useEffect(() => {
    const controller = new AbortController();
    const load = async (name: string, setter: (value: MapGeography) => void) => {
      for (const url of [`/api/map/${name}`, `/data/${name}.geojson`]) {
        try {
          const response = await fetch(url, { signal: controller.signal });
          if (!response.ok) continue;
          const result = await response.json();
          if (result.type === "FeatureCollection" && Array.isArray(result.features)) { setter(result); break; }
        } catch { if (controller.signal.aborted) break; }
      }
    };
    void Promise.allSettled([boundaries ? Promise.resolve() : load("boundaries", setLocalBoundaries), protectedAreas ? Promise.resolve() : load("mpa", setLocalProtectedAreas)]);
    return () => controller.abort();
  }, [boundaries, protectedAreas]);

  const applyCamera = useCallback((next: Camera, syncGoogle = true) => {
    const safe = { latitude: clamp(next.latitude, -78, 78), longitude: clamp(next.longitude, -180, 180), zoom: clamp(next.zoom, 2, 13) };
    cameraRef.current = safe;
    setCamera(safe);
    if (syncGoogle && mapInstance.current && engineRef.current === "google") {
      mapInstance.current.moveCamera({ center: { lat: safe.latitude, lng: safe.longitude }, zoom: safe.zoom });
    }
  }, []);

  const flyTo = useCallback((position: MapPosition, zoom = 7.5, duration = 1400, frameTarget = true) => {
    if (!validPosition(position)) return;
    if (introTimer.current) { window.clearTimeout(introTimer.current); introTimer.current = null; }
    cancelAnimationFrame(cameraAnimation.current);
    const from = cameraRef.current;
    const target = { ...position };
    // Offset the camera so its subject lands in the visible chart between overlay panels.
    if (frameTarget) {
      const { left, right } = viewGeometryRef.current;
      const world = worldPoint(position.longitude, position.latitude);
      const centered = unproject(world.x - ((left - right) / 2) / Math.pow(2, zoom), world.y);
      target.latitude = centered.latitude; target.longitude = centered.longitude;
    }
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (threeMap.current && engineRef.current === "3d") {
      threeMap.current.flyCameraTo?.({ endCamera: { center: { lat: target.latitude, lng: target.longitude, altitude: 0 }, range: 1800000 / Math.pow(2, zoom - 5), tilt: 45, heading: 0 }, durationMillis: reducedMotion ? 0 : duration });
    }
    if (reducedMotion) { applyCamera({ ...target, zoom }); return; }
    const start = performance.now();
    const frame = (time: number) => {
      const t = clamp((time - start) / duration, 0, 1);
      const e = ease(t);
      applyCamera({ latitude: from.latitude + (target.latitude - from.latitude) * e, longitude: from.longitude + (target.longitude - from.longitude) * e, zoom: from.zoom + (zoom - from.zoom) * e });
      if (t < 1) cameraAnimation.current = requestAnimationFrame(frame);
    };
    cameraAnimation.current = requestAnimationFrame(frame);
  }, [applyCamera]);

  useEffect(() => {
    if (!playIntro.current) return;
    hasPlayedMapIntro = true;
    introTimer.current = window.setTimeout(() => flyTo(DEFAULT_CAMERA, DEFAULT_CAMERA.zoom, 2400), 450);
    return () => { if (introTimer.current) window.clearTimeout(introTimer.current); };
  // Play the opening once per application session. A camera command cancels it.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => onCameraChangeRef.current?.(camera), 160);
    return () => window.clearTimeout(timer);
  }, [camera.latitude, camera.longitude, camera.zoom]);

  const fitPoints = useCallback((points: MapPosition[]) => {
    const valid = points.filter(validPosition);
    if (!valid.length) { flyTo(DEFAULT_CAMERA, DEFAULT_CAMERA.zoom); return; }
    const latitude = (Math.min(...valid.map(p => p.latitude)) + Math.max(...valid.map(p => p.latitude))) / 2;
    const longitude = (Math.min(...valid.map(p => p.longitude)) + Math.max(...valid.map(p => p.longitude))) / 2;
    const projected = valid.map(p => worldPoint(p.longitude, p.latitude));
    const spanX = Math.max(...projected.map(p => p.x)) - Math.min(...projected.map(p => p.x));
    const spanY = Math.max(...projected.map(p => p.y)) - Math.min(...projected.map(p => p.y));
    const view = viewGeometryRef.current;
    const zoom = Math.min(Math.log2(Math.max(160, dimensions.width - view.left - view.right - 130) / Math.max(spanX, 0.1)), Math.log2(Math.max(200, dimensions.height - 210) / Math.max(spanY, 0.1)), 9);
    flyTo({ latitude, longitude }, clamp(zoom, 2, 10));
  }, [dimensions, flyTo]);

  useImperativeHandle(ref, () => ({
    flyToIndia: () => { setFollowing(null); flyTo({ latitude: 19.8, longitude: 77.5 }, 4.6, 2200); },
    flyToKarnatakaCoast: () => { setFollowing(null); flyTo(DEFAULT_CAMERA, DEFAULT_CAMERA.zoom, 1800); },
    flyToRoute: (origin, destination) => {
      setFollowing(null);
      if (origin && destination) fitPoints([origin, destination]);
      else fitPoints((route?.optimized?.coordinates || route?.baseline?.coordinates || []).map(([longitude, latitude]) => ({ latitude, longitude })));
    },
    followVessel: id => { const vessel = validVessels.find(v => v.id === id); if (vessel) { setFollowing(id); flyTo(vessel, 8.2); } },
    orbitInvestigation: location => {
      setFollowing(null);
      if (threeMap.current && engineRef.current === "3d") {
        threeMap.current.flyCameraAround?.({ camera: { center: { lat: location.latitude, lng: location.longitude, altitude: 0 }, range: 35000, tilt: 55 }, durationMillis: 14000, repeatCount: 1 });
      } else flyTo(location, 8.2, 1800);
    },
    flyToDebrisHotspot: id => { const hotspot = validHotspots.find(h => h.id === id); if (hotspot) { setFollowing(null); flyTo(hotspot, 7.8); } },
    showWholeMissionArea: () => { setFollowing(null); fitPoints([...validVessels, ...validHotspots].length ? [...validVessels, ...validHotspots] : validPorts); },
  }), [flyTo, fitPoints, route, validVessels, validHotspots, validPorts]);

  useEffect(() => {
    if (focus && validPosition(focus)) { setFollowing(null); flyTo(focus, focus.zoom || 7.8); }
  // Camera commands deliberately run only when a new focus target arrives.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.latitude, focus?.longitude, focus?.zoom, focus?.id]);

  useEffect(() => () => cancelAnimationFrame(cameraAnimation.current), []);

  useEffect(() => {
    const next = collectors.filter(c => c.route?.length).map(c => ({ id: c.id, coordinates: c.route! }));
    const retired = previousCollectorRoutes.current.filter(previous => !next.some(current => current.id === previous.id && JSON.stringify(current.coordinates) === JSON.stringify(previous.coordinates)));
    previousCollectorRoutes.current = next;
    setRetiredRoutes(retired);
    if (!retired.length) return;
    const timer = window.setTimeout(() => setRetiredRoutes([]), 5500);
    return () => window.clearTimeout(timer);
  // Progress changes do not change a collector's assigned route.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collectorRoutesKey]);

  // Interpolate only between observed positions; never extrapolate invented AIS points.
  useEffect(() => {
    const previous = positionsRef.current;
    const start = performance.now();
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let animation = 0;
    let lastPaint = 0;
    const frame = (time: number) => {
      const progress = reducedMotion ? 1 : clamp((time - start) / 1800, 0, 1);
      if (time - lastPaint > 40 || progress === 1) {
        const next: typeof positions = {};
        validVessels.forEach(vessel => {
          const old = previous[vessel.id] || { ...vessel, heading: vessel.heading ?? 0 };
          const heading = vessel.heading != null && vessel.heading < 360 ? vessel.heading : old.heading;
          const delta = ((heading - old.heading + 540) % 360) - 180;
          next[vessel.id] = { latitude: old.latitude + (vessel.latitude - old.latitude) * ease(progress), longitude: old.longitude + (vessel.longitude - old.longitude) * ease(progress), heading: old.heading + delta * ease(progress) };
        });
        positionsRef.current = next;
        setPositions(next);
        lastPaint = time;
      }
      if (progress < 1) animation = requestAnimationFrame(frame);
    };
    animation = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(animation);
  // Identity and metadata refreshes do not restart motion for unchanged positions.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vesselPositionsKey]);

  useEffect(() => {
    if (!following) return;
    if (followingVessel) flyTo(followingVessel, Math.max(cameraRef.current.zoom, 7.8), 1700);
  // Follow only changes to this vessel, rather than unrelated AIS packets.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [following, followingVessel?.latitude, followingVessel?.longitude, flyTo]);

  useEffect(() => {
    if (!googleMapsKey || !googleContainer.current) return;
    let active = true;
    let listener: MapListener | undefined;
    let tileListener: MapListener | undefined;
    let observer: MutationObserver | undefined;
    let failed = false;
    let googleReady = false;
    const scope = window as MapWindow;
    const previousAuthFailure = scope.gm_authFailure;
    const fallback = () => {
      if (!active) return;
      failed = true;
      setEngine("offline");
      engineRef.current = "offline";
      setGoogleStatus("Google unavailable · real-data chart active");
      setThreeStatus("unavailable");
    };
    scope.gm_authFailure = fallback;
    setGoogleStatus("Connecting Google Maps");
    loadGoogleMaps(googleMapsKey).then(runtime => {
      if (!active || !runtime.Map || !googleContainer.current) return;
      const map = new runtime.Map(googleContainer.current, {
        center: { lat: cameraRef.current.latitude, lng: cameraRef.current.longitude }, zoom: cameraRef.current.zoom,
        disableDefaultUI: true, styles: GOOGLE_STYLE, backgroundColor: "#091d2b", mapTypeId: "roadmap",
        gestureHandling: "greedy", clickableIcons: false, tilt: 0, minZoom: 2, maxZoom: 13,
        isFractionalZoomEnabled: true, keyboardShortcuts: false,
      });
      mapInstance.current = map;
      tileListener = map.addListener("tilesloaded", () => {
        if (active && !failed && engineRef.current !== "3d" && !googleContainer.current?.querySelector(".gm-err-container")) {
          if (!googleReady) {
            googleReady = true;
            const current = cameraRef.current;
            map.moveCamera({ center: { lat: current.latitude, lng: current.longitude }, zoom: current.zoom });
          }
          setEngine("google"); engineRef.current = "google"; setGoogleStatus("Google Maps · connected");
        }
      });
      listener = map.addListener("bounds_changed", () => {
        if (engineRef.current !== "google") return;
        const current = map.getCenter();
        if (current) applyCamera({ latitude: current.lat(), longitude: current.lng(), zoom: map.getZoom() || 6.65 }, false);
      });
      observer = new MutationObserver(() => { if (googleContainer.current?.querySelector(".gm-err-container")) fallback(); });
      observer.observe(googleContainer.current, { childList: true, subtree: true });
    }).catch(fallback);
    return () => {
      active = false; listener?.remove(); tileListener?.remove(); observer?.disconnect();
      scope.gm_authFailure = previousAuthFailure;
    };
  }, [googleMapsKey, applyCamera]);

  const activate3D = async () => {
    if (engine === "3d") { setEngine(mapInstance.current ? "google" : "offline"); return; }
    const runtime = (window as MapWindow).google?.maps;
    if (!runtime?.importLibrary || !threeContainer.current) { setThreeStatus("unavailable"); return; }
    setThreeStatus("loading");
    try {
      const canvas = document.createElement("canvas");
      if (!canvas.getContext("webgl2") && !canvas.getContext("webgl")) throw new Error("WebGL unavailable");
      const library = await runtime.importLibrary("maps3d") as Maps3DLibrary;
      if (!library.Map3DElement) throw new Error("3D library unavailable");
      threeLibrary.current = library;
      if (!threeMap.current) {
        const map = new library.Map3DElement({
          center: { lat: cameraRef.current.latitude, lng: cameraRef.current.longitude, altitude: 0 },
          range: 1800000 / Math.pow(2, cameraRef.current.zoom - 5), tilt: 45, heading: 0,
          mode: "HYBRID", gestureHandling: "GREEDY",
        });
        map.style.width = "100%"; map.style.height = "100%";
        let initialised = false;
        const fallback = () => {
          setEngine(mapInstance.current ? "google" : "offline");
          setThreeStatus("unavailable");
        };
        const timeout = window.setTimeout(() => { if (!initialised) fallback(); }, 18000);
        map.addEventListener("gmp-steadychange", () => { initialised = true; window.clearTimeout(timeout); });
        map.addEventListener("gmp-error", () => { window.clearTimeout(timeout); fallback(); });
        const updateCamera = () => {
          if (engineRef.current !== "3d" || !map.center) return;
          applyCamera({ latitude: map.center.lat, longitude: map.center.lng, zoom: Math.log2(1800000 / Math.max(map.range, 1)) + 5 }, false);
        };
        map.addEventListener("gmp-centerchange", updateCamera);
        map.addEventListener("gmp-rangechange", updateCamera);
        threeContainer.current.replaceChildren(map);
        threeMap.current = map;
      }
      setThreeStatus("available"); setEngine("3d");
    } catch { setThreeStatus("unavailable"); }
  };

  useEffect(() => {
    if (engine !== "3d" || !threeMap.current || !threeLibrary.current) return;
    const map = threeMap.current;
    const library = threeLibrary.current;
    const Marker = library.Marker3DInteractiveElement || library.Marker3DElement;
    const elements: HTMLElement[] = [];
    if (Marker) {
      const addMarker = (position: MapPosition, label: string, onClick?: () => void) => {
        const marker = new Marker({ position: { lat: position.latitude, lng: position.longitude, altitude: 40 }, label, altitudeMode: "RELATIVE_TO_GROUND", extruded: true });
        if (onClick) marker.addEventListener("gmp-click", onClick);
        map.append(marker); elements.push(marker);
      };
      if (layers.vessels) validVessels.slice(0, 160).forEach(v => addMarker(v, `${v.name} · ${v.provenance || "SOURCE NOT SPECIFIED"}`, () => onVesselSelect?.(v)));
      if (layers.ports) validPorts.slice(0, 80).forEach(p => addMarker(p, p.name, () => onPortSelect?.(p)));
      if (layers.debris) validHotspots.slice(0, 80).forEach(h => addMarker(h, `${h.count ?? 0} debris observations`, () => onHotspotSelect?.(h)));
      collectors.filter(validPosition).forEach(c => addMarker(c, `${c.name || c.id} · SIMULATED ASSET`));
    }
    if (library.Polyline3DElement && layers.routes) {
      ([route?.baseline, route?.optimized] as const).forEach((item, index) => {
        if (!item?.coordinates.length) return;
        const polyline = new library.Polyline3DElement!({ strokeColor: index ? "#56ddc0" : "#a0aeb9", strokeWidth: index ? 5 : 3, altitudeMode: "CLAMP_TO_GROUND" });
        polyline.coordinates = item.coordinates.map(([lng, lat]) => ({ lat, lng }));
        map.append(polyline); elements.push(polyline);
      });
    }
    return () => elements.forEach(element => element.remove());
  }, [engine, validVessels, validPorts, validHotspots, collectors, route, layers.vessels, layers.ports, layers.debris, layers.routes, onVesselSelect, onPortSelect, onHotspotSelect]);

  const zoomBy = useCallback((delta: number) => {
    setFollowing(null);
    flyTo(cameraRef.current, cameraRef.current.zoom + delta, 400, false);
  }, [flyTo]);

  useEffect(() => {
    const element = rootRef.current;
    if (!element) return;
    const onWheel = (event: WheelEvent) => {
      if (engineRef.current !== "offline" && !chartMode) return;
      if ((event.target as Element).closest("button, .ocean-layer-menu")) return;
      event.preventDefault();
      cancelAnimationFrame(cameraAnimation.current);
      setFollowing(null);
      applyCamera({ ...cameraRef.current, zoom: cameraRef.current.zoom + clamp(-event.deltaY * 0.002, -0.4, 0.4) });
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, [applyCamera, chartMode]);

  const pointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if ((engine !== "offline" && !chartMode) || (event.target as Element).closest("[data-map-item], button, .ocean-layer-menu")) return;
    if (introTimer.current) { window.clearTimeout(introTimer.current); introTimer.current = null; }
    cancelAnimationFrame(cameraAnimation.current);
    setFollowing(null);
    drag.current = { x: event.clientX, y: event.clientY, camera: cameraRef.current };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const pointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const rect = rootRef.current?.getBoundingClientRect();
    if (!rect) return;
    const c = cameraRef.current;
    const worldCenter = worldPoint(c.longitude, c.latitude);
    const scale = Math.pow(2, c.zoom);
    setCursorCoordinates(unproject(worldCenter.x + (event.clientX - rect.left - dimensions.width / 2) / scale, worldCenter.y + (event.clientY - rect.top - dimensions.height / 2) / scale));
    if (!drag.current) return;
    const original = worldPoint(drag.current.camera.longitude, drag.current.camera.latitude);
    const next = unproject(original.x - (event.clientX - drag.current.x) / scale, original.y - (event.clientY - drag.current.y) / scale);
    applyCamera({ ...next, zoom: drag.current.camera.zoom });
  };
  const activateVessel = (vessel: MapVessel) => { onVesselSelect?.(vessel); setFollowing(vessel.id); flyTo(vessel, Math.max(camera.zoom, 7.4)); };
  const selectedVessel = validVessels.find(v => v.id === selectedVesselId);
  const activeVessel = validVessels.find(v => v.id === hovered) || selectedVessel;
  const activePosition = activeVessel && project((positions[activeVessel.id] || activeVessel).latitude, (positions[activeVessel.id] || activeVessel).longitude);
  const showOffline = engine === "offline" || chartMode;
  const viewportNorthWest = unproject(center.x - dimensions.width / 2 / worldScale, center.y - dimensions.height / 2 / worldScale);
  const viewportSouthEast = unproject(center.x + dimensions.width / 2 / worldScale, center.y + dimensions.height / 2 / worldScale);
  const regionCoversViewport = regionBounds && regionBounds.west <= viewportNorthWest.longitude && regionBounds.east >= viewportSouthEast.longitude && regionBounds.north >= viewportNorthWest.latitude && regionBounds.south <= viewportSouthEast.latitude;
  const regionCoversCenter = regionBounds && regionBounds.west <= camera.longitude && regionBounds.east >= camera.longitude && regionBounds.south <= camera.latitude && regionBounds.north >= camera.latitude;
  const coordinates = cursorCoordinates || camera;
  const kmPerPixel = Math.cos(camera.latitude * Math.PI / 180) * 40075.017 / (256 * worldScale);
  const scaleKm = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000].find(value => value / kmPerPixel >= 55) || 1000;
  const gridStep = camera.zoom >= 7.5 ? 0.5 : camera.zoom >= 5.5 ? 1 : camera.zoom >= 4 ? 5 : 15;
  const gridLongitudes = Array.from({ length: Math.ceil(360 / gridStep) }, (_, i) => -180 + i * gridStep).filter(lon => { const p = project(camera.latitude, lon); return p.x > 0 && p.x < dimensions.width; });
  const gridLatitudes = Array.from({ length: Math.ceil(160 / gridStep) }, (_, i) => -80 + i * gridStep).filter(lat => { const p = project(lat, camera.longitude); return p.y > 0 && p.y < dimensions.height; });
  const placeLabels = [
    { name: "ARABIAN SEA", latitude: 14.5, longitude: 70.5, size: 20, spacing: 7, ocean: true },
    { name: "INDIA", latitude: 19.6, longitude: 77.7, size: 20, spacing: 8 },
    { name: "KARNATAKA", latitude: 14.7, longitude: 76.05, size: 13, spacing: 4 },
    { name: "KERALA", latitude: 10.6, longitude: 76.5, size: 11, spacing: 3 },
    { name: "MAHARASHTRA", latitude: 18.6, longitude: 75.25, size: 11, spacing: 3 },
    { name: "GOA", latitude: 15.4, longitude: 74.2, size: 10, spacing: 2 },
    { name: "Karwar", latitude: 14.8136, longitude: 74.1297, size: 11, spacing: 0.2 },
    { name: "Udupi", latitude: 13.3409, longitude: 74.7421, size: 11, spacing: 0.2 },
    { name: "LAKSHADWEEP", latitude: 10.55, longitude: 72.3, size: 10, spacing: 3 },
    { name: "GULF OF MEXICO", latitude: 25.8, longitude: -90.4, size: 16, spacing: 5, ocean: true },
    { name: "NORTH ATLANTIC OCEAN", latitude: 33, longitude: -65, size: 17, spacing: 5, ocean: true },
    { name: "UNITED STATES", latitude: 37.8, longitude: -98, size: 15, spacing: 5 },
  ];

  return <div ref={rootRef} className={`ocean-map ${className}`} data-engine={showOffline ? "offline" : engine}
    style={{ "--ocean-left-inset": `${controlInsets?.left ?? panelInsets.left}px`, "--ocean-right-inset": `${controlInsets?.right ?? panelInsets.right}px` } as CSSProperties}
    onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }} onPointerLeave={() => { setCursorCoordinates(null); }}
    role="region" aria-label="Interactive maritime intelligence map. Drag to pan; use controls to zoom.">
    <div ref={googleContainer} className="ocean-google-surface" style={{ visibility: engine === "google" && !chartMode ? "visible" : "hidden" }} />
    <div ref={threeContainer} className="ocean-three-surface" style={{ visibility: engine === "3d" && !chartMode ? "visible" : "hidden" }} />

    {(engine !== "3d" || chartMode) && <svg className="ocean-chart" width="100%" height="100%" viewBox={`0 0 ${dimensions.width} ${dimensions.height}`} aria-label="Vessels, marine currents, debris observations, ports, and computed maritime routes">
      <defs>
        <radialGradient id={`${uid}-ocean`} cx="58%" cy="45%" r="80%"><stop stopColor="#102c3b" /><stop offset="0.7" stopColor="#0b202e" /><stop offset="1" stopColor="#081722" /></radialGradient>
        <linearGradient id={`${uid}-land`} x1="0" y1="0" x2="1" y2="1"><stop stopColor="#293b3b" /><stop offset="0.5" stopColor="#243c3c" /><stop offset="1" stopColor="#172c31" /></linearGradient>
        <radialGradient id={`${uid}-hotspot`}><stop stopColor="#efb164" stopOpacity="0.2" /><stop offset="0.45" stopColor="#d5944d" stopOpacity="0.11" /><stop offset="1" stopColor="#edbd70" stopOpacity="0" /></radialGradient>
        <filter id={`${uid}-glow`} x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="3" /></filter>
        <filter id={`${uid}-coast`} x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="8" /></filter>
        <marker id={`${uid}-arrow`} markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M1 1l4 2.5L1 6" fill="none" stroke="#69b9b3" strokeWidth="1.2" /></marker>
        <pattern id={`${uid}-land-texture`} width="7" height="7" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="0.45" fill="#8db3a1" opacity="0.1" /></pattern>
      </defs>

      {showOffline && <>
        <rect width={dimensions.width} height={dimensions.height} fill={`url(#${uid}-ocean)`} />
        {worldLandPath && !regionCoversViewport && <g transform={`translate(${dimensions.width / 2 - center.x * worldScale},${dimensions.height / 2 - center.y * worldScale}) scale(${worldScale})`}><path d={worldLandPath} fill={`url(#${uid}-land)`} stroke="#65847a" strokeWidth="0.8" fillRule="evenodd" vectorEffect="non-scaling-stroke" opacity="0.92" /></g>}
        {landPath && <g transform={`translate(${dimensions.width / 2 - center.x * worldScale},${dimensions.height / 2 - center.y * worldScale}) scale(${worldScale})`}>
          <path d={landPath} fill="none" stroke="#2b6168" strokeWidth="13" opacity="0.09" vectorEffect="non-scaling-stroke" />
          <path d={landPath} fill="none" stroke="#3b6870" strokeWidth="6" opacity="0.1" vectorEffect="non-scaling-stroke" />
          <path d={landPath} fill={`url(#${uid}-land)`} stroke="#65847a" strokeWidth="0.9" opacity="0.94" fillRule="evenodd" vectorEffect="non-scaling-stroke" />
        </g>}
      </>}

      {layers.grid && <g className="ocean-grid">
        {gridLongitudes.map(lon => { const p = project(camera.latitude, lon); return <g key={`lon-${lon}`}><line x1={p.x} y1="0" x2={p.x} y2={dimensions.height} /><text x={p.x + 6} y={dimensions.height - 65}>{Math.abs(lon).toFixed(gridStep < 1 ? 1 : 0)}°{lon < 0 ? "W" : "E"}</text></g>; })}
        {gridLatitudes.map(lat => { const p = project(lat, camera.longitude); return <g key={`lat-${lat}`}><line x1="0" y1={p.y} x2={dimensions.width} y2={p.y} /><text x="18" y={p.y - 7}>{Math.abs(lat).toFixed(gridStep < 1 ? 1 : 0)}°{lat < 0 ? "S" : "N"}</text></g>; })}
      </g>}

      {layers.boundaries && <g transform={`translate(${dimensions.width / 2 - center.x * worldScale},${dimensions.height / 2 - center.y * worldScale}) scale(${worldScale})`}>
        {boundaryPaths.map(boundary => <path key={boundary.id} d={boundary.path} fill="none" stroke={boundary.kind.includes("territorial") ? "#8aacaa" : "#608b88"} strokeWidth={boundary.kind.includes("territorial") ? 0.8 : 1} strokeDasharray={boundary.kind.includes("territorial") ? "2 5" : "5 7"} vectorEffect="non-scaling-stroke" opacity="0.36"><title>{boundary.name} · Marine Regions / VLIZ · scientific spatial context, verify current jurisdiction</title></path>)}
        {protectedPath && <path d={protectedPath} fill="#6dc394" fillOpacity="0.06" stroke="#79bf91" strokeWidth="1" strokeDasharray="4 3" vectorEffect="non-scaling-stroke"><title>Downloaded marine protected-area geometry · real data</title></path>}
      </g>}

      {showOffline && placeLabels.map(place => { const p = project(place.latitude, place.longitude); return inView(p) && <text key={place.name} x={p.x} y={p.y} textAnchor="middle" fill={place.ocean ? "#63848f" : "#87988c"} fontSize={place.size} letterSpacing={place.spacing} opacity={place.ocean ? 0.5 : 0.65} fontWeight="400" style={{ pointerEvents: "none" }}>{place.name}</text>; })}

      {layers.currents && <g className="ocean-currents">{visibleMarine.map((sample, index) => {
        const p = project(sample.latitude, sample.longitude);
        if (!inView(p, 50)) return null;
        const speed = sample.current_velocity!;
        const length = clamp(12 + speed * 32, 12, 55);
        const duration = clamp(9 / Math.max(speed, 0.05), 3, 30);
        return <g key={`${sample.latitude}-${sample.longitude}-${index}`} transform={`translate(${p.x},${p.y}) rotate(${sample.current_direction! - 90})`} opacity="0.48">
          <title>{`Model forecast · ${speed.toFixed(2)} m/s toward ${sample.current_direction!.toFixed(0)}°`}</title>
          <path d={`M${-length / 2},0H${length / 2}`} stroke="#508c91" strokeWidth="1" markerEnd={`url(#${uid}-arrow)`} />
          {speed > 0 && <circle r="1.3" fill="#9fe1d7"><animateMotion dur={`${duration}s`} repeatCount="indefinite" path={`M${-length / 2},0L${length / 2},0`} /><animate attributeName="opacity" values="0;1;1;0" dur={`${duration}s`} repeatCount="indefinite" /></circle>}
        </g>;
      })}</g>}

      {layers.routes && route && <g className="ocean-routes">
        {route.baseline && <path d={pathFromCoordinates(route.baseline.coordinates)} fill="none" stroke="#9baaba" strokeWidth="1.6" strokeDasharray="5 7" opacity="0.65"><title>Baseline maritime route · computed</title></path>}
        {route.optimized && <>
          <path d={pathFromCoordinates(route.optimized.coordinates)} fill="none" stroke="#4fdbbc" strokeWidth="13" opacity="0.1" />
          <path d={pathFromCoordinates(route.optimized.coordinates)} fill="none" stroke="#63e2bf" strokeWidth="2.5" pathLength="1" className="ocean-route-draw"><title>Environment-aware route · computed</title></path>
          <path d={pathFromCoordinates(route.optimized.coordinates)} fill="none" stroke="#e1fff2" strokeWidth="2.6" strokeDasharray="2 26" opacity="0.9" className="ocean-route-flow" />
        </>}
      </g>}

      {layers.debris && validHotspots.map((hotspot, index) => {
        const p = project(hotspot.latitude, hotspot.longitude);
        if (!inView(p)) return null;
        const radius = clamp(20 + Math.log2((hotspot.count || 1) + 1) * 5, 22, 52);
        const isSelected = mission.includes("debris") || mission.includes("swarm");
        return <g key={hotspot.id}>
          {hotspot.drift && <path d={pathFromCoordinates(hotspot.drift)} stroke="#edbd70" strokeWidth="1.4" strokeDasharray="3 6" fill="none" opacity="0.7"><title>Modelled drift estimate · increasing uncertainty</title></path>}
          {isSelected && hotspot.driftPoints?.filter(point => point.hours > 0 && validPosition(point)).map(point => {
            const driftPosition = project(point.latitude, point.longitude);
            const localKmPerPixel = Math.cos(point.latitude * Math.PI / 180) * 40075.017 / (256 * worldScale);
            return <g key={point.hours} transform={`translate(${driftPosition.x},${driftPosition.y})`}>
              {point.uncertainty_km != null && <circle r={Math.max(1, point.uncertainty_km / localKmPerPixel)} fill="#dcb576" fillOpacity="0.03" stroke="#dcb576" strokeOpacity="0.4" strokeWidth="0.8" strokeDasharray="2 3"><title>Illustrative uncertainty parameter: {point.uncertainty_km} km. Not a calibrated probability interval.</title></circle>}
              <circle r="2" fill="#e5c08b" />
              {camera.zoom > 8 && <text x="5" y="-5" fill="#d1b788" fontSize="8">+{point.hours}h</text>}
            </g>;
          })}
          <g transform={`translate(${p.x},${p.y})`} className="ocean-hotspot" data-map-item="hotspot" role="button" tabIndex={0}
            aria-label={`${hotspot.name || `Debris hotspot ${index + 1}`}, ${hotspot.count ?? "unknown"} observations, ${hotspot.provenance || "computed from observations"}`}
            onClick={() => { onHotspotSelect?.(hotspot); setFollowing(null); flyTo(hotspot, 7.8); }} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onHotspotSelect?.(hotspot); flyTo(hotspot, 7.8); } }}>
            <circle r={radius * 1.8} fill={`url(#${uid}-hotspot)`} />
            <circle r={radius} fill="#ddab61" fillOpacity="0.04" stroke="#dcb576" strokeWidth="0.8" strokeDasharray="2 5" opacity="0.5" />
            <circle r={radius * 0.58} fill="none" stroke="#dcb576" strokeWidth="0.7" className="ocean-hotspot-pulse" />
            <circle r="8" fill="#242c2d" stroke="#e1b476" strokeWidth="1.2" />
            <path d="m-3-1 3-3 3 3v4h-6z" fill="none" stroke="#eac488" strokeWidth="1" />
            {(isSelected || camera.zoom > 7) && <text x="15" y="4" fill="#e4c089" fontSize="10" letterSpacing="0.6">{hotspot.count ?? "—"} OBS.</text>}
            <title>{`${hotspot.category || hotspot.categories?.join(", ") || "Marine debris"} · ${hotspot.provenance || "COMPUTED HOTSPOT"}`}</title>
          </g>
        </g>;
      })}

      {layers.ports && validPorts.map(port => {
        const p = project(port.latitude, port.longitude);
        if (!inView(p, 20)) return null;
        const prominent = /mangal|karwar|udupi|kochi|cochin|mumbai|mormu|new mangalore/i.test(port.name);
        if (camera.zoom < 6 && !prominent) return null;
        return <g key={port.id} transform={`translate(${p.x},${p.y})`} className="ocean-port" data-map-item="port" role="button" tabIndex={0} aria-label={`${port.name}, port`}
          onClick={() => { onPortSelect?.(port); setFollowing(null); flyTo(port, 8); }} onKeyDown={event => { if (event.key === "Enter") { onPortSelect?.(port); flyTo(port, 8); } }}>
          <circle r="14" fill="transparent" />
          <circle r="5" fill="#162e36" stroke="#8daba6" strokeWidth="1.2" /><circle r="1.8" fill="#a5c5b5" />
          {(prominent || camera.zoom > 7.5) && <><path d="M7 0h9" stroke="#647d76" strokeWidth="0.8" /><text x="22" y="4" fill="#b3c5bd" fontSize={prominent ? 12 : 10} fontWeight={prominent ? 500 : 400}>{port.name.replace(/New Mangalore/i, "Mangaluru")}</text></>}
          <title>{`${port.name} · ${port.provenance || "REAL PORT DATA"}`}</title>
        </g>;
      })}

      {layers.vessels && validVessels.map(vessel => {
        const position = positions[vessel.id] || { ...vessel, heading: vessel.heading || 0 };
        const p = project(position.latitude, position.longitude);
        if (!inView(p, 40)) return null;
        const selected = vessel.id === selectedVesselId || vessel.id === hovered;
        const isFishing = /fishing/i.test(vessel.type || "");
        const attention = (vessel.risk || 0) >= 60;
        const color = attention ? MAP_COLORS.amber : isFishing ? MAP_COLORS.blue : MAP_COLORS.teal;
        return <g key={vessel.id}>
          {vessel.track && (selected || camera.zoom >= 8) && <path d={pathFromCoordinates(vessel.track)} fill="none" stroke={color} strokeWidth="1.4" opacity="0.35" />}
          <g transform={`translate(${p.x},${p.y})`} className="ocean-vessel" data-map-item="vessel" role="button" tabIndex={0}
            aria-label={`${vessel.name}, ${vessel.provenance || "source not specified"}${vessel.speed != null ? `, ${vessel.speed.toFixed(1)} knots` : ""}`}
            onMouseEnter={() => setHovered(vessel.id)} onMouseLeave={() => setHovered(null)}
            onFocus={() => setHovered(vessel.id)} onBlur={() => setHovered(null)}
            onClick={() => activateVessel(vessel)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activateVessel(vessel); } }}>
            <circle r="17" fill="transparent" />
            {selected && <><circle r="26" stroke={color} strokeWidth="0.8" fill={color} fillOpacity="0.035" opacity="0.7" /><path d="M-31-10v-10h10M21-20h10v10M-31 10v10h10M21 20h10V10" fill="none" stroke={color} strokeWidth="1" /></>}
            {attention && !selected && <circle r="18" fill="none" stroke={color} strokeWidth="0.7" opacity="0.5" strokeDasharray="2 5" />}
            <g transform={`rotate(${position.heading}) scale(${selected ? 1.35 : 1})`}>
              <path d="M-2 11-5 24M2 11l5 13" stroke={color} strokeWidth="0.8" opacity="0.18" />
              <path d="M0-10 4-4 4 7 0 10-4 7-4-4z" fill={color} stroke="#122c34" strokeWidth="1" />
              <path d="M-2-2h4v6h-4z" fill="#173d44" opacity="0.75" /><path d="M-2 6h4" stroke="#e8fff3" strokeWidth="1" opacity="0.7" />
              {selected && <path d="M0-15v-25" stroke={color} strokeWidth="1" opacity="0.5" strokeDasharray="3 4" />}
            </g>
          </g>
        </g>;
      })}

      {retiredRoutes.map(retired => <path key={`retired-${retired.id}`} d={pathFromCoordinates(retired.coordinates)} className="ocean-retired-route" fill="none" stroke="#d19371" strokeWidth="1.5" strokeDasharray="4 5"><title>Previous simulated assignment · superseded by replanning</title></path>)}
      {collectors.filter(validPosition).map(collector => {
        let position: MapPosition = collector;
        let heading = collector.heading || 0;
        if (collector.route?.length && collector.progress != null) {
          const index = clamp(collector.progress, 0, 1) * (collector.route.length - 1);
          const a = collector.route[Math.floor(index)], b = collector.route[Math.ceil(index)];
          const fraction = index - Math.floor(index);
          position = { longitude: a[0] + (b[0] - a[0]) * fraction, latitude: a[1] + (b[1] - a[1]) * fraction };
          if (collector.route.length > 1) {
            const leg = Math.min(Math.floor(index), collector.route.length - 2);
            heading = routeBearing(collector.route[leg], collector.route[leg + 1]);
          }
        }
        const p = project(position.latitude, position.longitude);
        return <g key={collector.id}>
          {collector.route && <path d={pathFromCoordinates(collector.route)} fill="none" stroke={MAP_COLORS.purple} strokeWidth="1.5" strokeDasharray="3 6" opacity="0.65" />}
          {inView(p) && <g transform={`translate(${p.x},${p.y})`}><circle r="16" fill="#25263c" stroke={MAP_COLORS.purple} strokeWidth="0.7" /><g transform={`rotate(${heading})`}><path d="m0-8 5 5v9H2V0h-4v6h-3v-9z" fill={MAP_COLORS.purple} /></g><text x="24" y="0" fill="#d3c5ed" fontSize="10">{collector.name || collector.id}</text><text x="24" y="13" fill="#9a8bae" fontSize="8" letterSpacing="0.5">SIMULATED ASSET</text></g>}
        </g>;
      })}

      {activeVessel && activePosition && inView(activePosition, 0) && layers.vessels && <g transform={`translate(${clamp(activePosition.x + 39, 10, dimensions.width - 204)},${clamp(activePosition.y - 54, 20, dimensions.height - 96)})`} className="ocean-vessel-label">
        <rect width="194" height="68" rx="8" fill="#0d202c" fillOpacity="0.97" stroke="#2b5155" />
        <circle cx="14" cy="18" r="3" fill={MAP_COLORS.teal} />
        <text x="25" y="22" fill="#e4eeeb" fontSize="11" fontWeight="600">{activeVessel.name.slice(0, 23)}</text>
        <text x="13" y="41" fill="#7e9b9e" fontSize="9">{activeVessel.speed != null ? `${activeVessel.speed.toFixed(1)} kn` : "Speed unavailable"} · {activeVessel.id}</text>
        <text x="13" y="56" fill="#70b4a5" fontSize="8" letterSpacing="0.9">{(activeVessel.provenance || "SOURCE NOT SPECIFIED").slice(0, 32)}</text>
      </g>}
    </svg>}

    <div className="ocean-vignette" />
    {showOffline && !worldLandPath && regionBounds && !regionCoversCenter && <div className="ocean-context-note">{worldStatus === "loading" ? "Loading global geographic context…" : "Global coastline unavailable · vessel coordinates remain visible"}</div>}
    <div className="ocean-compass" aria-label="Map orientation north"><span>N</span><svg width="27" height="37" viewBox="0 0 27 37" aria-hidden="true"><path d="m13.5 4 7 25-7-6-7 6z" fill="#a8c4b7" /><path d="m13.5 4 7 25-7-6z" fill="#506862" /></svg></div>

    <div className="ocean-map-controls">
      <button aria-label="Zoom in" title="Zoom in" onClick={() => zoomBy(0.75)}><MapIcon kind="plus" /></button>
      <button aria-label="Zoom out" title="Zoom out" onClick={() => zoomBy(-0.75)}><MapIcon kind="minus" /></button>
      <span />
      <button aria-label="Return to Karnataka coast" title="Return to Karnataka coast" onClick={() => { setFollowing(null); flyTo(DEFAULT_CAMERA, DEFAULT_CAMERA.zoom); }}><MapIcon kind="reset" /></button>
      <button aria-label="Show India" title="Show India" onClick={() => { setFollowing(null); flyTo({ latitude: 18.5, longitude: 76.5 }, 4.5); }}><MapIcon kind="globe" /></button>
      <button aria-label="Map layers" aria-expanded={showLayerMenu} title="Map layers" onClick={() => setShowLayerMenu(value => !value)}><MapIcon kind="layers" /></button>
    </div>

    {showLayerMenu && <div className="ocean-layer-menu">
      <strong>Chart layers</strong>
      {(["vessels", "ports", "currents", "debris", "boundaries", "routes", "grid"] as const).map(layer => <label key={layer}><span>{layer === "currents" ? "Forecast current vectors" : layer === "debris" ? "Debris observations" : layer === "boundaries" ? `Marine boundaries (${boundaryPaths.length})` : layer[0].toUpperCase() + layer.slice(1)}</span><input type="checkbox" checked={layers[layer]} disabled={layerOverrides?.[layer] !== undefined || (layer === "debris" && layerOverrides?.hotspots !== undefined)} onChange={event => setInternalLayers(current => ({ ...current, [layer]: event.target.checked }))} /></label>)}
      <p>Current arrows show model forecast direction and speed at sampled locations. Boundaries: Marine Regions / VLIZ, real cached geometry. {protectedPath ? "Protected-area geometry loaded." : "Protected-area geometry not loaded."}</p>
    </div>}

    {following && <button className="ocean-following" onClick={() => setFollowing(null)}><i /> Following {validVessels.find(v => v.id === following)?.name || following}<span>×</span></button>}

    {!hideLegend && <div className="ocean-legend">
      <span><i style={{ background: MAP_COLORS.teal }} />Vessel</span><span><i style={{ background: MAP_COLORS.blue }} />Fishing</span><span><i style={{ background: MAP_COLORS.amber }} />Debris hotspot</span>
      {!!validMarine.length && <span className="ocean-forecast-label">MODEL FORECAST · CURRENTS</span>}
    </div>}

    <div className="ocean-map-bottom">
      <div className="ocean-map-attribution"><span className="ocean-source-dot" />{showOffline ? (landPath ? "NATURAL EARTH · OFFLINE CACHE" : "GEOGRAPHIC CHART · LOADING COASTLINE") : engine === "3d" ? "GOOGLE PHOTOREALISTIC 3D" : "GOOGLE MAPS"}<span className="ocean-coordinate">{Math.abs(coordinates.latitude).toFixed(3)}° {coordinates.latitude < 0 ? "S" : "N"}&nbsp; {Math.abs(coordinates.longitude).toFixed(3)}° {coordinates.longitude < 0 ? "W" : "E"}</span></div>
      <div className="ocean-map-bottom-right">
        <div className="ocean-scale"><span style={{ width: `${scaleKm / kmPerPixel}px` }} /><small>{scaleKm} km</small></div>
        {engine !== "offline" && <button className={chartMode ? "active" : ""} onClick={() => setChartMode(value => !value)} title="Toggle cached chart">Chart</button>}
        {!!googleMapsKey && <button className={engine === "3d" ? "active" : ""} onClick={() => { setChartMode(false); void activate3D(); }} disabled={threeStatus === "loading" || threeStatus === "unavailable"} title={threeStatus === "unavailable" ? "3D is unavailable; standard map remains operational" : "Explore Google photorealistic 3D"}>{threeStatus === "loading" ? "Loading 3D…" : "3D"}</button>}
      </div>
    </div>
    <span className="ocean-sr-only" role="status">{googleStatus}. {validVessels.length} located vessels, {validHotspots.length} debris hotspots, {validMarine.length} current samples.</span>

    <style jsx>{`
      .ocean-map{position:relative;width:100%;height:100%;min-height:380px;overflow:hidden;background:#0b202e;isolation:isolate;touch-action:none;color:#a9bfb9;font-family:inherit;user-select:none}
      .ocean-google-surface,.ocean-three-surface,.ocean-chart{position:absolute;inset:0;width:100%;height:100%}.ocean-chart{pointer-events:none}.ocean-map[data-engine=offline]{cursor:grab}.ocean-map[data-engine=offline]:active{cursor:grabbing}
      .ocean-grid line{stroke:#557d89;stroke-width:.5;opacity:.11}.ocean-grid text{fill:#668894;font-size:8px;letter-spacing:1px;opacity:.45;font-family:monospace}
      .ocean-port,.ocean-vessel,.ocean-hotspot{pointer-events:all;cursor:pointer;outline:none}.ocean-port:focus circle,.ocean-vessel:focus>circle,.ocean-hotspot:focus>circle{stroke:#fff;stroke-width:2px}.ocean-port:hover text{fill:#fff}.ocean-vessel-label{pointer-events:none}
      .ocean-hotspot-pulse{animation:ocean-pulse 4s ease-in-out infinite;transform-origin:center}.ocean-route-draw{stroke-dasharray:1;stroke-dashoffset:0;animation:ocean-draw 2.8s cubic-bezier(.2,.7,.2,1)}.ocean-route-flow{animation:ocean-flow 3s linear infinite}.ocean-retired-route{animation:ocean-retire 5.5s ease-out forwards}
      .ocean-vignette{position:absolute;inset:0;box-shadow:inset 0 0 180px 28px rgba(4,12,19,.23);pointer-events:none}
      .ocean-context-note{position:absolute;left:50%;bottom:110px;transform:translateX(-50%);padding:9px 13px;background:#11262be8;border:1px solid #3d5559;border-radius:6px;color:#a0b8b4;font-size:10px;line-height:1.5;pointer-events:none;max-width:60%;text-align:center}
      .ocean-compass{position:absolute;right:calc(var(--ocean-right-inset,0px) + 25px);top:29px;display:flex;flex-direction:column;align-items:center;gap:0;pointer-events:none}.ocean-compass span{font-size:9px;letter-spacing:1px;color:#a5b8af}
      .ocean-map-controls{position:absolute;right:calc(var(--ocean-right-inset,0px) + 22px);top:113px;background:rgba(12,28,37,.92);border:1px solid #2b4147;border-radius:9px;display:flex;flex-direction:column;padding:4px;box-shadow:0 8px 24px #06101844;backdrop-filter:blur(16px)}
      .ocean-map-controls button{border:0;background:transparent;color:#9eb4b2;width:33px;height:36px;display:grid;place-items:center;cursor:pointer;border-radius:5px}.ocean-map-controls button:hover{background:#243c42;color:#e0ece5}.ocean-map-controls span{height:1px;background:#2a3f46;margin:3px 6px}
      .ocean-layer-menu{position:absolute;right:calc(var(--ocean-right-inset,0px) + 72px);top:110px;width:242px;padding:17px 18px;border:1px solid #2c484d;border-radius:12px;background:#10222eeF;box-shadow:0 14px 50px #030d1aaa;backdrop-filter:blur(20px);z-index:3}.ocean-layer-menu strong{font-size:12px;font-weight:600;display:block;margin-bottom:13px;color:#d2e3da}.ocean-layer-menu label{font-size:11px;display:flex;align-items:center;justify-content:space-between;padding:8px 0;color:#a9beb8;gap:10px}.ocean-layer-menu input{accent-color:#61d8b4}.ocean-layer-menu p{color:#6e9295;font-size:10px;line-height:1.6;border-top:1px solid #2b4147;margin:12px 0 0;padding-top:12px}
      .ocean-following{position:absolute;left:50%;top:68px;transform:translateX(-50%);display:flex;align-items:center;gap:8px;padding:9px 12px;background:#142d35ed;border:1px solid #3a615d;color:#bfd7ca;border-radius:7px;font-size:10px;cursor:pointer;max-width:calc(100% - 180px);white-space:nowrap}.ocean-following i{width:5px;height:5px;background:#65d2ad;border-radius:50%}.ocean-following span{margin-left:9px;font-size:17px;color:#77948e}
      .ocean-legend{position:absolute;left:calc(var(--ocean-left-inset,0px) + 25px);right:calc(var(--ocean-right-inset,0px) + 20px);bottom:72px;display:flex;align-items:center;gap:19px;pointer-events:none;flex-wrap:wrap}.ocean-legend>span{font-size:10px;color:#8aa5a6;display:flex;align-items:center;gap:6px}.ocean-legend i{width:5px;height:5px;border-radius:50%;display:inline-block}.ocean-legend .ocean-forecast-label{font-size:8px;letter-spacing:1.1px;color:#547b80;padding-left:2px}
      .ocean-map-bottom{position:absolute;bottom:32px;left:var(--ocean-left-inset,0px);right:var(--ocean-right-inset,0px);min-height:32px;display:flex;align-items:center;justify-content:space-between;padding:8px 22px;gap:12px;pointer-events:none}.ocean-map-attribution{display:flex;align-items:center;gap:7px;font-size:8px;letter-spacing:1px;color:#66888d;line-height:1.5}.ocean-source-dot{width:4px;height:4px;background:#648a88;border-radius:50%;flex-shrink:0}.ocean-coordinate{margin-left:18px;color:#648186;font-size:8px;letter-spacing:.5px;font-family:monospace}.ocean-map-bottom-right{display:flex;gap:7px;align-items:center;pointer-events:all}.ocean-map-bottom-right button{font-size:9px;border:1px solid #314950;background:#122733;border-radius:5px;padding:6px 9px;color:#91aca9;cursor:pointer}.ocean-map-bottom-right button.active{color:#80dcb8;border-color:#447e6c}.ocean-map-bottom-right button:disabled{opacity:.45;cursor:default}.ocean-scale{display:flex;flex-direction:column;align-items:center;gap:3px;margin-right:11px;color:#6c8b8f}.ocean-scale span{height:5px;border:1px solid #66868b;border-top:0;max-width:150px}.ocean-scale small{font-size:8px;white-space:nowrap}.ocean-sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}
      @keyframes ocean-pulse{0%,100%{opacity:.2;transform:scale(.82)}50%{opacity:.7;transform:scale(1.12)}}@keyframes ocean-draw{from{stroke-dashoffset:1}to{stroke-dashoffset:0}}@keyframes ocean-flow{to{stroke-dashoffset:-56}}@keyframes ocean-retire{from{opacity:.8}to{opacity:0}}
      @media(max-width:1450px){.ocean-coordinate{display:none}.ocean-legend .ocean-forecast-label{display:none}.ocean-map-attribution{font-size:7px;letter-spacing:.6px}}
      @media(max-width:900px){.ocean-legend{gap:12px;left:calc(var(--ocean-left-inset,0px) + 15px)}.ocean-map-bottom{padding:8px 14px}.ocean-compass{right:calc(var(--ocean-right-inset,0px) + 20px)}.ocean-map-controls{right:calc(var(--ocean-right-inset,0px) + 15px)}}
      @media(prefers-reduced-motion:reduce){.ocean-hotspot-pulse,.ocean-route-draw,.ocean-route-flow{animation:none}.ocean-currents circle{display:none}}
    `}</style>
  </div>;
});

export default OceanMap;
