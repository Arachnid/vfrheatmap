export interface LngLatBounds {
  west: number;
  south: number;
  east: number;
  north: number;
}

export interface TileKey {
  z: number;
  x: number;
  y: number;
}

const clampLat = (lat: number): number => Math.max(-85.05112878, Math.min(85.05112878, lat));

const lonToTileX = (lon: number, z: number): number => {
  const n = 2 ** z;
  return Math.floor(((lon + 180) / 360) * n);
};

const latToTileY = (lat: number, z: number): number => {
  const n = 2 ** z;
  const latRad = (clampLat(lat) * Math.PI) / 180;
  const y = (1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2;
  return Math.floor(y * n);
};

export function tilesForViewport(bounds: LngLatBounds, zoom: number): TileKey[] {
  const z = Math.max(5, Math.min(11, Math.floor(zoom)));
  const west = Math.min(bounds.west, bounds.east);
  const east = Math.max(bounds.west, bounds.east);
  const south = Math.min(bounds.south, bounds.north);
  const north = Math.max(bounds.south, bounds.north);
  const minX = lonToTileX(west, z);
  const maxX = lonToTileX(east, z);
  const minY = latToTileY(north, z);
  const maxY = latToTileY(south, z);
  const tiles: TileKey[] = [];
  for (let x = minX; x <= maxX; x += 1) {
    for (let y = minY; y <= maxY; y += 1) {
      tiles.push({ z, x, y });
    }
  }
  return tiles;
}
