import json
import pytest
from lab.spot139_binding import BindingError,validate_sources,deny_network,audit_native_fill,sha


def test_all_source_tampering_rejected_before_price_decode(tmp_path):
    paths=[]
    for n in range(39):
        p=tmp_path/str(n);p.write_bytes(b'not JSON deliberately');paths.append(dict(path=str(p),sha256=sha(p)))
    manifest=dict(bindings={},sources=paths,source_grade='SOURCE_INVENTORY_COMPLETE_NOT_EXECUTION_ADMITTED')
    assert validate_sources(manifest)
    (tmp_path/'17').write_bytes(b'changed')
    with pytest.raises(BindingError,match='tampered'):validate_sources(manifest)


def test_network_and_native_fill_semantics_fail_closed():
    with pytest.raises(BindingError):deny_network('socket.connect',())
    with pytest.raises(BindingError):audit_native_fill(dict(symbol='BTC',hour=1,inventory_after=1),{},1)
    with pytest.raises(BindingError,match='inventory'):audit_native_fill(dict(symbol='BTC',hour=1,inventory_after=1),{('BTC',1):100},.999)
    with pytest.raises(BindingError,match='force'):audit_native_fill(dict(symbol='BTC',hour=1,inventory_after=0,exit_reason='force_exit'),{('BTC',1):100},0)
