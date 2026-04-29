import { MapboxOverlay } from "@deck.gl/mapbox";
import type { Layer } from "@deck.gl/core";
import { getResolution } from "h3-js";
import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";

import { BottomBar } from "./components/BottomBar";
import { ControlPanel } from "./components/ControlPanel";
import { buildTrafficLayer } from "./layers/traffic";
import { filterCellsByAltitude } from "./tiles/filter";
import { TileManager } from "./tiles/manager";
import { tilesForViewport, type TileKey } from "./tiles/tileMath";
import type { Classification, Manifest, Metric, TileCell } from "./types";

const tileManager = new TileManager();
const SCHEMA_VERSION = 2;
const HEATMAP_GLOBAL_SATURATION_FRACTION = 0.99;
const H3_RESOLUTION_SCALE_FACTOR = 6;
const AIRSPACE_TILE_TEMPLATE = "./data/airspace/tiles/z{z}/x{x}/y{y}.png";
const AIRSPACE_BOUNDS: [number, number, number, number] = [-8, 49, 2, 61];
const rasterStyle = (
  name: string,
  tileUrl: string,
  attribution: string,
  background = "#f8fafc"
): maplibregl.StyleSpecification => ({
  version: 8,
  name,
  sources: {
    raster: {
      type: "raster",
      tiles: [tileUrl],
      tileSize: 256,
      attribution,
    },
  },
  layers: [
    { id: "background", type: "background", paint: { "background-color": background } },
    { id: "raster-layer", type: "raster", source: "raster" },
  ],
});
const LIGHT_BASEMAP_STYLE: maplibregl.StyleSpecification = rasterStyle(
  "light",
  "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  "© OpenStreetMap contributors",
  "#f8fafc"
);

