import { describe, expect, it } from "vitest";

import { tilesForViewport } from "./tileMath";

describe("tilesForViewport", () => {
  it("returns covering tiles for viewport", () => {
    const tiles = tilesForViewport({ west: -1.5, south: 50.5, east: -1.0, north: 51.0 }, 8);
    expect(tiles.length).toBeGreaterThan(0);
    expect(tiles[0]?.z).toBe(8);
  });
});
