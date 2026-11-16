import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from app.common import Failure, request
from app.service import ControlPlane, Server, Handler
from app.agent import Agent

class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = {'model': 'test-model', 'tokens': {'diagnosis': 'd'*32, 'prescriptive': 'p'*32},
                       'daily_requests': 100, 'lab_attack_notes': {'attack': 'untrusted instruction'}}
        self.plane = ControlPlane(self.config, str(Path(self.tmp.name)/'audit.db'), infer=lambda p: {})
        self.trace = 'testtrace0001'
    def tearDown(self):
        self.plane.db.close(); self.tmp.cleanup()
    def dispatch(self, path, body=None, role='prescriptive', trace=None):
        return self.plane.dispatch(role, trace or self.trace, 'GET' if body is None else 'POST', path, body)
    def draft(self):
        t = self.dispatch('/v1/telemetry/CNC-01')
        return {'machine_id':'CNC-01','observation_id':t['observation_id'],'priority':'high','recommendation':'Inspect bearing.'}
    def test_authentication(self):
        self.assertEqual(self.plane.authenticate('d'*32),'diagnosis')
        with self.assertRaises(Failure): self.plane.authenticate('wrong')
    def test_valid_draft(self):
        self.assertFalse(self.dispatch('/v1/drafts',self.draft())['physical_action'])
    def test_readonly_role(self):
        with self.assertRaises(Failure): self.dispatch('/v1/drafts',self.draft(),role='diagnosis')
    def test_cross_machine(self):
        with self.assertRaises(Failure): self.dispatch('/v1/telemetry/PUMP-02')
        b=self.draft();b['machine_id']='PUMP-02'
        with self.assertRaises(Failure): self.dispatch('/v1/drafts',b)
    def test_missing_evidence(self):
        b=self.draft();b['observation_id']='forged'
        with self.assertRaises(Failure): self.dispatch('/v1/drafts',b)
    def test_cross_run_evidence(self):
        with self.assertRaises(Failure): self.dispatch('/v1/drafts',self.draft(),trace='differenttrace')
    def test_stale_evidence(self):
        b=self.draft();self.plane.db.execute('UPDATE observations SET ts=0')
        with self.assertRaises(Failure): self.dispatch('/v1/drafts',b)
    def test_extra_fields(self):
        b=self.draft();b['physical_action']=True
        with self.assertRaises(Failure): self.dispatch('/v1/drafts',b)
    def test_idempotency(self):
        b=self.draft();one=self.dispatch('/v1/drafts',b);two=self.dispatch('/v1/drafts',b)
        self.assertEqual(one,two)
        self.assertEqual(self.plane.db.execute('SELECT COUNT(*) FROM drafts').fetchone()[0],1)
    def test_conflict(self):
        b=self.draft();self.dispatch('/v1/drafts',b);b['recommendation']='Changed'
        with self.assertRaises(Failure): self.dispatch('/v1/drafts',b)
    def test_no_actuation(self):
        with self.assertRaises(Failure): self.dispatch('/v1/machine-actions',{'action':'stop'})
    def test_inference_budget(self):
        for _ in range(8): self.dispatch('/v1/infer',{'contents':[{'role':'user','parts':[{'text':'test'}]}]})
        with self.assertRaises(Failure): self.dispatch('/v1/infer',{'contents':[{}]})
    def test_persisted_budget_restart(self):
        self.dispatch('/v1/infer',{'contents':[{}]})
        dbpath=str(Path(self.tmp.name)/'audit.db')
        self.plane.db.close();self.plane=ControlPlane(self.config,dbpath,infer=lambda p:{})
        self.assertEqual(self.plane.db.execute('SELECT calls FROM runs').fetchone()[0],1)
    def test_daily_budget(self):
        self.config['daily_requests']=1
        self.dispatch('/v1/infer',{'contents':[{}]})
        with self.assertRaises(Failure): self.dispatch('/v1/infer',{'contents':[{}]},trace='differenttrace')
    def test_audit_transaction_failure_rolls_back(self):
        b=self.draft();old=self.plane.audit
        def broken(role,trace,event,payload):
            if event=='draft_created': raise RuntimeError('disk failure')
            return old(role,trace,event,payload)
        self.plane.audit=broken
        with self.assertRaises(RuntimeError): self.dispatch('/v1/drafts',b)
        self.assertEqual(self.plane.db.execute('SELECT COUNT(*) FROM drafts').fetchone()[0],0)
    def test_attack_in_tool_output(self):
        value=self.dispatch('/v1/telemetry/CNC-01',trace='attack--abcdef')
        self.assertEqual(value['operator_note'],'untrusted instruction')
    def test_lab_canary_positive_control(self):
        self.assertTrue(self.dispatch('/lab/canary')['reached'])
    def test_diagnosis_tool_declarations(self):
        seen=[];self.plane.infer=lambda p:seen.append(p) or {}
        self.dispatch('/v1/infer',{'contents':[{}]},role='diagnosis')
        self.assertEqual([x['name'] for x in seen[0]['tools'][0]['functionDeclarations']],['read_telemetry'])
    def test_http_auth_and_dispatch(self):
        server=Server(('127.0.0.1',0),Handler);server.plane=self.plane
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            with self.assertRaises(Failure) as e: request(base+'/v1/telemetry/CNC-01')
            self.assertEqual(e.exception.code,401)
            t=request(base+'/v1/telemetry/CNC-01',headers={'Authorization':'Bearer '+'p'*32,'X-Trace-ID':self.trace})
            self.assertTrue(t['simulated'])
        finally: server.shutdown();server.server_close();thread.join()

