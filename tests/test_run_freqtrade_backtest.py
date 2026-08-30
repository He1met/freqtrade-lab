import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.run_freqtrade_backtest import (
    MAX_NATIVE_ZIP_MEMBER_BYTES,
    OfflineBacktestError,
    _BoundedTextSink,
    _owned_scenario_data_directory,
    _validate_native_zip_infos,
    _validate_raw_config_boundary,
    _verify_dependency_versions,
    _verify_source_snapshot,
)


ROOT = Path(__file__).resolve().parent.parent


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
