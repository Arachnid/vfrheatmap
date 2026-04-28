from __future__ import annotations

from dataclasses import dataclass

import h3
import mercantile


ZOOM_TO_H3_RESOLUTION: dict[int, int] = {
    5: 5,
    6: 5,
    7: 6,
    8: 7,
    9: 7,
    10: 8,
    11: 9,
}


@dataclass(frozen=True)
class TileKey:
    z: int
    x: int
    y: int


def h3_cell_to_tile(cell: int, zoom: int) -> TileKey:
    lat, lon = h3.cell_to_latlng(h3.int_to_str(int(cell)))
    tile = mercantile.tile(lon, lat, zoom)
    return TileKey(z=zoom, x=tile.x, y=tile.y)


def tiles_for_bbox(
    bbox: tuple[float, float, float, float],
    zoom: int,
) -> list[TileKey]:
    min_lat, min_lon, max_lat, max_lon = bbox
    return [
        TileKey(z=zoom, x=t.x, y=t.y)
        for t in mercantile.tiles(min_lon, min_lat, max_lon, max_lat, [zoom])
    ]

