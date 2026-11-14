import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/growth'))
import research_store as R
import verified_release as V
from test_verified_release import fact

HOSTS=['filings.example.org']
URL='https://filings.example.org/report.pdf'
TIME='2026-11-14T10:00:00Z'
BODY=b'SYNTHETIC TEST DOCUMENT ONLY'


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'research.sqlite3'
        self.store=R.ResearchStore(self.path)
        self.entity=self.store.add_entity('Synthetic fixture','JP','operator')
        self.doc=self.store.add_document(URL,BODY,TIME,'operator',HOSTS)

    def tearDown(self):
        self.store.close(); self.tmp.cleanup()

    def new_fact(self,**changes):
        return fact(entity_id=self.entity,reporting_entity_id=self.entity,document_id=self.doc,
                    document_sha256=hashlib.sha256(BODY).hexdigest(),source_url=URL,retrieved_at=TIME,**changes)

    def add(self,**changes):
        f=self.new_fact(**changes); self.store.add_fact(f,'operator'); return f['fact_id']

    def approve(self,fid):
        return self.store.review_fact(fid,'approved','reviewer','Compared original table',HOSTS)

    def test_end_to_end_approval_and_release(self):
        fid=self.add()
        raw=json.loads(self.store.db.execute('SELECT payload FROM fact').fetchone()[0])
        self.assertEqual(raw['verification_status'],'unverified')
        with self.assertRaises(V.ReleaseBlocked): self.store.create_release([fid],'operator',HOSTS)
        self.approve(fid)
        rid,payload=self.store.create_release([fid],'operator',HOSTS)
        self.assertTrue(rid.startswith('release_'))
        self.assertEqual(payload['facts'][0]['value_native'],'12340000')
        self.assertEqual(self.store.summary()['counts']['release_item'],1)
        self.assertNotIn(self.entity,json.dumps(payload))

    def test_source_bytes_are_preserved_and_hash_checked(self):
        row=self.store.db.execute('SELECT * FROM document').fetchone()
        self.assertEqual(row['body'],BODY)
        with self.assertRaises(ValueError):
            self.store.add_fact(self.new_fact(source_locator={}) | {'document_sha256':'b'*64},'operator')
        self.assertEqual(self.store.summary()['counts']['fact'],0)

    def test_duplicate_document_and_identifier(self):
        with self.assertRaises(sqlite3.IntegrityError): self.store.add_document(URL,BODY,TIME,'operator',HOSTS)
        self.store.add_identifier(self.entity,'KRX','0017J0','operator')
        other=self.store.add_entity('Different fixture','KR','operator')
        with self.assertRaises(sqlite3.IntegrityError): self.store.add_identifier(other,'KRX','0017J0','operator')

    def test_same_name_does_not_merge(self):
        another=self.store.add_entity('Synthetic fixture','JP','operator')
        self.assertNotEqual(another,self.entity)

    def test_populations_keep_distinct_memberships(self):
        a=self.store.add_population('core','v1','operator')
        b=self.store.add_population('financial','v1','operator')
        self.store.add_membership(a,self.entity,'included','fixture','operator')
        self.store.add_membership(b,self.entity,'hold','needs evidence','operator')
        self.assertEqual(self.store.summary()['counts']['membership'],2)

    def test_foreign_keys_and_atomic_audit(self):
        before=self.store.summary()
        with self.assertRaises(sqlite3.IntegrityError): self.store.add_identifier('missing','DART','001','operator')
        self.assertEqual(self.store.summary(),before)
        with self.assertRaises(ValueError): self.store.add_entity('No actor','JP','')
        self.assertEqual(self.store.summary(),before)

    def test_immutable_source_fact_review_and_audit(self):
        fid=self.add(); self.approve(fid)
        for table in ('document','fact','review','audit_event'):
            with self.subTest(table=table):
                with self.assertRaises(sqlite3.IntegrityError):
                    with self.store.db: self.store.db.execute('DELETE FROM '+table)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.db: self.store.db.execute("UPDATE fact SET sha256='x'")

    def test_revoke_blocks_new_release_preserves_history(self):
        fid=self.add(); self.approve(fid)
        self.store.create_release([fid],'operator',HOSTS)
        self.store.review_fact(fid,'revoked','reviewer','Source correction discovered',HOSTS)
        with self.assertRaises(V.ReleaseBlocked): self.store.create_release([fid],'operator',HOSTS)
        self.assertEqual(self.store.summary()['counts']['review'],2)
        self.assertEqual(self.store.summary()['counts']['release'],1)

    def test_revision_requires_own_approval(self):
        fid=self.add(); self.approve(fid)
        revised=self.new_fact(fact_id='revision-2',raw_value='12.35',value_native='12350000')
        self.store.add_fact(revised,'operator',supersedes=fid)
        with self.assertRaises(ValueError): self.store.create_release([fid],'operator',HOSTS)
        with self.assertRaises(ValueError): self.approve(fid)
        with self.assertRaises(V.ReleaseBlocked): self.store.create_release(['revision-2'],'operator',HOSTS)
        self.approve('revision-2')
        self.assertEqual(self.store.create_release(['revision-2'],'operator',HOSTS)[1]['facts'][0]['value_native'],'12350000')
        self.assertEqual(self.store.summary()['counts']['fact'],2)

    def test_revision_identity_cannot_change(self):
        fid=self.add()
        with self.assertRaises(ValueError): self.store.add_fact(self.new_fact(fact_id='bad-revision',currency='USD'),'operator',supersedes=fid)

    def test_bad_evidence_never_approved(self):
        fid=self.add(source_locator={})
        before=self.store.summary()
        with self.assertRaises(V.ReleaseBlocked): self.approve(fid)
        self.assertEqual(self.store.summary(),before)

    def test_batch_failure_does_not_create_partial_release(self):
        fid=self.add(); self.approve(fid)
        pending=self.add(fact_id='pending',metric='operating_income')
        before=self.store.summary()
        with self.assertRaises(V.ReleaseBlocked): self.store.create_release([fid,pending],'operator',HOSTS)
        self.assertEqual(self.store.summary(),before)

    def test_sites_separate_from_entities_no_guessed_coordinates(self):
        self.store.add_site(self.entity,'Fixture plant','factory','JP','unresolved address',self.doc,'p1','operator')
        self.store.add_site(self.entity,'Fixture lab','research','JP','fixture address',self.doc,'p2','operator',latitude=35.0,longitude=139.0,precision='city')
        self.assertEqual(self.store.summary()['counts']['entity'],1)
        self.assertEqual(self.store.summary()['counts']['site'],2)
        sites=self.store.db.execute('SELECT * FROM site').fetchall()
        self.assertIsNone(sites[0]['latitude'])
        self.assertTrue(all(s['status']=='unverified' for s in sites))
        with self.assertRaises(ValueError):
            self.store.add_site(self.entity,'bad','factory','JP','x',self.doc,'p1','operator',latitude=float('nan'),longitude=0,precision='building')

    def test_parent_child_relation_requires_evidence(self):
        child=self.store.add_entity('Fixture subsidiary','KR','operator')
        self.store.add_relation(self.entity,child,'subsidiary',self.doc,'p1','operator')
        with self.assertRaises(sqlite3.IntegrityError): self.store.add_relation(child,child,'subsidiary',self.doc,'p1','operator')

    def test_reopen_idempotent_schema(self):
        before=self.store.summary()
        with R.ResearchStore(self.path) as other:
            self.assertEqual(other.summary(),before)

    def test_repository_path_forbidden(self):
        path=R.REPO/'should-not-exist.sqlite3'
        with self.assertRaises(ValueError): R.ResearchStore(path)
        self.assertFalse(path.exists())

    def test_future_schema_rejected(self):
        other=Path(self.tmp.name)/'future.sqlite3'
        with sqlite3.connect(other) as db: db.execute('PRAGMA user_version=99')
        with self.assertRaises(ValueError): R.ResearchStore(other)

if __name__=='__main__': unittest.main()
