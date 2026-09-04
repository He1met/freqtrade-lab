import importlib.util
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lab.database import get_connection
from lab import bounded_research as pilot
from tests.test_development_run import _approved_candidate_database
from tests.test_search_data_producer import _ohlcv_table, _timestamps


ROOT = Path(__file__).resolve().parent.parent
HELPER = (
    ROOT
    / "tests"
    / "fixtures"
    / "freqtrade_2026_7"
    / "producer"
    / "fetch_okx_public_data.py"
)
PROFILE_HELPER = ROOT / "scripts" / "fetch_okx_profile_data.py"


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


def _write_profile_window(root: Path, **overrides) -> Path:
    value = {
        "schema": "freqtrade-lab-profile-source-window-v1",
        "data_start_utc": "2026-02-28T22:00:00Z",
        "search_start_utc": "2026-03-01T00:00:00Z",
        "development_start_utc": "2026-04-02T00:00:00Z",
        "end_exclusive_utc": "2026-05-02T00:00:00Z",
    }
    value.update(overrides)
    path = root / "window-spec.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _configure_profile_helper(
    module,
    tmp_path: Path,
    *,
    pair: str = "XRP/USDT:USDT",
    timeframe: str = "5m",
    pre_roll_candles: int = 24,
    **window_overrides,
) -> tuple[Path, str, dict[str, object], Path]:
    database, candidate_id = _approved_candidate_database(
        tmp_path / "profile", pair=pair, timeframe=timeframe
    )
    with get_connection(database) as connection:
        connection.execute(
            "UPDATE research_profiles SET history_start_date='2025-01-01'"
        )
        profile_id = str(
            connection.execute(
                "SELECT research_profile_id FROM generation_runs WHERE id="
                "(SELECT generation_run_id FROM candidates WHERE id=?)",
                (candidate_id,),
            ).fetchone()[0]
        )
        profile = pilot.load_profile_snapshot(connection, profile_id)
        connection.commit()
    window = _write_profile_window(tmp_path, **window_overrides)
    module.configure_profile_acquisition(
        database, profile_id, window, pre_roll_candles
    )
    return database, profile_id, profile, window


