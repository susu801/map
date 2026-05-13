# Visited China Map

Python map renderer for travel check-ins. It accepts a list of 6-digit Chinese administrative city codes and returns a `data:image/png;base64,...` image with visited cities highlighted and labeled.

The renderer uses Pillow for PNG encoding and Chinese city-name labels. The first bundled fallback data pack is intentionally simplified so the renderer can run offline; for production, generate or provide a licensed city-boundary GeoJSON data pack as described below.

## Production map assets

The renderer now looks for a detailed offline GeoJSON asset at:

```text
visited_china_map/assets/china_city_boundaries.geojson
```

Generate it from an online city-boundary source:

```bash
python3 scripts/download_map_assets.py
```

To add precise surrounding-country administrative boundaries for the map background:

```bash
python3 scripts/download_map_assets.py --skip-china --include-neighbors --neighbor-adm ADM1
```

The neighbor asset is written to:

```text
visited_china_map/assets/neighbor_boundaries.geojson
```

Set `--neighbor-adm ADM2` if you want denser lower-level administrative boundaries, but expect a much larger file and slower rendering. Neighbor data is downloaded from geoBoundaries and requires proper attribution and license review before production release.

Or point the service at your own reviewed/licensed GeoJSON:

```bash
VISITED_CHINA_MAP_GEOJSON=/path/to/china_city_boundaries.geojson \
python3 -m visited_china_map.server --host 127.0.0.1 --port 8000
```

You can also provide a custom neighbor boundary pack:

```bash
VISITED_CHINA_MAP_NEIGHBOR_GEOJSON=/path/to/neighbor_boundaries.geojson \
python3 -m visited_china_map.server --host 127.0.0.1 --port 8000
```

Expected GeoJSON shape:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": { "adcode": "440100", "name": "广州市" },
      "geometry": { "type": "MultiPolygon", "coordinates": [] }
    }
  ]
}
```

For上线发布, use reviewed map assets from a compliant source. The natural-resources standard map service at [http://bzdt.ch.mnr.gov.cn](http://bzdt.ch.mnr.gov.cn) is the right place to verify standard-map requirements; many downloads there are standard map images/templates rather than city-level GeoJSON, so this plugin keeps the data source configurable.

## Usage

Use the renderer as a pure Python module:

```python
from visited_china_map import render_visited_china_map

image_url = render_visited_china_map(
    ["110000", "310000", "440100", "440305"],
    width=1080,
    height=900,
)
```

`image_url` is a `data:image/png;base64,...` string that can be returned by an API or assigned directly to an image component. Labels are drawn for the visited cities. If you need to use a specific Chinese font, set `VISITED_CHINA_MAP_FONT=/path/to/font.ttf`.

## HTTP service

Run the built-in service:

```bash
python3 -m visited_china_map.server --host 127.0.0.1 --port 8000
```

If port `8000` is already in use, start it on another port:

```bash
python3 -m visited_china_map.server --host 127.0.0.1 --port 8001
```

Open the GUI tester:

```text
http://127.0.0.1:8000/
```

The GUI lets you enter city codes, adjust image size and highlight colors, preview the rendered map, inspect normalized city codes and warnings, and download the generated PNG.

Render a map as JSON:

```bash
curl -X POST http://127.0.0.1:8000/render \
  -H 'Content-Type: application/json' \
  -d '{"cityCodes":["110000","310101","440305"],"width":1080,"height":900}'
```

Response:

```json
{
  "image": "data:image/png;base64,...",
  "normalizedCityCodes": ["110000", "310000", "440300"],
  "warnings": [],
  "width": 1080,
  "height": 900
}
```

Other endpoints:

- `GET /health`: service health check.
- `GET /cities`: supported city code list from the bundled data pack.
- `POST /render.png`: same request body as `/render`, but returns raw `image/png`.
