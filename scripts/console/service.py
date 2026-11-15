"""Local console service; all mutations are trusted-operator actions, not public API."""
import base64, hashlib, json, sqlite3, sys, uuid
from pathlib import Path
from decimal import Decimal
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'growth'))
import research_store as R
import verified_release as V
import legacy_compare as L
from comparison import panels, comparison_results

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_HOSTS=['www.sec.gov','data.sec.gov','dart.fss.or.kr','opendart.fss.or.kr','disclosure2.edinet-fsa.go.jp','disclosure2dl.edinet-fsa.go.jp','ourbrand.asml.com','www.asml.com']
EXTRA='''
CREATE TABLE IF NOT EXISTS company_meta(seq INTEGER PRIMARY KEY AUTOINCREMENT,entity_id TEXT NOT NULL REFERENCES entity(id),payload TEXT NOT NULL,actor TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS site_review(seq INTEGER PRIMARY KEY AUTOINCREMENT,site_id TEXT NOT NULL REFERENCES site(id),status TEXT NOT NULL CHECK(status IN ('approved','revoked','rejected')),reviewer TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ingest_batch(id TEXT PRIMARY KEY,source TEXT NOT NULL,created_at TEXT NOT NULL);
'''

class ConsoleStore(R.ResearchStore):
    clock=staticmethod(R.now)
    def __init__(self,path,hosts=None):
        super().__init__(path); self.hosts=hosts or DEFAULT_HOSTS
        with self.db:
            self.db.executescript(EXTRA)
            L.initialize(self.db)
            for t in ('company_meta','site_review','ingest_batch'):
                for op in ('UPDATE','DELETE'):
                    self.db.execute(f'CREATE TRIGGER IF NOT EXISTS immutable_{t}_{op} BEFORE {op} ON {t} BEGIN SELECT RAISE(ABORT,"append-only table"); END')

    def add_fact(self,fact,actor,supersedes=None):
        if fact.get('entity_id') != fact.get('reporting_entity_id'):
            raise ValueError('본사 재무는 본사 법인에 등록하세요. 자회사 값으로 대체할 수 없습니다.')
        return super().add_fact(fact,actor,supersedes)

    def import_master(self,batch,actor='operator'):
        rows=batch['companies'];source=R.text(batch.get('source_url'),'source_url');bid=hashlib.sha256(R.encode(batch).encode()).hexdigest()
        if self.db.execute('SELECT 1 FROM ingest_batch WHERE id=?',(bid,)).fetchone():return {'inserted':0,'existing_batch':True}
        if not isinstance(rows,list) or len(rows)>10000:raise ValueError('최대 10,000개 기업을 반입할 수 있습니다.')
        inserted=0
        with self.db:
            for r in rows:
                name=R.text(r.get('name'),'name');code=R.text(r.get('legacy_code'),'legacy_code');country=r.get('country','KR');self._country(country)
                # The input declares its namespace; never join by company name.
                namespace=R.text(batch.get('namespace','legacy:KRX'),'namespace')
                old=self.db.execute('SELECT entity_id FROM identifier WHERE namespace=? AND value=?',(namespace,code)).fetchone()
                if old:eid=old['entity_id']
                else:
                    eid='ent_'+uuid.uuid4().hex
                    self.db.execute('INSERT INTO entity VALUES(?,?,?,?)',(eid,name,country,R.now()))
                    self.db.execute('INSERT INTO identifier VALUES(?,?,?)',(namespace,code,eid));inserted+=1
                meta={k:r.get(k,'') for k in ('market','category','population','legacy_group','process','business_type')}
                meta.update(source_url=source,source_ref='companies / '+code,classification_status='candidate')
                self.db.execute('INSERT INTO company_meta(entity_id,payload,actor,created_at) VALUES(?,?,?,?)',(eid,R.encode(meta),actor,R.now()))
            self.db.execute('INSERT INTO ingest_batch VALUES(?,?,?)',(bid,source,R.now()));self._audit('master.imported',bid,actor,{'inserted':inserted,'rows':len(rows)})
        return {'inserted':inserted,'existing_batch':False}

    def metadata(self,eid,meta,actor):
        if not self.db.execute('SELECT 1 FROM entity WHERE id=?',(eid,)).fetchone():raise ValueError('기업을 찾을 수 없습니다.')
        allowed=('market','category','population','process','business_type','source_url','source_ref','classification_status','note')
        m={k:meta.get(k,'') for k in allowed}
        if m['classification_status'] not in ('candidate','verified','hold','excluded'):raise ValueError('분류 상태를 확인하세요.')
        if m['classification_status']=='verified' and (not V.source_url(m['source_url'],self.hosts) or not m['source_ref']):raise ValueError('분류 확인에는 공식 원문 URL과 위치가 필요합니다.')
        with self.db:
            self.db.execute('INSERT INTO company_meta(entity_id,payload,actor,created_at) VALUES(?,?,?,?)',(eid,R.encode(m),actor,R.now()));self._audit('classification.updated',eid,actor)

    def review_site(self,sid,status,reason,actor):
        site=self.db.execute('SELECT * FROM site WHERE id=?',(sid,)).fetchone()
        if not site or status not in ('approved','revoked','rejected'):raise ValueError('사업장 또는 상태를 확인하세요.')
        R.text(reason,'reason')
        if status=='approved':
            doc=self.db.execute('SELECT * FROM document WHERE id=?',(site['document_id'],)).fetchone()
            if site['latitude'] is None or site['precision'] not in ('building','street') or not doc or not V.source_url(doc['url'],self.hosts) or hashlib.sha256(doc['body']).hexdigest()!=doc['sha256']:raise ValueError('정확한 좌표·정밀도·원문이 확인된 사업장만 지도 승인할 수 있습니다.')
        with self.db:
            self.db.execute('INSERT INTO site_review(site_id,status,reviewer,reason,created_at) VALUES(?,?,?,?,?)',(sid,status,actor,reason,R.now()));self._audit('site.'+status,sid,actor)

    def _facts(self):
        result=[]
        for r in self.db.execute('SELECT * FROM fact ORDER BY created_at DESC'):
            f=json.loads(r['payload']);rv=self.db.execute('SELECT * FROM review WHERE fact_id=? ORDER BY seq DESC LIMIT 1',(r['id'],)).fetchone()
            successor=self.db.execute('SELECT id FROM fact WHERE supersedes=?',(r['id'],)).fetchone()
            check=dict(f,verification_status='source_verified');issues=V.validate(check,self.hosts)
            status='superseded' if successor else rv['status'] if rv else 'pending'
            try:self._fact(r['id'])
            except ValueError:issues.append('document_mismatch')
            verified=status=='approved' and not issues and rv['fact_sha256']==V.digest(check)
            result.append({'id':r['id'],'entity_id':r['entity_id'],'payload':f,'status':status,'verified':verified,'issues':issues,'review':dict(rv) if rv else None,'supersedes':r['supersedes']})
        return result

    def snapshot(self,private=True):
        facts=self._facts();companies=[]
        for row in self.db.execute('SELECT * FROM entity ORDER BY legal_name'):
            c=dict(row);meta=self.db.execute('SELECT payload FROM company_meta WHERE entity_id=? ORDER BY seq DESC LIMIT 1',(row['id'],)).fetchone();c['meta']=json.loads(meta['payload']) if meta else {}
            c['identifiers']=[dict(x) for x in self.db.execute('SELECT namespace,value FROM identifier WHERE entity_id=?',(row['id'],))]
            cf=[f for f in facts if f['entity_id']==c['id']];c['verified_facts']=sum(f['verified'] for f in cf);c['pending_facts']=sum(not f['verified'] and f['status']!='superseded' for f in cf)
            c['coverage']={str(y):sum(f['verified'] and f['payload'].get('fiscal_end_year')==y for f in cf) for y in (2023,2024,2025)};companies.append(c)
        sites=[]
        for row in self.db.execute('SELECT * FROM site'):
            s=dict(row);rv=self.db.execute('SELECT * FROM site_review WHERE site_id=? ORDER BY seq DESC LIMIT 1',(s['id'],)).fetchone();s['status']=rv['status'] if rv else 'pending';sites.append(s)
        if not private:
            facts=[f for f in facts if f['verified']];sites=[s for s in sites if s['status']=='approved']
            # Explicit public projection: never serialize private payload/reviewer/notes.
            for c in companies:
                c['meta']={k:v for k,v in c['meta'].items() if k in ('market','category','population','process','business_type','source_url','source_ref','classification_status')}
                c['identifiers']=[i for i in c['identifiers'] if i['namespace'] in ('legacy:KRX','KRX','CIK')]
            for f in facts:
                p=f['payload'];loc=p['source_locator']
                f['payload']={**{k:p[k] for k in V.PUBLIC + V.OPTIONAL_PUBLIC if k in p},'source_locator':{k:loc[k] for k in ('type',)+V.LOCATORS[loc['type']]}}
                f.pop('review',None);f.pop('supersedes',None)
        return {'mode':'local' if private else 'preview','companies':companies,'facts':facts,'sites':sites,
                'documents':[dict(r) for r in self.db.execute('SELECT id,url,sha256,retrieved_at,length(body) AS bytes FROM document') if private or any(s['document_id']==r['id'] for s in sites) or any(f['payload']['document_sha256']==r['sha256'] for f in facts)],
                'relations':[dict(r) for r in self.db.execute('SELECT * FROM entity_relation')] if private else [],
                'events':[dict(r) for r in self.db.execute('SELECT * FROM audit_event ORDER BY seq DESC LIMIT 100')] if private else [],
                'legacy':L.inventory(self,private),'comparisons':panels(facts),'comparison_exclusions':comparison_results(facts)['excluded'],
                'counts':self.summary()['counts'] if private else {'entity':len(companies),'fact':len(facts),'site':len(sites)},'official_hosts':self.hosts,'generated_at':R.now()}

    def export_current(self,ids,actor):
        rid,payload=self.create_release(ids,actor,self.hosts)
        # Bind safe public entity UUIDs (not registration numbers) to facts.
        index={V.digest(dict(self._fact(fid),verification_status='source_verified')):self._fact(fid) for fid in ids}
        entities={}
        for f in payload['facts']:
            original=index[f['fact_sha256']];eid=original['reporting_entity_id'];pid='pub_'+hashlib.sha256(eid.encode()).hexdigest()[:24]
            e=self.db.execute('SELECT legal_name,country FROM entity WHERE id=?',(eid,)).fetchone();entities[pid]=dict(e);f['company_id']=pid
        return {'release_id':rid,'entities':entities,**payload}

    def action(self,action,data,actor='local-operator'):
        if action=='import_master':return self.import_master(data,actor)
        if action=='entity':
            return {'id':self.add_entity(data['name'],data['country'],actor)}
        if action=='metadata':self.metadata(data['entity_id'],data['meta'],actor);return {'ok':True}
        if action=='document':
            return {'id':self.add_document(data['url'],base64.b64decode(data['content_base64'],validate=True),data['retrieved_at'],actor,self.hosts)}
        if action=='fact':
            f=data['fact'];f['fact_id']=f.get('fact_id') or 'fact_'+uuid.uuid4().hex
            d=self.db.execute('SELECT * FROM document WHERE id=?',(f['document_id'],)).fetchone()
            if not d:raise ValueError('원문을 먼저 등록하세요.')
            f.update(document_sha256=d['sha256'],source_url=d['url'],retrieved_at=d['retrieved_at'])
            f.setdefault('reporting_entity_id',f['entity_id']);f.setdefault('reported_or_derived','reported');f['verification_status']='unverified'
            self.add_fact(f,actor,data.get('supersedes'));return {'id':f['fact_id']}
        if action=='review':return {'seq':self.review_fact(data['fact_id'],data['status'],actor,data['reason'],self.hosts)}
        if action=='site':return {'id':self.add_site(actor=actor,**data)}
        if action=='site_review':self.review_site(data['site_id'],data['status'],data['reason'],actor);return {'ok':True}
        if action=='relation':return {'id':self.add_relation(actor=actor,**data)}
        if action=='legacy_bind':
            R.text(data['reason'],'reason')
            with self.db:
                self.db.execute('INSERT INTO legacy_binding(observation_id,entity_id,actor,reason,created_at) VALUES(?,?,?,?,?)',(data['observation_id'],data['entity_id'],actor,data['reason'],R.now()))
                self._audit('legacy.entity_bound',data['observation_id'],actor)
            return {'ok':True}
        if action=='export':return self.export_current(data['fact_ids'],actor)
        raise ValueError('지원하지 않는 작업입니다.')
