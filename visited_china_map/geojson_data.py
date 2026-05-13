from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from .data import CITY_FEATURES, TAIWAN_REGION_FEATURE, CityFeature, Ring

DEFAULT_ASSET_PATH = Path(__file__).with_name("assets") / "china_city_boundaries.geojson"
ASSET_ENV_VAR = "VISITED_CHINA_MAP_GEOJSON"


def load_city_features() -> list[CityFeature]:
    path = Path(os.environ.get(ASSET_ENV_VAR, DEFAULT_ASSET_PATH))
    if path.exists():
        return _with_fallback_regions(_load_geojson_features(str(path)))

    return _with_fallback_regions(CITY_FEATURES)


@lru_cache(maxsize=4)
def _load_geojson_features(path: str) -> list[CityFeature]:
    with open(path, "r", encoding="utf-8") as file:
        geojson = json.load(file)

    if geojson.get("type") != "FeatureCollection":
        raise ValueError(f"{path} must be a GeoJSON FeatureCollection.")

    features: list[CityFeature] = []
    for feature in geojson.get("features", []):
        parsed = _parse_feature(feature)
        if parsed is not None:
            features.append(parsed)

    if not features:
        raise ValueError(f"{path} does not contain usable city boundary features.")

    return features


def _parse_feature(feature: dict[str, Any]) -> CityFeature | None:
    properties = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}
    code = _string_property(properties, "adcode", "code", "gb", "gbcode")
    name = _string_property(properties, "name", "fullname", "full_name")

    if code is None or name is None:
        return None

    rings = _geometry_to_rings(geometry)
    if not rings:
        return None

    return {
        "code": code,
        "name": name,
        "province_code": _province_code(code),
        "geometry": rings,
        "aliases": _aliases_for_code(code),
    }


def _string_property(properties: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = properties.get(key)
        if isinstance(value, (str, int)):
            return str(value)

    return None


def _geometry_to_rings(geometry: dict[str, Any]) -> list[Ring]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")

    if geometry_type == "Polygon":
        return _polygon_to_rings(coordinates)

    if geometry_type == "MultiPolygon":
        rings: list[Ring] = []
        for polygon in coordinates or []:
            rings.extend(_polygon_to_rings(polygon))
        return rings

    return []


def _polygon_to_rings(polygon: Any) -> list[Ring]:
    if not isinstance(polygon, list) or not polygon:
        return []

    # The current rasterizer does not support holes, so it draws each outer ring.
    # City-level Chinese administrative geometries in the data packs used here are
    # still visually useful with this simplification.
    outer = polygon[0]
    if not isinstance(outer, list):
        return []

    ring: Ring = []
    for position in outer:
        if (
            isinstance(position, list)
            and len(position) >= 2
            and isinstance(position[0], (int, float))
            and isinstance(position[1], (int, float))
        ):
            ring.append((float(position[0]), float(position[1])))

    return [ring] if len(ring) >= 4 else []


def _province_code(code: str) -> str:
    return f"{code[:2]}0000" if len(code) == 6 else code


def _aliases_for_code(code: str) -> list[str]:
    aliases: list[str] = []
    if code in {"110000", "120000", "310000", "500000"}:
        aliases.append(f"{code[:2]}0100")
    return aliases


def _with_fallback_regions(features: list[CityFeature]) -> list[CityFeature]:
    normalized_features = [
        TAIWAN_REGION_FEATURE if feature["code"] == "710000" else feature for feature in features
    ]
    existing_codes = {feature["code"] for feature in normalized_features}
    required = {"710000", "810000", "820000"}
    additions = [
        TAIWAN_REGION_FEATURE if feature["code"] == "710000" else feature
        for feature in CITY_FEATURES
        if feature["code"] in required - existing_codes
    ]
    return [*normalized_features, *additions]
