import type { Metric } from "../types";

export type ShareBounds = {
  west: number;
  south: number;
  east: number;
  north: number;
};

export type AppShareOptions = {
  showVfr: boolean;
  showIfr: boolean;
  showHelicopter: boolean;
  metric: Metric;
  showAirspace: boolean;
};

/** Full serializable view + UI state for ?query sharing. */
export type AppShareSnapshot = AppShareOptions & {
  bounds: ShareBounds;
};

const SHARE_FORMAT_VERSION = "1";

const METRIC_TO_PARAM: Record<Metric, string> = {
  flight_count: "fc",
  time_seconds: "ts",
};

const PARAM_TO_METRIC: Record<string, Metric> = {
  fc: "flight_count",
  ts: "time_seconds",
  flight_count: "flight_count",
  time_seconds: "time_seconds",
};

function parseBoolParam(params: URLSearchParams, key: string): boolean | undefined {
  const v = params.get(key);
  if (v === "0") {
    return false;
  }
  if (v === "1") {
    return true;
  }
  return undefined;
}

function inLonRange(n: number): boolean {
  return Number.isFinite(n) && n >= -180 && n <= 180;
}

function inLatRange(n: number): boolean {
  return Number.isFinite(n) && n >= -85.05112878 && n <= 85.05112878;
}

/**
 * Read optional bbox + layer/metric options from a URL search string.
 * Omitted keys stay undefined so callers can merge with app defaults.
 */
export function parseAppShareFromSearch(search: string): Partial<AppShareSnapshot> {
  const raw = search.startsWith("?") ? search.slice(1) : search;
  const params = new URLSearchParams(raw);
  const out: Partial<AppShareSnapshot> = {};

  const bbox = params.get("bbox");
  if (bbox) {
    const parts = bbox.split(",").map((s) => Number.parseFloat(s.trim()));
    if (parts.length === 4 && parts.every((n) => Number.isFinite(n))) {
      const [west, south, east, north] = parts;
      if (inLonRange(west) && inLonRange(east) && inLatRange(south) && inLatRange(north)) {
        out.bounds = { west, south, east, north };
      }
    }
  }

  const vfr = parseBoolParam(params, "vfr");
  if (vfr !== undefined) {
    out.showVfr = vfr;
  }
  const ifr = parseBoolParam(params, "ifr");
  if (ifr !== undefined) {
    out.showIfr = ifr;
  }
  const heli = parseBoolParam(params, "heli");
  if (heli !== undefined) {
    out.showHelicopter = heli;
  }
  const air = parseBoolParam(params, "airspace");
  if (air !== undefined) {
    out.showAirspace = air;
  }

  const metricRaw = params.get("metric");
  if (metricRaw && PARAM_TO_METRIC[metricRaw]) {
    out.metric = PARAM_TO_METRIC[metricRaw];
  }

  return out;
}

/** Query string (no leading ?) for the given snapshot. */
export function buildSearchParamsString(snapshot: AppShareSnapshot): string {
  const { bounds } = snapshot;
  const q = new URLSearchParams();
  q.set("v", SHARE_FORMAT_VERSION);
  q.set(
    "bbox",
    [bounds.west, bounds.south, bounds.east, bounds.north].map((n) => n.toFixed(5)).join(",")
  );
  q.set("vfr", snapshot.showVfr ? "1" : "0");
  q.set("ifr", snapshot.showIfr ? "1" : "0");
  q.set("heli", snapshot.showHelicopter ? "1" : "0");
  q.set("airspace", snapshot.showAirspace ? "1" : "0");
  q.set("metric", METRIC_TO_PARAM[snapshot.metric]);
  return q.toString();
}

/** Absolute URL for copying (current origin + path + encoded query). */
export function buildAbsoluteShareUrl(snapshot: AppShareSnapshot): string {
  const u = new URL(window.location.href);
  u.search = buildSearchParamsString(snapshot);
  return u.toString();
}
