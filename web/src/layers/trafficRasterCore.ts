/**
 * Heatmap raster math shared by the main thread (cache bookkeeping) and the traffic web worker.
 */
import { cellToBoundary, cellToLatLng } from "h3-js";

export interface ViewBounds {
  west: number;
  south: number;
  east: number;
  north: number;
}

/** Minimal cell payload for rasterization (structured-clone friendly). */
export type RasterCellInput = {
  h3: string;
  metricValue: number;
};

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

export const HEATMAP_SOFT_KNEE = 1.0;
/** Extra mercator span per side; raster is enlarged then cropped to reduce tile-edge seams. */
export const HEATMAP_OVERSCAN_PAD = 0.125;

function lonToMercatorX(lon: number): number {
  return (lon + 180) / 360;
}

function latToMercatorY(lat: number): number {
  const clamped = Math.max(-85.05112878, Math.min(85.05112878, lat));
  const rad = (clamped * Math.PI) / 180;
  return (1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2;
}

function colorForIntensity(intensity: number): [number, number, number, number] {
  const t = Math.max(0, Math.min(1, intensity));
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

function sampleBilinearRgba(
  src: Uint8ClampedArray,
  srcW: number,
  srcH: number,
  sx: number,
  sy: number,
  out: Uint8ClampedArray,
  outIdx: number
): void {
  const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
  const x = clamp(sx, 0, srcW - 1);
  const y = clamp(sy, 0, srcH - 1);
  const x0 = Math.floor(x);
  const y0 = Math.floor(y);
  const x1 = Math.min(srcW - 1, x0 + 1);
  const y1 = Math.min(srcH - 1, y0 + 1);
  const fx = x - x0;
  const fy = y - y0;
  for (let c = 0; c < 4; c += 1) {
    const i00 = (y0 * srcW + x0) * 4 + c;
    const i10 = (y0 * srcW + x1) * 4 + c;
    const i01 = (y1 * srcW + x0) * 4 + c;
    const i11 = (y1 * srcW + x1) * 4 + c;
    const v0 = src[i00] * (1 - fx) + src[i10] * fx;
    const v1 = src[i01] * (1 - fx) + src[i11] * fx;
    out[outIdx + c] = Math.round(v0 * (1 - fy) + v1 * fy);
  }
}

function resampleOverscanToTile(
  src: Uint8ClampedArray,
  srcW: number,
  srcH: number,
  outW: number,
  outH: number,
  pad: number
): Uint8ClampedArray {
  const scale = 1 + 2 * pad;
  const uOff = pad / scale;
  const uSpan = 1 / scale;
  const out = new Uint8ClampedArray(outW * outH * 4);
  for (let oy = 0; oy < outH; oy += 1) {
    const v = uOff + ((oy + 0.5) / outH) * uSpan;
    const sy = v * srcH - 0.5;
    for (let ox = 0; ox < outW; ox += 1) {
      const u = uOff + ((ox + 0.5) / outW) * uSpan;
      const sx = u * srcW - 0.5;
      const di = (oy * outW + ox) * 4;
      sampleBilinearRgba(src, srcW, srcH, sx, sy, out, di);
    }
  }
  return out;
}

export function buildInterpolatedImage(
  bounds: ViewBounds,
  cells: RasterCellInput[],
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

  const pad = HEATMAP_OVERSCAN_PAD;
  const overscanScale = 1 + 2 * pad;
  const expandedWestX = westX - spanX * pad;
  const expandedSpanX = spanX * overscanScale;
  const expandedMinY = minY - spanY * pad;
  const expandedSpanY = spanY * overscanScale;

  const points: InterpolationPoint[] = [];

  for (const cell of cells) {
    const [lat, lon] = cellToLatLng(cell.h3);
    const x = (lonToMercatorX(lon) - expandedWestX) / expandedSpanX;
    const y = (latToMercatorY(lat) - expandedMinY) / expandedSpanY;
    const value = Math.max(0, cell.metricValue);
    if (value <= 0) {
      continue;
    }
    points.push({ lon, lat, x, y, value });
  }

  if (points.length === 0 || normalizationMax <= 0) {
    return null;
  }

  const baseQuality = tileZoom >= 10 ? 96 : tileZoom >= 9 ? 120 : 160;
  const quality = points.length > 5000 ? Math.min(baseQuality, 96) : points.length > 2000 ? Math.min(baseQuality, 120) : baseQuality;
  const internalW = Math.ceil(quality * overscanScale);
  const internalH = Math.ceil(quality * overscanScale);
  const bucketIndex = buildBucketIndex(points);

  const image = new Uint8ClampedArray(internalW * internalH * 4);
  const sampleCell = cells[0];
  const [sampleLat, sampleLon] = cellToLatLng(sampleCell.h3);
  const sampleBoundary = cellToBoundary(sampleCell.h3);
  let influenceRadiusNormTile = 0.04;
  if (sampleBoundary.length > 0) {
    const [bLat, bLon] = sampleBoundary[0];
    const x0 = (lonToMercatorX(sampleLon) - westX) / spanX;
    const y0 = (latToMercatorY(sampleLat) - minY) / spanY;
    const x1 = (lonToMercatorX(bLon) - westX) / spanX;
    const y1 = (latToMercatorY(bLat) - minY) / spanY;
    const d = Math.hypot(x1 - x0, y1 - y0);
    influenceRadiusNormTile = Math.max(0.01, d * 2.6);
  }
  const influenceRadiusExpanded = influenceRadiusNormTile / overscanScale;
  const influenceRadiusSq = influenceRadiusExpanded * influenceRadiusExpanded;

  for (let py = 0; py < internalH; py += 1) {
    const yNorm = (py + 0.5) / internalH;
    for (let px = 0; px < internalW; px += 1) {
      const xNorm = (px + 0.5) / internalW;
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
        const idx = (py * internalW + px) * 4;
        image[idx] = 0;
        image[idx + 1] = 0;
        image[idx + 2] = 0;
        image[idx + 3] = 0;
        continue;
      }
      const ratio = Math.max(0, nearestValue / normalizationMax);
      const compressed = ratio / (ratio + HEATMAP_SOFT_KNEE);
      const shaped = Math.pow(compressed, 0.7);
      const [r, g, b, a] = colorForIntensity(shaped);
      const idx = (py * internalW + px) * 4;
      image[idx] = r;
      image[idx + 1] = g;
      image[idx + 2] = b;
      image[idx + 3] = a;
    }
  }

  const cropped = resampleOverscanToTile(image, internalW, internalH, quality, quality, pad);
  return { data: cropped, width: quality, height: quality };
}
