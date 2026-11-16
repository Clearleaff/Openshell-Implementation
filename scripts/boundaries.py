#!/usr/bin/env python3
"""Collect runtime probes plus a reachable positive control. Never guesses from timeouts."""
import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.common import request
p=argparse.ArgumentParser()
p.add_argument('--host-url',default='http://127.0.0.1:8765')
a=p.parse_args()
out=Path('evidence/live-boundaries-'+uuid.uuid4().hex);out.mkdir(parents=True)
for role in ('diagnosis','prescriptive'):
    cfg=json.loads(Path('runtime',role,'config.json').read_text())
    positive=request(a.host_url+'/lab/canary',headers={'Authorization':'Bearer '+cfg['token'],'X-Trace-ID':'positive-'+uuid.uuid4().hex})
    (out/(role+'-host-control.json')).write_text(json.dumps(positive))
    with (out/(role+'-probes.txt')).open('w') as f:
        subprocess.run(['openshell','sandbox','exec','-n','prescptr-'+role,'--no-login-shell','--','python','-m','app.probes'],stdout=f,stderr=subprocess.STDOUT,timeout=60,check=True)
    with (out/(role+'-runtime.log')).open('w') as f:
        subprocess.run(['openshell','logs','prescptr-'+role,'--since','30m','--source','sandbox'],stdout=f,stderr=subprocess.STDOUT,timeout=60,check=True)
print(str(out))
print('Review policy_denied + supervisor events + absence of lab_canary_reached for probe traces. Timeouts are inconclusive.')