export default function App() {
  const mapContainer = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const reloadTilesRef = useRef<(() => Promise<void>) | null>(null);
  const selectedClassificationsRef = useRef<Classification[]>([]);
  const requestSeqRef = useRef(0);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cells, setCells] = useState<TileCell[]>([]);
  const [showVfr, setShowVfr] = useState(true);
  const [showIfr, setShowIfr] = useState(false);
  const [showHelicopter, setShowHelicopter] = useState(false);
  const [metric, setMetric] = useState<Metric>("flight_count");
  const [minBin, setMinBin] = useState(0);
  const [maxBin, setMaxBin] = useState(54);
  const [showAirspace, setShowAirspace] = useState(true);
  const [visibleTiles, setVisibleTiles] = useState<TileKey[]>([]);

  const selectedClassifications = useMemo(() => {
    const values: Classification[] = [];
    if (showVfr) {
      values.push("vfr");
    }
    if (showIfr) {
      values.push("ifr");
    }
    if (showHelicopter) {
      values.push("helicopter");
    }
    return values;
  }, [showVfr, showIfr, showHelicopter]);

  useEffect(() => {
    selectedClassificationsRef.current = selectedClassifications;
  }, [selectedClassifications]);

  useEffect(() => {
    const onError = (event: ErrorEvent) => {
      console.error("[app] window error", event.error ?? event.message);
    };
    const onUnhandledRejection = (event: PromiseRejectionEvent) => {
      console.error("[app] unhandled rejection", event.reason);
    };
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onUnhandledRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onUnhandledRejection);
    };
  }, []);

  useEffect(() => {
    fetch("./data/manifest.json")
      .then((response) => response.json())
      .then((data: Manifest) => {
        console.debug("[app] manifest loaded", data);
        if (data.schema_version !== SCHEMA_VERSION) {
          setError(`Unsupported data schema version ${data.schema_version}.`);
          return;
        }
        setManifest(data);
      })
      .catch((manifestError: unknown) => {
        console.error("[app] failed to load manifest", manifestError);
        setError("Failed to load manifest.json");
      });
  }, []);

  useEffect(() => {
    if (!mapContainer.current || mapRef.current) {
      return;
    }
    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: LIGHT_BASEMAP_STYLE,
      center: [-1.5, 52.5],
      zoom: 6,
      attributionControl: {},
    });
    mapRef.current = map;
    const overlay = new MapboxOverlay({ interleaved: true, layers: [] });
    overlayRef.current = overlay;
    map.addControl(overlay);
    const reloadTiles = async () => {
      const requestId = ++requestSeqRef.current;
      const bounds = map.getBounds();
      const zoom = map.getZoom();
      const visibleTiles = tilesForViewport(
        {
          west: bounds.getWest(),
          south: bounds.getSouth(),
          east: bounds.getEast(),
          north: bounds.getNorth(),
        },
        map.getZoom()
      );
      console.debug("[app] reloading tiles", {
        requestId,
        selectedClassifications: selectedClassificationsRef.current,
        zoom,
        visibleTileCount: visibleTiles.length,
      });
      setVisibleTiles(visibleTiles);
      const tileCells = (
        await Promise.all(selectedClassificationsRef.current.map((c) => tileManager.loadTiles(c, visibleTiles)))
      ).flat();
      if (requestId === requestSeqRef.current) {
        console.debug("[app] tiles loaded", {
          requestId,
          totalCells: tileCells.length,
        });
        setCells(tileCells);
        setError(null);
      }
    };
    reloadTilesRef.current = reloadTiles;
    map.on("load", () => {
      reloadTiles().catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        console.error("[app] tile load failed on map load", error);
        setError("Failed to load tile data");
      });
    });
    map.on("moveend", () => {
      reloadTiles().catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        console.error("[app] tile load failed on moveend", error);
        setError("Failed to load tile data");
      });
    });
    return () => {
      reloadTilesRef.current = null;
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!mapRef.current || !reloadTilesRef.current) {
      return;
    }
    reloadTilesRef.current().catch((error: unknown) => {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      console.error("[app] tile load failed after classification change", error);
      setError("Failed to load tile data");
    });
  }, [selectedClassifications]);

  useEffect(() => {
    if (!mapRef.current) {
      return;
    }
    const map = mapRef.current!;
    const applyAirspace = () => {
      if (!map.getSource("airspace-raster-source")) {
        map.addSource("airspace-raster-source", {
          type: "raster",
          tiles: [AIRSPACE_TILE_TEMPLATE],
          tileSize: 256,
          bounds: AIRSPACE_BOUNDS,
          minzoom: 5,
          maxzoom: 11,
          attribution: "© OpenAIP",
        });
        map.addLayer({
          id: "airspace-raster",
          type: "raster",
          source: "airspace-raster-source",
          paint: {
            "raster-opacity": 0.85,
          },
        });
      }
      map.setLayoutProperty("airspace-raster", "visibility", showAirspace ? "visible" : "none");
      return Promise.resolve();
    };
    if (!map.isStyleLoaded()) {
      map.once("style.load", () => {
        applyAirspace().catch(() => setError("Failed to load airspace"));
      });
      return;
    }
    applyAirspace().catch(() => setError("Failed to load airspace"));
  }, [showAirspace]);

  const renderableCells = useMemo(
    () => filterCellsByAltitude(cells, Math.min(minBin, maxBin), Math.max(minBin, maxBin), metric),
    [cells, minBin, maxBin, metric]
  );
  const dominantH3Resolution = useMemo(() => {
    if (renderableCells.length === 0) {
      return null;
    }
    const counts = new Map<number, number>();
    for (const cell of renderableCells) {
      const resolution = getResolution(cell.h3);
      counts.set(resolution, (counts.get(resolution) ?? 0) + 1);
    }
    let dominant: number | null = null;
    let bestCount = -1;
    for (const [resolution, count] of counts.entries()) {
      if (count > bestCount) {
        bestCount = count;
        dominant = resolution;
      }
    }
    return dominant;
  }, [renderableCells]);
  const heatmapScaleMax = useMemo(() => {
    if (manifest?.classification_scales) {
      const targetResolution = dominantH3Resolution;
      let maxPercentileFromManifest = 0;
      let maxFromManifest = 0;
      for (const classification of selectedClassifications) {
        const scale = manifest.classification_scales[classification];
        if (!scale) {
          continue;
        }
        if (targetResolution !== null && targetResolution !== undefined) {
          const perResolutionScale = scale.by_resolution?.[String(targetResolution)];
          if (perResolutionScale) {
            const percentileValue =
              metric === "flight_count" ? perResolutionScale.flight_count_p90 : perResolutionScale.time_seconds_p90;
            if (percentileValue > maxPercentileFromManifest) {
              maxPercentileFromManifest = percentileValue;
            }
          }
        }
        const value = metric === "flight_count" ? scale.flight_count_max : scale.time_seconds_max;
        if (value > maxFromManifest) {
          maxFromManifest = value;
        }
      }
      if (maxPercentileFromManifest > 0) {
        return maxPercentileFromManifest * HEATMAP_GLOBAL_SATURATION_FRACTION;
      }
      if (maxFromManifest > 0) {
        const baseResolution = Math.min(...manifest.h3_resolutions);
        const fallbackResolution = dominantH3Resolution ?? baseResolution;
        // Legacy fallback for manifests without per-resolution percentile scales.
        // Scale denominator down as resolution increases so zoomed-in tiles stay visible.
        const resolutionFactor = H3_RESOLUTION_SCALE_FACTOR ** (baseResolution - fallbackResolution);
        return maxFromManifest * HEATMAP_GLOBAL_SATURATION_FRACTION * resolutionFactor;
      }
    }
    const positiveValues = renderableCells.map((cell) => cell.metricValue).filter((value) => value > 0);
    if (positiveValues.length === 0) {
      return 0;
    }
    return positiveValues.reduce((max, value) => Math.max(max, value), 0);
  }, [manifest, selectedClassifications, metric, renderableCells, dominantH3Resolution]);
  const flightsTotal = renderableCells.reduce((acc, cell) => acc + cell.selectedFlightCount, 0);
  const secondsTotal = renderableCells.reduce((acc, cell) => acc + cell.selectedTimeSeconds, 0);

  useEffect(() => {
    if (!overlayRef.current) {
      return;
    }
    const layers: Layer[] = [];
    const trafficLayers = buildTrafficLayer(renderableCells, visibleTiles, heatmapScaleMax);
    layers.push(...trafficLayers);
    console.debug("[app] updating deck layers", {
      renderableCells: renderableCells.length,
      layerCount: layers.length,
    });
    try {
      overlayRef.current.setProps({ layers });
    } catch (layerError) {
      console.error("[app] failed to update deck layers", layerError);
      setError("Failed to render traffic layers");
    }
  }, [renderableCells, visibleTiles, heatmapScaleMax]);

  if (error) {
    return <div className="p-4 text-sm text-red-700">{error}</div>;
  }

  return (
    <div className="relative h-full w-full">
      <div ref={mapContainer} className="h-full w-full" />
      <ControlPanel
        showVfr={showVfr}
        showIfr={showIfr}
        showHelicopter={showHelicopter}
        metric={metric}
        minBin={minBin}
        maxBin={maxBin}
        showAirspace={showAirspace}
        onToggleVfr={() => setShowVfr((prev) => !prev)}
        onToggleIfr={() => setShowIfr((prev) => !prev)}
        onToggleHelicopter={() => setShowHelicopter((prev) => !prev)}
        onMetricChange={setMetric}
        onMinBinChange={setMinBin}
        onMaxBinChange={setMaxBin}
        onToggleAirspace={() => setShowAirspace((prev) => !prev)}
      />
      {manifest ? (
        <BottomBar
          startDate={manifest.date_range.start}
          endDate={manifest.date_range.end}
          flights={flightsTotal}
          seconds={secondsTotal}
        />
      ) : null}
    </div>
  );
}
