"""Deterministic, downloadable evidence bundles for the bounded Python explorer."""
import csv
import hashlib
import io
import json
import platform
import sys
import zipfile
from datetime import datetime, timezone
from tla_parser import tla_to_python_from_string
from verification import verify

def make_report(source, property_text='', max_depth=12, max_states=120):
    if not isinstance(source, str) or not source.strip():
        raise ValueError("A TLA+ specification is required.")
    output=tla_to_python_from_string(source)
    graph=verify(source,property_text,max_depth,max_states)
    sha=hashlib.sha256(source.encode('utf-8')).hexdigest()
    settings={'engine':'restricted_python_explicit_state_explorer','max_depth':max_depth,'max_states':max_states,'property':property_text,'source_sha256':sha,'python_version':platform.python_version(),'complete':not graph['summary']['truncated']}
    memo=io.StringIO()
    memo.write('# Verification evidence\n\n')
    memo.write('This run uses a restricted-subset Python state explorer, NOT TLC.\n\n')
    memo.write('Model SHA-256: '+sha+'\n\n')
    for key,val in graph['summary'].items():memo.write(f'- {key}: {val}\n')
    memo.write('\nThe state-graph pass is limited to the explored finite reachable graph.\n')
    def csv_bytes(header,rows):
        stream=io.StringIO(newline='')
        w=csv.writer(stream);w.writerow(header);w.writerows(rows)
        return stream.getvalue()
    transitions=csv_bytes(['source','target','action'],((e['source'],e['target'],e.get('action','')) for e in graph['edges']))
    states=csv_bytes(['id','depth','state_json'],((n['id'],n['depth'],json.dumps(n['state'],sort_keys=True)) for n in graph['nodes']))
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED) as z:
        files={'model.tla':source,'generated_model.py':output,'states.csv':states,'transitions.csv':transitions,'verification.json':json.dumps(graph,indent=2,sort_keys=True),'run_manifest.json':json.dumps(settings,indent=2,sort_keys=True),'README.md':memo.getvalue()}
        for filename,content in sorted(files.items()):
            info=zipfile.ZipInfo(filename,(2020,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,content.encode('utf-8'))
    return buf.getvalue()
