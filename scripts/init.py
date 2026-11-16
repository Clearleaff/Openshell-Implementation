#!/usr/bin/env python3
"""Create local role credentials once. Never puts a Gemini key in agent config."""
import argparse
import json
import os
import secrets
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--lab-adversarial-connectors', action='store_true', help='Enable synthetic diagnostic attack-surface connectors in a disposable lab only')
p.add_argument('--model', required=True, help='Exact generateContent-capable model available to your AI Studio project')
p.add_argument('--base-url', default='http://host.openshell.internal:8765')
p.add_argument('--interval', type=int, default=15)
p.add_argument('--daily-requests', type=int, default=100)
a = p.parse_args()
if not 1 <= a.interval <= 30 or not 1 <= a.daily_requests <= 10000:
    p.error('interval must be 1..30; daily requests 1..10000')
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
os.umask(0o077)
r = Path('runtime')
if (r / 'control.json').exists():
    p.error('runtime/control.json already exists; retain credentials or deliberately remove/move it before initializing again')
r.mkdir(exist_ok=True)
tokens = {role: secrets.token_urlsafe(32) for role in ('diagnosis', 'prescriptive')}
attacks = json.loads(Path('fixtures/attacks.json').read_text())
config = {'model': a.model, 'tokens': tokens, 'min_interval_seconds': a.interval,
          'daily_requests': a.daily_requests, 'lab_adversarial_connectors': a.lab_adversarial_connectors, 'lab_attack_notes': {c['id']: c['note'] for c in attacks}}
(r / 'control.json').write_text(json.dumps(config, indent=2))
for role, token in tokens.items():
    d = r / role
    d.mkdir(exist_ok=True)
    (d / 'config.json').write_text(json.dumps({'role': role, 'token': token, 'base_url': a.base_url, 'lab_adversarial_connectors': a.lab_adversarial_connectors}))
print('Created runtime configs. Keep runtime private; do not upload control.json to a sandbox.')
