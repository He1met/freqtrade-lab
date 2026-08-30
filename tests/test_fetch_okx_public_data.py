import importlib.util
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
HELPER = (
    ROOT
    / "tests"
    / "fixtures"
    / "freqtrade_2026_7"
    / "producer"
    / "fetch_okx_public_data.py"
)


@pytest.fixture
def acquisition_module(monkeypatch):
    ccxt = types.ModuleType("ccxt")
    ccxt.okx = type("okx", (), {})
    pandas = types.ModuleType("pandas")
    pandas.__version__ = "3.0.3"
    pyarrow = types.ModuleType("pyarrow")
    pyarrow.__version__ = "25.0.0"
    freqtrade = types.ModuleType("freqtrade")
    freqtrade.__version__ = "2026.7"
    freqtrade.__file__ = str(ROOT / "freqtrade" / "__init__.py")
    converter = types.ModuleType("freqtrade.data.converter")
    converter.ohlcv_to_dataframe = lambda *args, **kwargs: None
    history = types.ModuleType("freqtrade.data.history")
    history.get_datahandler = lambda *args, **kwargs: None
    enums = types.ModuleType("freqtrade.enums")
    enums.CandleType = types.SimpleNamespace(
        FUTURES="futures", MARK="mark", FUNDING_RATE="funding_rate"
    )
    for name, module in {
        "ccxt": ccxt,
        "pandas": pandas,
        "pyarrow": pyarrow,
        "freqtrade": freqtrade,
        "freqtrade.data": types.ModuleType("freqtrade.data"),
        "freqtrade.data.converter": converter,
        "freqtrade.data.history": history,
        "freqtrade.enums": enums,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    spec = importlib.util.spec_from_file_location("_test_okx_acquisition", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Session:
    def __init__(self):
        self.status_code = 200
        self.calls = []
        self.last_response = None

    def request(self, method, url, *args, **kwargs):
        self.calls.append((method, url, kwargs))
        self.last_response = _Response(self.status_code)
        return self.last_response


class _Exchange:
    def __init__(self):
        self.session = _Session()

    def fetch(self, url, method="GET", headers=None, body=None):
        return self.session.request(method, url, headers=headers, data=body)


def test_request_guard_rejects_redirects_and_forbidden_endpoint_before_followup(
    acquisition_module,
) -> None:
    exchange = _Exchange()
    acquisition_module.install_request_guard(exchange)
    assert exchange.session.trust_env is False
    allowed = "https://www.okx.com/api/v5/public/instruments?instType=SWAP"

    exchange.fetch(allowed)
    assert exchange.session.calls[-1][2]["allow_redirects"] is False

    exchange.session.status_code = 302
    with pytest.raises(RuntimeError, match="redirect response rejected"):
        exchange.fetch(allowed)
    assert exchange.session.last_response.closed is True

    call_count = len(exchange.session.calls)
    with pytest.raises(RuntimeError, match="forbidden pre-request endpoint"):
        exchange.fetch("https://example.invalid/api/v5/public/instruments")
    assert len(exchange.session.calls) == call_count


def test_funding_history_requires_the_complete_fixed_window(acquisition_module) -> None:
    step = 8 * 60 * 60 * 1000
    start = int(acquisition_module.DEVELOPMENT_START.timestamp() * 1000)
    timestamps = list(range(start, acquisition_module.DATA_END_MS, step))
    complete = [{"timestamp": timestamp, "fundingRate": 0.0001} for timestamp in timestamps]

    assert acquisition_module.validate_funding_history(complete)["rows"] == len(complete)
    with pytest.raises(RuntimeError, match="every fixed eight-hour timestamp"):
        acquisition_module.validate_funding_history(complete[:-1])


def test_ohlcv_values_reject_corrupt_prices_and_volume(acquisition_module) -> None:
    valid = [[1, 1.0, 1.2, 0.8, 1.1, 10.0]]
    acquisition_module.validate_ohlcv_values(
        valid, label="futures", volume_required=True
    )
    acquisition_module.validate_ohlcv_values(
        [[1, 1.0, 1.2, 0.8, 1.1, None]],
        label="mark",
        volume_required=False,
    )

    for corrupt in (
        [[1, float("nan"), 1.2, 0.8, 1.1, 10.0]],
        [[1, 1.0, 0.9, 0.8, 1.1, 10.0]],
        [[1, 1.0, 1.2, 0.0, 1.1, 10.0]],
        [[1, 1.0, 1.2, 0.8, 1.1, -1.0]],
    ):
        with pytest.raises(RuntimeError):
            acquisition_module.validate_ohlcv_values(
                corrupt, label="futures", volume_required=True
            )


def test_output_boundary_uses_directory_identity_for_case_alias(
    acquisition_module, tmp_path: Path
) -> None:
    boundary = tmp_path / "CaseBoundary"
    boundary.mkdir()
    alias = tmp_path / "caseboundary"
    if not alias.exists():
        pytest.skip("filesystem is case-sensitive")

    assert acquisition_module.is_same_or_below_existing_directory(alias, boundary)


def test_acquisition_failure_removes_owned_output_root(
    acquisition_module, monkeypatch, tmp_path: Path
) -> None:
    output_root = tmp_path / "partial-output"
    monkeypatch.setattr(
        acquisition_module,
        "parse_args",
        lambda: types.SimpleNamespace(output_root=output_root),
    )
    monkeypatch.setattr(acquisition_module, "validate_runtime", lambda: {})

    def fail_after_partial_write(root, runtime):
        (root / "partial.txt").write_text("partial", encoding="utf-8")
        raise RuntimeError("controlled acquisition failure")

    monkeypatch.setattr(acquisition_module, "acquire", fail_after_partial_write)

    with pytest.raises(RuntimeError, match="controlled acquisition failure"):
        acquisition_module.main()

    assert not output_root.exists()
