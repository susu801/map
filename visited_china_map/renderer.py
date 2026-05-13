from __future__ import annotations

import base64
import io
import os
import re
import struct
import zlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, TypeAlias, TypedDict

from .data import (
    CHINA_BOUNDS,
    DISTRICT_TO_CITY,
    CityFeature,
    Position,
    Ring,
)
from .geojson_data import load_city_features

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - exercised only in minimal installs.
    Image = None
    ImageDraw = None
    ImageFont = None

DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 900

RGBA: TypeAlias = tuple[int, int, int, int]
Point: TypeAlias = tuple[float, float]
Projector: TypeAlias = Callable[[Position], Point]
WarningCallback: TypeAlias = Callable[["RenderWarning"], None]


class MapTheme(TypedDict, total=False):
    background: str
    land_fill: str
    land_stroke: str
    city_fill: str
    city_stroke: str
    visited_fill: str
    visited_stroke: str
    inset_stroke: str
    label_text: str
    label_halo: str
    label_marker: str


@dataclass(frozen=True)
class RenderWarning:
    code: str
    reason: str


DEFAULT_THEME: MapTheme = {
    "background": "#f8fbff",
    "land_fill": "#edf3f8",
    "land_stroke": "#aab9c8",
    "city_fill": "#dfe8f0",
    "city_stroke": "#bccbd8",
    "visited_fill": "#21b7a8",
    "visited_stroke": "#0f766e",
    "inset_stroke": "#8fa0b1",
    "label_text": "#1f3347",
    "label_halo": "#ffffff",
    "label_marker": "#0f766e",
}

FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
)

MUNICIPALITY_PREFIXES = {
    "11": "110000",
    "12": "120000",
    "31": "310000",
    "50": "500000",
}

CITY_BOUNDARY_FEATURES = load_city_features()
FEATURE_INDEX: dict[str, CityFeature] = {}
for feature in CITY_BOUNDARY_FEATURES:
    FEATURE_INDEX[feature["code"]] = feature
    for alias in feature.get("aliases", []):
        FEATURE_INDEX[alias] = feature


def render_visited_china_map(
    city_codes: list[str],
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    theme: MapTheme | None = None,
    on_warning: WarningCallback | None = None,
) -> str:
    """Render a China visited-city highlight map as a PNG data URL."""
    safe_width = max(1, int(width))
    safe_height = max(1, int(height))
    resolved_theme = {**DEFAULT_THEME, **(theme or {})}
    normalized = normalize_city_codes(city_codes, on_warning=on_warning)
    theme_key = tuple(sorted(resolved_theme.items()))
    png = _render_cached(tuple(normalized), safe_width, safe_height, theme_key)
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def normalize_city_codes(
    city_codes: list[str],
    *,
    on_warning: WarningCallback | None = None,
) -> list[str]:
    normalized: set[str] = set()

    for raw_code in city_codes:
        if not re.fullmatch(r"\d{6}", raw_code):
            _warn(on_warning, raw_code, "invalid-code")
            continue

        candidate = _resolve_city_code(raw_code)
        if candidate is None or candidate not in FEATURE_INDEX:
            _warn(on_warning, raw_code, "unknown-city")
            continue

        normalized.add(FEATURE_INDEX[candidate]["code"])

    return sorted(normalized)


def get_supported_city_codes() -> list[str]:
    return [feature["code"] for feature in CITY_BOUNDARY_FEATURES]


def _warn(callback: WarningCallback | None, code: str, reason: str) -> None:
    if callback:
        callback(RenderWarning(code=code, reason=reason))


def _resolve_city_code(code: str) -> str | None:
    if code in FEATURE_INDEX:
        return code

    municipality = MUNICIPALITY_PREFIXES.get(code[:2])
    if municipality:
        return municipality

    if code in DISTRICT_TO_CITY:
        return DISTRICT_TO_CITY[code]

    prefecture_code = code[:4] + "00"
    return prefecture_code if prefecture_code in FEATURE_INDEX else None


@lru_cache(maxsize=64)
def _render_cached(
    visited_codes: tuple[str, ...],
    width: int,
    height: int,
    theme_key: tuple[tuple[str, str], ...],
) -> bytes:
    theme = dict(theme_key)
    raster = _render_to_raster(width, height, theme, set(visited_codes))
    return _encode_png(raster, width, height)


def _render_to_raster(width: int, height: int, theme: dict[str, str], visited: set[str]) -> bytearray:
    pixels = bytearray(width * height * 4)
    project = _create_projector(width, height)

    _fill_all(pixels, _parse_color(theme["background"]))

    for feature in CITY_BOUNDARY_FEATURES:
        is_visited = feature["code"] in visited
        _draw_rings(
            pixels,
            width,
            height,
            feature["geometry"],
            project,
            _parse_color(theme["visited_fill"] if is_visited else theme["city_fill"]),
            _parse_color(theme["visited_stroke"] if is_visited else theme["city_stroke"]),
        )

    _draw_city_labels(pixels, width, height, project, theme, visited)
    return pixels


