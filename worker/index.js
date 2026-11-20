// Cloudflare Worker: read-only proxy for Yahoo reference-price bars.
// Mirrors /api/stock in server.py. Only GET /api/stock, fixed upstream host,
// strict symbol pattern, days in {1,3,7}, CORS limited to ALLOWED origins.
const ALLOWED = ["https://kranmal.github.io", "http://localhost:8803", "http://127.0.0.1:8803"];
const SYMBOL_RE = /^[A-Z0-9.=^-]{1,15}$/;
const YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/";

class NoData extends Error {}

async function fetchStock(symbol, days) {
  const now = Math.floor(Date.now() / 1000);
  const url = `${YAHOO}${encodeURIComponent(symbol)}?interval=15m&period1=${now - days * 86400}&period2=${now}&includePrePost=true`;
  const r = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0" }, cf: { cacheTtl: 10, cacheEverything: true } });
  if (r.status === 404) throw new NoData("no reference data for " + symbol);
  if (!r.ok) throw new Error("upstream HTTP " + r.status);
  const chart = (await r.json()).chart;
  if (chart.error || !chart.result || !chart.result.length) throw new NoData("no reference data for " + symbol);
  const res = chart.result[0], meta = res.meta;
  const ts = res.timestamp || [], closes = res.indicators.quote[0].close;
  const points = [];
  ts.forEach((t, i) => { if (closes[i] != null) points.push({ t: t * 1000, v: closes[i] }); });
  const periods = meta.currentTradingPeriod || {};
  const inside = n => { const p = periods[n]; return !!p && p.start <= now && now < p.end; };
  const session = inside("regular") ? "regular" : inside("pre") ? "pre" : inside("post") ? "post" : "closed";
  let price, tMs;
  if (session === "regular" || !points.length) { price = meta.regularMarketPrice; tMs = meta.regularMarketTime * 1000; }
  else { price = points[points.length - 1].v; tMs = points[points.length - 1].t; }
  return { symbol, price, time: tMs, prevClose: meta.previousClose ?? null, session, points };
}

export default {
  async fetch(req) {
    const origin = req.headers.get("Origin");
    const cors = { "Vary": "Origin", "Cache-Control": "no-store" };
    if (origin && ALLOWED.includes(origin)) cors["Access-Control-Allow-Origin"] = origin;
    const json = (code, obj) => new Response(JSON.stringify(obj), { status: code, headers: { ...cors, "Content-Type": "application/json" } });
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: { ...cors, "Access-Control-Allow-Methods": "GET", "Access-Control-Max-Age": "86400" } });
    if (req.method !== "GET") return json(405, { error: "method not allowed" });
    const u = new URL(req.url);
    if (u.pathname !== "/api/stock") return json(404, { error: "not found" });
    const days = u.searchParams.get("days") || "3";
    const symbol = (u.searchParams.get("symbol") || "NVDA").toUpperCase();
    if (!["1", "3", "7"].includes(days)) return json(400, { error: "days must be 1, 3 or 7" });
    if (!SYMBOL_RE.test(symbol)) return json(400, { error: "bad symbol" });
    try { return json(200, await fetchStock(symbol, Number(days))); }
    catch (e) {
      if (e instanceof NoData) return json(404, { error: e.message });
      return json(502, { error: "stock quote failed: " + String(e.message).slice(0, 120) });
    }
  },
};
