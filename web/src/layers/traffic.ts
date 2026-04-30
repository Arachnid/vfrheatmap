import { BitmapLayer } from "@deck.gl/layers";
import { cellToLatLng } from "h3-js";

import type { ViewBounds } from "./trafficRasterCore";
import TrafficWorker from "./traffic.worker?worker";
import type { TrafficRasterJob, TrafficRasterRequest } from "./traffic.worker";
import type { RenderableCell } from "../types";
import type { TileKey } from "../tiles/tileMath";

function normalizeBounds(bounds: ViewBounds): ViewBounds {
  return {
    west: Math.min(bounds.west, bounds.east),
    east: Math.max(bounds.west, bounds.east),
    south: Math.min(bounds.south, bounds.north),
    north: Math.max(bounds.south, bounds.north),
  };
}

function clampLat(lat: number): number {
  return Math.max(-85.05112878, Math.min(85.05112878, lat));
}

function lonToTileX(lon: number, z: number): number {
  const n = 2 ** z;
  return Math.floor(((lon + 180) / 360) * n);
}

function latToTileY(lat: number, z: number): number {
  const n = 2 ** z;
  const latRad = (clampLat(lat) * Math.PI) / 180;
  const y = (1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2;
  return Math.floor(y * n);
}

function tileBounds(tile: TileKey): ViewBounds {
  const n = 2 ** tile.z;
  const west = (tile.x / n) * 360 - 180;
  const east = ((tile.x + 1) / n) * 360 - 180;
  const mercatorToLat = (yy: number): number => {
    const m = Math.PI * (1 - (2 * yy) / n);
    return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(m) - Math.exp(-m)));
  };
  const north = mercatorToLat(tile.y);
  const south = mercatorToLat(tile.y + 1);
  return { west, south, east, north };
}

const TILE_CACHE_MAX = 512;
const heatTileCache = new Map<string, HTMLCanvasElement>();

/** Last rendered heat canvas per slippy tile `z/x/y` (for stale display while a new raster runs). */
const lastHeatCanvasByTileSlot = new Map<string, HTMLCanvasElement>();

/** Max `child.z - ancestor.z` for using a lower-zoom tile as a placeholder image (avoids always hitting a distant z6 tile from the first view). */
const MAX_ANCESTOR_DELTA_Z = 3;

function tileSlotKey(tile: TileKey): string {
  return `${tile.z}/${tile.x}/${tile.y}`;
}

/** Cache keys look like `z/x/y:signature…:scale123` where the signature may contain `:`. */
function slotKeyFromCacheKey(cacheKey: string): string | null {
  const match = /^(\d+\/\d+\/\d+):/.exec(cacheKey);
  return match ? match[1] : null;
}

function rememberSlotCanvas(tile: TileKey, canvas: HTMLCanvasElement): void {
  lastHeatCanvasByTileSlot.set(tileSlotKey(tile), canvas);
}

function parentTile(tile: TileKey): TileKey {
  return { z: tile.z - 1, x: tile.x >> 1, y: tile.y >> 1 };
}

/**
 * Extract the sub-rectangle of `source` that covers `child` when `source` is a full tile raster
 * for `ancestor` (child is a descendant in the slippy pyramid).
 */
function cropChildFromAncestorCanvas(
  child: TileKey,
  ancestor: TileKey,
  source: HTMLCanvasElement
): HTMLCanvasElement | null {
  const dz = child.z - ancestor.z;
  const grid = 1 << dz;
  const W = source.width;
  const H = source.height;
  const ox = child.x - (ancestor.x << dz);
  const oy = child.y - (ancestor.y << dz);
  const sw = W / grid;
  const sh = H / grid;
  const sx = (ox * W) / grid;
  const sy = (oy * H) / grid;
  const outW = Math.max(1, Math.round(sw));
  const outH = Math.max(1, Math.round(sh));
  const out = document.createElement("canvas");
  out.width = outW;
  out.height = outH;
  const ctx = out.getContext("2d", { colorSpace: "srgb" });
  if (!ctx) {
    return null;
  }
  ctx.drawImage(source, sx, sy, sw, sh, 0, 0, outW, outH);
  return out;
}

