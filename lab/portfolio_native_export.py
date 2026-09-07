"""Read one exact native strategy result without confusing exported config."""
import json
import zipfile


def read_strategy_export(path,strategy_name):
    found=[]
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if not info.filename.endswith('.json'): continue
            if info.file_size>16*1024*1024: raise ValueError('oversized native JSON')
            value=json.loads(archive.read(info))  # CRC, decoding and JSON errors propagate.
            if not isinstance(value,dict): raise ValueError('native JSON root must be object')
            strategies=value.get('strategy')
            if isinstance(strategies,dict) and strategy_name in strategies:
                payload=strategies[strategy_name]
                if not isinstance(payload,dict): raise ValueError('strategy payload must be object')
                found.append(payload)
    if len(found)!=1: raise ValueError('exactly one native strategy payload required')
    return found[0]
