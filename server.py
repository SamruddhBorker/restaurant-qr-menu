#!/usr/bin/env python3
"""Restaurant QR menu with live stock.

    python server.py                       # http://127.0.0.1:8000
    python server.py --host 0.0.0.0        # let phones on your Wi-Fi reach it

Customers open the menu (from a table QR code). Staff sign in at /staff with a
PIN to change stock and prices. Set STAFF_PIN in the environment, or one is
generated and printed at startup. Standard library only.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import socket
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import qr
from db import MenuDB

HERE = Path(__file__).parent
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/staff": ("staff.html", "text/html; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8"),
          "/menu.js": ("menu.js", "application/javascript; charset=utf-8"),
          "/staff.js": ("staff.js", "application/javascript; charset=utf-8")}
MAX_BODY = 100_000
SESSION_SECONDS = 12 * 3600
MAX_FAILS, LOCKOUT_SECONDS = 5, 60
SECURITY_HEADERS = {
    "Content-Security-Policy": ("default-src 'self'; img-src 'self' data:; "
                                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


class App:
    """Shared state: database, config, staff sessions, login throttling."""

    def __init__(self, db: MenuDB, cfg: dict, pin: str) -> None:
        self.db, self.cfg, self.pin = db, cfg, pin
        self.sessions: dict[str, float] = {}
        self.fails: dict[str, list[float]] = {}

    def locked(self, ip: str) -> bool:
        now = time.time()
        recent = [t for t in self.fails.get(ip, []) if now - t < LOCKOUT_SECONDS]
        self.fails[ip] = recent
        return len(recent) >= MAX_FAILS

    def login(self, ip: str, pin: str) -> str | None:
        if self.locked(ip):
            return None
        if hmac.compare_digest(pin.encode(), self.pin.encode()):
            self.fails.pop(ip, None)
            token = secrets.token_urlsafe(32)
            self.sessions[token] = time.time() + SESSION_SECONDS
            return token
        self.fails.setdefault(ip, []).append(time.time())
        return None

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        exp = self.sessions.get(token)
        if exp is None or exp < time.time():
            self.sessions.pop(token, None)
            return False
        return True


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "QRMenu"

        # ---- plumbing
        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in {**SECURITY_HEADERS, **(extra or {})}.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj, extra: dict | None = None) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json",
                       {"Cache-Control": "no-store", **(extra or {})})

        def _err(self, code: int, msg: str) -> None:
            self._json(code, {"error": msg})

        def _token(self) -> str | None:
            c = SimpleCookie(self.headers.get("Cookie", ""))
            return c["session"].value if "session" in c else None

        def _staff(self) -> bool:
            if app.valid(self._token()):
                return True
            self._err(401, "sign in required")
            return False

        def _body(self) -> dict | None:
            try:
                n = int(self.headers.get("Content-Length", 0))
                if n > MAX_BODY:
                    self._err(413, "too large")
                    return None
                if n == 0:
                    return {}
                data = json.loads(self.rfile.read(n))
                if not isinstance(data, dict):
                    raise ValueError
                return data
            except ValueError:
                self._err(400, "bad json")
                return None

        def _csrf_ok(self) -> bool:
            """Mutations must come from our own pages (custom header + same origin)."""
            if self.headers.get("X-Staff") != "1":
                self._err(403, "missing X-Staff header")
                return False
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != self.headers.get("Host"):
                self._err(403, "cross-origin request refused")
                return False
            return True

        # ---- routes
        def do_GET(self) -> None:
            url = urlparse(self.path)
            path = url.path
            if path in STATIC:
                name, ctype = STATIC[path]
                return self._send(200, (HERE / "static" / name).read_bytes(), ctype,
                                  {"Cache-Control": "no-cache"})
            if path == "/api/menu":
                etag = f'W/"{app.db.version()}"'
                if self.headers.get("If-None-Match") == etag:
                    return self._send(304, b"", "application/json",
                                      {"ETag": etag, "Cache-Control": "no-cache"})
                body = {"name": app.cfg["restaurant_name"], "currency": app.cfg["currency"],
                        "version": app.db.version(), "items": app.db.list_items()}
                return self._send(200, json.dumps(body).encode(), "application/json",
                                  {"ETag": etag, "Cache-Control": "no-cache"})
            if path == "/api/staff/session":
                return self._json(200, {"signed_in": app.valid(self._token())})
            if path == "/api/staff/qr.svg":
                if not self._staff():
                    return
                data = parse_qs(url.query).get("data", [""])[0]
                if not data:
                    return self._err(400, "data is required")
                try:
                    svg = qr.to_svg(data)
                except ValueError as e:
                    return self._err(400, str(e))
                return self._send(200, svg.encode(), "image/svg+xml",
                                  {"Cache-Control": "no-store"})
            self._err(404, "not found")

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if not self._csrf_ok():
                return
            data = self._body()
            if data is None:
                return
            if path == "/api/staff/login":
                ip = self.client_address[0]
                if app.locked(ip):
                    return self._err(429, "too many attempts, wait a minute")
                token = app.login(ip, str(data.get("pin", "")))
                if not token:
                    return self._err(401, "wrong PIN")
                cookie = (f"session={token}; HttpOnly; SameSite=Strict; Path=/; "
                          f"Max-Age={SESSION_SECONDS}")
                return self._json(200, {"ok": True}, {"Set-Cookie": cookie})
            if path == "/api/staff/logout":
                app.sessions.pop(self._token() or "", None)
                return self._json(200, {"ok": True},
                                  {"Set-Cookie": "session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
            if not self._staff():
                return
            if path == "/api/staff/items":
                try:
                    return self._json(201, app.db.create(data))
                except ValueError as e:
                    return self._err(400, str(e))
            parts = path.strip("/").split("/")  # api staff items <id> sold
            if len(parts) == 5 and parts[:3] == ["api", "staff", "items"] \
                    and parts[3].isdigit() and parts[4] == "sold":
                res = app.db.sold_one(int(parts[3]))
                if res is None:
                    return self._err(404, "no such item")
                if res == "none_left":
                    return self._err(409, "none left in stock")
                return self._json(200, res)
            self._err(404, "not found")

        def do_PUT(self) -> None:
            parts = urlparse(self.path).path.strip("/").split("/")
            if not (len(parts) == 4 and parts[:3] == ["api", "staff", "items"] and parts[3].isdigit()):
                return self._err(404, "not found")
            if not self._csrf_ok() or not self._staff():
                return
            data = self._body()
            if data is None:
                return
            try:
                item = app.db.update(int(parts[3]), data)
            except ValueError as e:
                return self._err(400, str(e))
            self._json(200, item) if item else self._err(404, "no such item")

        def do_DELETE(self) -> None:
            parts = urlparse(self.path).path.strip("/").split("/")
            if not (len(parts) == 4 and parts[:3] == ["api", "staff", "items"] and parts[3].isdigit()):
                return self._err(404, "not found")
            if not self._csrf_ok() or not self._staff():
                return
            if app.db.delete(int(parts[3])):
                self._json(200, {"ok": True})
            else:
                self._err(404, "no such item")

        def log_message(self, *a) -> None:
            pass

    return Handler


def make_app(db_path: str = "menu.db", cfg_path: Path = HERE / "config.json",
             pin: str | None = None) -> App:
    cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    db = MenuDB(db_path, cfg.get("low_stock_threshold", 5))
    if db.count() == 0:
        db.seed(cfg.get("seed_menu", []))
    return App(db, cfg, pin or os.environ.get("STAFF_PIN") or f"{secrets.randbelow(10**6):06d}")


def lan_ip() -> str:
    try:  # UDP "connect" sends nothing; it just asks the OS which interface it would use
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--db", default="menu.db")
    args = ap.parse_args()
    app = make_app(args.db)
    srv = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    shown = lan_ip() if args.host == "0.0.0.0" else args.host
    print(f"Menu:   http://{shown}:{args.port}/")
    print(f"Staff:  http://{shown}:{args.port}/staff   PIN: {app.pin}")
    if "STAFF_PIN" not in os.environ:
        print("(PIN was generated for this run; set STAFF_PIN to keep one permanently)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
