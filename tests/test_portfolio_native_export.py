import json
import zipfile
import pytest
from lab.portfolio_native_export import read_strategy_export


def archive(tmp_path,values):
    path=tmp_path/'native.zip'
    with zipfile.ZipFile(path,'w') as z:
        for i,value in enumerate(values): z.writestr(f'{i}.json',json.dumps(value))
    return path


def test_config_null_does_not_mask_exact_result(tmp_path):
    path=archive(tmp_path,[{'strategy':None},{'strategy':{'PortfolioCausalProbe':{'trades':[]}}}])
    assert read_strategy_export(path,'PortfolioCausalProbe')=={'trades':[]}


def test_duplicate_payload_and_wrong_name_rejected(tmp_path):
    value={'strategy':{'PortfolioCausalProbe':{'trades':[]}}}
    with pytest.raises(ValueError,match='exactly one'): read_strategy_export(archive(tmp_path,[value,value]),'PortfolioCausalProbe')
    with pytest.raises(ValueError): read_strategy_export(archive(tmp_path,[value]),'WrongStrategy')


def test_corrupt_json_and_archive_rejected(tmp_path):
    path=tmp_path/'bad.zip'
    with zipfile.ZipFile(path,'w') as z: z.writestr('broken.json','{')
    with pytest.raises(ValueError): read_strategy_export(path,'PortfolioCausalProbe')
    path.write_bytes(b'broken archive')
    with pytest.raises(zipfile.BadZipFile): read_strategy_export(path,'PortfolioCausalProbe')
