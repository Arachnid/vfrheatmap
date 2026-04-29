import { BitmapLayer } from "@deck.gl/layers";
import { cellToBoundary, cellToLatLng } from "h3-js";

import type { RenderableCell } from "../types";
import type { TileKey } from "../tiles/tileMath";

interface ViewBounds {
  west: number;
  south: number;
  east: number;
  north: number;
}

function normalizeBounds(bounds: ViewBounds): ViewBounds {
  return {
    west: Math.min(bounds.west, bounds.east),
    east: Math.max(bounds.west, bounds.east),
    south: Math.min(bounds.south, bounds.north),
    north: Math.max(bounds.south, bounds.north),
  };
}

type InterpolationPoint = {
  lon: number;
  lat: number;
  x: number;
  y: number;
  value: number;
};

type BucketIndex = {
  gridSize: number;
  buckets: Map<number, number[]>;
};
const TILE_CACHE_MAX = 512;
const heatTileCache = new Map<string, HTMLCanvasElement>();
const HEATMAP_SOFT_KNEE = 1.0;

function lonToMercatorX(lon: number): number {
  return (lon + 180) / 360;
}

function latToMercatorY(lat: number): number {
  const clamped = Math.max(-85.05112878, Math.min(85.05112878, lat));
  const rad = (clamped * Math.PI) / 180;
  return (1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2;
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
  const mercatorToLat = (y: number): number => {
    const m = Math.PI * (1 - (2 * y) / n);
    return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(m) - Math.exp(-m)));
  };
  const north = mercatorToLat(tile.y);
  const south = mercatorToLat(tile.y + 1);
  return { west, south, east, north };
}

function colorForIntensity(intensity: number): [number, number, number, number] {
  const t = Math.max(0, Math.min(1, intensity));
  // Wider multihue ramp with moderated opacity.
  const stops: Array<[number, number, number, number]> = [
    [18, 22, 64, 8],
    [33, 102, 172, 28],
    [56, 182, 196, 52],
    [80, 212, 104, 80],
    [244, 227, 82, 104],
    [250, 160, 62, 122],
    [236, 86, 54, 138],
    [198, 42, 132, 150],
  ];
  const scaled = t * (stops.length - 1);
  const i = Math.floor(scaled);
  const j = Math.min(stops.length - 1, i + 1);
  const f = scaled - i;
  const lerp = (a: number, b: number) => Math.round(a + (b - a) * f);
  return [
    lerp(stops[i][0], stops[j][0]),
    lerp(stops[i][1], stops[j][1]),
    lerp(stops[i][2], stops[j][2]),
    lerp(stops[i][3], stops[j][3]),
  ];
}

function buildBucketIndex(points: InterpolationPoint[]): BucketIndex {
  const gridSize = Math.max(12, Math.min(48, Math.round(Math.sqrt(points.length / 4))));
  const buckets = new Map<number, number[]>();
  for (let i = 0; i < points.length; i += 1) {
    const p = points[i];
    const bx = Math.max(0, Math.min(gridSize - 1, Math.floor(p.x * gridSize)));
    const by = Math.max(0, Math.min(gridSize - 1, Math.floor(p.y * gridSize)));
    const key = by * gridSize + bx;
    const list = buckets.get(key);
    if (list) {
      list.push(i);
    } else {
      buckets.set(key, [i]);
    }
  }
  return { gridSize, buckets };
}

