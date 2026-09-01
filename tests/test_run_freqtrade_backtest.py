import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts import run_freqtrade_backtest as runner_module
from scripts.run_freqtrade_backtest import (
    MAX_NATIVE_ZIP_MEMBER_BYTES,
    OfflineBacktestError,
    _BoundedTextSink,
    _owned_scenario_data_directory,
    _parse_args,
    _resolve_new_receipt,
    _write_scenario_open_receipt,
    _validate_native_zip_infos,
    _validate_raw_config_boundary,
    _validate_results,
    _verify_dependency_versions,
    _verify_source_snapshot,
)


ROOT = Path(__file__).resolve().parent.parent


def _runner_argv() -> list[str]:
    return [
        "--runner-sha256",
        "0" * 64,
        "--freqtrade-source",
        "/tmp/freqtrade-source",
        "--source-tree-sha256",
        "1" * 64,
        "--scenario",
        "DEVELOPMENT",
        "--config",
        "/tmp/config.json",
        "--data-dir",
        "/tmp/data",
        "--user-data-dir",
        "/tmp/user-data",
        "--strategy-path",
        "/tmp/strategies",
        "--strategy-file",
        "/tmp/strategies/Strategy.py",
        "--strategy-sha256",
        "2" * 64,
        "--strategy",
        "Strategy",
        "--timerange",
        "20260801-20260802",
        "--fee",
        "0.0005",
        "--export-dir",
        "/tmp/export",
        "--market-snapshot",
        "/tmp/market.json",
        "--leverage-tiers",
        "/tmp/tiers.json",
        "--data-provenance",
        "/tmp/provenance.json",
    ]


def test_allow_zero_trades_cli_is_explicit_and_defaults_false() -> None:
    assert _parse_args(_runner_argv()).allow_zero_trades is False
    assert _parse_args(_runner_argv()).scenario_open_receipt is None
    assert _parse_args([*_runner_argv(), "--allow-zero-trades"]).allow_zero_trades is True


def test_scenario_open_receipt_is_exclusive_and_persisted(tmp_path: Path) -> None:
    path = _resolve_new_receipt(tmp_path / "HOLDOUT.json", "scenario receipt")
    value = {"schema": "test", "scenario": "HOLDOUT"}

    receipt_sha = _write_scenario_open_receipt(path, value)

    assert receipt_sha == hashlib.sha256(path.read_bytes()).hexdigest()
    assert json.loads(path.read_bytes()) == value
    with pytest.raises(OfflineBacktestError, match="already exists"):
        _write_scenario_open_receipt(path, value)


def test_holdout_receipt_precedes_any_retained_market_byte_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    data = tmp_path / "data"
    user_data = tmp_path / "user-data"
    strategies = tmp_path / "strategies"
    export = tmp_path / "export"
    receipts = tmp_path / "receipts"
    for directory in (source, data, user_data, strategies, export, receipts):
        directory.mkdir()
    config = tmp_path / "config.json"
    strategy = strategies / "Strategy.py"
    market = tmp_path / "market.json"
    tiers = tmp_path / "tiers.json"
    provenance = tmp_path / "provenance.json"
    config.write_text("{}\n", encoding="utf-8")
    strategy.write_text("class Strategy: pass\n", encoding="utf-8")
    market.write_text('{"retained":"market"}\n', encoding="utf-8")
    tiers.write_text('{"retained":"tiers"}\n', encoding="utf-8")
    provenance.write_text("{}\n", encoding="utf-8")
    receipt = receipts / "HOLDOUT.json"
    runner_sha = hashlib.sha256(Path(runner_module.__file__).read_bytes()).hexdigest()
    args = _parse_args(
        [
            "--runner-sha256",
            runner_sha,
            "--freqtrade-source",
            str(source),
            "--source-tree-sha256",
            "1" * 64,
            "--scenario",
            "HOLDOUT",
            "--config",
            str(config),
            "--data-dir",
            str(data),
            "--user-data-dir",
            str(user_data),
            "--strategy-path",
            str(strategies),
            "--strategy-file",
            str(strategy),
            "--strategy-sha256",
            "2" * 64,
            "--strategy",
            "Strategy",
            "--timerange",
            "20260801-20260802",
            "--fee",
            "0.0005",
            "--export-dir",
            str(export),
            "--market-snapshot",
            str(market),
            "--leverage-tiers",
            str(tiers),
            "--data-provenance",
            str(provenance),
            "--scenario-open-receipt",
            str(receipt),
        ]
    )
    monkeypatch.setattr(runner_module, "_validate_raw_config_boundary", lambda _value: None)
    monkeypatch.setattr(runner_module, "_verify_strategy_input", lambda *_args: None)
    monkeypatch.setattr(runner_module, "_verify_source_snapshot", lambda *_args: None)
    real_read = runner_module._read_regular_file

    def guarded_read(path: Path, label: str, limit: int) -> bytes:
        if Path(path) in {market, tiers} and not receipt.exists():
            raise AssertionError(f"{label} was read before the open receipt")
        return real_read(Path(path), label, limit)

    def stop_before_engine(_source: Path, _sha: str):
        assert receipt.is_file()
        raise runner_module.OfflineBacktestError("TEST_STOP_AFTER_OPEN_RECEIPT")

    monkeypatch.setattr(runner_module, "_read_regular_file", guarded_read)
    monkeypatch.setattr(runner_module, "_load_official_freqtrade", stop_before_engine)

    with pytest.raises(
        OfflineBacktestError, match="TEST_STOP_AFTER_OPEN_RECEIPT"
    ):
        runner_module._execute(args)

    assert json.loads(receipt.read_text(encoding="utf-8"))["scenario"] == "HOLDOUT"


