import base64
import hashlib
import importlib.util
import io
import json
import sys
import traceback
import types
import zipfile
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
    history_start_date: str = "2025-01-01",
    **window_overrides,
) -> tuple[Path, str, dict[str, object], Path]:
    database, candidate_id = _approved_candidate_database(
        tmp_path / "profile", pair=pair, timeframe=timeframe
    )
    with get_connection(database) as connection:
        connection.execute(
            "UPDATE research_profiles SET history_start_date=?",
            (history_start_date,),
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
    module.configure_profile_acquisition(database, profile_id, window, pre_roll_candles)
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
        self.last_http_response = None

    def publicGetPublicFundingRateHistory(self, params):
        rows = [
            {"instId": params["instId"], "fundingTime": str(timestamp),
             "fundingRate": "0.9", "realizedRate": "0.0001"}
            for timestamp in range(params["before"] + 1, params["after"], self.interval_ms)
        ][:params["limit"]]
        response = {"code": "0", "data": rows}
        self.last_http_response = json.dumps(response)
        return response

    def fetch_funding_rate_history(self, symbol, *, since, limit, params):
        self.calls.append((symbol, since, limit, dict(params)))
        response = self.publicGetPublicFundingRateHistory({
            "instId": symbol.replace("/", "-").split(":")[0] + "-SWAP",
            "before": since - 1, "limit": limit, **params,
        })
        return sorted([
            {"timestamp": int(row["fundingTime"]), "fundingRate": float(row["realizedRate"]),
             "symbol": symbol, "info": row}
            for row in response["data"]
        ], key=lambda row: row["timestamp"])[:limit]


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


def _funding_archive_bytes(
    csv_name: str,
    rows: list[tuple[str, str, str]],
    *,
    header: tuple[str, str, str] = (
        "instrument_name",
        "funding_rate",
        "funding_time",
    ),
    extra_member: bool = False,
) -> bytes:
    csv_bytes = (
        ",".join(header) + "\r\n" + "".join(",".join(row) + "\r\n" for row in rows)
    ).encode("utf-8")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(csv_name, csv_bytes)
        if extra_member:
            archive.writestr("unexpected.csv", csv_bytes)
    return output.getvalue()


def _funding_catalog_group_bytes(
    module,
    months: list[tuple[int, int]],
    *,
    details_override=None,
    groups_override=None,
) -> bytes:
    begin = module._archive_month_bounds(*months[0])[0]
    end = module._archive_month_bounds(*months[-1])[1]
    groups = []
    for year, month in months:
        date_ts = module._archive_month_bounds(year, month)[0]
        _, archive_name, _ = module._archive_names(year, month)
        groups.append(
            {
                "dateTs": str(date_ts),
                "filename": archive_name,
                "sizeMB": "0",
                "url": (
                    "https://static.okx.com/cdn/okex/traderecords/"
                    f"swaprates/monthly/{year:04d}{month:02d}/"
                    f"{archive_name}?v=999"
                ),
            }
        )
    if groups_override is not None:
        groups = groups_override
    details = [
        {
            "ccy": "",
            "dateRangeEnd": str(module._archive_month_bounds(*months[-1])[0]),
            "dateRangeStart": str(begin),
            "groupDetails": groups,
            "groupSizeMB": "0",
            "instFamily": module.PAIR_FAMILY,
            "instId": "",
            "instType": "SWAP",
        }
    ]
    if details_override is not None:
        details = details_override
    value = {
        "code": "0",
        "data": {
            "begin": str(begin),
            "ccyList": [],
            "dateAggrType": "monthly",
            "details": details,
            "end": str(end),
            "exportTime": "1",
            "instrumentList": [module.PAIR_FAMILY],
            "totalSizeMB": "0",
        },
        "msg": "",
    }
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _funding_catalog_bytes(
    module,
    year: int,
    month: int,
    *,
    details_override=None,
) -> bytes:
    return _funding_catalog_group_bytes(
        module,
        [(year, month)],
        details_override=details_override,
    )


def _mock_monthly_archives(module, monkeypatch, *, poison="SEALED_RATE_MARKER"):
    """Serve complete synthetic local months, including protected boundary rows."""
    first = int(module.SEARCH_START.timestamp() * 1000)
    stop = module.DATA_END_MS
    archives = {}
    month_rows = {}
    for year, month in module._archive_months():
        begin, last_day = module._archive_month_bounds(year, month)
        rows = [
            (
                module.INSTRUMENT_ID,
                "0.0001" if first <= timestamp < stop else poison,
                str(timestamp + 1000),
            )
            for timestamp in range(
                begin, last_day + 24 * 60 * 60 * 1000, module.FUNDING_INTERVAL_MS
            )
        ]
        month_rows[(year, month)] = rows

    def request(method, url, *, body=None):
        if method == "POST":
            begin = int(json.loads(body)["dateQuery"]["begin"])
            group = next(
                group for group in module._archive_month_groups()
                if module._archive_month_bounds(*group[0])[0] == begin
            )
            return _funding_catalog_group_bytes(module, group), {
                "content-type": "application/json"
            }
        for (year, month), rows in month_rows.items():
            _, archive_name, csv_name = module._archive_names(year, month)
            if url.endswith(f"/{archive_name}?v=999"):
                raw = _funding_archive_bytes(csv_name, rows)
                archives[archive_name] = raw
                return raw, {"content-type": "application/zip"}
        pytest.fail("unexpected synthetic archive request")

    monkeypatch.setattr(module, "archive_http_request", request)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    return month_rows, archives


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
    _, _, _, window = _configure_profile_helper(profile_acquisition_module, tmp_path)

    assert profile_acquisition_module.load_window_spec(window) == (
        datetime(2026, 2, 28, 22, tzinfo=timezone.utc),
        datetime(2026, 3, 1, tzinfo=timezone.utc),
        datetime(2026, 4, 2, tzinfo=timezone.utc),
        datetime(2026, 5, 2, tzinfo=timezone.utc),
    )
    assert profile_acquisition_module.PROFILE_ACQUISITION["search_timerange"] == (
        "20260301-20260402"
    )
    assert (
        profile_acquisition_module.PROFILE_ACQUISITION["development_timerange"]
        == "20260402-20260502"
    )


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
    profile_acquisition_module, monkeypatch, tmp_path: Path
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
    _mock_monthly_archives(profile_acquisition_module, monkeypatch)
    requests = []
    profile_acquisition_module.fetch_archive_funding_history(requests)
    root = tmp_path / "profile-source"
    receipt = _prepare_generated_root(root)
    series = {
        "XRP_USDT_USDT-1d-futures.feather": (
            profile_acquisition_module.DATA_START,
            timedelta(days=1),
            False,
        ),
        "XRP_USDT_USDT-1h-mark.feather": (
            profile_acquisition_module.DATA_START,
            timedelta(hours=1),
            True,
        ),
        "XRP_USDT_USDT-1h-funding_rate.feather": (
            profile_acquisition_module.SEARCH_START,
            timedelta(hours=8),
            False,
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
    funding_path = (
        root / "data" / "okx" / "futures" / "XRP_USDT_USDT-1h-funding_rate.feather"
    )
    assert funding_path.name == "XRP_USDT_USDT-1h-funding_rate.feather"
    assert feather.read_table(funding_path).column_names == [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
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
                "requests": requests,
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
    assert (
        provenance["files"]["producer/historical_fetch_okx_public_data.py"]["sha256"]
        == "8a9ad34654693bbada15da4a90caacb380364ea8b747f2d5be193633080d843f"
    )
    assert any(
        name.endswith("-1d-futures.feather") for name in provenance["local_only_files"]
    )
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


def test_profile_60_30_rest_funding_uses_three_bounded_batches(
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

    funding = profile_acquisition_module.fetch_rest_funding_history(exchange, requests)

    assert len(funding) == 270
    assert [call[2] for call in exchange.calls] == [101, 101, 71]
    assert all(call[2] <= 101 for call in exchange.calls)
    assert [request["label"] for request in requests] == [
        "funding-history-1",
        "funding-history-2",
        "funding-history-3",
    ]
    for _, since, limit, params in exchange.calls:
        assert params == {
            "after": since + (limit - 1) * profile_acquisition_module.FUNDING_INTERVAL_MS
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
    with pytest.raises(RuntimeError, match="every fixed eight-hour timestamp"):
        profile_acquisition_module.validate_funding_history(funding + [funding[-1]])


def test_issue_45_profile_window_binds_exact_90_day_pre_roll(
    profile_acquisition_module, tmp_path: Path
) -> None:
    _configure_profile_helper(
        profile_acquisition_module,
        tmp_path,
        pair="BTC/USDT:USDT",
        timeframe="1d",
        pre_roll_candles=90,
        history_start_date="2024-12-01",
        data_start_utc="2024-12-01T00:00:00Z",
        search_start_utc="2025-03-01T00:00:00Z",
        development_start_utc="2025-09-01T00:00:00Z",
        end_exclusive_utc="2026-03-01T00:00:00Z",
    )

    assert profile_acquisition_module.DATA_START == datetime(
        2024, 12, 1, tzinfo=timezone.utc
    )
    assert profile_acquisition_module.PROFILE_ACQUISITION["pre_roll_candles"] == 90
    assert profile_acquisition_module._archive_months() == [
        (2025, month) for month in range(3, 13)
    ] + [(2026, 1), (2026, 2), (2026, 3)]
    assert [
        len(group) for group in profile_acquisition_module._archive_month_groups()
    ] == [6, 6, 1]
    assert profile_acquisition_module._archive_month_groups() == [
        [(2025, month) for month in range(3, 9)],
        [(2025, month) for month in range(9, 13)] + [(2026, 1), (2026, 2)],
        [(2026, 3)],
    ]


def test_expired_funding_window_selects_monthly_archive(
    profile_acquisition_module, monkeypatch, tmp_path: Path
) -> None:
    _configure_profile_helper(
        profile_acquisition_module,
        tmp_path,
        timeframe="1d",
        pre_roll_candles=1,
        data_start_utc="2026-03-31T00:00:00Z",
        search_start_utc="2026-04-01T00:00:00Z",
        development_start_utc="2026-05-03T00:00:00Z",
        end_exclusive_utc="2026-05-05T00:00:00Z",
    )
    expected = [{"timestamp": 1, "fundingRate": 0.1}]
    monkeypatch.setattr(
        profile_acquisition_module,
        "fetch_archive_funding_history",
        lambda requests: expected,
    )
    monkeypatch.setattr(
        profile_acquisition_module,
        "fetch_rest_funding_history",
        lambda exchange, requests: pytest.fail("REST path must not be selected"),
    )

    actual = profile_acquisition_module.fetch_funding_history(
        object(), [], fetched_at=datetime(2026, 9, 4, tzinfo=timezone.utc)
    )

    assert actual is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    (("3", 3.0), ("99", 2.0), ("invalid", 2.0), (None, 2.0)),
)
def test_catalog_retry_after_is_bounded(
    profile_acquisition_module, value, expected
) -> None:
    assert profile_acquisition_module._catalog_retry_delay(value) == expected


def test_catalog_retry_after_http_date_is_honored(profile_acquisition_module) -> None:
    now = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)

    assert (
        profile_acquisition_module._catalog_retry_delay(
            "Sat, 05 Sep 2026 00:00:04 GMT", now=now
        )
        == 4.0
    )


@pytest.mark.parametrize(
    "months",
    (
        [],
        [(2026, month) for month in range(1, 8)],
        [(2026, 4), (2026, 6)],
    ),
)
def test_archive_catalog_group_rejects_unbounded_or_nonconsecutive_months(
    profile_acquisition_module, tmp_path: Path, months
) -> None:
    _configure_profile_helper(profile_acquisition_module, tmp_path)

    with pytest.raises(RuntimeError, match="consecutive and bounded"):
        profile_acquisition_module._archive_catalog_group(months, [])


def test_archive_catalog_retries_one_429_and_records_both_attempts(
    profile_acquisition_module, monkeypatch, tmp_path: Path
) -> None:
    _configure_profile_helper(profile_acquisition_module, tmp_path)
    months = [(2026, 4), (2026, 5)]
    raw = _funding_catalog_group_bytes(profile_acquisition_module, months)
    calls = []
    sleeps = []

    def request(method, url, *, body=None):
        calls.append((method, url, body))
        if len(calls) == 1:
            raise profile_acquisition_module.ArchiveCatalogRateLimited(
                b'{"code":"50011","msg":"rate limit"}',
                {
                    "content-type": "application/json",
                    "retry-after": "3",
                },
            )
        return raw, {
            "content-type": "application/json",
            "content-length": str(len(raw)),
        }

    monkeypatch.setattr(profile_acquisition_module, "archive_http_request", request)
    monkeypatch.setattr(
        profile_acquisition_module.time,
        "sleep",
        lambda seconds: sleeps.append(seconds),
    )
    receipts = []

    entries = profile_acquisition_module._archive_catalog_group(months, receipts)

    assert [(entry[0], entry[1]) for entry in entries] == months
    assert [receipt["http_status"] for receipt in receipts] == [429, 200]
    assert [receipt["attempt"] for receipt in receipts] == [1, 2]
    assert receipts[0]["retry_wait_seconds"] == 3.0
    assert sleeps == [
        profile_acquisition_module.ARCHIVE_CATALOG_THROTTLE_SECONDS,
        3.0,
    ]


def test_archive_funding_crosses_okx_local_month_and_records_hashes(
    profile_acquisition_module, monkeypatch, tmp_path: Path
) -> None:
    _configure_profile_helper(
        profile_acquisition_module,
        tmp_path,
        pair="BTC/USDT:USDT",
        timeframe="1d",
        pre_roll_candles=1,
        data_start_utc="2026-03-31T00:00:00Z",
        search_start_utc="2026-04-01T00:00:00Z",
        development_start_utc="2026-05-03T00:00:00Z",
        end_exclusive_utc="2026-05-05T00:00:00Z",
    )
    first = int(profile_acquisition_module.SEARCH_START.timestamp() * 1000)
    stop = profile_acquisition_module.DATA_END_MS
    expected_timestamps = list(
        range(first, stop, profile_acquisition_module.FUNDING_INTERVAL_MS)
    )
    month_rows: dict[tuple[int, int], list[tuple[str, str, str]]] = {
        (2026, 4): [("BTC-USDT-SWAP", "0.0001", str(first - 8 * 60 * 60 * 1000))],
        (2026, 5): [],
    }
    for index, timestamp in enumerate(expected_timestamps):
        local = datetime.fromtimestamp(timestamp / 1000, timezone.utc).astimezone(
            profile_acquisition_module.ARCHIVE_TIMEZONE
        )
        month_rows[(local.year, local.month)].append(
            ("BTC-USDT-SWAP", "0.0001", str(timestamp + index % 3 * 1000))
        )
    month_rows[(2026, 5)].append(("BTC-USDT-SWAP", "0.0001", str(stop)))
    archives: dict[str, bytes] = {}
    for year, month in ((2026, 4), (2026, 5)):
        _, archive_name, csv_name = profile_acquisition_module._archive_names(
            year, month
        )
        url = (
            "https://static.okx.com/cdn/okex/traderecords/swaprates/monthly/"
            f"{year:04d}{month:02d}/{archive_name}?v=999"
        )
        archives[url] = _funding_archive_bytes(csv_name, month_rows[(year, month)])
    calls = []
    sleeps = []

    def request(method, url, *, body=None):
        calls.append((method, url, body))
        if method == "POST":
            raw = _funding_catalog_group_bytes(
                profile_acquisition_module, [(2026, 4), (2026, 5)]
            )
            return raw, {
                "content-type": "application/json;charset=UTF-8",
                "content-length": str(len(raw)),
            }
        raw = archives[url]
        md5 = base64.b64encode(hashlib.md5(raw).digest()).decode("ascii")
        return raw, {
            "content-type": "application/zip",
            "content-length": str(len(raw)),
            "content-md5": md5,
            "etag": hashlib.md5(raw).hexdigest(),
        }

    monkeypatch.setattr(profile_acquisition_module, "archive_http_request", request)
    monkeypatch.setattr(
        profile_acquisition_module.time,
        "sleep",
        lambda seconds: sleeps.append(seconds),
    )
    receipts = []

    rows = profile_acquisition_module.fetch_archive_funding_history(receipts)

    assert [row["timestamp"] for row in rows] == expected_timestamps
    assert [item["label"] for item in receipts] == [
        "funding-archive-catalog-2026-04-through-2026-05-attempt-1",
        "funding-archive-2026-04",
        "funding-archive-2026-05",
    ]
    assert all(
        receipt["archive_sha256"] == receipt["response_sha256"]
        and len(receipt["csv_sha256"]) == 64
        for receipt in receipts
        if receipt["method"] == "GET"
    )
    normalizations = [
        receipt["timestamp_normalization"]
        for receipt in receipts
        if receipt["method"] == "GET"
    ]
    assert {item["method"] for item in normalizations} == {
        profile_acquisition_module.FUNDING_ARCHIVE_TIMESTAMP_NORMALIZATION
    }
    assert {item["maximum_allowed_drift_ms"] for item in normalizations} == {2000}
    assert max(item["maximum_observed_drift_ms"] for item in normalizations) == 2000
    assert sum(item["normalized_rows"] for item in normalizations) > 0
    assert len([call for call in calls if call[0] == "POST"]) == 1
    assert sleeps == [profile_acquisition_module.ARCHIVE_CATALOG_THROTTLE_SECONDS]


@pytest.mark.parametrize("drift_ms", (-1, 2001, 3000))
def test_archive_funding_rejects_timestamp_outside_post_grid_drift_budget(
    profile_acquisition_module, monkeypatch, tmp_path: Path, drift_ms: int
) -> None:
    _configure_profile_helper(
        profile_acquisition_module,
        tmp_path,
        pair="BTC/USDT:USDT",
        timeframe="1d",
        pre_roll_candles=1,
        data_start_utc="2026-03-31T00:00:00Z",
        search_start_utc="2026-04-01T00:00:00Z",
        development_start_utc="2026-05-03T00:00:00Z",
        end_exclusive_utc="2026-05-05T00:00:00Z",
    )
    # Keep the negative drift inside the permitted window; before-start rows
    # are now deliberately skipped without interpreting their rate.
    timestamp = int(profile_acquisition_module.SEARCH_START.timestamp() * 1000)
    timestamp += profile_acquisition_module.FUNDING_INTERVAL_MS
    _, archive_name, csv_name = profile_acquisition_module._archive_names(2026, 4)
    archive = _funding_archive_bytes(
        csv_name,
        [("BTC-USDT-SWAP", "0.0001", str(timestamp + drift_ms))],
    )
    monkeypatch.setattr(
        profile_acquisition_module,
        "_archive_month_groups",
        lambda: [[(2026, 4)]],
    )
    monkeypatch.setattr(
        profile_acquisition_module,
        "_archive_catalog_group",
        lambda months, requests: [
            (
                2026,
                4,
                "https://static.okx.com/cdn/okex/traderecords/swaprates/monthly/"
                f"202604/{archive_name}?v=999",
                archive_name,
                csv_name,
            )
        ],
    )
    monkeypatch.setattr(
        profile_acquisition_module,
        "archive_http_request",
        lambda method, url: (
            archive,
            {
                "content-type": "application/zip",
                "content-length": str(len(archive)),
            },
        ),
    )

    with pytest.raises(RuntimeError, match="timestamp drifted"):
        profile_acquisition_module.fetch_archive_funding_history([])


def test_issue_45_archive_uses_6_6_1_groups_and_binds_provenance(
    profile_acquisition_module, monkeypatch, tmp_path: Path
) -> None:
    _configure_profile_helper(
        profile_acquisition_module,
        tmp_path,
        pair="BTC/USDT:USDT",
        timeframe="1d",
        pre_roll_candles=90,
        history_start_date="2024-12-01",
        data_start_utc="2024-12-01T00:00:00Z",
        search_start_utc="2025-03-01T00:00:00Z",
        development_start_utc="2025-09-01T00:00:00Z",
        end_exclusive_utc="2026-03-01T00:00:00Z",
    )
    first = int(profile_acquisition_module.SEARCH_START.timestamp() * 1000)
    stop = profile_acquisition_module.DATA_END_MS
    expected_timestamps = list(
        range(first, stop, profile_acquisition_module.FUNDING_INTERVAL_MS)
    )
    groups = profile_acquisition_module._archive_month_groups()
    month_rows = {month: [] for group in groups for month in group}
    for timestamp in expected_timestamps:
        local = datetime.fromtimestamp(timestamp / 1000, timezone.utc).astimezone(
            profile_acquisition_module.ARCHIVE_TIMEZONE
        )
        month_rows[(local.year, local.month)].append(
            ("BTC-USDT-SWAP", "0.0001", str(timestamp))
        )
    archives = {}
    for year, month in month_rows:
        _, archive_name, csv_name = profile_acquisition_module._archive_names(
            year, month
        )
        url = (
            "https://static.okx.com/cdn/okex/traderecords/swaprates/monthly/"
            f"{year:04d}{month:02d}/{archive_name}?v=999"
        )
        archives[url] = _funding_archive_bytes(csv_name, month_rows[(year, month)])
    calls = []
    sleeps = []

    def request(method, url, *, body=None):
        calls.append((method, url, body))
        if method == "POST":
            payload = json.loads(body)
            begin = int(payload["dateQuery"]["begin"])
            selected = next(
                group
                for group in groups
                if profile_acquisition_module._archive_month_bounds(*group[0])[0]
                == begin
            )
            raw = _funding_catalog_group_bytes(profile_acquisition_module, selected)
            return raw, {
                "content-type": "application/json",
                "content-length": str(len(raw)),
            }
        raw = archives[url]
        return raw, {
            "content-type": "application/zip",
            "content-length": str(len(raw)),
        }

    monkeypatch.setattr(profile_acquisition_module, "archive_http_request", request)
    monkeypatch.setattr(
        profile_acquisition_module.time,
        "sleep",
        lambda seconds: sleeps.append(seconds),
    )
    receipts = []

    rows = profile_acquisition_module.fetch_archive_funding_history(receipts)

    assert len(rows) == 1095
    assert [row["timestamp"] for row in rows] == expected_timestamps
    catalog_receipts = [receipt for receipt in receipts if receipt["method"] == "POST"]
    assert [receipt["label"] for receipt in catalog_receipts] == [
        "funding-archive-catalog-2025-03-through-2025-08-attempt-1",
        "funding-archive-catalog-2025-09-through-2026-02-attempt-1",
        "funding-archive-catalog-2026-03-attempt-1",
    ]
    assert len([receipt for receipt in receipts if receipt["method"] == "GET"]) == 13
    assert len([call for call in calls if call[0] == "POST"]) == 3
    assert sleeps == [profile_acquisition_module.ARCHIVE_CATALOG_THROTTLE_SECONDS] * 3

    root = tmp_path / "issue-45-source"
    receipt_path = _prepare_generated_root(root)
    for name in (
        "BTC_USDT_USDT-1d-futures.feather",
        "BTC_USDT_USDT-1h-mark.feather",
        "BTC_USDT_USDT-1h-funding_rate.feather",
    ):
        (root / "data" / "okx" / "futures" / name).write_bytes(name.encode())
    receipt_path.write_bytes(
        profile_acquisition_module.canonical_bytes({"requests": receipts})
    )
    provenance_path = profile_acquisition_module.write_profile_provenance(
        root, receipt_path, _runtime(profile_acquisition_module)
    )
    provenance = json.loads(provenance_path.read_bytes())

    assert provenance["files"][receipt_path.name]["sha256"] == pilot.digest(
        receipt_path.read_bytes()
    )
    assert provenance["source"]["pair"] == "BTC/USDT:USDT"


@pytest.mark.parametrize(
    "url",
    (
        "https://example.invalid/cdn/okex/traderecords/swaprates/monthly/202604/"
        "BTC-USDT-SWAP-fundingrates-2026-04.zip?v=999",
        "https://static.okx.com/other/202604/"
        "BTC-USDT-SWAP-fundingrates-2026-04.zip?v=999",
        "https://static.okx.com/cdn/okex/traderecords/swaprates/monthly/202604/"
        "BTC-USDT-SWAP-fundingrates-2026-04.zip?v=changed",
    ),
)
def test_archive_endpoint_rejects_unpinned_asset_before_io(
    profile_acquisition_module, url: str
) -> None:
    with pytest.raises(RuntimeError, match="forbidden funding archive endpoint"):
        profile_acquisition_module._validate_archive_endpoint("GET", url)


def test_archive_http_rejects_redirect_without_followup(
    profile_acquisition_module, monkeypatch
) -> None:
    class Response:
        status = 302

        def getheaders(self):
            return [("Location", "https://example.invalid/file.zip")]

        def close(self):
            self.closed = True

    response = Response()

    class Connection:
        def __init__(self, host, timeout):
            self.host = host

        def request(self, method, target, *, body, headers):
            self.target = target

        def getresponse(self):
            return response

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        profile_acquisition_module.http.client, "HTTPSConnection", Connection
    )
    url = (
        "https://static.okx.com/cdn/okex/traderecords/swaprates/monthly/"
        "202604/XRP-USDT-SWAP-fundingrates-2026-04.zip?v=999"
    )

    with pytest.raises(RuntimeError, match="redirect response rejected"):
        profile_acquisition_module.archive_http_request("GET", url)

    assert response.closed is True


def test_archive_http_exposes_catalog_429_for_bounded_retry(
    profile_acquisition_module, monkeypatch
) -> None:
    raw = b'{"code":"50011","msg":"rate limit"}'

    class Response:
        status = 429

        def getheaders(self):
            return [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(raw))),
                ("Retry-After", "3"),
            ]

        def getheader(self, name):
            return None

        def read(self, maximum):
            return raw

        def close(self):
            pass

    class Connection:
        def __init__(self, host, timeout):
            pass

        def request(self, method, target, *, body, headers):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(
        profile_acquisition_module.http.client, "HTTPSConnection", Connection
    )

    with pytest.raises(
        profile_acquisition_module.ArchiveCatalogRateLimited
    ) as captured:
        profile_acquisition_module.archive_http_request(
            "POST",
            profile_acquisition_module.ARCHIVE_CATALOG_URL,
            body=b"{}",
        )

    assert captured.value.body == raw
    assert captured.value.headers["retry-after"] == "3"


def test_archive_http_rejects_content_md5_mismatch(
    profile_acquisition_module, monkeypatch
) -> None:
    raw = b"not-the-attested-archive"

    class Response:
        status = 200

        def getheaders(self):
            return [
                ("Content-Length", str(len(raw))),
                ("Content-MD5", base64.b64encode(b"0" * 16).decode("ascii")),
            ]

        def getheader(self, name):
            return None

        def read(self, maximum):
            return raw

        def close(self):
            pass

    class Connection:
        def __init__(self, host, timeout):
            pass

        def request(self, method, target, *, body, headers):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(
        profile_acquisition_module.http.client, "HTTPSConnection", Connection
    )
    url = (
        "https://static.okx.com/cdn/okex/traderecords/swaprates/monthly/"
        "202604/XRP-USDT-SWAP-fundingrates-2026-04.zip?v=999"
    )

    with pytest.raises(RuntimeError, match="Content-MD5 mismatch"):
        profile_acquisition_module.archive_http_request("GET", url)


@pytest.mark.parametrize(
    ("header", "instrument", "rate", "extra_member", "message"),
    (
        (
            ("bad", "funding_rate", "funding_time"),
            "XRP-USDT-SWAP",
            "0.1",
            False,
            "header changed",
        ),
        (
            ("instrument_name", "funding_rate", "funding_time"),
            "BTC-USDT-SWAP",
            "0.1",
            False,
            "instrument mismatch",
        ),
        (
            ("instrument_name", "funding_rate", "funding_time"),
            "XRP-USDT-SWAP",
            "nan",
            False,
            "not finite",
        ),
        (
            ("instrument_name", "funding_rate", "funding_time"),
            "XRP-USDT-SWAP",
            "0.1",
            True,
            "must contain exactly",
        ),
    ),
)
def test_archive_parser_fails_closed_on_format_drift(
    profile_acquisition_module,
    monkeypatch,
    tmp_path: Path,
    header,
    instrument,
    rate,
    extra_member,
    message,
) -> None:
    _configure_profile_helper(profile_acquisition_module, tmp_path)
    _, archive_name, csv_name = profile_acquisition_module._archive_names(2026, 4)
    raw = _funding_archive_bytes(
        csv_name,
        [(instrument, rate, "1775001600000")],
        header=header,
        extra_member=extra_member,
    )

    with pytest.raises(RuntimeError, match=message):
        profile_acquisition_module._parse_funding_archive(
            raw, archive_name=archive_name, csv_name=csv_name,
            year=2026, month=4,
            start_ms=int(profile_acquisition_module.SEARCH_START.timestamp() * 1000),
            end_exclusive_ms=profile_acquisition_module.DATA_END_MS,
        )


@pytest.mark.parametrize("details", ([], [{}, {}]))
def test_archive_catalog_rejects_missing_or_duplicate_month(
    profile_acquisition_module, monkeypatch, tmp_path: Path, details
) -> None:
    _configure_profile_helper(profile_acquisition_module, tmp_path)
    raw = _funding_catalog_bytes(
        profile_acquisition_module, 2026, 4, details_override=details
    )
    monkeypatch.setattr(
        profile_acquisition_module,
        "archive_http_request",
        lambda method, url, *, body=None: (
            raw,
            {"content-type": "application/json", "content-length": str(len(raw))},
        ),
    )
    monkeypatch.setattr(profile_acquisition_module.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="missing, duplicate, or extra"):
        profile_acquisition_module._archive_catalog_group([(2026, 4)], [])


@pytest.mark.parametrize("case", ("missing", "duplicate", "extra"))
def test_archive_catalog_group_rejects_month_set_drift(
    profile_acquisition_module, monkeypatch, tmp_path: Path, case: str
) -> None:
    _configure_profile_helper(profile_acquisition_module, tmp_path)
    months = [(2026, 4), (2026, 5)]
    value = json.loads(_funding_catalog_group_bytes(profile_acquisition_module, months))
    groups = value["data"]["details"][0]["groupDetails"]
    if case == "missing":
        groups.pop()
    elif case == "duplicate":
        groups[1] = dict(groups[0])
    else:
        groups.append(
            {
                "dateTs": "0",
                "filename": "unexpected.zip",
                "sizeMB": "0",
                "url": "https://static.okx.com/unexpected.zip?v=999",
            }
        )
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    monkeypatch.setattr(
        profile_acquisition_module,
        "archive_http_request",
        lambda method, url, *, body=None: (
            raw,
            {"content-type": "application/json", "content-length": str(len(raw))},
        ),
    )
    monkeypatch.setattr(profile_acquisition_module.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="catalog group"):
        profile_acquisition_module._archive_catalog_group(months, [])


def test_profile_store_uses_freqtrade_funding_rate_format_and_names(
    profile_acquisition_module, monkeypatch, tmp_path: Path
) -> None:
    _configure_profile_helper(
        profile_acquisition_module,
        tmp_path,
        pair="BTC/USDT:USDT",
        timeframe="1d",
        pre_roll_candles=1,
        data_start_utc="2026-03-31T00:00:00Z",
        search_start_utc="2026-04-01T00:00:00Z",
        development_start_utc="2026-05-03T00:00:00Z",
        end_exclusive_utc="2026-05-05T00:00:00Z",
    )
    calls = []

    def convert(rows, timeframe, symbol, *, fill_missing, drop_incomplete):
        calls.append(
            ("convert", rows, timeframe, symbol, fill_missing, drop_incomplete)
        )
        return {
            "rows": rows,
            "columns": ["date", "open", "high", "low", "close", "volume"],
        }

    class Handler:
        def ohlcv_store(self, symbol, timeframe, frame, candle_type):
            calls.append(("store", symbol, timeframe, frame, candle_type))

    monkeypatch.setattr(
        profile_acquisition_module.transport, "ohlcv_to_dataframe", convert
    )
    monkeypatch.setattr(
        profile_acquisition_module.transport,
        "get_datahandler",
        lambda data_dir, data_format: Handler(),
    )
    funding = [{"timestamp": 1, "fundingRate": 0.0001}]

    profile_acquisition_module.store_profile_market_data(
        tmp_path / "data", [[1, 1, 1, 1, 1, 1]], [[1, 1, 1, 1, 1, 0]], funding
    )

    funding_convert = [call for call in calls if call[0] == "convert"][-1]
    assert funding_convert[1] == [[1, 0.0001, 0, 0, 0, 0]]
    assert funding_convert[2:4] == ("1h", "BTC/USDT:USDT")
    assert funding_convert[4:] == (False, False)
    assert [call[4] for call in calls if call[0] == "store"] == [
        profile_acquisition_module.transport.CandleType.FUTURES,
        profile_acquisition_module.transport.CandleType.MARK,
        profile_acquisition_module.transport.CandleType.FUNDING_RATE,
    ]
    assert [call[2] for call in calls if call[0] == "store"] == ["1d", "1h", "1h"]


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
    selected = acquisition_module.load_local_candidate_inputs(strategy, research_spec)
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
    assert provenance["contract"]["strategy"] == ("strategies/StrategyTestV3Futures.py")
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


def test_persistent_catalog_429_removes_owned_output_and_provenance(
    profile_acquisition_module, monkeypatch, tmp_path: Path
) -> None:
    database, profile_id, _, window = _configure_profile_helper(
        profile_acquisition_module, tmp_path
    )
    output_root = tmp_path / "partial-profile-output"
    monkeypatch.setattr(
        profile_acquisition_module,
        "parse_args",
        lambda: types.SimpleNamespace(
            output_root=output_root,
            window_spec=window,
            profile_database=database,
            profile_id=profile_id,
            pre_roll_candles=24,
        ),
    )
    monkeypatch.setattr(profile_acquisition_module, "validate_runtime", lambda: {})
    monkeypatch.setattr(
        profile_acquisition_module, "implementation_snapshot", lambda: {}
    )
    attempts = []

    def rate_limited(method, url, *, body=None):
        attempts.append((method, url, body))
        raise profile_acquisition_module.ArchiveCatalogRateLimited(
            b'{"code":"50011","msg":"rate limit"}',
            {"content-type": "application/json", "retry-after": "999"},
        )

    monkeypatch.setattr(
        profile_acquisition_module, "archive_http_request", rate_limited
    )
    monkeypatch.setattr(profile_acquisition_module.time, "sleep", lambda seconds: None)
    receipts = []

    def fail_archive(root, runtime):
        (root / "partial-archive.zip").write_bytes(b"partial")
        profile_acquisition_module._archive_catalog_group([(2026, 4)], receipts)

    monkeypatch.setattr(profile_acquisition_module, "acquire", fail_archive)

    with pytest.raises(RuntimeError, match="remained rate limited"):
        profile_acquisition_module.main()

    assert not output_root.exists()
    assert not (output_root / "retained-data-provenance.json").exists()
    assert len(attempts) == 2
    assert [receipt["http_status"] for receipt in receipts] == [429, 429]
    assert receipts[0]["retry_wait_seconds"] == (
        profile_acquisition_module.ARCHIVE_CATALOG_RETRY_FALLBACK_SECONDS
    )


@pytest.mark.parametrize("poison", ("NaN", "Inf", "-Inf", "BAD_RATE_MARKER", "1e9999"))
@pytest.mark.parametrize("timeframe", ("5m", "1d"))
def test_archive_boundary_never_converts_protected_rates(
    profile_acquisition_module, monkeypatch, tmp_path, poison, timeframe
):
    module = profile_acquisition_module
    _configure_profile_helper(
        module, tmp_path, timeframe=timeframe,
        pre_roll_candles=24 if timeframe == "5m" else 1,
        data_start_utc=(
            "2026-02-28T22:00:00Z" if timeframe == "5m" else "2026-02-28T00:00:00Z"
        ),
        search_start_utc="2026-03-01T00:00:00Z",
        development_start_utc="2026-04-02T00:00:00Z",
        end_exclusive_utc="2026-05-01T00:00:00Z",
    )
    _, archives = _mock_monthly_archives(module, monkeypatch, poison=poison)
    conversions = []

    class GuardedFloat(float):
        def __new__(cls, value):
            if value == poison:
                raise AssertionError("protected rate conversion attempted")
            conversions.append(value)
            return super().__new__(cls, value)

    monkeypatch.setattr(module, "float", GuardedFloat, raising=False)
    receipts = []
    # Exercise the production route selection as well as catalog/parser/validator.
    rows = module.fetch_funding_history(
        object(), receipts, fetched_at=datetime(2026, 9, 5, tzinfo=timezone.utc)
    )
    first = int(module.SEARCH_START.timestamp() * 1000)
    assert [row["timestamp"] for row in rows] == list(
        range(first, module.DATA_END_MS, module.FUNDING_INTERVAL_MS)
    )
    assert conversions == ["0.0001"] * 183
    assert all(row["fundingRate"] == 0.0001 for row in rows)
    monthly = [receipt for receipt in receipts if receipt["method"] == "GET"]
    assert [receipt["csv_rows"] for receipt in monthly] == [93, 90, 93]
    assert [receipt["csv_physical_lines"] for receipt in monthly] == [94, 91, 94]
    assert [
        receipt["rate_selection"]["selected_rows"] for receipt in monthly
    ] == [92, 90, 1]
    assert [
        receipt["rate_selection"]["uninterpreted_rate_rows"] for receipt in monthly
    ] == [1, 0, 92]
    for receipt in monthly:
        raw = archives[receipt["archive_filename"]]
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            csv_raw = archive.read(receipt["csv_filename"])
        assert (
            receipt["archive_sha256"] == receipt["response_sha256"]
            == hashlib.sha256(raw).hexdigest()
        )
        assert receipt["archive_bytes"] == receipt["response_bytes"] == len(raw)
        assert receipt["csv_sha256"] == hashlib.sha256(csv_raw).hexdigest()
        assert receipt["csv_bytes"] == len(csv_raw)
        assert receipt["rate_selection"]["start_ms"] == first
        assert receipt["rate_selection"]["end_exclusive_ms"] == module.DATA_END_MS
        assert (
            receipt["rate_selection"]["uninterpreted_rate_validation"]
            == "NOT_PERFORMED"
        )
        assert receipt["timestamp_normalization"]["scope"] == "SELECTED_ROWS"
        assert receipt["timestamp_normalization"]["maximum_observed_drift_ms"] == 1000
        assert (
            receipt["timestamp_normalization"]["normalized_rows"]
            == receipt["rate_selection"]["selected_rows"]
        )
    assert poison not in json.dumps(receipts)


def _parse_synthetic_archive(module, rows, *, start_ms, end_ms, month=4):
    _, archive_name, csv_name = module._archive_names(2026, month)
    raw = _funding_archive_bytes(csv_name, rows)
    return module._parse_funding_archive(
        raw, archive_name=archive_name, csv_name=csv_name,
        year=2026, month=month, start_ms=start_ms, end_exclusive_ms=end_ms,
    )


@pytest.mark.parametrize(
    ("start_delta", "end_delta", "raw_delta", "selected"),
    (
        (0, 28800000, 0, True),
        (0, 28800000, 2000, True),
        (0, 28800000, -1, False),
        (0, 28800000, 28800000, False),
        (0, 28800000, 28802000, False),
        (0, 28801000, 28800000, True),
        (0, 28801000, 28800500, True),
        (0, 28801000, 28801000, False),
        (0, 28801000, 28802000, False),
        (1000, 28800000, 2000, False),
    ),
)
def test_archive_selection_requires_both_raw_and_normalized_half_open_times(
    profile_acquisition_module, monkeypatch, start_delta, end_delta, raw_delta, selected
):
    module = profile_acquisition_module
    monkeypatch.setattr(module, "INSTRUMENT_ID", "XRP-USDT-SWAP")
    grid = 1775001600000  # 2026-04-01T00:00:00Z
    poison = "BOUNDARY_RATE_MUST_NOT_BE_READ"
    result, receipt = _parse_synthetic_archive(
        module,
        [(module.INSTRUMENT_ID, "0.1" if selected else poison, str(grid + raw_delta))],
        start_ms=grid + start_delta, end_ms=grid + end_delta,
    )
    expected_timestamp = (
        grid + raw_delta // module.FUNDING_INTERVAL_MS * module.FUNDING_INTERVAL_MS
    )
    assert result == (
        [{"timestamp": expected_timestamp, "fundingRate": 0.1}] if selected else []
    )
    assert receipt["csv_rows"] == 1
    assert receipt["rate_selection"]["selected_rows"] == int(selected)
    assert receipt["rate_selection"]["uninterpreted_rate_rows"] == int(not selected)
    if not selected:
        assert receipt["timestamp_normalization"]["maximum_observed_drift_ms"] is None


@pytest.mark.parametrize("rate", ("NaN", "Inf", "-Inf", "BAD_RATE_MARKER", "1e9999"))
def test_archive_selected_poison_rates_still_fail_without_value_in_traceback(
    profile_acquisition_module, monkeypatch, rate, capsys
):
    module = profile_acquisition_module
    monkeypatch.setattr(module, "INSTRUMENT_ID", "XRP-USDT-SWAP")
    with pytest.raises(RuntimeError, match="row 2 rate is (invalid|not finite)"):
        try:
            _parse_synthetic_archive(
                module, [(module.INSTRUMENT_ID, rate, "1775001601000")],
                start_ms=1775001600000, end_ms=1775030400000,
            )
        except RuntimeError:
            traceback.print_exc()
            raise
    captured = capsys.readouterr()
    assert rate not in captured.err
    assert "row 2 rate is" in captured.err


@pytest.mark.parametrize(
    ("fields", "message"),
    (
        (("XRP-USDT-SWAP", "unused"), "shape changed"),
        (("BTC-USDT-SWAP", "unused", "1775030400000"), "instrument mismatch"),
        *(
            (("XRP-USDT-SWAP", "unused", value), "timestamp is invalid")
            for value in (
                "1775030400", "17750304000000", "+1775030400000", "1775030400000.0",
                "１７７５０３０４０００００", " 1775030400000", "invalid",
            )
        ),
    ),
)
def test_archive_checks_unselected_row_identity_shape_and_strict_timestamp(
    profile_acquisition_module, monkeypatch, fields, message
):
    module = profile_acquisition_module
    monkeypatch.setattr(module, "INSTRUMENT_ID", "XRP-USDT-SWAP")
    monkeypatch.setattr(
        module, "float", lambda value: pytest.fail("rate accessed before row validation"),
        raising=False,
    )
    with pytest.raises(RuntimeError, match=message):
        _parse_synthetic_archive(
            module, [fields], start_ms=1775001600000, end_ms=1775030400000,
        )


def test_archive_does_not_access_unselected_rate_field_and_counts_physical_lines(
    profile_acquisition_module, monkeypatch
):
    module = profile_acquisition_module
    monkeypatch.setattr(module, "INSTRUMENT_ID", "XRP-USDT-SWAP")
    original_reader = module.csv.reader

    class ProtectedFields(list):
        def __getitem__(self, index):
            if index == 1:
                pytest.fail("protected rate field accessed")
            return super().__getitem__(index)

    class GuardedReader:
        def __init__(self, *args, **kwargs):
            self.reader = original_reader(*args, **kwargs)

        def __iter__(self):
            return self

        def __next__(self):
            fields = next(self.reader)
            return ProtectedFields(fields) if self.reader.line_num > 1 else fields

        @property
        def line_num(self):
            return self.reader.line_num

    monkeypatch.setattr(module.csv, "reader", GuardedReader)
    rows, receipt = _parse_synthetic_archive(
        module, [(module.INSTRUMENT_ID, '"SEALED\nMULTILINE"', "1775030400000")],
        start_ms=1775001600000, end_ms=1775030400000,
    )
    assert rows == []
    assert receipt["csv_rows"] == 1
    assert receipt["csv_physical_lines"] == 3
    assert receipt["rate_selection"]["uninterpreted_rate_rows"] == 1


@pytest.mark.parametrize("case", ("missing", "duplicate", "collision", "wrong_month"))
def test_archive_selected_sequence_and_month_still_fail_closed(
    profile_acquisition_module, monkeypatch, tmp_path, case
):
    module = profile_acquisition_module
    _configure_profile_helper(module, tmp_path)
    month_rows, _ = _mock_monthly_archives(module, monkeypatch)
    rows = month_rows[(2026, 4)]
    if case == "missing":
        del rows[10]
    elif case == "duplicate":
        rows.append(rows[10])
    elif case == "collision":
        instrument, rate, timestamp = rows[10]
        rows.append((instrument, rate, str(int(timestamp) + 1000)))
    else:
        rows.append(month_rows[(2026, 3)][10])
    message = (
        "every fixed eight-hour timestamp" if case == "missing"
        else "timestamp drifted" if case == "wrong_month"
        else "duplicate UTC timestamps"
    )
    with pytest.raises(RuntimeError, match=message):
        module.fetch_archive_funding_history([])


@pytest.mark.parametrize(
    ("timestamp", "actual_month", "drift", "reasons"),
    (
        (1775001602001, "2026-04", 2001, "DRIFT_EXCEEDS_LIMIT"),
        (1775001603000, "2026-04", 3000, "DRIFT_EXCEEDS_LIMIT"),
        (1777593600000, "2026-05", 0, "MONTH_MISMATCH"),
        (1743465600000, "2025-04", 0, "MONTH_MISMATCH"),
        (1777593602001, "2026-05", 2001, "MONTH_MISMATCH,DRIFT_EXCEEDS_LIMIT"),
    ),
)
def test_archive_timestamp_error_has_safe_context_before_rate_access(
    profile_acquisition_module, monkeypatch, timestamp, actual_month, drift, reasons
):
    # Entirely synthetic rows: no public archive values or retained market data.
    module = profile_acquisition_module
    monkeypatch.setattr(module, "INSTRUMENT_ID", "XRP-USDT-SWAP")
    poison = "PRIVATE_RATE_MUST_NOT_BE_ACCESSED"
    original_reader = module.csv.reader

    class ProtectedFields(list):
        def __getitem__(self, index):
            if index == 1:
                pytest.fail("rate field accessed before timestamp rejection")
            return super().__getitem__(index)

    def guarded_reader(*args, **kwargs):
        reader = original_reader(*args, **kwargs)
        yield next(reader)
        for fields in reader:
            yield ProtectedFields(fields)

    monkeypatch.setattr(module.csv, "reader", guarded_reader)
    _, archive_name, csv_name = module._archive_names(2026, 4)
    raw = _funding_archive_bytes(
        csv_name, [(module.INSTRUMENT_ID, poison, str(timestamp))]
    )
    with pytest.raises(RuntimeError, match="funding archive month 2026-04 timestamp drifted") as error:
        module._parse_funding_archive(
            raw, archive_name=archive_name, csv_name=csv_name,
            year=2026, month=4, start_ms=1735689600000, end_exclusive_ms=1798761600000,
        )
    message = str(error.value)
    assert message == (
        f"funding archive month 2026-04 timestamp drifted: reasons={reasons}; "
        f"row=2; expected_month=2026-04; actual_month={actual_month}; "
        f"month_timezone=UTC+08:00; raw_timestamp_ms={timestamp}; "
        f"normalized_timestamp_ms={timestamp - drift}; drift_ms={drift}; "
        f"maximum_drift_ms=2000; archive_sha256={hashlib.sha256(raw).hexdigest()}"
    )
    assert poison not in ''.join(traceback.format_exception(error.value))


@pytest.mark.parametrize("failure", ("rate", "timestamp"))
def test_archive_selected_failure_through_main_cleans_output_and_stderr(
    profile_acquisition_module, monkeypatch, tmp_path, capsys, failure
):
    module = profile_acquisition_module
    database, profile_id, _, window = _configure_profile_helper(module, tmp_path)
    month_rows, _ = _mock_monthly_archives(module, monkeypatch)
    poison = "PRIVATE_SYNTHETIC_RATE_MARKER"
    instrument, _, timestamp = month_rows[(2026, 3)][1]
    if failure == "timestamp":
        timestamp = str(int(timestamp) + 2001)
    month_rows[(2026, 3)][1] = (instrument, poison, timestamp)
    message = "row 3 rate is invalid" if failure == "rate" else "DRIFT_EXCEEDS_LIMIT"
    output = tmp_path / "failed-source"
    sibling = tmp_path / "unrelated.txt"
    sibling.write_text("keep")
    monkeypatch.setattr(sys, "argv", [
        str(PROFILE_HELPER), "--output-root", str(output),
        "--window-spec", str(window), "--profile-database", str(database),
        "--profile-id", profile_id, "--pre-roll-candles", "24",
    ])
    monkeypatch.setattr(module, "validate_runtime", lambda: _runtime(module))
    market = {"id": module.INSTRUMENT_ID, "symbol": module.SYMBOL, "swap": True, "linear": True}
    closed = []
    exchange = types.SimpleNamespace(
        public_get_public_instruments=lambda params: {"code": "0", "data": [{
            "instId": module.INSTRUMENT_ID, "instType": "SWAP",
            "settleCcy": "USDT", "state": "live",
        }]},
        parse_market=lambda instrument: market,
        set_markets=lambda *args: None,
        fetch_market_leverage_tiers=lambda *args: [{"symbol": module.SYMBOL}],
        close=lambda: closed.append(True),
    )
    monkeypatch.setattr(module.transport.ccxt, "okx", lambda config: exchange)
    monkeypatch.setattr(module, "install_request_guard", lambda exchange: None)
    monkeypatch.setattr(module, "request_receipt", lambda exchange, label: {"label": label})
    monkeypatch.setattr(module, "fetch_profile_candles", lambda *args, **kwargs: [])
    monkeypatch.setattr(module, "store_profile_market_data", lambda *args: pytest.fail("data published"))
    monkeypatch.setattr(module, "write_profile_provenance", lambda *args: pytest.fail("provenance published"))
    with pytest.raises(RuntimeError, match=message):
        try:
            module.main()
        except RuntimeError:
            traceback.print_exc()
            raise
    assert closed == [True]
    assert not output.exists()
    assert sibling.read_text() == "keep"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err
    assert poison not in captured.err
    assert "could not convert string to float" not in captured.err
