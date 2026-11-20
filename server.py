#!/usr/bin/env python3
"""Serve the dashboard and proxy ONE read-only request: Yahoo reference-price bars.

Why: Yahoo Finance's chart endpoint sends no CORS headers, so the page can't
call it from the browser. This server fetches it server-side instead.

- Binds to 127.0.0.1 only.
- Client input: `symbol` (must match a strict Yahoo-symbol pattern, URL-quoted
  before use; host and path are fixed) and `days` in {1, 3, 7}.
- Results are cached for 10 seconds.
- Yahoo's chart endpoint is unofficial and may change or rate-limit. Personal use only.

Usage: python3 server.py [port]    (default 8803)
"""
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SYMBOL = "NVDA"
SYMBOL_RE = re.compile(r"^[A-Z0-9.=^-]{1,15}$")  # Yahoo symbols like NVDA, BTC-USD, ^GSPC, GC=F, EURUSD=X
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=15m&period1=%d&period2=%d&includePrePost=true"
TTL = 10
_cache = {}
_lock = threading.Lock()


class NoData(Exception):
    pass


def fetch_stock(symbol, days):
    now = int(time.time())
    url = YAHOO % (quote(symbol, safe=""), now - days * 86400, now)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            chart = json.load(r)["chart"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NoData("no reference data for %s" % symbol)
        raise
    if chart.get("error") or not chart.get("result"):
        raise NoData("no reference data for %s" % symbol)
    res = chart["result"][0]
    meta = res["meta"]
    ts = res.get("timestamp") or []
    closes = res["indicators"]["quote"][0]["close"]
    points = [{"t": t * 1000, "v": c} for t, c in zip(ts, closes) if c is not None]
    periods = meta.get("currentTradingPeriod", {})

    def inside(name):
        p = periods.get(name)
        return bool(p) and p["start"] <= now < p["end"]

    session = "regular" if inside("regular") else "pre" if inside("pre") else "post" if inside("post") else "closed"
    if session == "regular" or not points:
        price, t_ms = meta["regularMarketPrice"], meta["regularMarketTime"] * 1000
    else:  # extended hours / closed: last traded bar (includes pre/post)
        price, t_ms = points[-1]["v"], points[-1]["t"]
    return {
        "symbol": symbol,
        "price": price,
        "time": t_ms,
        "prevClose": meta.get("previousClose"),
        "session": session,
        "points": points,
    }


def cached_stock(symbol, days):
    key = (symbol, days)
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
    data = fetch_stock(symbol, days)
    with _lock:
        if len(_cache) > 200:
            _cache.clear()
        _cache[key] = (time.time(), data)
    return data


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            with open(os.path.join(ROOT, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if u.path == "/api/stock":
            q = parse_qs(u.query)
            days = q.get("days", ["3"])[0]
            symbol = q.get("symbol", [DEFAULT_SYMBOL])[0].upper()
            if days not in ("1", "3", "7"):
                return self._json(400, {"error": "days must be 1, 3 or 7"})
            if not SYMBOL_RE.match(symbol):
                return self._json(400, {"error": "bad symbol"})
            try:
                return self._json(200, cached_stock(symbol, int(days)))
            except NoData as e:
                return self._json(404, {"error": str(e)})
            except Exception as e:  # keep the message short; never leak a traceback
                return self._json(502, {"error": "stock quote failed: %s" % str(e)[:120]})
        self._json(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8803
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("Serving on http://127.0.0.1:%d" % port, flush=True)
    srv.serve_forever()
