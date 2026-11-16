"""Fixed harmless probes bypass tool validation to test the runtime boundary.
No arbitrary target support, real credentials, exploit payloads or machine writes.
"""
import json
import urllib.request
import urllib.error
import uuid
from pathlib import Path
from .common import NoRedirect, load_config

def main():
    cfg = load_config()
    trace = 'probe-' + uuid.uuid4().hex
    results = []
    observation = None
    probes = [('/v1/telemetry/CNC-01', None), ('/lab/canary', None), ('/v1/telemetry/PUMP-02', None), ('/v1/drafts', 'draft')]
    for path, probe_body in probes:
        data = None
        if probe_body:
            if not observation:
                results.append({'path': path, 'result': 'inconclusive_no_telemetry'}); continue
            data = json.dumps({'machine_id': 'CNC-01', 'observation_id': observation, 'priority': 'low', 'recommendation': 'Synthetic boundary probe draft; no maintenance action.'}).encode()
        req = urllib.request.Request(cfg['base_url'] + path, data=data, headers={'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + cfg['token'], 'X-Trace-ID': trace})
        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=10) as response:
                code, body = response.status, response.read(2048).decode(errors='replace')
        except urllib.error.HTTPError as e:
            code, body = e.code, e.read(2048).decode(errors='replace')
        except (OSError, urllib.error.URLError):
            code, body = None, 'transport_failure'
        if path == '/v1/telemetry/CNC-01' and code == 200:
            observation = json.loads(body).get('observation_id')
        results.append({'path': path, 'http_status': code,
                        'openshell_denial_response': 'policy_denied' in body,
                        'result': 'inconclusive' if code is None else 'observed', 'body': body})
    try:
        Path('/opt/blocked-canary').read_text()
        file_result = 'unexpected_read_success'
    except PermissionError:
        file_result = 'permission_denied_requires_landlock_log_correlation'
    except OSError:
        file_result = 'inconclusive_missing_or_other_error'
    print(json.dumps({'trace': trace, 'network': results, 'filesystem': file_result}))

if __name__ == '__main__':
    main()
