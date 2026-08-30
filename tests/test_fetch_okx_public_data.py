import importlib.util
import json
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


def _write_candidate_inputs(
    root: Path, *, class_name: str = "LocalCandidate"
) -> tuple[Path, Path, bytes, bytes]:
    strategy_bytes = (
        "from freqtrade.strategy import IStrategy\n\n"
        f"class {class_name}(IStrategy):\n"
        "    pass\n"
    ).encode("utf-8")
    spec_bytes = (
        json.dumps(
            {
                "schema": "freqtrade-lab-research-spec-v1",
                "profile": {},
                "candidate": {"class_name": class_name},
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    strategy = root / "ChosenCandidate.py"
    research_spec = root / "chosen-candidate-spec.json"
    strategy.write_bytes(strategy_bytes)
    research_spec.write_bytes(spec_bytes)
    return strategy, research_spec, strategy_bytes, spec_bytes


def _prepare_generated_root(root: Path) -> Path:
    (root / "data" / "okx" / "futures").mkdir(parents=True)
    (root / "market_snapshot.json").write_bytes(b"{}\n")
    (root / "isolated_tiers_snapshot.json").write_bytes(b"[]\n")
    receipt = root / "retrieval_receipt.json"
    receipt.write_bytes(b"{}\n")
    return receipt


def _runtime(acquisition_module) -> dict[str, object]:
    return {
        "freqtrade_tag": acquisition_module.EXPECTED_VERSIONS["freqtrade"],
        "freqtrade_commit": acquisition_module.EXPECTED_FREQTRADE_COMMIT,
        "versions": dict(acquisition_module.EXPECTED_VERSIONS),
    }


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


def test_custom_candidate_inputs_are_optional_but_must_be_paired(
    acquisition_module, tmp_path: Path
) -> None:
    strategy = tmp_path / "ChosenCandidate.py"
    strategy.write_text("class ChosenCandidate:\n    pass\n", encoding="utf-8")

    assert acquisition_module.load_local_candidate_inputs(None, None) is None
    with pytest.raises(RuntimeError, match="must be provided together"):
        acquisition_module.load_local_candidate_inputs(strategy, None)


def test_custom_candidate_updates_fixed_config_and_provenance(
    acquisition_module, tmp_path: Path
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    strategy, research_spec, strategy_bytes, spec_bytes = _write_candidate_inputs(
        source_root
    )
    selected = acquisition_module.load_local_candidate_inputs(
        strategy, research_spec
    )
    assert selected is not None

    output_root = tmp_path / "output"
    receipt = _prepare_generated_root(output_root)
    provenance_path = acquisition_module.write_local_producer_inputs(
        output_root, receipt, _runtime(acquisition_module), selected
    )

    copied_strategy = output_root / "strategies" / "ChosenCandidate.py"
    copied_spec = output_root / "research-spec.json"
    assert copied_strategy.read_bytes() == strategy_bytes
    assert copied_spec.read_bytes() == spec_bytes
    config = json.loads((output_root / "config.json").read_bytes())
    assert config["strategy"] == "LocalCandidate"

    provenance = json.loads(provenance_path.read_bytes())
    assert provenance["contract"]["config"] == "config.json"
    assert provenance["contract"]["strategy"] == "strategies/ChosenCandidate.py"
    assert provenance["files"]["research-spec.json"]["role"] == (
        "user_selected_local_research_spec"
    )
    assert provenance["files"]["strategies/ChosenCandidate.py"]["role"] == (
        "user_selected_local_candidate_strategy"
    )
    assert "UPSTREAM_LICENSE.txt" not in provenance["files"]
    for relative in (
        "config.json",
        "research-spec.json",
        "strategies/ChosenCandidate.py",
    ):
        data = (output_root / relative).read_bytes()
        record = provenance["files"][relative]
        assert record["bytes"] == len(data)
        assert record["sha256"] == acquisition_module.sha256(data)


def test_default_candidate_output_remains_the_fixed_fixture(
    acquisition_module, tmp_path: Path
) -> None:
    output_root = tmp_path / "default-output"
    receipt = _prepare_generated_root(output_root)
    provenance_path = acquisition_module.write_local_producer_inputs(
        output_root, receipt, _runtime(acquisition_module)
    )

    provenance = json.loads(provenance_path.read_bytes())
    assert provenance["contract"]["strategy"] == (
        "strategies/StrategyTestV3Futures.py"
    )
    assert provenance["files"]["research-spec.json"]["role"] == (
        "fixed_research_profile_and_candidate"
    )
    assert provenance["files"]["strategies/StrategyTestV3Futures.py"]["role"] == (
        "gpl_upstream_test_strategy"
    )
    assert provenance["files"]["UPSTREAM_LICENSE.txt"]["role"] == (
        "upstream_gpl_license"
    )
    assert (output_root / "config.json").read_bytes() == (
        acquisition_module.FIXTURE_ROOT / "config.json"
    ).read_bytes()


def test_acquisition_failure_removes_owned_output_root(
    acquisition_module, monkeypatch, tmp_path: Path
) -> None:
    output_root = tmp_path / "partial-output"
    monkeypatch.setattr(
        acquisition_module,
        "parse_args",
        lambda: types.SimpleNamespace(
            output_root=output_root,
            strategy_file=None,
            research_spec=None,
        ),
    )
    monkeypatch.setattr(acquisition_module, "validate_runtime", lambda: {})

    def fail_after_partial_write(root, runtime):
        (root / "partial.txt").write_text("partial", encoding="utf-8")
        raise RuntimeError("controlled acquisition failure")

    monkeypatch.setattr(acquisition_module, "acquire", fail_after_partial_write)

    with pytest.raises(RuntimeError, match="controlled acquisition failure"):
        acquisition_module.main()

    assert not output_root.exists()