/**
 * Exact-slot heat if present; otherwise a crop from the finest loaded ancestor (lower zoom) within
 * `MAX_ANCESTOR_DELTA_Z`, so zoom-in reuses parent heat but we do not always mask the loading pattern
 * with a very old low-zoom tile from the first view.
 */
function heatCanvasForPendingTile(tile: TileKey): HTMLCanvasElement | null {
  const exact = lastHeatCanvasByTileSlot.get(tileSlotKey(tile));
  if (exact) {
    return exact;
  }
  let ancestor = parentTile(tile);
  while (ancestor.z >= 0) {
    const dz = tile.z - ancestor.z;
    if (dz <= MAX_ANCESTOR_DELTA_Z) {
      const canvas = lastHeatCanvasByTileSlot.get(tileSlotKey(ancestor));
      if (canvas) {
        const cropped = cropChildFromAncestorCanvas(tile, ancestor, canvas);
        if (cropped) {
          return cropped;
        }
      }
    }
    if (ancestor.z === 0) {
      break;
    }
    ancestor = parentTile(ancestor);
  }
  return null;
}

let nextRequestId = 0;
let workerInstance: Worker | null = null;

function getWorker(): Worker {
  if (!workerInstance) {
    workerInstance = new TrafficWorker();
  }
  return workerInstance;
}

function evictOldestCacheEntry(): void {
  const oldest = heatTileCache.keys().next().value as string | undefined;
  if (!oldest) {
    return;
  }
  const canvas = heatTileCache.get(oldest);
  heatTileCache.delete(oldest);
  const slot = slotKeyFromCacheKey(oldest);
  if (slot && canvas && lastHeatCanvasByTileSlot.get(slot) === canvas) {
    lastHeatCanvasByTileSlot.delete(slot);
  }
}

function touchCache(key: string): HTMLCanvasElement | undefined {
  const c = heatTileCache.get(key);
  if (c) {
    heatTileCache.delete(key);
    heatTileCache.set(key, c);
  }
  return c;
}

function putCache(key: string, canvas: HTMLCanvasElement): void {
  heatTileCache.set(key, canvas);
  const slot = slotKeyFromCacheKey(key);
  if (slot) {
    lastHeatCanvasByTileSlot.set(slot, canvas);
  }
  while (heatTileCache.size > TILE_CACHE_MAX) {
    evictOldestCacheEntry();
  }
}

/** Deck.GL samples Canvas + ImageBitmap textures differently; canvas matches pre-worker appearance. */
function imageBitmapToCanvas(bmp: ImageBitmap): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = bmp.width;
  canvas.height = bmp.height;
  const ctx = canvas.getContext("2d", { colorSpace: "srgb" });
  if (!ctx) {
    bmp.close();
    throw new Error("Canvas 2D context unavailable for traffic tile");
  }
  ctx.drawImage(bmp, 0, 0);
  bmp.close();
  return canvas;
}

function tileSignature(cells: RenderableCell[]): string {
  let metricSum = 0;
  let maxMetric = 0;
  for (const c of cells) {
    metricSum += c.metricValue;
    maxMetric = Math.max(maxMetric, c.metricValue);
  }
  return `${cells.length}:${Math.round(metricSum)}:${Math.round(maxMetric)}`;
}

type OrderedTile = {
  tile: TileKey;
  bounds: ViewBounds;
  cacheKey: string;
  candidates: RenderableCell[];
};

const bitmapLayerProps = {
  desaturate: 0,
  transparentColor: [0, 0, 0, 0] as [number, number, number, number],
  textureParameters: {
    minFilter: "linear" as const,
    magFilter: "linear" as const,
    mipmapFilter: "none" as const,
    addressModeU: "clamp-to-edge" as const,
    addressModeV: "clamp-to-edge" as const,
  },
  parameters: { depthTest: false },
};