function nearest3IdwValue(px: number, py: number, points: InterpolationPoint[], bucketIndex: BucketIndex): number {
  let d1 = Number.POSITIVE_INFINITY;
  let d2 = Number.POSITIVE_INFINITY;
  let d3 = Number.POSITIVE_INFINITY;
  let v1 = 0;
  let v2 = 0;
  let v3 = 0;

  const { gridSize, buckets } = bucketIndex;
  const cx = Math.max(0, Math.min(gridSize - 1, Math.floor(px * gridSize)));
  const cy = Math.max(0, Math.min(gridSize - 1, Math.floor(py * gridSize)));
  const candidates: number[] = [];
  for (let ring = 0; ring <= 3; ring += 1) {
    for (let by = Math.max(0, cy - ring); by <= Math.min(gridSize - 1, cy + ring); by += 1) {
      for (let bx = Math.max(0, cx - ring); bx <= Math.min(gridSize - 1, cx + ring); bx += 1) {
        // Only evaluate the current ring perimeter.
        if (ring > 0 && bx > cx - ring && bx < cx + ring && by > cy - ring && by < cy + ring) {
          continue;
        }
        const key = by * gridSize + bx;
        const bucket = buckets.get(key);
        if (bucket) {
          candidates.push(...bucket);
        }
      }
    }
    if (candidates.length >= 12) {
      break;
    }
  }
  if (candidates.length > 0) {
    for (const idx of candidates) {
      const p = points[idx];
      const dx = px - p.x;
      const dy = py - p.y;
      const d = dx * dx + dy * dy;
      if (d < d1) {
        d3 = d2;
        v3 = v2;
        d2 = d1;
        v2 = v1;
        d1 = d;
        v1 = p.value;
      } else if (d < d2) {
        d3 = d2;
        v3 = v2;
        d2 = d;
        v2 = p.value;
      } else if (d < d3) {
        d3 = d;
        v3 = p.value;
      }
    }
  } else {
    // Rare fallback: no nearby buckets populated. Scan all points once.
    for (let idx = 0; idx < points.length; idx += 1) {
      const p = points[idx];
      const dx = px - p.x;
      const dy = py - p.y;
      const d = dx * dx + dy * dy;
      if (d < d1) {
        d3 = d2;
        v3 = v2;
        d2 = d1;
        v2 = v1;
        d1 = d;
        v1 = p.value;
      } else if (d < d2) {
        d3 = d2;
        v3 = v2;
        d2 = d;
        v2 = p.value;
      } else if (d < d3) {
        d3 = d;
        v3 = p.value;
      }
    }
  }
  // Exact centroid hit.
  if (d1 <= 1e-12) {
    return v1;
  }
  const eps = 1e-9;
  const w1 = 1 / (d1 + eps);
  const w2 = Number.isFinite(d2) ? 1 / (d2 + eps) : 0;
  const w3 = Number.isFinite(d3) ? 1 / (d3 + eps) : 0;
  const wSum = w1 + w2 + w3;
  if (wSum <= 0) {
    return 0;
  }
  return (w1 * v1 + w2 * v2 + w3 * v3) / wSum;
}

function buildInterpolatedImage(
  bounds: ViewBounds,
  cells: RenderableCell[],
  normalizationMax: number,
  tileZoom: number
): { data: Uint8ClampedArray; width: number; height: number } | null {
  const westX = lonToMercatorX(bounds.west);
  const eastX = lonToMercatorX(bounds.east);
  const northY = latToMercatorY(bounds.north);
  const southY = latToMercatorY(bounds.south);
  const minY = Math.min(northY, southY);
  const spanX = Math.max(1e-9, eastX - westX);
  const spanY = Math.max(1e-9, Math.abs(southY - northY));
  const points: InterpolationPoint[] = [];

  for (const cell of cells) {
    const [lat, lon] = cellToLatLng(cell.h3);
    const x = (lonToMercatorX(lon) - westX) / spanX;
    const y = (latToMercatorY(lat) - minY) / spanY;
    const value = Math.max(0, cell.metricValue);
    if (value <= 0) {
      continue;
    }
    points.push({ lon, lat, x, y, value });
  }

  if (points.length === 0 || normalizationMax <= 0) {
    return null;
  }

  // Lower tile raster resolution at high zoom where many tiles are visible.
  // This is the main lever for responsiveness during zoomed-in pans.
  const baseQuality = tileZoom >= 10 ? 96 : tileZoom >= 9 ? 120 : 160;
  const quality = points.length > 5000 ? Math.min(baseQuality, 96) : points.length > 2000 ? Math.min(baseQuality, 120) : baseQuality;
  const width = quality;
  const height = quality;
  const bucketIndex = buildBucketIndex(points);

  const image = new Uint8ClampedArray(width * height * 4);
  const sampleCell = cells[0];
  const [sampleLat, sampleLon] = cellToLatLng(sampleCell.h3);
  const sampleBoundary = cellToBoundary(sampleCell.h3);
  let influenceRadiusNorm = 0.04;
  if (sampleBoundary.length > 0) {
    const [bLat, bLon] = sampleBoundary[0];
    const x0 = (lonToMercatorX(sampleLon) - westX) / spanX;
    const y0 = (latToMercatorY(sampleLat) - minY) / spanY;
    const x1 = (lonToMercatorX(bLon) - westX) / spanX;
    const y1 = (latToMercatorY(bLat) - minY) / spanY;
    const d = Math.hypot(x1 - x0, y1 - y0);
    influenceRadiusNorm = Math.max(0.01, d * 2.6);
  }
  const influenceRadiusSq = influenceRadiusNorm * influenceRadiusNorm;

  for (let py = 0; py < height; py += 1) {
    const yNorm = (py + 0.5) / height;
    for (let px = 0; px < width; px += 1) {
      const xNorm = (px + 0.5) / width;
      // Use the nearest-neighbour candidate distance from the IDW pass directly,
      // avoiding an extra O(N points) scan for every pixel.
      const nearestValue = nearest3IdwValue(xNorm, yNorm, points, bucketIndex);
      if (!Number.isFinite(nearestValue)) {
        continue;
      }
      let nearestSq = Number.POSITIVE_INFINITY;
      const { gridSize, buckets } = bucketIndex;
      const cx = Math.max(0, Math.min(gridSize - 1, Math.floor(xNorm * gridSize)));
      const cy = Math.max(0, Math.min(gridSize - 1, Math.floor(yNorm * gridSize)));
      for (let ring = 0; ring <= 2; ring += 1) {
        for (let by = Math.max(0, cy - ring); by <= Math.min(gridSize - 1, cy + ring); by += 1) {
          for (let bx = Math.max(0, cx - ring); bx <= Math.min(gridSize - 1, cx + ring); bx += 1) {
            const bucket = buckets.get(by * gridSize + bx);
            if (!bucket) {
              continue;
            }
            for (const idx of bucket) {
              const p = points[idx];
              const dx = xNorm - p.x;
              const dy = yNorm - p.y;
              const d2 = dx * dx + dy * dy;
              if (d2 < nearestSq) {
                nearestSq = d2;
              }
            }
          }
        }
      }
      if (!Number.isFinite(nearestSq) || nearestSq > influenceRadiusSq) {
        const idx = (py * width + px) * 4;
        image[idx] = 0;
        image[idx + 1] = 0;
        image[idx + 2] = 0;
        image[idx + 3] = 0;
        continue;
      }
      const ratio = Math.max(0, nearestValue / normalizationMax);
      // Soft-knee compression keeps top-end contrast instead of hard-clipping busy areas.
      const compressed = ratio / (ratio + HEATMAP_SOFT_KNEE);
      // Keep weaker values visible without over-saturating the map.
      const shaped = Math.pow(compressed, 0.7);
      const [r, g, b, a] = colorForIntensity(shaped);
      const idx = (py * width + px) * 4;
      image[idx] = r;
      image[idx + 1] = g;
      image[idx + 2] = b;
      image[idx + 3] = a;
    }
  }
  return { data: image, width, height };
}

