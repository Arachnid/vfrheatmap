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

export type TrafficRasterLayerOut = {
  cacheKey: string;
  layerId: string;
  bounds: [number, number, number, number];
  bitmap: ImageBitmap;
};

self.onmessage = (event: MessageEvent<TrafficRasterRequest>) => {
  const { requestId, jobs } = event.data;
  const layers: TrafficRasterLayerOut[] = [];

  for (const job of jobs) {
    const image = buildInterpolatedImage(job.bounds, job.cells, job.normalizedScale, job.tileZ);
    if (!image) {
      continue;
    }
    const canvas = new OffscreenCanvas(image.width, image.height);
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      continue;
    }
    ctx.putImageData(new ImageData(new Uint8ClampedArray(image.data), image.width, image.height), 0, 0);
    const bitmap = canvas.transferToImageBitmap();
    layers.push({
      cacheKey: job.cacheKey,
      layerId: job.layerId,
      bounds: [job.bounds.west, job.bounds.south, job.bounds.east, job.bounds.north],
      bitmap,
    });
  }

  postMessage({ requestId, layers }, { transfer: layers.map((L) => L.bitmap) });
};
