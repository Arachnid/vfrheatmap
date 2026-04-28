import type { Classification, TileCell, TilePayload } from "../types";
import type { TileKey } from "./tileMath";

const MAX_CACHE_SIZE = 200;

function tileId(classification: Classification, key: TileKey): string {
  return `${classification}:${key.z}/${key.x}/${key.y}`;
}

async function parseMaybeGzipJson<T>(response: Response): Promise<T | null> {
  const bytes = await response.arrayBuffer();
  const decoder = new TextDecoder();
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("text/html")) {
    return null;
  }
  const preview = decoder.decode(bytes.slice(0, 64));
  if (preview.startsWith("<!doctype html") || preview.startsWith("<html")) {
    return null;
  }
  try {
    return JSON.parse(decoder.decode(bytes)) as T;
  } catch {
    try {
      const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
      const text = await new Response(stream).text();
      return JSON.parse(text) as T;
    } catch {
      return null;
    }
  }
}

export class TileManager {
  private cache = new Map<string, TileCell[]>();
  private inFlight = new Map<string, AbortController>();

  async loadTiles(classification: Classification, keys: TileKey[]): Promise<TileCell[]> {
    console.debug("[tiles] loadTiles start", { classification, requestedTiles: keys.length });
    const result: TileCell[] = [];
    const wanted = new Set(keys.map((k) => tileId(classification, k)));
    const classificationPrefix = `${classification}:`;
    for (const [key, controller] of this.inFlight.entries()) {
      if (!key.startsWith(classificationPrefix)) {
        continue;
      }
      if (!wanted.has(key)) {
        controller.abort();
        this.inFlight.delete(key);
      }
    }
    await Promise.all(
      keys.map(async (key) => {
        const id = tileId(classification, key);
        const cached = this.cache.get(id);
        if (cached) {
          result.push(...cached);
          this.cache.delete(id);
          this.cache.set(id, cached);
          return;
        }
        const controller = new AbortController();
        this.inFlight.set(id, controller);
        try {
          const url = `./data/tiles/${classification}/z${key.z}/x${key.x}/y${key.y}.json.gz`;
          const response = await fetch(`./data/tiles/${classification}/z${key.z}/x${key.x}/y${key.y}.json.gz`, {
            signal: controller.signal,
          });
          if (!response.ok) {
            console.debug("[tiles] missing tile", { classification, tile: key, status: response.status, url });
            return;
          }
          const payload = await parseMaybeGzipJson<TilePayload>(response);
          if (!payload) {
            console.debug("[tiles] non-tile response treated as missing", { classification, tile: key, url });
            return;
          }
          console.debug("[tiles] tile loaded", { classification, tile: key, cells: payload.cells.length });
          this.cache.set(id, payload.cells);
          if (this.cache.size > MAX_CACHE_SIZE) {
            const oldest = this.cache.keys().next().value as string | undefined;
            if (oldest) {
              this.cache.delete(oldest);
            }
          }
          result.push(...payload.cells);
        } catch (error) {
          if (error instanceof DOMException && error.name === "AbortError") {
            console.debug("[tiles] tile request aborted", { classification, tile: key });
            return;
          }
          console.error("[tiles] tile request failed", { classification, tile: key, error });
          throw error;
        } finally {
          this.inFlight.delete(id);
        }
      })
    );
    console.debug("[tiles] loadTiles done", { classification, loadedCells: result.length });
    return result;
  }
}