function tileCacheGetOrCreate(key: string, image: { data: Uint8ClampedArray; width: number; height: number }): HTMLCanvasElement | null {
  const hit = heatTileCache.get(key);
  if (hit) {
    heatTileCache.delete(key);
    heatTileCache.set(key, hit);
    return hit;
  }
  const canvas = document.createElement("canvas");
  canvas.width = image.width;
  canvas.height = image.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return null;
  }
  ctx.putImageData(new ImageData(new Uint8ClampedArray(image.data), image.width, image.height), 0, 0);
  heatTileCache.set(key, canvas);
  if (heatTileCache.size > TILE_CACHE_MAX) {
    const oldest = heatTileCache.keys().next().value as string | undefined;
    if (oldest) {
      heatTileCache.delete(oldest);
    }
  }
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

export function buildTrafficLayer(cells: RenderableCell[], visibleTiles: TileKey[], normalizationMax: number): BitmapLayer[] {
  if (cells.length === 0 || visibleTiles.length === 0 || normalizationMax <= 0) {
    return [];
  }
  // Quantize scale slightly for better cache hit rate while keeping perceived consistency.
  const scaleStep = Math.max(1, Math.round(normalizationMax * 0.02));
  const normalizedScale = Math.max(scaleStep, Math.round(normalizationMax / scaleStep) * scaleStep);

  const byTile = new Map<string, RenderableCell[]>();
  for (const cell of cells) {
    const [lat, lon] = cellToLatLng(cell.h3);
    const z = visibleTiles[0].z;
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

  const layers: BitmapLayer[] = [];
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
    let canvas = heatTileCache.get(cacheKey) ?? null;
    if (!canvas) {
      const image = buildInterpolatedImage(bounds, candidates, normalizedScale, tile.z);
      if (!image) {
        continue;
      }
      canvas = tileCacheGetOrCreate(cacheKey, image);
      if (!canvas) {
        continue;
      }
    } else {
      heatTileCache.delete(cacheKey);
      heatTileCache.set(cacheKey, canvas);
    }

    layers.push(
      new BitmapLayer({
        id: `traffic-layer-${tile.z}-${tile.x}-${tile.y}`,
        image: canvas,
        bounds: [bounds.west, bounds.south, bounds.east, bounds.north],
        desaturate: 0,
        transparentColor: [0, 0, 0, 0],
        textureParameters: {
          minFilter: "linear",
          magFilter: "linear",
          mipmapFilter: "none",
          addressModeU: "clamp-to-edge",
          addressModeV: "clamp-to-edge",
        },
        parameters: { depthTest: false },
      })
    );
  }
  return layers;
}