/** Single shared texture for tiles still rasterizing in the worker. */
let loadingPatternCanvas: HTMLCanvasElement | null = null;

function getLoadingPatternCanvas(): HTMLCanvasElement {
  if (!loadingPatternCanvas) {
    const size = 40;
    const c = document.createElement("canvas");
    c.width = size;
    c.height = size;
    const ctx = c.getContext("2d", { colorSpace: "srgb" });
    if (ctx) {
      ctx.fillStyle = "rgba(226, 232, 240, 0.42)";
      ctx.fillRect(0, 0, size, size);
      ctx.strokeStyle = "rgba(148, 163, 184, 0.55)";
      ctx.lineWidth = 1.5;
      const step = 8;
      for (let i = -size; i < size * 2; i += step) {
        ctx.beginPath();
        ctx.moveTo(i, 0);
        ctx.lineTo(i + size, size);
        ctx.stroke();
      }
    }
    loadingPatternCanvas = c;
  }
  return loadingPatternCanvas;
}

function makePlaceholderLayer(tile: TileKey, bounds: ViewBounds): BitmapLayer {
  return new BitmapLayer({
    id: `traffic-loading-${tile.z}-${tile.x}-${tile.y}`,
    image: getLoadingPatternCanvas(),
    bounds: [bounds.west, bounds.south, bounds.east, bounds.north],
    tintColor: [235, 242, 252],
    ...bitmapLayerProps,
  });
}

function makeBitmapLayer(
  tile: TileKey,
  bounds: ViewBounds,
  image: HTMLCanvasElement
): BitmapLayer {
  return new BitmapLayer({
    id: `traffic-layer-${tile.z}-${tile.x}-${tile.y}`,
    image,
    bounds: [bounds.west, bounds.south, bounds.east, bounds.north],
    ...bitmapLayerProps,
  });
}

function buildPartialLayersWithPlaceholders(ordered: OrderedTile[], jobs: TrafficRasterJob[]): BitmapLayer[] {
  const pendingKeys = new Set(jobs.map((j) => j.cacheKey));
  const layers: BitmapLayer[] = [];
  for (const item of ordered) {
    const cached = touchCache(item.cacheKey);
    if (cached) {
      rememberSlotCanvas(item.tile, cached);
      layers.push(makeBitmapLayer(item.tile, item.bounds, cached));
    } else if (pendingKeys.has(item.cacheKey)) {
      const fallback = heatCanvasForPendingTile(item.tile);
      if (fallback) {
        layers.push(makeBitmapLayer(item.tile, item.bounds, fallback));
      } else {
        layers.push(makePlaceholderLayer(item.tile, item.bounds));
      }
    }
  }
  return layers;
}

function collectOrderedTiles(
  cells: RenderableCell[],
  visibleTiles: TileKey[],
  normalizedScale: number
): OrderedTile[] {
  const byTile = new Map<string, RenderableCell[]>();
  const z = visibleTiles[0].z;
  for (const cell of cells) {
    const [lat, lon] = cellToLatLng(cell.h3);
    const x = lonToTileX(lon, z);
    const y = latToTileY(lat, z);
    const key = `${z}/${x}/${y}`;
    const list = byTile.get(key);
    if (list) {
      list.push(cell);
    } else {
      byTile.set(key, [cell]);
    }
  }

  const ordered: OrderedTile[] = [];
  for (const tile of visibleTiles) {
    const bounds = normalizeBounds(tileBounds(tile));
    const candidates: RenderableCell[] = [];
    for (let dx = -1; dx <= 1; dx += 1) {
      for (let dy = -1; dy <= 1; dy += 1) {
        const neigh = byTile.get(`${tile.z}/${tile.x + dx}/${tile.y + dy}`);
        if (neigh) {
          candidates.push(...neigh);
        }
      }
    }
    if (candidates.length === 0) {
      continue;
    }
    const cacheKey = `${tile.z}/${tile.x}/${tile.y}:${tileSignature(candidates)}:scale${normalizedScale}`;
    ordered.push({ tile, bounds, cacheKey, candidates });
  }
  return ordered;
}