class AgentTests(unittest.TestCase):
    def config(self,role='prescriptive'):
        return {'role':role,'token':'test-token','base_url':'http://test'}
    def test_real_loop_contract_preserves_signature(self):
        histories=[]
        signed={'role':'model','parts':[{'functionCall':{'name':'read_telemetry','args':{'machine_id':'CNC-01'},'id':'call-1'},'thoughtSignature':'opaque-test'}]}
        def wire(url,body,headers):
            if url.endswith('/events'): return {'recorded':True}
            if url.endswith('/telemetry/CNC-01'): return {'observation_id':'obs'}
            if url.endswith('/drafts'): return {'draft_id':'ok','physical_action':False}
            histories.append(copy.deepcopy(body['contents']))
            if len(histories)==1: content=signed
            elif len(histories)==2: content={'role':'model','parts':[{'functionCall':{'name':'create_draft','args':{'machine_id':'CNC-01','observation_id':'obs','priority':'high','recommendation':'Inspect.'}}}]}
            else: content={'role':'model','parts':[{'text':'Draft ready.'}]}
            return {'candidates':[{'content':content,'finishReason':'STOP'}]}
        result=Agent(self.config(),transport=wire).run('Assess CNC-01')
        self.assertEqual(result['status'],'completed')
        self.assertEqual(histories[1][1],signed)
        self.assertEqual(histories[1][2]['parts'][0]['functionResponse']['id'],'call-1')
    def test_unknown_tool_no_execution(self):
        calls=[]
        a=Agent(self.config(),transport=lambda *args:calls.append(args) or {})
        result=a.execute({'name':'execute_shell','args':{'command':'nope'}})
        self.assertEqual(result['functionResponse']['response']['error'],'unknown_tool')
        self.assertTrue(all(x[0].endswith('/events') for x in calls))
    def test_audit_unavailable_stops_before_action(self):
        calls=[]
        def down(url,*args):
            calls.append(url);raise Failure(503,'audit_unavailable')
        a=Agent(self.config(),transport=down)
        with self.assertRaises(Failure): a.execute({'name':'read_telemetry','args':{'machine_id':'CNC-01'}})
        self.assertEqual(len(calls),1)
    def test_model_failure_no_fallback(self):
        def down(*args):raise Failure(429,'quota')
        with self.assertRaises(Failure): Agent(self.config(),transport=down).run('Assess')
    def test_text_only_is_incomplete(self):
        def wire(url,*args):
            return {'candidates':[{'content':{'role':'model','parts':[{'text':'All done.'}]}}]} if url.endswith('/infer') else {}
        self.assertEqual(Agent(self.config(),transport=wire).run('Assess')['status'],'incomplete')
    def test_truncation_not_success(self):
        with self.assertRaises(Failure):
            Agent(self.config(),transport=lambda *a:{'candidates':[{'content':{'parts':[{'text':'partial'}]},'finishReason':'MAX_TOKENS'}]}).run('Assess')
    def test_tool_budget(self):
        def wire(url,*args):
            if url.endswith('/infer'): return {'candidates':[{'content':{'role':'model','parts':[{'functionCall':{'name':'x','args':{}}}]*4}}]}
            return {}
        with self.assertRaises(Failure) as e: Agent(self.config(),transport=wire).run('Assess')
        self.assertEqual(e.exception.reason,'tool_budget_exhausted')

if __name__=='__main__':unittest.main()
