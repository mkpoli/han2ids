#!/usr/bin/env python3
"""Serve the han2ids demo: static pages plus one local reading endpoint."""
from __future__ import annotations

import argparse
import base64
import binascii
import io
import json
import os
import re
import sys
import threading
import traceback
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageOps

from han2ids import __version__
from han2ids.infer import Han2IDS

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
MAX_BODY = 24 * 1024 * 1024
MAX_PIXELS = 25_000_000
DATA_URL = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=\s]+)$")


def decode_data_url(value: str) -> Image.Image:
    """Decode a browser data URL into an oriented RGB or RGBA image."""
    if not isinstance(value, str):
        raise ValueError("Send the image as a PNG, JPEG, or WebP data URL.")  # noqa: TRY004
    match = DATA_URL.fullmatch(value)
    if not match:
        raise ValueError("Send the image as a PNG, JPEG, or WebP data URL.")
    try:
        raw = base64.b64decode(re.sub(r"\s+", "", match.group(2)), validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("The image data is not valid base64.") from error
    if len(raw) > MAX_BODY:
        raise ValueError("The image is too large.")

    try:
        with Image.open(io.BytesIO(raw)) as opened:
            image = ImageOps.exif_transpose(opened)
            if image.width * image.height > MAX_PIXELS:
                raise ValueError("The image has too many pixels.")
            image = image.convert("RGBA" if image.mode in ("P", "PA", "LA", "RGBA") else "RGB")
            image.load()
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("The image could not be opened.") from error
    return image


class DemoServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, reader: Han2IDS):
        super().__init__(address, handler)
        self.reader = reader
        self.lock = threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    server: DemoServer

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, format, *args):
        if self.command != "GET" or self.path.startswith("/api/"):
            super().log_message(format, *args)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self.send_json({
                "ok": True,
                "model": __version__,
                "device": str(self.server.reader.device),
            })
            return
        if path.startswith("/api/"):
            self.send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
            return
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/read":
            self.send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json({"error": "Bad request."}, HTTPStatus.BAD_REQUEST)
            return
        if length <= 0:
            self.send_json({"error": "The request has no body."}, HTTPStatus.BAD_REQUEST)
            return
        if length > MAX_BODY:
            self.send_json({"error": "The image is too large."}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return

        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object.")  # noqa: TRY004
            image = decode_data_url(payload.get("image", ""))
            try:
                top_k = int(payload.get("top_k", 1))
            except (TypeError, ValueError) as error:
                raise ValueError("top_k must be an integer.") from error
            top_k = min(5, max(1, top_k))
            tta = payload.get("tta", True) is not False
            with self.server.lock:
                if top_k > 1:
                    readings = self.server.reader.read_topk(image, k=top_k, tta=tta)
                else:
                    readings = [self.server.reader.read(image, tta=tta)]
        except ValueError as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        except Exception:  # noqa: BLE001 -- the endpoint must answer with JSON, not a traceback page.
            traceback.print_exc()
            self.send_json({"error": "The reader failed on this image."}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self.send_json({"readings": [
            {
                "ids": reading.ids,
                "confidence": round(reading.confidence, 4),
                "variant": reading.variant,
                "valid": reading.valid,
            }
            for reading in readings
        ]})

    def send_json(self, body: dict, status: HTTPStatus = HTTPStatus.OK):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="han2ids-demo", description="Serve the han2ids demo site.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8402)
    parser.add_argument(
        "--checkpoint", type=Path,
        default=Path(os.environ.get("HAN2IDS_MODEL", BASE.parent / "models" / "han2ids-v0.4.pt")),
    )
    parser.add_argument("--cpu", action="store_true", help="run on the CPU even when CUDA is available")
    args = parser.parse_args(argv)

    if not args.checkpoint.exists():
        parser.error(f"Checkpoint not found: {args.checkpoint}")

    try:
        reader = Han2IDS(args.checkpoint, device="cpu" if args.cpu else None)
    except Exception as error:  # noqa: BLE001 -- a failed checkpoint load should read as one line.
        print(f"Could not load {args.checkpoint}: {error}", file=sys.stderr)
        return 2

    server = DemoServer((args.host, args.port), Handler, reader)
    host, port = server.server_address[:2]
    print(f"han2ids v{__version__} on {reader.device}: http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