def _create_projector(width: int, height: int) -> Projector:
    padding_x = width * 0.08
    padding_y = height * 0.08
    map_width = width - padding_x * 2
    map_height = height - padding_y * 2
    lon_span = CHINA_BOUNDS["max_lon"] - CHINA_BOUNDS["min_lon"]
    lat_span = CHINA_BOUNDS["max_lat"] - CHINA_BOUNDS["min_lat"]
    scale = min(map_width / lon_span, map_height / lat_span)
    offset_x = (width - lon_span * scale) / 2
    offset_y = (height - lat_span * scale) / 2

    def project(position: Position) -> Point:
        lon, lat = position
        return (
            offset_x + (lon - CHINA_BOUNDS["min_lon"]) * scale,
            offset_y + (CHINA_BOUNDS["max_lat"] - lat) * scale,
        )

    return project


def _draw_rings(
    pixels: bytearray,
    width: int,
    height: int,
    rings: list[Ring],
    project: Projector,
    fill: RGBA,
    stroke: RGBA,
) -> None:
    for ring in rings:
        polygon = [project(position) for position in ring]
        _fill_polygon(pixels, width, height, polygon, fill)
        _stroke_polygon(pixels, width, height, polygon, stroke)


def _fill_all(pixels: bytearray, color: RGBA) -> None:
    r, g, b, a = color
    for index in range(0, len(pixels), 4):
        pixels[index : index + 4] = bytes((r, g, b, a))


def _fill_rect(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    rect_width: int,
    rect_height: int,
    color: RGBA,
) -> None:
    for py in range(max(0, y), min(height, y + rect_height)):
        for px in range(max(0, x), min(width, x + rect_width)):
            _set_pixel(pixels, width, px, py, color)


def _stroke_rect(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    rect_width: int,
    rect_height: int,
    color: RGBA,
) -> None:
    _draw_line(pixels, width, height, x, y, x + rect_width, y, color)
    _draw_line(pixels, width, height, x + rect_width, y, x + rect_width, y + rect_height, color)
    _draw_line(pixels, width, height, x + rect_width, y + rect_height, x, y + rect_height, color)
    _draw_line(pixels, width, height, x, y + rect_height, x, y, color)


def _fill_polygon(
    pixels: bytearray,
    width: int,
    height: int,
    polygon: list[Point],
    color: RGBA,
) -> None:
    min_x, max_x, min_y, max_y = _polygon_bounds(polygon, width, height)

    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            if _point_in_polygon(x + 0.5, y + 0.5, polygon):
                _set_pixel(pixels, width, x, y, color)


def _stroke_polygon(
    pixels: bytearray,
    width: int,
    height: int,
    polygon: list[Point],
    color: RGBA,
) -> None:
    for current, next_point in zip(polygon, polygon[1:]):
        _draw_line(pixels, width, height, current[0], current[1], next_point[0], next_point[1], color)


def _draw_line(
    pixels: bytearray,
    width: int,
    height: int,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    color: RGBA,
) -> None:
    x = round(x1)
    y = round(y1)
    target_x = round(x2)
    target_y = round(y2)
    dx = abs(target_x - x)
    sx = 1 if x < target_x else -1
    dy = -abs(target_y - y)
    sy = 1 if y < target_y else -1
    error = dx + dy

    while True:
        if 0 <= x < width and 0 <= y < height:
            _set_pixel(pixels, width, x, y, color)

        if x == target_x and y == target_y:
            break

        doubled = error * 2
        if doubled >= dy:
            error += dy
            x += sx
        if doubled <= dx:
            error += dx
            y += sy


def _polygon_bounds(polygon: list[Point], width: int, height: int) -> tuple[int, int, int, int]:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return (
        _clamp(int(min(xs)), 0, width - 1),
        _clamp(int(max(xs) + 1), 0, width - 1),
        _clamp(int(min(ys)), 0, height - 1),
        _clamp(int(max(ys) + 1), 0, height - 1),
    )


def _point_in_polygon(x: float, y: float, polygon: list[Point]) -> bool:
    inside = False
    j = len(polygon) - 1

    for i, point in enumerate(polygon):
        xi, yi = point
        xj, yj = polygon[j]
        intersects = (yi > y) != (yj > y) and x < ((xj - xi) * (y - yi)) / (yj - yi) + xi
        if intersects:
            inside = not inside
        j = i

    return inside


def _draw_city_labels(
    pixels: bytearray,
    width: int,
    height: int,
    project: Projector,
    theme: dict[str, str],
    visited: set[str],
) -> None:
    if Image is None or ImageDraw is None or ImageFont is None or not visited:
        return

    font = _load_label_font(width)
    if font is None:
        return

    image = Image.frombytes("RGBA", (width, height), bytes(pixels))
    draw = ImageDraw.Draw(image, "RGBA")
    text_color = _parse_color(theme["label_text"])
    halo_color = _parse_color(theme["label_halo"])
    marker_color = _parse_color(theme["label_marker"])
    occupied: list[tuple[int, int, int, int]] = []

    for feature in CITY_BOUNDARY_FEATURES:
        if feature["code"] not in visited:
            continue

        point = _feature_label_point(feature, project)
        if point is None:
            continue

        _draw_label(draw, width, height, point, feature["name"], font, text_color, halo_color, marker_color, occupied)

    pixels[:] = image.tobytes()


