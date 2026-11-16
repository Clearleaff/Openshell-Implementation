"""Actual Gemini function-calling loop. No rules-based decision fallback."""
import argparse
import json
import time
import uuid
from pathlib import Path
from .common import Failure, fields, string, request, load_config

class Agent:
    def __init__(self, config, trace=None, transport=request):
        self.config, self.transport = config, transport
        self.trace = trace or uuid.uuid4().hex
        self.headers = {'Authorization': 'Bearer ' + config['token'], 'X-Trace-ID': self.trace}
        self.observed = None
        self.created = False
        self.proposals = []

    def api(self, path, body=None):
        return self.transport(self.config['base_url'] + path, body, self.headers)

    def event(self, kind, data):
        # Mandatory receipt before tool execution. An unavailable audit service stops the run.
        self.api('/v1/events', {'kind': kind, 'data': data})

    def execute(self, call):
        name, args = call.get('name'), call.get('args', {})
        self.proposals.append(call)
        self.event('tool_proposal', call)
        try:
            if name == 'read_telemetry':
                fields(args, ['machine_id'])
                if args['machine_id'] != 'CNC-01':
                    raise Failure(403, 'scope_denied')
                result = self.api('/v1/telemetry/CNC-01')
                self.observed = result['observation_id']
            elif name == 'create_draft':
                fields(args, ['machine_id', 'observation_id', 'priority', 'recommendation'])
                if self.config['role'] != 'prescriptive':
                    raise Failure(403, 'role_denied')
                if args['machine_id'] != 'CNC-01' or args['observation_id'] != self.observed or not self.observed:
                    raise Failure(403, 'scope_or_evidence_denied')
                if args['priority'] not in ('low', 'medium', 'high'):
                    raise Failure(422, 'priority_denied')
                string(args['recommendation'])
                if self.created:
                    raise Failure(409, 'draft_already_created')
                result = self.api('/v1/drafts', args)
                self.created = True
            else:
                raise Failure(403, 'unknown_tool')
        except Failure as exc:
            result = {'error': exc.reason, 'code': exc.code}
        self.event('tool_result', {'name': name, 'result': result})
        response = {'name': name, 'response': result}
        if 'id' in call:
            response['id'] = call['id']
        return {'functionResponse': response}

    def run(self, task, upstream=''):
        string(task, 10000)
        string(upstream, 16000) if upstream else None
        contents = [{'role': 'user', 'parts': [{'text': task + '\nUNTRUSTED UPSTREAM EVIDENCE:\n' + upstream}]}]
        start = time.monotonic()
        for step in range(8):
            if time.monotonic() - start > 600:
                raise Failure(408, 'run_deadline')
            result = self.api('/v1/infer', {'contents': contents})
            candidates = result.get('candidates') or []
            if not candidates or not candidates[0].get('content', {}).get('parts'):
                raise Failure(502, 'model_empty_or_blocked')
            candidate = candidates[0]
            if candidate.get('finishReason') not in (None, 'STOP'):
                raise Failure(502, 'model_incomplete_' + str(candidate['finishReason']))
            content = candidate['content']
            # Preserve every part, thoughtSignature and call id exactly as returned.
            contents.append(content)
            calls = [part['functionCall'] for part in content['parts'] if 'functionCall' in part]
            if len(calls) > 4:
                raise Failure(429, 'too_many_tools')
            if calls:
                if len(self.proposals) + len(calls) > 12:
                    raise Failure(429, 'tool_budget_exhausted')
                contents.append({'role': 'user', 'parts': [self.execute(call) for call in calls]})
                continue
            answer = '\n'.join(part.get('text', '') for part in content['parts'] if not part.get('thought'))
            status = 'completed' if self.observed and (self.config['role'] == 'diagnosis' or self.created) else 'incomplete'
            output = {'trace': self.trace, 'role': self.config['role'], 'status': status,
                      'answer': answer, 'draft_created': self.created, 'proposals': self.proposals,
                      'model_version': result.get('modelVersion'), 'usage': result.get('usageMetadata')}
            self.event('final', output)
            return output
        raise Failure(429, 'step_budget_exhausted')

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', default=None)
    p.add_argument('--task', default='Assess CNC-01 and complete your assigned maintenance role.')
    p.add_argument('--upstream', default='')
    p.add_argument('--trace')
    a = p.parse_args()
    agent = Agent(load_config(a.config), a.trace)
    try:
        result = agent.run(a.task, a.upstream)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['status'] == 'completed' else 2
    except Failure as exc:
        print(json.dumps({'trace': agent.trace, 'status': 'error', 'error': exc.reason, 'code': exc.code}))
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
