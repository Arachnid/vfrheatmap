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
  if (oldest) {
    heatTileCache.delete(oldest);
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
  signal: AbortSignal
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

  let freshTiles = new Map<string, HTMLCanvasElement>();

  if (jobs.length > 0) {
    const worker = getWorker();
    const requestId = ++nextRequestId;
    const payload: TrafficRasterRequest = { requestId, jobs };

    freshTiles = await new Promise<Map<string, HTMLCanvasElement>>((resolve, reject) => {
      const onAbort = () => {
        worker.removeEventListener("message", onMessage);
        reject(new DOMException("Aborted", "AbortError"));
      };

      const onMessage = (event: MessageEvent<{ requestId: number; layers: Array<{ cacheKey: string; bitmap: ImageBitmap }> }>) => {
        const { requestId: rid, layers } = event.data;
        if (rid !== requestId) {
          for (const L of layers) {
            L.bitmap.close();
          }
          return;
        }
        worker.removeEventListener("message", onMessage);
        signal.removeEventListener("abort", onAbort);
        if (signal.aborted) {
          for (const L of layers) {
            L.bitmap.close();
          }
          reject(new DOMException("Aborted", "AbortError"));
          return;
        }
        const out = new Map<string, HTMLCanvasElement>();
        for (const L of layers) {
          out.set(L.cacheKey, imageBitmapToCanvas(L.bitmap));
        }
        resolve(out);
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
    }
    if (!canvas) {
      continue;
    }
    layers.push(makeBitmapLayer(item.tile, item.bounds, canvas));
  }

  return layers;
}