def _load_label_font(width: int):
    font_size = _clamp(int(width * 0.018), 13, 22)
    configured_font = os.environ.get("VISITED_CHINA_MAP_FONT")
    candidates = (configured_font, *FONT_CANDIDATES) if configured_font else FONT_CANDIDATES

    for path in candidates:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, font_size)

    return None


def _feature_label_point(feature: CityFeature, project: Projector) -> Point | None:
    best_polygon: list[Point] | None = None
    best_area = -1.0

    for ring in feature["geometry"]:
        polygon = [project(position) for position in ring]
        area = abs(_polygon_area(polygon))
        if area > best_area:
            best_area = area
            best_polygon = polygon

    if not best_polygon:
        return None

    return _polygon_centroid(best_polygon)


def _draw_label(
    draw,
    width: int,
    height: int,
    point: Point,
    text: str,
    font,
    text_color: RGBA,
    halo_color: RGBA,
    marker_color: RGBA,
    occupied: list[tuple[int, int, int, int]],
) -> None:
    x, y = point
    marker_radius = max(3, int(width * 0.004))
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    candidates = (
        (8, -text_height - 8),
        (8, 7),
        (-text_width - 8, -text_height - 8),
        (-text_width - 8, 7),
        (-text_width / 2, -text_height - 12),
    )

    text_x = text_y = None
    label_rect = None
    for offset_x, offset_y in candidates:
        candidate_x = _clamp(int(x + offset_x), 2, max(2, width - text_width - 2))
        candidate_y = _clamp(int(y + offset_y), 2, max(2, height - text_height - 2))
        candidate_rect = (
            candidate_x - 4,
            candidate_y - 4,
            candidate_x + text_width + 4,
            candidate_y + text_height + 4,
        )
        if not any(_rects_intersect(candidate_rect, existing) for existing in occupied):
            text_x = candidate_x
            text_y = candidate_y
            label_rect = candidate_rect
            break

    if text_x is None or text_y is None or label_rect is None:
        return

    draw.ellipse(
        (
            int(x - marker_radius),
            int(y - marker_radius),
            int(x + marker_radius),
            int(y + marker_radius),
        ),
        fill=marker_color,
        outline=(255, 255, 255, 230),
        width=1,
    )
    for dx, dy in ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)):
        draw.text((text_x + dx, text_y + dy), text, font=font, fill=halo_color)
    draw.text((text_x, text_y), text, font=font, fill=text_color)
    occupied.append(label_rect)


def _polygon_area(polygon: list[Point]) -> float:
    area = 0.0
    for current, next_point in zip(polygon, polygon[1:]):
        area += current[0] * next_point[1] - next_point[0] * current[1]
    return area / 2


def _polygon_centroid(polygon: list[Point]) -> Point:
    area = _polygon_area(polygon)
    if abs(area) < 0.001:
        return (
            sum(point[0] for point in polygon) / len(polygon),
            sum(point[1] for point in polygon) / len(polygon),
        )

    cx = 0.0
    cy = 0.0
    for current, next_point in zip(polygon, polygon[1:]):
        cross = current[0] * next_point[1] - next_point[0] * current[1]
        cx += (current[0] + next_point[0]) * cross
        cy += (current[1] + next_point[1]) * cross

    factor = 1 / (6 * area)
    return cx * factor, cy * factor


def _rects_intersect(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> bool:
    return first[0] < second[2] and first[2] > second[0] and first[1] < second[3] and first[3] > second[1]


def _set_pixel(pixels: bytearray, width: int, x: int, y: int, color: RGBA) -> None:
    index = (y * width + x) * 4
    pixels[index : index + 4] = bytes(color)


def _parse_color(color: str) -> RGBA:
    hex_color = color.removeprefix("#")
    if not re.fullmatch(r"([a-fA-F\d]{6}|[a-fA-F\d]{8})", hex_color):
        raise ValueError(f'Unsupported color "{color}". Use #RRGGBB or #RRGGBBAA.')

    red = int(hex_color[0:2], 16)
    green = int(hex_color[2:4], 16)
    blue = int(hex_color[4:6], 16)
    alpha = int(hex_color[6:8], 16) if len(hex_color) == 8 else 255
    return red, green, blue, alpha


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _encode_png(pixels: bytearray, width: int, height: int) -> bytes:
    if Image is not None:
        with io.BytesIO() as output:
            Image.frombytes("RGBA", (width, height), bytes(pixels)).save(output, format="PNG", optimize=True)
            return output.getvalue()

    raw = bytearray()
    row_length = width * 4

    for y in range(height):
        raw.append(0)
        start = y * row_length
        raw.extend(pixels[start : start + row_length])

    signature = b"\x89PNG\r\n\x1a\n"
    return b"".join(
        [
            signature,
            _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
            _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=6)),
            _png_chunk(b"IEND", b""),
        ]
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )
