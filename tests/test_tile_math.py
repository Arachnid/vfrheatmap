from __future__ import annotations

import h3

from adsb_vfr.tiles.tile_math import ZOOM_TO_H3_RESOLUTION, h3_cell_to_tile, tiles_for_bbox


def test_zoom_mapping_complete() -> None:
    assert ZOOM_TO_H3_RESOLUTION == {
        5: 5,
        6: 5,
        7: 6,
        8: 7,
        9: 7,
        10: 8,
        11: 9,
    }


def test_h3_cell_to_tile_is_stable() -> None:
    cell = int(h3.str_to_int(h3.latlng_to_cell(51.4700, -0.4543, 7)))
    tile = h3_cell_to_tile(cell, zoom=8)
    assert tile.z == 8
    assert isinstance(tile.x, int)
    assert isinstance(tile.y, int)


def test_tiles_for_bbox_returns_coverage() -> None:
    tiles = tiles_for_bbox((50.5, -1.5, 51.0, -1.0), zoom=8)
    assert len(tiles) > 0
    assert all(t.z == 8 for t in tiles)