/**
 * Rasterize traffic heat tiles off the main thread. Pass an AbortSignal from useEffect cleanup
 * so superseded results are dropped (worker bitmaps are closed when stale).
 */
export async function buildTrafficLayersAsync(
  cells: RenderableCell[],
  visibleTiles: TileKey[],
  normalizationMax: number,
  signal: AbortSignal,
  onPartialLayers?: (layers: BitmapLayer[]) => void
): Promise<BitmapLayer[]> {
  if (cells.length === 0 || visibleTiles.length === 0 || normalizationMax <= 0) {
    return [];
  }

  const scaleStep = Math.max(1, Math.round(normalizationMax * 0.02));
  const normalizedScale = Math.max(scaleStep, Math.round(normalizationMax / scaleStep) * scaleStep);

  const ordered = collectOrderedTiles(cells, visibleTiles, normalizedScale);
  if (ordered.length === 0) {
    return [];
  }

  const jobs: TrafficRasterJob[] = [];
  for (const item of ordered) {
    if (heatTileCache.has(item.cacheKey)) {
      continue;
    }
    jobs.push({
      cacheKey: item.cacheKey,
      layerId: `traffic-layer-${item.tile.z}-${item.tile.x}-${item.tile.y}`,
      bounds: item.bounds,
      cells: item.candidates.map((c) => ({ h3: c.h3, metricValue: c.metricValue })),
      normalizedScale,
      tileZ: item.tile.z,
    });
  }

  if (onPartialLayers && !signal.aborted) {
    onPartialLayers(buildPartialLayersWithPlaceholders(ordered, jobs));
  }

  let freshTiles = new Map<string, HTMLCanvasElement>();

  if (jobs.length > 0) {
    const worker = getWorker();
    const requestId = ++nextRequestId;
    const payload: TrafficRasterRequest = { requestId, jobs };

    await new Promise<void>((resolve, reject) => {
      const onAbort = () => {
        worker.removeEventListener("message", onMessage);
        reject(new DOMException("Aborted", "AbortError"));
      };

      const onMessage = (
        event: MessageEvent<
          | { requestId: number; layer: { cacheKey: string; bitmap: ImageBitmap } }
          | { requestId: number; done: true }
        >
      ) => {
        const data = event.data;
        const rid = data.requestId;
        if (rid !== requestId) {
          if ("layer" in data && data.layer) {
            data.layer.bitmap.close();
          }
          return;
        }
        if ("layer" in data && data.layer) {
          const { bitmap } = data.layer;
          if (signal.aborted) {
            bitmap.close();
            return;
          }
          const canvas = imageBitmapToCanvas(bitmap);
          putCache(data.layer.cacheKey, canvas);
          freshTiles.set(data.layer.cacheKey, canvas);
          if (onPartialLayers && !signal.aborted) {
            onPartialLayers(buildPartialLayersWithPlaceholders(ordered, jobs));
          }
          return;
        }
        if ("done" in data && data.done) {
          worker.removeEventListener("message", onMessage);
          signal.removeEventListener("abort", onAbort);
          if (signal.aborted) {
            reject(new DOMException("Aborted", "AbortError"));
            return;
          }
          resolve();
        }
      };

      signal.addEventListener("abort", onAbort, { once: true });
      worker.addEventListener("message", onMessage);
      worker.postMessage(payload);
    });
  }

  if (signal.aborted) {
    return [];
  }

  const layers: BitmapLayer[] = [];
  for (const item of ordered) {
    let canvas = touchCache(item.cacheKey);
    if (!canvas) {
      canvas = freshTiles.get(item.cacheKey);
      if (canvas) {
        putCache(item.cacheKey, canvas);
      }
    } else {
      rememberSlotCanvas(item.tile, canvas);
    }
    if (!canvas) {
      continue;
    }
    layers.push(makeBitmapLayer(item.tile, item.bounds, canvas));
  }

  return layers;
}