def _load_acquisition_module(monkeypatch, request, helper: Path):
    real_arrow = bool(getattr(request, "param", False))
    if real_arrow:
        pytest.importorskip("pyarrow")
        pytest.importorskip("pyarrow.feather")
    ccxt = types.ModuleType("ccxt")
    ccxt.okx = type("okx", (), {})
    pandas = types.ModuleType("pandas")
    pandas.__version__ = "3.0.3"
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
    modules = {
        "ccxt": ccxt,
        "pandas": pandas,
        "freqtrade": freqtrade,
        "freqtrade.data": types.ModuleType("freqtrade.data"),
        "freqtrade.data.converter": converter,
        "freqtrade.data.history": history,
        "freqtrade.enums": enums,
    }
    if not real_arrow:
        pyarrow = types.ModuleType("pyarrow")
        pyarrow.__version__ = "25.0.0"
        modules["pyarrow"] = pyarrow
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    spec = importlib.util.spec_from_file_location(
        f"_test_okx_acquisition_{helper.stem}", helper
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if real_arrow:
        monkeypatch.delitem(sys.modules, "pandas", raising=False)
    return module


@pytest.fixture
def acquisition_module(monkeypatch, request):
    return _load_acquisition_module(monkeypatch, request, HELPER)


@pytest.fixture
def profile_acquisition_module(monkeypatch, request):
    return _load_acquisition_module(monkeypatch, request, PROFILE_HELPER)


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


class _FundingExchange:
    def __init__(self, interval_ms: int):
        self.interval_ms = interval_ms
        self.calls = []

    def fetch_funding_rate_history(self, symbol, *, since, limit, params):
        self.calls.append((symbol, since, limit, dict(params)))
        return [
            {"timestamp": timestamp, "fundingRate": 0.0001}
            for timestamp in range(since, params["after"], self.interval_ms)
        ]


class _CandleExchange:
    def __init__(self, step_seconds: int):
        self.step_seconds = step_seconds
        self.calls = []

    def parse_timeframe(self, timeframe):
        assert timeframe == "5m"
        return self.step_seconds

    def fetch_ohlcv(self, symbol, *, timeframe, since, limit, params):
        self.calls.append((symbol, timeframe, since, limit, dict(params)))
        step_ms = self.step_seconds * 1000
        return [
            [since + index * step_ms, 1.0, 1.2, 0.8, 1.1, 10.0]
            for index in range(limit)
        ]


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


def test_profile_source_window_derives_5m_warmup_and_contract(
    profile_acquisition_module, tmp_path: Path
) -> None:
    _, _, _, window = _configure_profile_helper(
        profile_acquisition_module, tmp_path
    )

    assert profile_acquisition_module.load_window_spec(window) == (
        datetime(2026, 2, 28, 22, tzinfo=timezone.utc),
        datetime(2026, 3, 1, tzinfo=timezone.utc),
        datetime(2026, 4, 2, tzinfo=timezone.utc),
        datetime(2026, 5, 2, tzinfo=timezone.utc),
    )
    assert profile_acquisition_module.PROFILE_ACQUISITION["search_timerange"] == (
        "20260301-20260402"
    )
    assert profile_acquisition_module.PROFILE_ACQUISITION[
        "development_timerange"
    ] == "20260402-20260502"


def test_profile_5m_mark_series_floors_non_hour_warmup(
    profile_acquisition_module, tmp_path: Path
) -> None:
    _configure_profile_helper(
        profile_acquisition_module,
        tmp_path,
        pre_roll_candles=20,
        data_start_utc="2026-02-28T22:20:00Z",
    )

    assert profile_acquisition_module.DATA_START == datetime(
        2026, 2, 28, 22, 20, tzinfo=timezone.utc
    )
    assert profile_acquisition_module.MARK_START_MS == int(
        datetime(2026, 2, 28, 22, tzinfo=timezone.utc).timestamp() * 1000
    )


def test_profile_candle_fetch_uses_the_selected_pair_not_historical_xrp(
    profile_acquisition_module, monkeypatch, tmp_path: Path
) -> None:
    _configure_profile_helper(
        profile_acquisition_module,
        tmp_path,
        pair="BTC/USDT:USDT",
    )
    monkeypatch.setattr(
        profile_acquisition_module,
        "request_receipt",
        lambda exchange, label: {"label": label},
    )
    exchange = _CandleExchange(5 * 60)
    requests = []

    rows = profile_acquisition_module.fetch_profile_candles(
        exchange,
        timeframe="5m",
        start_ms=0,
        end_ms=10 * 60 * 1000,
        page_limit=300,
        price=None,
        label="futures-5m",
        requests=requests,
    )

    assert len(rows) == 2
    assert exchange.calls[0][0] == "BTC/USDT:USDT"
    assert profile_acquisition_module.transport.SYMBOL == "XRP/USDT:USDT"


@pytest.mark.parametrize("profile_acquisition_module", [True], indirect=True)
def test_profile_1d_mode_writes_prepare_search_data_source_contract(
    profile_acquisition_module, tmp_path: Path
) -> None:
    import pyarrow as pa
    import pyarrow.feather as feather

    database, candidate_id = _approved_candidate_database(
        tmp_path / "profile", pair="XRP/USDT:USDT", timeframe="1d"
    )
    with get_connection(database) as connection:
        connection.execute(
            "UPDATE research_profiles SET history_start_date='2025-12-01'"
        )
        profile_id = connection.execute(
            "SELECT research_profile_id FROM generation_runs WHERE id="
            "(SELECT generation_run_id FROM candidates WHERE id=?)",
            (candidate_id,),
        ).fetchone()[0]
        profile = pilot.load_profile_snapshot(connection, profile_id)
        connection.commit()
    window = _write_profile_window(
        tmp_path,
        data_start_utc="2025-12-06T00:00:00Z",
        search_start_utc="2026-03-01T00:00:00Z",
        development_start_utc="2026-04-02T00:00:00Z",
        end_exclusive_utc="2026-05-02T00:00:00Z",
    )
    profile_acquisition_module.configure_profile_acquisition(
        database, profile_id, window, 85
    )
    root = tmp_path / "profile-source"
    receipt = _prepare_generated_root(root)
    series = {
        "XRP_USDT_USDT-1d-futures.feather": (
            profile_acquisition_module.DATA_START, timedelta(days=1), False
        ),
        "XRP_USDT_USDT-1h-mark.feather": (
            profile_acquisition_module.DATA_START, timedelta(hours=1), True
        ),
        "XRP_USDT_USDT-1h-funding_rate.feather": (
            profile_acquisition_module.SEARCH_START, timedelta(hours=8), False
        ),
    }
    for name, (start, step, missing_volume) in series.items():
        feather.write_feather(
            _ohlcv_table(
                pa,
                _timestamps(start, profile_acquisition_module.DATA_END, step),
                missing_volume=missing_volume,
            ),
            root / "data" / "okx" / "futures" / name,
            compression="uncompressed",
        )
    (root / "market_snapshot.json").write_bytes(
        profile_acquisition_module.canonical_bytes(
            {"id": "XRP-USDT-SWAP", "symbol": "XRP/USDT:USDT"}
        )
    )
    (root / "isolated_tiers_snapshot.json").write_bytes(
        profile_acquisition_module.canonical_bytes([{"symbol": "XRP/USDT:USDT"}])
    )
    receipt.write_bytes(
        profile_acquisition_module.canonical_bytes(
            {
                "host": "www.okx.com",
                "authentication": "none",
                "pair": "XRP/USDT:USDT",
                "instrument_id": "XRP-USDT-SWAP",
                "data_window": {
                    "start_utc": profile_acquisition_module.DATA_START.isoformat(),
                    "end_exclusive_utc": profile_acquisition_module.DATA_END.isoformat(),
                    "fully_closed_at_fetch": True,
                    "development_start_utc": (
                        profile_acquisition_module.SEARCH_START.isoformat()
                    ),
                    "holdout_start_utc": (
                        profile_acquisition_module.DEVELOPMENT_START.isoformat()
                    ),
                    "startup_candles_required": 85,
                },
            }
        )
    )

    provenance_path = profile_acquisition_module.write_profile_provenance(
        root, receipt, _runtime(profile_acquisition_module)
    )

    provenance = json.loads(provenance_path.read_bytes())
    assert json.loads((root / "config.json").read_bytes()) == (
        pilot.profile_search_config(profile)
    )
    assert provenance["source"]["pair"] == "XRP/USDT:USDT"
    assert provenance["contract"] == {
        "config": "config.json",
        "data_dir": "data/okx",
        "development_timerange": "20260301-20260402",
        "holdout_timerange": "20260402-20260502",
        "leverage_tiers": "isolated_tiers_snapshot.json",
        "market_snapshot": "market_snapshot.json",
        "profile_acquisition": {
            key: profile_acquisition_module.PROFILE_ACQUISITION[key]
            for key in pilot.PROFILE_ACQUISITION_FIELDS
        },
        "timeframe": "1d",
    }
    assert provenance["files"]["producer/fetch_okx_profile_data.py"]["sha256"] == (
        pilot.digest(PROFILE_HELPER.read_bytes())
    )
    assert provenance["files"][
        "producer/historical_fetch_okx_public_data.py"
    ]["sha256"] == "8a9ad34654693bbada15da4a90caacb380364ea8b747f2d5be193633080d843f"
    assert any(name.endswith("-1d-futures.feather") for name in provenance["local_only_files"])
    prepared = pilot.prepare_search_data(
        root,
        tmp_path / "prepared-search",
        pilot.digest(provenance_path.read_bytes()),
        pilot.digest(receipt.read_bytes()),
        database_path=database,
        profile_id=profile_id,
        search_timerange="20260301-20260402",
        development_timerange="20260402-20260502",
        pre_roll_candles=85,
    )
    assert prepared == {
        "status": "SEARCH_DATA_READY",
        "search_timerange": "20260301-20260402",
        "provenance_sha256": prepared["provenance_sha256"],
        "rows": {
            "futures_1d": 117,
            "mark_1h": 2808,
            "funding_history": 96,
        },
    }


def test_profile_window_rejects_duplicate_and_unknown_fields(
    profile_acquisition_module, tmp_path: Path
) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema":"freqtrade-lab-profile-source-window-v1",'
        '"schema":"freqtrade-lab-profile-source-window-v1",'
        '"data_start_utc":"2026-02-28T22:00:00Z",'
        '"search_start_utc":"2026-03-01T00:00:00Z",'
        '"development_start_utc":"2026-04-02T00:00:00Z",'
        '"end_exclusive_utc":"2026-05-02T00:00:00Z"}',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="duplicate key"):
        profile_acquisition_module.load_window_spec(duplicate)

    unknown = _write_profile_window(tmp_path, pair="BTC/USDT:USDT")
    with pytest.raises(RuntimeError, match="shape/version"):
        profile_acquisition_module.load_window_spec(unknown)


