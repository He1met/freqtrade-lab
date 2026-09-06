"""The narrowly supported OKX and Binance research market identities."""
import ast
import re
from typing import Mapping, Any

SOURCE_HOSTS = {"okx": "www.okx.com", "binance": "fapi.binance.com"}


def exchange_name(value: Mapping[str, Any]) -> str:
    exchange = value.get("exchange", "okx")
    return exchange.get("name", "") if isinstance(exchange, Mapping) else exchange


def market_domain(exchange: str, mode: str) -> str | None:
    if not isinstance(exchange, str) or not isinstance(mode, str):
        return None
    return {("okx", "futures"): "OKX_CRYPTO_PERP",
            ("okx", "spot"): "OKX_CRYPTO_SPOT",
            ("binance", "futures"): "BINANCE_CRYPTO_PERP"}.get((exchange, mode))


def valid_market(value: Mapping[str, Any], *, profile: bool = False) -> bool:
    mode = (value.get("trading_mode"), value.get("margin_mode"))
    if not all(isinstance(item, str) for item in mode):
        return False
    exchange = exchange_name(value)
    domain = market_domain(exchange, mode[0])
    return (domain is not None
            and mode in {("futures", "isolated"), ("spot", "")}
            and (not profile or value.get("domain") == domain))


def pair_quote(pair: str, *, spot: bool) -> str:
    pattern = r"([A-Za-z0-9-]+)/USDT" if spot else r"([A-Za-z0-9-]+)/([A-Za-z0-9-]+):\2"
    match = re.fullmatch(pattern, pair)
    if match is None:
        raise ValueError("pair is outside the spot USDT or linear futures boundary")
    return "USDT" if spot else match.group(2)


def validate_spot_source(source: str) -> None:
    """Extra market binding after the existing bounded AST security check."""
    tree = ast.parse(source)
    fields = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == "can_short"
                      for target in node.targets)]
    if len(fields) != 1 or not isinstance(fields[0].value, ast.Constant) or fields[0].value.value is not False:
        raise ValueError("spot requires literal can_short = False")
    forbidden = {"enter_short", "exit_short", "leverage", "funding_rate", "lagged_funding"}
    for node in ast.walk(tree):
        if ((isinstance(node, ast.Name) and node.id in forbidden)
                or (isinstance(node, ast.Attribute) and node.attr in forbidden)
                or (isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in forbidden)):
            raise ValueError("spot forbids short, leverage and funding signals")
