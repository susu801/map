import json
import tempfile
import unittest
from pathlib import Path

from visited_china_map.geojson_data import _load_geojson_features, load_city_features


class GeoJsonDataTest(unittest.TestCase):
    def test_loads_feature_collection_with_polygon_and_multipolygon(self):
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"adcode": 440100, "name": "广州市"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [[113.0, 22.5], [114.0, 22.5], [114.0, 23.5], [113.0, 22.5]]
                        ],
                    },
                },
                {
                    "type": "Feature",
                    "properties": {"adcode": "440300", "name": "深圳市"},
                    "geometry": {
                        "type": "MultiPolygon",
                        "coordinates": [
                            [
                                [
                                    [113.7, 22.2],
                                    [114.6, 22.2],
                                    [114.6, 22.8],
                                    [113.7, 22.2],
                                ]
                            ]
                        ],
                    },
                },
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cities.geojson"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            features = _load_geojson_features(str(path))

        self.assertEqual([feature["code"] for feature in features], ["440100", "440300"])
        self.assertEqual(features[0]["name"], "广州市")
        self.assertEqual(len(features[1]["geometry"]), 1)

    def test_normalizes_taiwan_region_layer_name(self):
        taiwan = next(feature for feature in load_city_features() if feature["code"] == "710000")

        self.assertEqual(taiwan["name"], "台湾地区")
        self.assertGreaterEqual(len(taiwan["geometry"]), 1)


if __name__ == "__main__":
    unittest.main()