def test_profile_60_30_funding_uses_three_bounded_batches(
    profile_acquisition_module, monkeypatch, tmp_path: Path
) -> None:
    _configure_profile_helper(
        profile_acquisition_module,
        tmp_path,
        data_start_utc="2026-03-31T22:00:00Z",
        search_start_utc="2026-04-01T00:00:00Z",
        development_start_utc="2026-05-31T00:00:00Z",
        end_exclusive_utc="2026-06-30T00:00:00Z",
    )
    monkeypatch.setattr(
        profile_acquisition_module,
        "request_receipt",
        lambda exchange, label: {"label": label},
    )
    exchange = _FundingExchange(profile_acquisition_module.FUNDING_INTERVAL_MS)
    requests = []

    funding = profile_acquisition_module.fetch_funding_history(exchange, requests)

    assert len(funding) == 270
    assert [call[2] for call in exchange.calls] == [100, 100, 70]
    assert all(call[2] <= 100 for call in exchange.calls)
    assert [request["label"] for request in requests] == [
        "funding-history-1",
        "funding-history-2",
        "funding-history-3",
    ]
    for _, since, limit, params in exchange.calls:
        assert params == {
            "after": since + limit * profile_acquisition_module.FUNDING_INTERVAL_MS
        }
    assert exchange.calls[0][1] == int(
        profile_acquisition_module.SEARCH_START.timestamp() * 1000
    )
    assert exchange.calls[-1][3]["after"] == profile_acquisition_module.DATA_END_MS
    assert [call[1] for call in exchange.calls[1:]] == [
        call[3]["after"] for call in exchange.calls[:-1]
    ]
    assert profile_acquisition_module.validate_funding_history(funding)["rows"] == 270
    with pytest.raises(RuntimeError, match="every fixed eight-hour timestamp"):
        profile_acquisition_module.validate_funding_history(funding[:-1])


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