def test_zero_trade_result_requires_explicit_allowance_and_matching_count() -> None:
    results = {
        "strategy": {
            "Strategy": {
                "trades": [],
                "total_trades": 0,
            }
        }
    }

    with pytest.raises(OfflineBacktestError, match="produced zero trades"):
        _validate_results(results, "Strategy", "XRP/USDT:USDT", 0.0005)

    assert (
        _validate_results(
            results,
            "Strategy",
            "XRP/USDT:USDT",
            0.0005,
            allow_zero_trades=True,
        )
        == 0
    )

    results["strategy"]["Strategy"]["total_trades"] = 1
    with pytest.raises(OfflineBacktestError, match="disagrees with trade records"):
        _validate_results(
            results,
            "Strategy",
            "XRP/USDT:USDT",
            0.0005,
            allow_zero_trades=True,
        )


def test_owned_scenario_data_cleanup_never_deletes_preexisting_sibling(
    tmp_path: Path,
) -> None:
    preexisting = tmp_path / "scenario-data"
    preexisting.mkdir()
    marker = preexisting / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(RuntimeError, match="controlled"):
        with _owned_scenario_data_directory(tmp_path) as owned:
            assert owned != preexisting
            (owned / "temporary.txt").write_text("temporary", encoding="utf-8")
            raise RuntimeError("controlled")

    assert marker.read_text(encoding="utf-8") == "keep"
    assert not list(tmp_path.glob(".scenario-data-*"))


@pytest.mark.parametrize(
    "config",
    (
        {"pairlists": [{"method": "StaticPairList"}], "add_config_files": []},
        {"pairlists": [{"method": "VolumePairList"}]},
        {
            "pairlists": [{"method": "StaticPairList"}],
            "exchange": {"private_key": "unsafe"},
        },
    ),
)
def test_raw_runner_config_rejects_include_dynamic_pairlist_and_secret(config) -> None:
    with pytest.raises(OfflineBacktestError):
        _validate_raw_config_boundary(config)


def test_raw_runner_config_accepts_only_the_fixed_runtime_shape() -> None:
    config_path = ROOT / "tests" / "fixtures" / "freqtrade_2026_7" / "producer" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config.update(
        {
            "config_files": [str(config_path)],
            "datadir": "/local/data",
            "export": "trades",
            "exportdirectory": "/local/output",
            "strategy_path": "/local/strategies",
            "timerange": "20260801-20260804",
            "user_data_dir": "/local/user_data",
        }
    )

    _validate_raw_config_boundary(config)


def test_runner_requires_recorded_and_runtime_dependency_versions() -> None:
    provenance = {
        "freqtrade": {
            "dependencies": {
                "ccxt": "4.5.68",
                "pandas": "3.0.3",
                "pyarrow": "25.0.0",
                "python": "Python 3.13.13",
            }
        }
    }
    runtime = {
        "ccxt": "4.5.68",
        "pandas": "3.0.3",
        "pyarrow": "25.0.0",
        "python": "3.13.13",
        "freqtrade": "2026.7",
    }

    _verify_dependency_versions(provenance, runtime)

    runtime["pyarrow"] = "25.0.1"
    with pytest.raises(OfflineBacktestError, match="dependency versions"):
        _verify_dependency_versions(provenance, runtime)


def test_source_snapshot_is_hash_bound_and_rejects_extra_or_changed_bytes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "snapshot"
    package = source / "freqtrade"
    package.mkdir(parents=True)
    package_init = package / "__init__.py"
    package_init.write_bytes(b'__version__ = "2026.7"\n')

    data = package_init.read_bytes()
    digest = hashlib.sha256(b"freqtrade-lab-source-tree-v1\0")
    digest.update(b"freqtrade/__init__.py\0")
    digest.update(str(len(data)).encode("ascii"))
    digest.update(b"\0")
    digest.update(data)
    digest.update(b"\0")
    receipt = digest.hexdigest()

    assert _verify_source_snapshot(source, receipt) == receipt

    package_init.write_bytes(data + b"# changed\n")
    with pytest.raises(OfflineBacktestError, match="producer receipt"):
        _verify_source_snapshot(source, receipt)

    package_init.write_bytes(data)
    (source / "unexpected.txt").write_text("outside package", encoding="utf-8")
    with pytest.raises(OfflineBacktestError, match="only the freqtrade package"):
        _verify_source_snapshot(source, receipt)


def test_runner_bounds_candidate_text_and_zip_expansion_before_reading() -> None:
    sink = _BoundedTextSink(limit=4)
    assert sink.write("test") == 4
    with pytest.raises(OfflineBacktestError, match="text output"):
        sink.write("x")

    info = zipfile.ZipInfo("report.json")
    info.file_size = MAX_NATIVE_ZIP_MEMBER_BYTES + 1
    info.compress_size = 1
    with pytest.raises(OfflineBacktestError, match="expansion limit"):
        _validate_native_zip_infos([info])
