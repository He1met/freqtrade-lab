"""The two narrowly supported OKX research market identities."""
import ast
import re
from typing import Mapping, Any


def valid_market(value: Mapping[str, Any], *, profile: bool = False) -> bool:
    mode = (value.get("trading_mode"), value.get("margin_mode"))
    domains = {("futures", "isolated"): "OKX_CRYPTO_PERP",
               ("spot", ""): "OKX_CRYPTO_SPOT"}
    return mode in domains and (not profile or value.get("domain") == domains[mode])


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
