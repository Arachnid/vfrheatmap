from __future__ import annotations

from adsb_vfr.tiles.airspace import parse_airspace_items


def test_parse_airspace_items_filters_types_and_bbox() -> None:
    items = [
        {
            "name": "CTR TEST",
            "type": "CTR",
            "icaoClass": "D",
            "lowerLimit": {"value": 0, "unit": "FT", "referenceDatum": "AMSL"},
            "upperLimit": {"value": 4500, "unit": "FT", "referenceDatum": "AMSL"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-1.2, 50.8], [-1.2, 50.9], [-1.0, 50.9], [-1.0, 50.8], [-1.2, 50.8]]],
            },
            "properties": {"frequency": "123.450"},
        },
        {
            "name": "Class G Area",
            "type": "CLASSG",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-1.2, 50.8], [-1.2, 50.9], [-1.0, 50.9], [-1.0, 50.8], [-1.2, 50.8]]],
            },
        },
    ]
    feature_collection = parse_airspace_items(items, bbox=(50.0, -2.0, 51.5, 0.0))
    assert feature_collection["type"] == "FeatureCollection"
    assert len(feature_collection["features"]) == 1
    assert feature_collection["features"][0]["properties"]["type"] == "CTR"

