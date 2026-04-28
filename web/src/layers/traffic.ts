import { BitmapLayer, LineLayer } from "@deck.gl/layers";
import { cellToBoundary, cellToLatLng } from "h3-js";

import type { RenderableCell } from "../types";

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
  // Matches the existing blue->orange ramp style.
  const stops: Array<[number, number, number, number]> = [
    [20, 60, 120, 0],
    [45, 95, 160, 70],
    [70, 140, 190, 120],
    [130, 180, 140, 160],
    [220, 170, 90, 210],
    [255, 110, 45, 245],
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
  const source = candidates.length > 0 ? candidates : points.map((_, idx) => idx);
  for (const idx of source) {
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

function buildInterpolatedImage(bounds: ViewBounds, cells: RenderableCell[]): { data: Uint8ClampedArray; width: number; height: number } | null {
  const westX = lonToMercatorX(bounds.west);
  const eastX = lonToMercatorX(bounds.east);
  const northY = latToMercatorY(bounds.north);
  const southY = latToMercatorY(bounds.south);
  const minY = Math.min(northY, southY);
  const spanX = Math.max(1e-9, eastX - westX);
  const spanY = Math.max(1e-9, Math.abs(southY - northY));
  const points: InterpolationPoint[] = [];
  let maxValue = 0;

  for (const cell of cells) {
    const [lat, lon] = cellToLatLng(cell.h3);
    const x = (lonToMercatorX(lon) - westX) / spanX;
    const y = (latToMercatorY(lat) - minY) / spanY;
    const value = Math.max(0, cell.metricValue);
    if (value <= 0) {
      continue;
    }
    points.push({ lon, lat, x, y, value });
    if (value > maxValue) {
      maxValue = value;
    }
  }

  if (points.length === 0 || maxValue <= 0) {
    return null;
  }

  // Reduce raster resolution when point counts are high to keep interaction smooth.
  const quality = points.length > 5000 ? 120 : points.length > 2000 ? 150 : 200;
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
      let nearestSq = Number.POSITIVE_INFINITY;
      for (const p of points) {
        const dx = xNorm - p.x;
        const dy = yNorm - p.y;
        const d2 = dx * dx + dy * dy;
        if (d2 < nearestSq) {
          nearestSq = d2;
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

      const value = nearest3IdwValue(xNorm, yNorm, points, bucketIndex);
      const normalized = Math.max(0, Math.min(1, value / maxValue));
      // Gentle contrast for low-value structure without hotspot look.
      const shaped = Math.pow(normalized, 0.7);
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

export function buildTrafficLayer(cells: RenderableCell[], viewBounds: ViewBounds | null, _viewZoom: number) {
  if (cells.length === 0) {
    return null;
  }
  if (!viewBounds) {
    return null;
  }
  const bounds = normalizeBounds(viewBounds);
  const image = buildInterpolatedImage(bounds, cells);
  if (!image) {
    return null;
  }
  const bitmapCanvas = document.createElement("canvas");
  bitmapCanvas.width = image.width;
  bitmapCanvas.height = image.height;
  const ctx = bitmapCanvas.getContext("2d");
  if (!ctx) {
    return null;
  }
  const pixelData = new Uint8ClampedArray(image.data);
  ctx.putImageData(new ImageData(pixelData, image.width, image.height), 0, 0);
  return new BitmapLayer({
    id: "traffic-layer",
    image: bitmapCanvas,
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
  });
}

export function buildArrowLayer(cells: RenderableCell[], enabled: boolean) {
  if (!enabled) {
    return null;
  }
  const DIRECTIONAL_SHARE_THRESHOLD = 0.5;
  const lines: Array<{ sourcePosition: [number, number]; targetPosition: [number, number] }> = [];
  const wrapIndex = (idx: number) => ((idx % 16) + 16) % 16;
  const axisShare = (hist: number[], headingBin: number) => {
    const total = hist.reduce((acc, value) => acc + value, 0);
    if (total <= 0) {
      return 0;
    }
    const opposite = wrapIndex(headingBin + 8);
    const bins = [
      wrapIndex(headingBin - 1),
      headingBin,
      wrapIndex(headingBin + 1),
      wrapIndex(opposite - 1),
      opposite,
      wrapIndex(opposite + 1),
    ];
    const aligned = bins.reduce((acc, idx) => acc + (hist[idx] ?? 0), 0);
    return aligned / total;
  };
  const arrowLengthDeg = (h3Cell: string, lat: number, lon: number) => {
    const boundary = cellToBoundary(h3Cell);
    if (boundary.length === 0) {
      return 0.02;
    }
    const latRad = (lat * Math.PI) / 180;
    const cosLat = Math.max(0.25, Math.cos(latRad));
    let minRadius = Number.POSITIVE_INFINITY;
    for (const [bLat, bLon] of boundary) {
      const dx = (bLon - lon) * cosLat;
      const dy = bLat - lat;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < minRadius) {
        minRadius = dist;
      }
    }
    if (!Number.isFinite(minRadius) || minRadius <= 0) {
      return 0.02;
    }
    return minRadius * 0.75;
  };
  const addArrow = (lon: number, lat: number, east: number, north: number, lengthDeg: number) => {
    const latRad = (lat * Math.PI) / 180;
    const cosLat = Math.max(0.25, Math.cos(latRad));
    const mag = Math.sqrt(east * east + north * north);
    if (mag <= 1e-6) {
      return;
    }
    const ux = east / mag;
    const uy = north / mag;
    lines.push({
      sourcePosition: [lon, lat],
      targetPosition: [lon + (ux * lengthDeg) / cosLat, lat + uy * lengthDeg],
    });
  };

  for (const cell of cells) {
    if (cell.metricValue <= 0 || cell.coherence < 0.3) {
      continue;
    }
    const [lat, lon] = cellToLatLng(cell.h3);
    const length = arrowLengthDeg(cell.h3, lat, lon);
    if (cell.coherence > 0.6) {
      const heading = (Math.atan2(cell.mean_track_y, cell.mean_track_x) * 180) / Math.PI;
      const headingNorm = (heading + 360) % 360;
      const headingBin = Math.floor(headingNorm / 22.5) % 16;
      if (axisShare(cell.track_hist, headingBin) < DIRECTIONAL_SHARE_THRESHOLD) {
        continue;
      }
      addArrow(lon, lat, cell.mean_track_y, cell.mean_track_x, length);
      continue;
    }
    const hist = cell.track_hist;
    const peak1 = hist.reduce((best, value, idx) => (value > hist[best] ? idx : best), 0);
    const opposite = (peak1 + 8) % 16;
    const peak2Candidates = [opposite, (opposite + 1) % 16, (opposite + 15) % 16];
    const peak2 = peak2Candidates.reduce((best, idx) => (hist[idx] > hist[best] ? idx : best), peak2Candidates[0]);
    const low = Math.min(hist[peak1], hist[peak2]);
    const troughIdx = (peak1 + 4) % 16;
    const trough = hist[troughIdx];
    const heading = (Math.atan2(cell.mean_track_y, cell.mean_track_x) * 180) / Math.PI;
    const headingNorm = (heading + 360) % 360;
    const headingBin = Math.floor(headingNorm / 22.5) % 16;
    const dominantAxisShare = axisShare(hist, headingBin);
    if (low <= 0 || trough > low * 0.3) {
      if (dominantAxisShare >= DIRECTIONAL_SHARE_THRESHOLD) {
        addArrow(lon, lat, cell.mean_track_y, cell.mean_track_x, length);
      }
      continue;
    }
    if (axisShare(hist, peak1) < DIRECTIONAL_SHARE_THRESHOLD) {
      continue;
    }
    const angle1 = ((peak1 + 0.5) * 360) / 16;
    const angle2 = ((peak2 + 0.5) * 360) / 16;
    const vec = (angleDeg: number) => {
      const rad = (angleDeg * Math.PI) / 180;
      return [Math.sin(rad), Math.cos(rad)] as const;
    };
    const [x1, y1] = vec(angle1);
    const [x2, y2] = vec(angle2);
    addArrow(lon, lat, x1, y1, length);
    addArrow(lon, lat, x2, y2, length);
  }
  return new LineLayer({
    id: "direction-arrows",
    data: lines,
    getSourcePosition: (d: { sourcePosition: [number, number] }) => d.sourcePosition,
    getTargetPosition: (d: { targetPosition: [number, number] }) => d.targetPosition,
    getColor: [30, 30, 30, 190],
    getWidth: 2,
    widthUnits: "pixels",
  });
}
