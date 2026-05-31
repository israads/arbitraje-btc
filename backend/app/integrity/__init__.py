"""C2 — Integridad de order book por exchange. FR-020.

Binance `U/u`/nonce; Kraken CRC32 top-10 (OFF por defecto en ccxt.pro, activar vía
`options` + `zlib`); Coinbase `sequence_num` + canal `heartbeats`. `qty=0` borra.

Implementación: STORY-015. (MVP se apoya en la reconstrucción interna de ccxt.pro.)
"""
