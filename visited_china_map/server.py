from __future__ import annotations

import argparse
import base64
import errno
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    get_supported_city_codes,
    normalize_city_codes,
    render_visited_china_map,
)
from .renderer import MapTheme, RenderWarning

MAX_BODY_BYTES = 1024 * 1024


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


class MapServiceHandler(BaseHTTPRequestHandler):
    server_version = "VisitedChinaMapService/0.1"

    def do_GET(self) -> None:
        if self.path in {"/", "/app"}:
            self._send_html(APP_HTML)
            return

        if self.path == "/health":
            self._send_json({"ok": True})
            return

        if self.path == "/cities":
            self._send_json({"cityCodes": get_supported_city_codes()})
            return

        self._send_json(
            {
                "error": "not-found",
                "message": "Use GET /health, GET /cities, or POST /render.",
            },
            status=HTTPStatus.NOT_FOUND,
        )

    def do_POST(self) -> None:
        if self.path not in {"/render", "/render.png"}:
            self._send_json(
                {
                    "error": "not-found",
                    "message": "Use POST /render or POST /render.png to render a visited map.",
                },
                status=HTTPStatus.NOT_FOUND,
            )
            return

        try:
            payload = self._read_json()
            response = render_payload(payload)
        except ValueError as error:
            self._send_json(
                {"error": "bad-request", "message": str(error)},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        if self.path == "/render.png":
            self._send_png(data_url_to_png_bytes(response["image"]))
            return

        self._send_json(response)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length_header = self.headers.get("Content-Length")
        if not length_header:
            raise ValueError("Missing Content-Length header.")

        try:
            length = int(length_header)
        except ValueError as error:
            raise ValueError("Invalid Content-Length header.") from error

        if length > MAX_BODY_BYTES:
            raise ValueError("Request body is too large.")

        raw_body = self.rfile.read(length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("Request body must be valid JSON.") from error

        if not isinstance(payload, dict):
            raise ValueError("Request JSON must be an object.")

        return payload

    def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, payload: str, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = payload.encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_png(self, payload: bytes, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


def render_payload(payload: dict[str, Any]) -> dict[str, Any]:
    city_codes = payload.get("cityCodes")
    if not isinstance(city_codes, list) or not all(isinstance(code, str) for code in city_codes):
        raise ValueError('"cityCodes" must be a list of 6-digit code strings.')

    width = _optional_int(payload.get("width"), DEFAULT_WIDTH, "width")
    height = _optional_int(payload.get("height"), DEFAULT_HEIGHT, "height")
    theme = payload.get("theme")
    if theme is not None and not _is_string_dict(theme):
        raise ValueError('"theme" must be an object with string color values.')

    warnings: list[RenderWarning] = []
    normalized = normalize_city_codes(city_codes, on_warning=warnings.append)
    image_url = render_visited_china_map(
        normalized,
        width=width,
        height=height,
        theme=theme if theme is not None else None,
    )

    return {
        "image": image_url,
        "normalizedCityCodes": normalized,
        "warnings": [{"code": warning.code, "reason": warning.reason} for warning in warnings],
        "width": width,
        "height": height,
    }


def data_url_to_png_bytes(data_url: str) -> bytes:
    prefix = "data:image/png;base64,"
    if not data_url.startswith(prefix):
        raise ValueError("Expected a PNG data URL.")

    return base64.b64decode(data_url.removeprefix(prefix))


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    try:
        server = ReusableThreadingHTTPServer((host, port), MapServiceHandler)
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            raise SystemExit(
                f"Port {port} is already in use on {host}. "
                f"Try --port {port + 1}, or stop the process using that port."
            ) from error
        raise

    actual_host, actual_port = server.server_address[:2]
    print(f"Visited China Map service listening on http://{actual_host}:{actual_port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the visited China map HTTP service.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)


def _optional_int(value: Any, default: int, name: str) -> int:
    if value is None:
        return default

    if not isinstance(value, int):
        raise ValueError(f'"{name}" must be an integer.')

    if value < 1:
        raise ValueError(f'"{name}" must be greater than 0.')

    return value


def _is_string_dict(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    )


APP_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>中国城市打卡地图测试器</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #07111f;
      --panel: #0d1a2b;
      --line: #213449;
      --text: #eef7fb;
      --muted: #8da4b7;
      --accent: #25e8e6;
      --accent-dark: #16bbb7;
      --warn: #ffd27a;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      padding: 22px 28px 14px;
      border-bottom: 1px solid var(--line);
      background: rgba(13, 26, 43, 0.92);
    }
    h1 {
      margin: 0;
      font-size: 22px;
      font-weight: 720;
      letter-spacing: 0;
    }
    main {
      display: grid;
      grid-template-columns: 360px minmax(0, 1fr);
      gap: 18px;
      padding: 18px;
      max-width: 1400px;
      margin: 0 auto;
    }
    aside, section {
      background: rgba(13, 26, 43, 0.86);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    aside {
      padding: 16px;
      align-self: start;
    }
    label {
      display: block;
      margin: 0 0 8px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 650;
    }
    textarea, input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 11px;
      color: var(--text);
      background: #0a1523;
      font: inherit;
      outline: none;
    }
    textarea {
      min-height: 170px;
      resize: vertical;
      line-height: 1.5;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    textarea:focus, input:focus { border-color: var(--accent); }
    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-top: 14px;
    }
    .field { margin-top: 14px; }
    button {
      appearance: none;
      border: 1px solid transparent;
      border-radius: 6px;
      padding: 10px 12px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }
    .primary {
      width: 100%;
      margin-top: 16px;
      color: #fff;
      background: var(--accent);
    }
    .primary:hover { background: var(--accent-dark); }
    .secondary {
      width: 100%;
      margin-top: 10px;
      color: var(--text);
      background: #0a1523;
      border-color: var(--line);
    }
    .preview {
      min-height: 620px;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      overflow: hidden;
    }
    .toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
    }
    .status {
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .canvas {
      display: grid;
      place-items: center;
      padding: 16px;
      background: #06101b;
    }
    img {
      max-width: 100%;
      max-height: 72vh;
      background: #06101b;
      border: 1px solid var(--line);
      border-radius: 8px;
      object-fit: contain;
    }
    pre {
      margin: 0;
      padding: 12px 14px;
      min-height: 86px;
      max-height: 180px;
      overflow: auto;
      border-top: 1px solid var(--line);
      color: var(--muted);
      background: #0a1523;
      font-size: 12px;
      line-height: 1.5;
    }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }
    .chip {
      border: 1px solid var(--line);
      background: #0a1523;
      color: var(--muted);
      padding: 6px 8px;
      border-radius: 999px;
      font-size: 12px;
      cursor: pointer;
    }
    .hint {
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }
    @media (max-width: 900px) {
      main { grid-template-columns: 1fr; }
      .preview { min-height: 480px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>中国城市打卡地图测试器</h1>
  </header>
  <main>
    <aside>
      <label for="codes">城市代码</label>
      <textarea id="codes" spellcheck="false">110000
310101
440100
440305
510100
999999</textarea>
      <div class="hint">支持换行、逗号、空格分隔。区县码会归并到对应城市；未知代码会出现在 warnings。</div>
      <div class="chips">
        <button class="chip" data-codes="110000 310000 440100 440305">京沪广深</button>
        <button class="chip" data-codes="510100 610100 420100 330100">热门城市</button>
        <button class="chip" data-codes="650100 540100 230100 460202">边疆与海岛</button>
      </div>
      <div class="row">
        <div>
          <label for="width">宽度</label>
          <input id="width" type="number" min="1" value="1080">
        </div>
        <div>
          <label for="height">高度</label>
          <input id="height" type="number" min="1" value="900">
        </div>
      </div>
      <div class="row">
        <div>
          <label for="visitedFill">高亮填充</label>
          <input id="visitedFill" type="color" value="#21b7a8">
        </div>
        <div>
          <label for="visitedStroke">高亮描边</label>
          <input id="visitedStroke" type="color" value="#0f766e">
        </div>
      </div>
      <button id="render" class="primary">渲染地图</button>
      <button id="download" class="secondary" disabled>下载 PNG</button>
    </aside>
    <section class="preview">
      <div class="toolbar">
        <strong>预览</strong>
        <span id="status" class="status">等待渲染</span>
      </div>
      <div class="canvas">
        <img id="preview" alt="渲染后的中国打卡地图">
      </div>
      <pre id="meta">{}</pre>
    </section>
  </main>
  <script>
    const codesInput = document.querySelector("#codes");
    const widthInput = document.querySelector("#width");
    const heightInput = document.querySelector("#height");
    const fillInput = document.querySelector("#visitedFill");
    const strokeInput = document.querySelector("#visitedStroke");
    const renderButton = document.querySelector("#render");
    const downloadButton = document.querySelector("#download");
    const preview = document.querySelector("#preview");
    const statusEl = document.querySelector("#status");
    const metaEl = document.querySelector("#meta");
    let latestImage = "";

    function parseCodes(value) {
      return value.split(/[\s,，;；]+/).map((code) => code.trim()).filter(Boolean);
    }

    async function renderMap() {
      statusEl.textContent = "渲染中...";
      renderButton.disabled = true;
      downloadButton.disabled = true;
      const payload = {
        cityCodes: parseCodes(codesInput.value),
        width: Number(widthInput.value),
        height: Number(heightInput.value),
        theme: {
          visited_fill: fillInput.value,
          visited_stroke: strokeInput.value
        }
      };

      try {
        const response = await fetch("/render", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.message || "请求失败");
        }
        latestImage = data.image;
        preview.src = latestImage;
        metaEl.textContent = JSON.stringify({
          normalizedCityCodes: data.normalizedCityCodes,
          warnings: data.warnings,
          width: data.width,
          height: data.height
        }, null, 2);
        statusEl.textContent = `已渲染 ${data.normalizedCityCodes.length} 个城市`;
        downloadButton.disabled = false;
      } catch (error) {
        statusEl.textContent = "渲染失败";
        metaEl.textContent = String(error);
      } finally {
        renderButton.disabled = false;
      }
    }

    function downloadPng() {
      if (!latestImage) return;
      const link = document.createElement("a");
      link.href = latestImage;
      link.download = "visited-china-map.png";
      link.click();
    }

    document.querySelectorAll(".chip").forEach((button) => {
      button.addEventListener("click", () => {
        codesInput.value = button.dataset.codes.split(" ").join("\n");
        renderMap();
      });
    });
    renderButton.addEventListener("click", renderMap);
    downloadButton.addEventListener("click", downloadPng);
    renderMap();
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
