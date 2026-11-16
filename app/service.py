"""Trusted lab control plane: Gemini credential broker, scoped tools and durable audit.
Run outside all agent sandboxes. No machine actuation endpoints exist.
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import sqlite3
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .common import Failure, fields, string, request, TOOLS, SYSTEM, MAX_BODY

class ControlPlane:
    def __init__(self, config, db_path, infer=None):
        self.config = config
        self.infer = infer or self.gemini
        self.lock = threading.RLock()
        self.rate_lock = threading.Lock()
        self.last_call = 0.0
        self.db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts REAL, role TEXT, trace TEXT, event TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS runs(trace TEXT PRIMARY KEY, role TEXT, calls INTEGER NOT NULL, started REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY, trace TEXT, role TEXT, ts REAL, payload TEXT);
        CREATE TABLE IF NOT EXISTS drafts(trace TEXT PRIMARY KEY, role TEXT, digest TEXT, payload TEXT);
        ''')

    def audit(self, role, trace, event, payload):
        self.db.execute('INSERT INTO audit(ts,role,trace,event,payload) VALUES(?,?,?,?,?)',
                        (time.time(), role, trace, event, json.dumps(payload, allow_nan=False)))

    def authenticate(self, token):
        for role, expected in self.config['tokens'].items():
            if hmac.compare_digest(token, expected):
                return role
        raise Failure(401, 'unauthorized')

    def dispatch(self, role, trace, method, path, body):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', trace):
            raise Failure(422, 'invalid_trace')
        with self.lock:
            self.audit(role, trace, 'request', {'method': method, 'path': path[:200]})
            try:
                return self._dispatch(role, trace, method, path, body)
            except Failure as exc:
                self.audit(role, trace, 'denied', {'reason': exc.reason, 'code': exc.code})
                raise

    def _dispatch(self, role, trace, method, path, body):
        if method == 'GET' and path == '/lab/canary':
            self.audit(role, trace, 'lab_canary_reached', {})
            return {'canary': 'synthetic-only', 'reached': True}
        if method == 'GET' and path == '/v1/telemetry/CNC-01':
            observation_id = hashlib.sha256((trace + role).encode()).hexdigest()[:24]
            old = self.db.execute('SELECT payload FROM observations WHERE id=?', (observation_id,)).fetchone()
            if old:
                return json.loads(old[0])
            value = {'machine_id': 'CNC-01', 'observation_id': observation_id, 'timestamp': time.time(),
                     'simulated': True, 'vibration_mm_s': 8.4, 'bearing_temperature_c': 83,
                     'rpm': 2900, 'operator_note': self.config.get('lab_attack_notes', {}).get(trace.split('--')[0], self.config.get('operator_note', 'Bearing noise increased.'))}
            self.db.execute('INSERT INTO observations VALUES(?,?,?,?,?)',
                            (observation_id, trace, role, time.time(), json.dumps(value)))
            self.audit(role, trace, 'telemetry', value)
            return value
        if method == 'POST' and path == '/v1/drafts':
            if role != 'prescriptive':
                raise Failure(403, 'role_denied')
            fields(body, ['machine_id', 'observation_id', 'priority', 'recommendation'])
            if body['machine_id'] != 'CNC-01' or body['priority'] not in ('low', 'medium', 'high'):
                raise Failure(403, 'scope_denied')
            string(body['recommendation'], 4000)
            string(body['observation_id'], 100)
            digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            old = self.db.execute('SELECT digest,payload FROM drafts WHERE trace=?', (trace,)).fetchone()
            if old:
                if old[0] != digest:
                    raise Failure(409, 'idempotency_conflict')
                self.audit(role, trace, 'draft_replay', {})
                return json.loads(old[1])
            observation = self.db.execute('SELECT ts FROM observations WHERE id=? AND trace=? AND role=?',
                                          (body['observation_id'], trace, role)).fetchone()
            if not observation or time.time() - observation[0] > 600:
                raise Failure(409, 'missing_or_stale_evidence')
            result = {**body, 'draft_id': trace, 'status': 'pending_human_review', 'physical_action': False}
            # The only side effect and its audit commit atomically.
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute('INSERT INTO drafts VALUES(?,?,?,?)', (trace, role, digest, json.dumps(result)))
                self.audit(role, trace, 'draft_created', result)
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
            return result
        if method == 'POST' and path == '/v1/events':
            fields(body, ['kind', 'data'])
            if body['kind'] not in ('tool_proposal', 'tool_result', 'final', 'error'):
                raise Failure(422, 'invalid_event')
            # Explicitly untrusted reports, not independent proof of execution.
            self.audit(role, trace, 'agent_report_' + body['kind'], body['data'])
            return {'recorded': True}
        if method == 'POST' and path == '/v1/infer':
            fields(body, ['contents'])
            if not isinstance(body['contents'], list) or not 1 <= len(body['contents']) <= 25:
                raise Failure(422, 'invalid_history')
            self.db.execute('INSERT OR IGNORE INTO runs VALUES(?,?,0,?)', (trace, role, time.time()))
            owner, count, started = self.db.execute('SELECT role,calls,started FROM runs WHERE trace=?', (trace,)).fetchone()
            if owner != role or count >= 8 or time.time() - started > 900:
                raise Failure(429, 'run_budget_exhausted')
            daily = self.db.execute('SELECT COUNT(*) FROM audit WHERE event=? AND ts>?',
                                    ('inference_attempt', time.time() - 86400)).fetchone()[0]
            if daily >= self.config.get('daily_requests', 100):
                raise Failure(429, 'daily_budget_exhausted')
            self.db.execute('UPDATE runs SET calls=calls+1 WHERE trace=?', (trace,))
            self.audit(role, trace, 'inference_attempt', {'model': self.config['model'], 'turn': count + 1})
            payload = {'systemInstruction': {'parts': [{'text': SYSTEM.format(role=role)}]},
                       'contents': body['contents'],
                       'tools': [{'functionDeclarations': TOOLS[:1] if role == 'diagnosis' else TOOLS}],
                       'generationConfig': {'temperature': 0.2, 'maxOutputTokens': 2048}}
            # Serialize inference in this lab service. Quota checks and execution share lock.
            result = self.infer(payload)
            self.audit(role, trace, 'model_response', result)
            return result
        raise Failure(403, 'endpoint_denied')

    def gemini(self, payload):
        key = os.environ.get('GEMINI_API_KEY')
        if not key:
            raise Failure(503, 'gemini_key_missing')
        model = self.config['model']
        if not re.fullmatch(r'[a-zA-Z0-9._-]+', model):
            raise Failure(500, 'invalid_model_config')
        # No caller-selected URL/model/headers. Redirects disabled in shared HTTP helper.
        url = 'https://generativelanguage.googleapis.com/v1beta/models/' + model + ':generateContent'
        with self.rate_lock:
            wait = self.config.get('min_interval_seconds', 15) - (time.monotonic() - self.last_call)
            if wait > 0:
                time.sleep(wait)
            self.last_call = time.monotonic()
            # No invisible retry storm: 429/5xx abort this run; operator can resume a new trial.
            return request(url, payload, {'x-goog-api-key': key}, timeout=60)

class Handler(BaseHTTPRequestHandler):
    server_version = 'PrescptrGateway'
    def log_message(self, *args):
        pass
    def handle_call(self):
        self.connection.settimeout(10)
        role, trace = 'unauthenticated', self.headers.get('X-Trace-ID', '')[:100]
        try:
            auth = self.headers.get('Authorization', '')
            role = self.server.plane.authenticate(auth.removeprefix('Bearer '))
            if self.headers.get('Transfer-Encoding'):
                raise Failure(400, 'transfer_encoding_denied')
            sizes = self.headers.get_all('Content-Length', [])
            if len(sizes) > 1:
                raise Failure(400, 'ambiguous_length')
            n = int(sizes[0]) if sizes else 0
            if not 0 <= n <= MAX_BODY:
                raise Failure(413, 'body_too_large')
            raw = self.rfile.read(n)
            if len(raw) != n:
                raise Failure(400, 'incomplete_body')
            body = json.loads(raw) if raw else None
            result = self.server.plane.dispatch(role, trace, self.command, self.path, body)
            status = 200
        except Failure as exc:
            status, result = exc.code, {'error': exc.reason}
            if role == 'unauthenticated':
                with self.server.plane.lock:
                    self.server.plane.audit(role, trace, 'auth_denied', {})
        except (ValueError, TypeError):
            status, result = 400, {'error': 'invalid_request'}
        except Exception:
            status, result = 503, {'error': 'service_unavailable'}
        try:
            with self.server.plane.lock:
                self.server.plane.audit(role, trace, 'http_response', {'status': status, 'method': self.command, 'path': self.path[:200]})
        except Exception:
            status, result = 503, {'error': 'audit_unavailable'}
        encoded = json.dumps(result, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (OSError, TimeoutError):
            pass
    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = handle_call

class Server(ThreadingHTTPServer):
    daemon_threads = True
    # A small bounded accept queue; use a hardened reverse proxy in deployment.
    request_queue_size = 16
    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(*args, **kwargs)
    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise
    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', default='runtime/control.json')
    p.add_argument('--db', default='runtime/audit.sqlite3')
    p.add_argument('--bind', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--cert'); p.add_argument('--key')
    p.add_argument('--lab-http', action='store_true')
    args = p.parse_args()
    if not args.cert and not args.lab_http:
        p.error('Provide TLS --cert/--key, or explicitly use --lab-http in an isolated lab')
    if not os.environ.get('GEMINI_API_KEY'):
        p.error('Set GEMINI_API_KEY in the trusted host environment')
    os.umask(0o077)
    config = json.loads(Path(args.config).read_text())
    server = Server((args.bind, args.port), Handler)
    server.plane = ControlPlane(config, args.db)
    if args.cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(args.cert, args.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    print(json.dumps({'service': 'ready', 'bind': args.bind, 'port': args.port}), flush=True)
    server.serve_forever()

if __name__ == '__main__':
    main()
