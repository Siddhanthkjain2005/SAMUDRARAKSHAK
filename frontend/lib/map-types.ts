export type MapCoordinate = [longitude: number, latitude: number];

export interface MapPosition { latitude: number; longitude: number }

export interface MapVessel extends MapPosition {
  id: string;
  name: string;
  heading?: number | null;
  speed?: number | null;
  provenance?: string;
  timestamp?: string;
  type?: string;
  risk?: number;
  track?: MapCoordinate[];
}

export interface MapPort extends MapPosition {
  id: string;
  name: string;
  country?: string;
  provenance?: string;
}

export interface MapHotspot extends MapPosition {
  id: string;
  count?: number;
  name?: string;
  category?: string;
  categories?: string[];
  priority?: number;
  provenance?: string;
  drift?: MapCoordinate[];
  driftPoints?: (MapPosition & { hours: number; uncertainty_km?: number })[];
}

export interface MapRoute {
  baseline?: { coordinates: MapCoordinate[] };
  optimized?: { coordinates: MapCoordinate[] };
}

/** Velocities must be metres/second; directions point TOWARD clockwise from north. */
export interface MapMarineSample extends MapPosition {
  timestamp?: string;
  current_velocity?: number | null;
  current_direction?: number | null;
  wave_height?: number | null;
  provenance?: string;
}

export interface MapCollector extends MapPosition {
  id: string;
  name?: string;
  heading?: number;
  route?: MapCoordinate[];
  /** Explicit simulation progress from the mission coordinator, between 0 and 1. */
  progress?: number;
  state?: string;
}

export interface MapFocus extends MapPosition { zoom?: number; id?: string | number }
export interface MapLayers {
  vessels: boolean;
  ports: boolean;
  currents: boolean;
  debris: boolean;
  /** Compatibility alias for the application-level debris-hotspot toggle. */
  hotspots?: boolean;
  boundaries: boolean;
  routes: boolean;
  grid: boolean;
}

export interface MapGeometry {
  type: string;
  coordinates?: unknown;
  geometries?: MapGeometry[];
}

export interface MapGeography {
  type: string;
  features?: { geometry: MapGeometry | null; properties?: Record<string, unknown> }[];
  geometry?: MapGeometry;
  coordinates?: unknown;
}

export interface OceanMapProps {
  googleMapsKey?: string;
  vessels?: MapVessel[];
  ports?: MapPort[];
  hotspots?: MapHotspot[];
  route?: MapRoute | null;
  marine?: MapMarineSample[];
  collectors?: MapCollector[];
  mission?: string;
  selectedVesselId?: string | null;
  onVesselSelect?: (vessel: MapVessel) => void;
  onHotspotSelect?: (hotspot: MapHotspot) => void;
  onPortSelect?: (port: MapPort) => void;
  onCameraChange?: (camera: MapFocus) => void;
  focus?: MapFocus | null;
  layers?: Partial<MapLayers>;
  geography?: MapGeography | null;
  worldGeography?: MapGeography | null;
  boundaries?: MapGeography | null;
  protectedAreas?: MapGeography | null;
  /** Normally measured from surrounding panels; override for a different host layout. */
  controlInsets?: { left?: number; right?: number };
  className?: string;
  /** Suppress built-in bottom-left legend if the surrounding application supplies one. */
  hideLegend?: boolean;
  cinematicIntro?: boolean;
}

export interface OceanMapHandle {
  flyToIndia: () => void;
  flyToKarnatakaCoast: () => void;
  flyToRoute: (origin?: MapPosition, destination?: MapPosition) => void;
  followVessel: (id: string) => void;
  orbitInvestigation: (location: MapPosition) => void;
  flyToDebrisHotspot: (id: string) => void;
  showWholeMissionArea: () => void;
}
