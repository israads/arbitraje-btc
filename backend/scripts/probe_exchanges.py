"""Probe de conectividad: ¿qué exchanges entregan order book de BTC vía ccxt.pro?

Para cada (exchange, símbolo candidato) intenta UN `watch_order_book` (WS) con timeout;
si falla, prueba REST `fetch_order_book` como respaldo. Reporta OK/ERROR, latencia y
top-of-book. No hace trading ni requiere API keys (solo datos públicos).

Uso:  .venv/bin/python scripts/probe_exchanges.py
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

# (ccxt_id, [símbolos candidatos], quote_ccy informativo)
CANDIDATES: list[tuple[str, list[str], str]] = [
    ("bitso", ["BTC/MXN"], "MXN"),
    ("kraken", ["BTC/USD"], "USD"),
    ("coinbase", ["BTC/USD"], "USD"),  # Coinbase Advanced (ccxt id "coinbase")
    ("gemini", ["BTC/USD"], "USD"),
    ("bitstamp", ["BTC/USD", "BTC/USDT"], "USD"),
    ("binance", ["BTC/USDT"], "USDT"),
    ("okx", ["BTC/USDT", "BTC/USDC"], "USDT"),
    ("bybit", ["BTC/USDT"], "USDT"),
    ("bitfinex", ["BTC/USD"], "USD"),
    ("gateio", ["BTC/USDT", "BTC/USDC"], "USDT"),
    ("kucoin", ["BTC/USDT", "BTC/USDC"], "USDT"),
    ("bitget", ["BTC/USDT"], "USDT"),
    ("mexc", ["BTC/USDT"], "USDT"),
    ("cryptocom", ["BTC/USD", "BTC/USDT"], "USD"),
]

WS_TIMEOUT = 12.0
REST_TIMEOUT = 12.0


async def _try_ws(client: Any, symbol: str) -> dict[str, Any]:
    ob = await asyncio.wait_for(client.watch_order_book(symbol, 5), timeout=WS_TIMEOUT)
    return ob


async def _try_rest(client: Any, symbol: str) -> dict[str, Any]:
    ob = await asyncio.wait_for(client.fetch_order_book(symbol, 5), timeout=REST_TIMEOUT)
    return ob


async def probe_one(ex_id: str, symbols: list[str], quote: str) -> dict[str, Any]:
    import ccxt.pro as ccxtpro

    result: dict[str, Any] = {"id": ex_id, "quote": quote, "symbol": None, "via": None,
                              "ok": False, "ms": None, "bid": None, "ask": None, "err": None}
    klass = getattr(ccxtpro, ex_id, None)
    if klass is None:
        result["err"] = "no existe en ccxt.pro"
        return result
    client = klass({"enableRateLimit": True})
    try:
        for sym in symbols:
            for via, fn in (("ws", _try_ws), ("rest", _try_rest)):
                t0 = time.monotonic()
                try:
                    ob = await fn(client, sym)
                    bids, asks = ob.get("bids") or [], ob.get("asks") or []
                    result.update(
                        symbol=sym, via=via, ok=True,
                        ms=round((time.monotonic() - t0) * 1000, 1),
                        bid=bids[0][0] if bids else None,
                        ask=asks[0][0] if asks else None,
                        err=None,
                    )
                    return result
                except Exception as e:  # noqa: BLE001 — probe: capturamos todo y reportamos
                    result["err"] = f"{type(e).__name__}: {str(e)[:90]}"
        return result
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass


async def main() -> None:
    results = await asyncio.gather(*(probe_one(*c) for c in CANDIDATES))
    ok = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    print(f"\n{'EXCHANGE':12} {'SÍMBOLO':10} {'VÍA':5} {'LAT':>8}  {'BID':>12} {'ASK':>12}")
    print("-" * 70)
    for r in sorted(results, key=lambda x: (not x["ok"], x["id"])):
        mark = "OK " if r["ok"] else "XX "
        lat = f"{r['ms']} ms" if r["ms"] is not None else "—"
        print(f"{mark}{r['id']:9} {str(r['symbol'] or '—'):10} {str(r['via'] or '—'):5} "
              f"{lat:>8}  {str(r['bid'] or '—'):>12} {str(r['ask'] or '—'):>12}")
        if not r["ok"]:
            print(f"     └─ {r['err']}")
    print(f"\n{len(ok)}/{len(results)} conectan.  OK: {', '.join(r['id'] for r in ok)}")
    if bad:
        print(f"Fallan: {', '.join(r['id'] for r in bad)}")


if __name__ == "__main__":
    asyncio.run(main())
