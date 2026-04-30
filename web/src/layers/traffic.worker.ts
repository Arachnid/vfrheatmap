import { buildInterpolatedImage, type RasterCellInput, type ViewBounds } from "./trafficRasterCore";

export type TrafficRasterJob = {
  cacheKey: string;
  layerId: string;
  bounds: ViewBounds;
  cells: RasterCellInput[];
  normalizedScale: number;
  tileZ: number;
};

export type TrafficRasterRequest = {
  requestId: number;
  jobs: TrafficRasterJob[];
};

self.onmessage = (event: MessageEvent<TrafficRasterRequest>) => {
  const { requestId, jobs } = event.data;

  for (const job of jobs) {
    const image = buildInterpolatedImage(job.bounds, job.cells, job.normalizedScale, job.tileZ);
    if (!image) {
      continue;
    }
    const canvas = new OffscreenCanvas(image.width, image.height);
    const ctx = canvas.getContext("2d", { colorSpace: "srgb" });
    if (!ctx) {
      continue;
    }
    ctx.putImageData(new ImageData(new Uint8ClampedArray(image.data), image.width, image.height), 0, 0);
    const bitmap = canvas.transferToImageBitmap();
    postMessage({ requestId, layer: { cacheKey: job.cacheKey, bitmap } }, { transfer: [bitmap] });
  }

  postMessage({ requestId, done: true as const });
};
