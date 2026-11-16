#!/usr/bin/env python3
import json
import os
import subprocess
from pathlib import Path
os.chdir(Path(__file__).resolve().parent.parent)
Path('evidence').mkdir(exist_ok=True)
version = subprocess.check_output(['openshell', '--version'], text=True)
Path('evidence/openshell-version.txt').write_text(version)
if '0.1.5' not in version:
    raise SystemExit('Targets OpenShell v0.1.5; review CLI/policy compatibility before changing this version gate.')
subprocess.run(['docker', 'build', '-t', 'prescptr-gemini:local', '.'], check=True)
for role in ('diagnosis', 'prescriptive'):
    config = json.loads(Path('runtime', role, 'config.json').read_text())
    # Scope-limited service token is visible to this agent; Google API key is never passed.
    env = {**os.environ, 'PRESCPTR_CONFIG': json.dumps(config)}
    env.pop('GEMINI_API_KEY', None)
    subprocess.run(['openshell', 'sandbox', 'create', '--name', 'prescptr-' + role,
                    '--from', 'prescptr-gemini:local', '--policy', 'policies/' + role + '.yaml',
                    '--env-from', 'PRESCPTR_CONFIG', '--cpu', '1', '--memory', '512Mi',
                    '--detach', '--', 'sleep', 'infinity'], env=env, check=True)
    with Path('evidence', 'policy-' + role + '.txt').open('w') as f:
        subprocess.run(['openshell', 'policy', 'get', 'prescptr-' + role, '--full'], stdout=f, check=True)
