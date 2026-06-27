from __future__ import annotations

from app.config import ExchangeConfig, Settings
from app.models.config import ExchangeOverride, SimConfig
from app.sim.inventory import Portfolio
from app.store.config_store import apply_sim_config


def _settings() -> Settings:
    return Settings(
        default_trade_qty_btc=1.0,
        exchanges={
            "binance": ExchangeConfig(
                id="binance", symbol="BTC/USDT", quote_ccy="USDT",
                fee_taker=0.0010, withdrawal_btc=0.0002, ob_limit=20,
                initial_btc=2.0, initial_quote=100_000.0, enabled=True,
            ),
            "kraken": ExchangeConfig(
                id="kraken", symbol="BTC/USD", quote_ccy="USD",
                fee_taker=0.0040, withdrawal_btc=0.00005, ob_limit=25,
                initial_btc=2.0, initial_quote=100_000.0, enabled=True,
            ),
        },
    )


def test_apply_sim_config_mutates_settings() -> None:
    s = _settings()
    cfg = SimConfig(
        exchanges={
            "binance": ExchangeOverride(fee_taker=0.0005, enabled=False, initial_btc=5.0),
        },
        default_trade_qty_btc=0.5,
        min_net_profit_usd=10.0,
    )
    changed = apply_sim_config(s, cfg)
    assert s.exchanges["binance"].fee_taker == 0.0005
    assert s.exchanges["binance"].enabled is False
    assert s.exchanges["binance"].initial_btc == 5.0
    assert s.default_trade_qty_btc == 0.5
    assert s.min_net_profit_usd == 10.0
    # kraken intacto
    assert s.exchanges["kraken"].fee_taker == 0.0040
    assert len(changed) >= 4


def test_apply_sim_config_ignores_unknown_venue() -> None:
    s = _settings()
    cfg = SimConfig(exchanges={"nope": ExchangeOverride(enabled=False)})
    changed = apply_sim_config(s, cfg)
    assert changed == []


def test_portfolio_reseed_picks_up_new_balances() -> None:
    s = _settings()
    p = Portfolio(s)
    assert p.venues["binance"].btc == 2.0
    # cambia la config base y re-siembra
    s.exchanges["binance"].initial_btc = 9.0
    s.exchanges["kraken"].enabled = False
    p.reseed()
    assert p.venues["binance"].btc == 9.0
    assert "kraken" not in p.venues  # deshabilitado → no se siembra
    assert p.realized_pnl == 0.0
