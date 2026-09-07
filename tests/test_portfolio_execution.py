from decimal import Decimal as D
import pytest
from lab.portfolio_execution import capped_targets, executable_quantity, fill_equity


def test_netting_before_caps_and_shared_budget_respects_marked_loss():
    prices = {"BTC": 100, "ETH": 50}
    assert capped_targets([{"BTC": 10}, {"BTC": -10}], prices, 1000)["BTC"] == 0
    families = [{"BTC": 40, "ETH": 80}]
    targets = capped_targets(families, prices, 840)
    assert targets == {"BTC": D("3.36"), "ETH": D("6.72")}
    assert sum(abs(q)*prices[p] for p, q in targets.items()) == D("672")


@pytest.mark.parametrize("target,expected", [("0.4999", "0"), ("0.5009", "0.500"), ("-0.5009", "-0.500"), ("121", "0")])
def test_floor_minimum_skip_not_round_up(target, expected):
    assert executable_quantity(target, 100, step="0.001", min_qty="0.001", min_notional=50, max_qty=120) == D(expected)


def test_filled_orders_partial_exit_fees_and_unrealized_equity():
    fills = [{"pair": "BTC", "side": "buy", "amount": "4", "price": "100"},
             {"pair": "BTC", "side": "sell", "amount": "1", "price": "110"}]
    result = fill_equity(fills, {"BTC": "80"}, funding="-0.04")
    # Realized +10, remaining position -60, two fill fees .306, funding -.04.
    assert result["equity"] == D("949.654")
    assert result["inventory"] == {"BTC": D(3)}
    with pytest.raises(ValueError): fill_equity(fills, {})


def test_closed_roundtrip_and_funding_sign_do_not_double_count():
    fills = [{"pair": "ETH", "side": "sell", "amount": "2", "price": "50"},
             {"pair": "ETH", "side": "buy", "amount": "2", "price": "40"}]
    assert fill_equity(fills, {}, funding="0.01")["equity"] == D("1019.902")
    assert fill_equity(fills, {}, funding="0.01", slippage="0.0006")["equity"] == D("1019.794")


def test_synthetic_config_keeps_old_single_pair_api_unchanged():
    from scripts.run_portfolio_synthetic import synthetic_config
    from lab.bounded_research import profile_search_config, PilotError
    config = synthetic_config("B-risk")
    assert config["max_open_trades"] == 2 and config["dry_run_wallet"] == 1000
    assert config["exchange"]["pair_whitelist"] == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    with pytest.raises(PilotError): profile_search_config({"pairs":config["exchange"]["pair_whitelist"]})
