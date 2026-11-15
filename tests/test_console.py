import hashlib,json,sys,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/console'))
from service import ConsoleStore,ROOT,V
from server import make_server
from test_verified_release import fact

HOSTS=['filings.example.org'];URL='https://filings.example.org/report.pdf';BODY=b'SYNTHETIC TEST ONLY';TIME='2026-11-14T12:00:00Z'
class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db.sqlite3';self.s=ConsoleStore(self.path,HOSTS)
        self.eid=self.s.add_entity('Synthetic fixture','KR','tester');self.did=self.s.add_document(URL,BODY,TIME,'tester',HOSTS)
    def tearDown(self):self.s.close();self.tmp.cleanup()
    def add(self,**kw):
        f=fact(entity_id=self.eid,reporting_entity_id=self.eid,document_id=self.did,source_url=URL,document_sha256=hashlib.sha256(BODY).hexdigest(),retrieved_at=TIME,**kw)
        self.s.add_fact(f,'tester');return f['fact_id']
    def approve(self,fid):self.s.review_fact(fid,'approved','private-reviewer','private-note',HOSTS)
    def test_legacy_import_idempotent_separate_populations(self):
        batch=json.loads((ROOT/'data/public/legacy-master.json').read_text());self.assertEqual(self.s.import_master(batch)['inserted'],189)
        self.assertEqual(self.s.import_master(batch)['inserted'],0)
        companies=self.s.snapshot()['companies'];self.assertEqual(sum(c['meta'].get('population')=='core' for c in companies),160)
        self.assertEqual(sum(c['meta'].get('population')=='managed' for c in companies),29)
    def test_failed_master_batch_is_atomic(self):
        before=self.s.summary();batch={'source_url':URL,'companies':[{'name':'A','legacy_code':'1'},{'name':'B','legacy_code':''}]}
        with self.assertRaises(ValueError):self.s.import_master(batch)
        self.assertEqual(before,self.s.summary())
    def test_public_projection_no_internal_fields(self):
        fid=self.add(private_note='secret-value');self.approve(fid);self.s.add_identifier(self.eid,'INTERNAL','private-id','tester')
        self.s.metadata(self.eid,dict(classification_status='candidate',note='private-classification'),'tester')
        snap=self.s.snapshot(False);text=json.dumps(snap)
        for secret in ['secret-value','private-reviewer','private-note','private-id','private-classification']:self.assertNotIn(secret,text)
        self.assertEqual(len(snap['facts']),1);self.assertEqual(snap['events'],[])
    def test_comparison_hold_survives_public_projection(self):
        fid=self.add(comparison_eligible=False,metric_basis='issuer_defined');self.approve(fid)
        payload=self.s.snapshot(False)['facts'][0]['payload']
        self.assertIs(payload['comparison_eligible'],False)
        self.assertEqual(payload['metric_basis'],'issuer_defined')
        release=self.s.export_current([fid],'tester')
        self.assertIn('issuer_defined',json.dumps(release))
    def test_invalid_comparison_metadata_blocks_approval(self):
        fid=self.add(comparison_eligible='false')
        with self.assertRaises(ValueError):self.approve(fid)
    def test_public_projection_hides_pending_and_revoked(self):
        fid=self.add();self.assertEqual(self.s.snapshot(False)['facts'],[]);self.approve(fid)
        self.s.review_fact(fid,'revoked','tester','correction',HOSTS);self.assertEqual(self.s.snapshot(False)['facts'],[])
    def test_release_rechecks_approval_and_hides_identifiers(self):
        fid=self.add(private_note='secret');self.approve(fid);p=self.s.export_current([fid],'tester')
        self.assertEqual(len(p['entities']),1);self.assertNotIn('secret',json.dumps(p));self.assertNotIn(self.eid,json.dumps(p))
        self.s.review_fact(fid,'revoked','tester','correction',HOSTS)
        with self.assertRaises(V.ReleaseBlocked):self.s.export_current([fid],'tester')
    def test_incomplete_candidate_does_not_crash_snapshot(self):
        self.s.action('fact',{'fact':{'entity_id':self.eid,'document_id':self.did}},'tester')
        f=self.s.snapshot()['facts'][0];self.assertFalse(f['verified']);self.assertTrue(f['issues'])
    def test_site_precision_and_revocation(self):
        city=self.s.add_site(self.eid,'Synthetic city','factory','KR','fixture',self.did,'p1','tester',latitude=35,longitude=127,precision='city')
        with self.assertRaises(ValueError):self.s.review_site(city,'approved','checked','tester')
        exact=self.s.add_site(self.eid,'Synthetic building','factory','KR','fixture',self.did,'p1','tester',latitude=35,longitude=127,precision='building')
        self.s.review_site(exact,'approved','checked','tester');self.assertEqual(len(self.s.snapshot(False)['sites']),1)
        self.s.review_site(exact,'revoked','changed','tester');self.assertEqual(self.s.snapshot(False)['sites'],[])
    def test_classification_requires_allowed_source(self):
        with self.assertRaises(ValueError):self.s.metadata(self.eid,dict(classification_status='verified',source_url='javascript:alert(1)',source_ref='p1'),'tester')
    def test_parent_financials_cannot_replace_subsidiary(self):
        other=self.s.add_entity('Synthetic parent','US','tester')
        f=fact(entity_id=self.eid,reporting_entity_id=other,document_id=self.did,source_url=URL,document_sha256=hashlib.sha256(BODY).hexdigest(),retrieved_at=TIME)
        with self.assertRaises(ValueError):self.s.add_fact(f,'tester')
        self.assertEqual(self.s.summary()['counts']['fact'],0)
    def test_restart_preserves_append_only_data(self):
        fid=self.add();self.approve(fid)
        with ConsoleStore(self.path,HOSTS) as other:self.assertTrue(other.snapshot()['facts'][0]['verified'])

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db.sqlite3'
        with ConsoleStore(self.path):pass
        self.server=make_server(self.path,0);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def request(self,path,headers=None,data=None):
        req=urllib.request.Request(self.url+path,headers=headers or {},data=json.dumps(data).encode() if data is not None else None)
        try:
            with urllib.request.urlopen(req) as r:return r.status,r.headers,r.read()
        except urllib.error.HTTPError as e:return e.code,e.headers,e.read()
    def auth(self):return {'Authorization':'Bearer '+self.server.token,'Content-Type':'application/json'}
    def test_auth_and_cross_origin(self):
        self.assertEqual(self.request('/api/snapshot')[0],401)
        self.assertEqual(self.request('/api/snapshot',self.auth())[0],200)
        self.assertEqual(self.request('/api/snapshot',{**self.auth(),'Origin':'https://evil.example'})[0],401)
        self.assertEqual(self.request('/api/snapshot',{**self.auth(),'Host':'evil.example'})[0],401)
    def test_write_then_read_and_invalid_input(self):
        self.assertEqual(self.request('/api/entity',self.auth(),{'name':'Synthetic HTTP','country':'KR'})[0],200)
        status,headers,body=self.request('/api/snapshot',self.auth());self.assertEqual(len(json.loads(body)['companies']),1)
        self.assertIn("script-src 'self'",headers['Content-Security-Policy'])
        self.assertEqual(self.request('/api/entity',self.auth(),{})[0],400)
    def test_private_paths_not_served(self):
        for p in ['/../README.md','/snapshot.json','/data/public/legacy-master.json','/.git/config']:
            self.assertEqual(self.request(p)[0],404)
    def test_preview_is_readonly(self):
        self.server.preview=True
        self.assertEqual(self.request('/api/entity',{}, {'name':'x'})[0],403)
        self.assertEqual(json.loads(self.request('/api/snapshot')[2])['mode'],'preview')
    def test_original_bytes_download_not_html(self):
        with ConsoleStore(self.path,HOSTS) as s:did=s.add_document(URL,b'<script>evil()</script>',TIME,'tester',HOSTS)
        status,headers,body=self.request('/api/document?id='+did,self.auth())
        self.assertEqual(status,200);self.assertEqual(headers['Content-Type'],'application/octet-stream')
        self.assertEqual(body,b'<script>evil()</script>')


