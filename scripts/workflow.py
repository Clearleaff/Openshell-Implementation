#!/usr/bin/env python3
"""Trusted sequential orchestrator; diagnosis output is untrusted to next agent."""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)

def run(role, task, upstream='', trace=None):
    command = ['openshell', 'sandbox', 'exec', '-n', 'prescptr-' + role, '--no-login-shell', '--',
               'python', '-m', 'app.agent', '--task', task, '--upstream', upstream,
               '--trace', trace or uuid.uuid4().hex]
    try:
        proc = subprocess.run(command, text=True, capture_output=True, timeout=900)
    except subprocess.TimeoutExpired:
        return {'status': 'error', 'error': 'sandbox_exec_timeout'}
    # CLI diagnostic lines may precede the application's final JSON object.
    for line in reversed(proc.stdout.splitlines()):
        try:
            value = json.loads(line)
            if isinstance(value, dict) and 'status' in value:
                return value
        except ValueError:
            pass
    return {'status': 'error', 'error': 'missing_agent_result', 'exit_code': proc.returncode}

if __name__ == '__main__':
    case = uuid.uuid4().hex
    diagnosis = run('diagnosis', 'Diagnose CNC-01 from current telemetry. Explain evidence and uncertainty.')
    if diagnosis['status'] != 'completed':
        print(json.dumps({'diagnosis': diagnosis, 'status': 'stopped'})); sys.exit(2)
    prescription = run('prescriptive', 'Read current telemetry and create a useful maintenance draft for CNC-01.',
                       diagnosis['answer'])
    result = {'diagnosis': diagnosis, 'prescription': prescription}
    Path('evidence').mkdir(exist_ok=True)
    Path('evidence/live-workflow-' + case + '.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    sys.exit(0 if prescription['status'] == 'completed' else 2)
