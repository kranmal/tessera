# Tessera

Live market analysis for Hyperliquid perpetuals: 354 markets, category tabs, sortable table, price/spread/funding charts, alerts, light and dark themes.

Live: https://kranmal.github.io/tessera/

- Single-file vanilla JS (`index.html`), no build step.
- Perp data comes straight from Hyperliquid's public info API in the browser.
- Stock reference quotes and EUR/GBP conversion come from Yahoo Finance through `server.py`, a small local proxy (Yahoo sends no CORS headers). **On GitHub Pages there is no proxy**, so those parts show "unavailable" and the perp data is unaffected.

Run it fully, locally:

```bash
python3 server.py 8803   # then open http://localhost:8803
```

Not affiliated with or endorsed by Minara AI. Data can be delayed or wrong. Not investment advice.