class LegacyTests(unittest.TestCase):
    setUp=ConsoleTests.setUp
    tearDown=ConsoleTests.tearDown
    def test_legacy_unverified_preserves_bytes_and_no_duplicate_import(self):
        import legacy_compare as L
        folder=Path(self.tmp.name)/'input';folder.mkdir()
        docs={'pair-roster.json':{'groups':[{'g':'fixture','items':[{'i':'fixture','dom':[],'glo':[{'n':'Fixture','p':{'n':'Parent'}}]}]}]},'growth-companies.json':{'unit':'억 원','years':[2023,2024,2025],'modes':[{'id':'blend','rows':[{'n':'Fixture','s':'연결','r':[1,2,3],'o':[0,1,2]}]}]},'pair-extra.json':{'unit':'억 원','rows':[]},'pair-parent-consolidated.json':{'years':[2023,2024,2025],'companies':[{'name':'Parent','currency':'JPY','unit':'백만','periods':['9 months','',''],'revenue':[1,2,None],'verification':['공식 원문 대조','','']}]}}
        for name,data in docs.items():(folder/name).write_text(json.dumps(data))
        self.assertEqual(L.import_files(self.s,folder)['inserted'],3)
        self.assertEqual(L.import_files(self.s,folder)['inserted'],0)
        rows=L.inventory(self.s,True);self.assertTrue(all(r['status']=='legacy_unverified' for r in rows));self.assertEqual(self.s.summary()['counts']['fact'],0)
        public=L.inventory(self.s,False);self.assertTrue(all('original' not in r for r in public))
        self.assertEqual(next(r for r in rows if r['kind']=='native_reference')['original']['revenue'][2],None)
        self.assertEqual(next(r for r in rows if r['kind']=='converted')['currency'],'KRW')
        row=self.s.db.execute('SELECT * FROM legacy_source LIMIT 1').fetchone();self.assertEqual(hashlib.sha256(row['body']).hexdigest(),row['sha256'])
    def test_comparison_requires_six_same_basis_facts(self):
        from comparison import panels
        rows=[]
        for y in (2023,2024,2025):
            for m in ('revenue','operating_income'):
                p=fact(fiscal_end_year=y,metric=m,period_start=f'{y}-01-01',period_end=f'{y}-12-31',value_native=str((y-2022)*100))
                rows.append({'entity_id':'test','verified':True,'payload':p})
        result=panels(rows);self.assertEqual(result[0]['series']['revenue']['yoy_percent'],[None,'100.00','50.00'])
        self.assertEqual(panels(rows[:-1]),[])
        rows[0]['payload']['currency']='USD';self.assertEqual(panels(rows),[])
    def test_source_adapter_blocks_changed_pdf(self):
        from import_asml import extract
        p=Path(self.tmp.name)/'x.pdf';p.write_bytes(b'not a real pdf')
        contract=json.loads((ROOT/'data/public/asml-source-contract.json').read_text())
        with self.assertRaises(ValueError):extract(p,contract)

if __name__=='__main__':unittest.main()
