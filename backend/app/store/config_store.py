"""Persistencia de la configuración base + aplicación a `Settings`.

`load_app_config`/`save_app_config` guardan un dict JSON bajo una clave en `app_config`.
`apply_sim_config` muta `Settings` in-place con los overrides (fees, balances, venues, umbrales),
de modo que el motor que se construye después los use. Es la "configuración base" del sistema.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ..config import Settings
from ..models.config import SimConfig
from .db import AppConfigRow, make_session_factory

log = logging.getLogger("app.store.config_store")

_SIM_KEY = "sim_config"


async def load_app_config(engine: AsyncEngine, key: str = _SIM_KEY) -> dict[str, Any]:
    """Devuelve el dict persistido bajo `key`, o {} si no existe / es ilegible."""
    factory = make_session_factory(engine)
    async with factory() as session:
        result = await session.execute(select(AppConfigRow).where(AppConfigRow.key == key))
        row = result.scalar_one_or_none()
    if row is None:
        return {}
    try:
        return dict(json.loads(str(row.value_json)))
    except (ValueError, TypeError):
        log.warning("config %s ilegible; ignorando", key)
        return {}


async def save_app_config(engine: AsyncEngine, data: dict[str, Any], key: str = _SIM_KEY) -> None:
    """Upsert del dict bajo `key` (idempotente)."""
    factory = make_session_factory(engine)
    payload = json.dumps(data)
    stmt = sqlite_insert(AppConfigRow).values(key=key, value_json=payload)
    stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value_json": payload})
    async with factory() as session, session.begin():
        await session.execute(stmt)


def _walk_sim_config(
    settings: Settings, cfg: SimConfig, *, apply: bool, include_enabled: bool
) -> list[str]:
    """Recorre las diferencias REALES entre `cfg` y `settings` (valor efectivo ≠ runtime,
    PRD-009 RF-006: presencia ≠ cambio). Con `apply=True` las muta; con `apply=False` sólo
    las lista (fase de preparación, sin efectos). `include_enabled=False` excluye `enabled`
    (camino hot: el endpoint lo bloquea con 409; sólo el arranque lo aplica)."""
    changed: list[str] = []
    for venue, ov in cfg.exchanges.items():
        ex = settings.exchanges.get(venue)
        if ex is None:
            continue
        if include_enabled and ov.enabled is not None and ov.enabled != ex.enabled:
            if apply:
                ex.enabled = ov.enabled
            changed.append(f"{venue}.enabled={ov.enabled}")
        if ov.fee_taker is not None and ov.fee_taker != ex.fee_taker:
            if apply:
                ex.fee_taker = ov.fee_taker
            changed.append(f"{venue}.fee_taker={ov.fee_taker}")
        if ov.initial_btc is not None and ov.initial_btc != ex.initial_btc:
            if apply:
                ex.initial_btc = ov.initial_btc
            changed.append(f"{venue}.initial_btc={ov.initial_btc}")
        if ov.initial_quote is not None and ov.initial_quote != ex.initial_quote:
            if apply:
                ex.initial_quote = ov.initial_quote
            changed.append(f"{venue}.initial_quote={ov.initial_quote}")
    if cfg.default_trade_qty_btc is not None and (
        cfg.default_trade_qty_btc != settings.default_trade_qty_btc
    ):
        if apply:
            settings.default_trade_qty_btc = cfg.default_trade_qty_btc
        changed.append(f"default_trade_qty_btc={cfg.default_trade_qty_btc}")
    if cfg.min_net_profit_usd is not None and (
        cfg.min_net_profit_usd != settings.min_net_profit_usd
    ):
        if apply:
            settings.min_net_profit_usd = cfg.min_net_profit_usd
        changed.append(f"min_net_profit_usd={cfg.min_net_profit_usd}")
    if cfg.max_slippage is not None and cfg.max_slippage != settings.max_slippage:
        if apply:
            settings.max_slippage = cfg.max_slippage
        changed.append(f"max_slippage={cfg.max_slippage}")
    if cfg.exec_latency_ms is not None and cfg.exec_latency_ms != settings.exec_latency_ms:
        if apply:
            settings.exec_latency_ms = cfg.exec_latency_ms
        changed.append(f"exec_latency_ms={cfg.exec_latency_ms}")
    return changed


def diff_sim_config(
    settings: Settings, cfg: SimConfig, *, include_enabled: bool = True
) -> list[str]:
    """Fase de PREPARACIÓN (PRD-009 RF-007): lista los cambios reales SIN mutar `settings`."""
    return _walk_sim_config(settings, cfg, apply=False, include_enabled=include_enabled)


def apply_sim_config(
    settings: Settings, cfg: SimConfig, *, include_enabled: bool = True
) -> list[str]:
    """Aplica a `settings` in-place SOLO los campos que difieren del runtime. Devuelve la
    lista de cambios aplicados (para auditoría).

    Es la fuente de la "configuración base": muta los `ExchangeConfig` (enabled/fee/inventario)
    y los umbrales económicos globales. El portfolio debe re-sembrarse aparte para reflejar
    balances. `include_enabled=False` en el camino hot (el endpoint bloquea `enabled` con 409);
    el arranque conserva el default y sigue aplicando el `enabled` persistido."""
    return _walk_sim_config(settings, cfg, apply=True, include_enabled=include_enabled)
