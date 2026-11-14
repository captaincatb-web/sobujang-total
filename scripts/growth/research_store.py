"""Local SQLite research store. Never expose this trusted-operator API as a web API.

DB must live outside the repository. Source bytes, facts and reviews are append-only.
This is provenance/integrity plumbing, not user authentication or tamper-proof storage.
"""
from collections import Counter
import argparse
import datetime as dt
import hashlib
import json
import math
import sqlite3
import uuid
from pathlib import Path

import verified_release as V

REPO = Path(__file__).resolve().parents[2]
SCHEMA = '''
CREATE TABLE IF NOT EXISTS entity (
 id TEXT PRIMARY KEY, legal_name TEXT NOT NULL, country TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS identifier (
 namespace TEXT NOT NULL, value TEXT NOT NULL, entity_id TEXT NOT NULL REFERENCES entity(id),
 PRIMARY KEY(namespace,value)
);
CREATE TABLE IF NOT EXISTS population (
 id TEXT PRIMARY KEY, label TEXT NOT NULL, version TEXT NOT NULL,
 UNIQUE(label,version)
);
CREATE TABLE IF NOT EXISTS membership (
 population_id TEXT NOT NULL REFERENCES population(id), entity_id TEXT NOT NULL REFERENCES entity(id),
 status TEXT NOT NULL CHECK(status IN ('included','hold','excluded')), reason TEXT NOT NULL,
 PRIMARY KEY(population_id,entity_id)
);
CREATE TABLE IF NOT EXISTS document (
 id TEXT PRIMARY KEY, url TEXT NOT NULL, sha256 TEXT NOT NULL, retrieved_at TEXT NOT NULL,
 body BLOB NOT NULL, UNIQUE(url,sha256)
);
CREATE TABLE IF NOT EXISTS entity_relation (
 id TEXT PRIMARY KEY, parent_id TEXT NOT NULL REFERENCES entity(id),
 child_id TEXT NOT NULL REFERENCES entity(id), kind TEXT NOT NULL CHECK(kind IN ('subsidiary','branch')),
 document_id TEXT NOT NULL REFERENCES document(id), source_ref TEXT NOT NULL,
 CHECK(parent_id <> child_id), UNIQUE(parent_id,child_id,kind,document_id)
);
CREATE TABLE IF NOT EXISTS site (
 id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entity(id), name TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('headquarters','factory','research','service','sales')),
 country TEXT NOT NULL, address_raw TEXT NOT NULL, address_normalized TEXT,
 latitude REAL, longitude REAL, precision TEXT,
 document_id TEXT NOT NULL REFERENCES document(id), source_ref TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status = 'unverified'),
 CHECK((latitude IS NULL AND longitude IS NULL) OR
       (latitude IS NOT NULL AND longitude IS NOT NULL AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180))
);
CREATE TABLE IF NOT EXISTS fact (
 id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entity(id),
 reporting_entity_id TEXT NOT NULL REFERENCES entity(id), document_id TEXT NOT NULL REFERENCES document(id),
 payload TEXT NOT NULL, sha256 TEXT NOT NULL, supersedes TEXT REFERENCES fact(id),
 created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_successor ON fact(supersedes) WHERE supersedes IS NOT NULL;
CREATE TABLE IF NOT EXISTS review (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, fact_id TEXT NOT NULL REFERENCES fact(id),
 fact_sha256 TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('approved','rejected','revoked')),
 reviewer TEXT NOT NULL, reason TEXT NOT NULL, reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS release (
 id TEXT PRIMARY KEY, manifest TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS release_item (
 release_id TEXT NOT NULL REFERENCES release(id), fact_id TEXT NOT NULL REFERENCES fact(id),
 review_seq INTEGER NOT NULL REFERENCES review(seq), PRIMARY KEY(release_id,fact_id)
);
CREATE TABLE IF NOT EXISTS audit_event (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, object_id TEXT NOT NULL,
 actor TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
);
'''
TABLES = ('entity','identifier','population','membership','document','entity_relation','site','fact','review','release','release_item','audit_event')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + ' must be nonempty text')
    return value


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class ResearchStore:
    def __init__(self, path):
        path = Path(path).expanduser().resolve()
        if path == REPO or REPO in path.parents:
            raise ValueError('Research database must be outside the public repository')
        if not path.parent.is_dir():
            raise ValueError('Create a private parent directory before initializing the database')
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise ValueError('Unsupported schema version')
        if version == 0:
            # One transaction: a failed migration cannot leave a partial version.
            triggers = ''.join(f'CREATE TRIGGER IF NOT EXISTS immutable_{t}_{op} BEFORE {op.upper()} ON {t} BEGIN SELECT RAISE(ABORT, "append-only table"); END;' for t in TABLES for op in ('update','delete'))
            try:
                self.db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA + triggers + '\nPRAGMA user_version=1; COMMIT;')
            except Exception:
                self.db.rollback(); self.db.close(); raise
        try:
            path.chmod(0o600)
        except OSError:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _audit(self, action, object_id, actor, detail=None):
        self.db.execute('INSERT INTO audit_event(action,object_id,actor,detail,created_at) VALUES(?,?,?,?,?)',
                        (action, object_id, text(actor,'actor'), encode(detail or {}), now()))

    def add_entity(self, legal_name, country, actor):
        text(legal_name,'legal_name'); self._country(country)
        eid = 'ent_' + uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO entity VALUES(?,?,?,?)', (eid, legal_name, country, now()))
            self._audit('entity.created', eid, actor)
        return eid

    @staticmethod
    def _country(country):
        if not isinstance(country,str) or len(country) != 2 or not country.isascii() or not country.isalpha() or not country.isupper():
            raise ValueError('Country must be a two-letter uppercase code')

    def add_identifier(self, entity_id, namespace, value, actor):
        text(namespace,'namespace'); text(value,'value')
        with self.db:
            self.db.execute('INSERT INTO identifier VALUES(?,?,?)', (namespace,value,entity_id))
            self._audit('identifier.created',entity_id,actor,{'namespace':namespace})

    def add_population(self, label, version, actor):
        text(label,'label'); text(version,'version'); pid='pop_'+uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO population VALUES(?,?,?)',(pid,label,version))
            self._audit('population.created',pid,actor)
        return pid

    def add_membership(self, population_id, entity_id, status, reason, actor):
        text(reason,'reason')
        with self.db:
            self.db.execute('INSERT INTO membership VALUES(?,?,?,?)',(population_id,entity_id,status,reason))
            self._audit('membership.created',entity_id,actor,{'population_id':population_id,'status':status})

    def add_document(self, url, body, retrieved_at, actor, official_hosts):
        if not V.source_url(url,official_hosts) or not V.timestamp(retrieved_at):
            raise ValueError('Invalid source URL or timestamp')
        if not isinstance(body,bytes) or not body:
            raise ValueError('Nonempty original document bytes required')
        did='doc_'+uuid.uuid4().hex; sha=hashlib.sha256(body).hexdigest()
        with self.db:
            self.db.execute('INSERT INTO document VALUES(?,?,?,?,?)',(did,url,sha,retrieved_at,body))
            self._audit('document.created',did,actor,{'sha256':sha})
        return did

    def add_relation(self, parent_id, child_id, kind, document_id, source_ref, actor):
        text(source_ref,'source_ref'); rid='rel_'+uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO entity_relation VALUES(?,?,?,?,?,?)',(rid,parent_id,child_id,kind,document_id,source_ref))
            self._audit('relation.created',rid,actor)
        return rid

    def add_site(self, entity_id, name, kind, country, address_raw, document_id, source_ref, actor,
                 address_normalized=None, latitude=None, longitude=None, precision=None):
        for key,val in (('name',name),('address_raw',address_raw),('source_ref',source_ref)):
            text(val,key)
        self._country(country)
        if (latitude is None) != (longitude is None):
            raise ValueError('Both coordinates or neither are required')
        if latitude is not None:
            if any(type(v) not in (float,int) or not math.isfinite(v) for v in (latitude,longitude)) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise ValueError('Invalid WGS84 coordinate')
            if precision not in ('building','street','city','region'):
                raise ValueError('Coordinate precision required')
        elif precision is not None:
            raise ValueError('Precision without coordinates')
        sid='site_'+uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO site VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (sid,entity_id,name,kind,country,address_raw,address_normalized,latitude,longitude,precision,document_id,source_ref,'unverified'))
            self._audit('site.created',sid,actor)
        return sid

    def add_fact(self, fact, actor, supersedes=None):
        # Caller cannot assign verified state. Version IDs are stable per snapshot.
        f=json.loads(encode(fact)); f['verification_status']='unverified'
        for k in ('fact_id','entity_id','reporting_entity_id','document_id'):
            text(f.get(k),k)
        self._check_document(f)
        if supersedes:
            old=self.db.execute('SELECT payload FROM fact WHERE id=?',(supersedes,)).fetchone()
            if not old:
                raise ValueError('Unknown predecessor')
            old=json.loads(old['payload'])
            for k in ('entity_id','reporting_entity_id','metric','period_start','period_end','scope','currency'):
                if old.get(k) != f.get(k):
                    raise ValueError('Revision must describe the same fact identity')
        with self.db:
            self.db.execute('INSERT INTO fact VALUES(?,?,?,?,?,?,?,?)',
                            (f['fact_id'],f['entity_id'],f['reporting_entity_id'],f['document_id'],encode(f),V.digest(f),supersedes,now()))
            self._audit('fact.created',f['fact_id'],actor,{'supersedes':supersedes})
        return f['fact_id']

    def _check_document(self,f):
        d=self.db.execute('SELECT * FROM document WHERE id=?',(f.get('document_id'),)).fetchone()
        if not d or hashlib.sha256(d['body']).hexdigest() != d['sha256']:
            raise ValueError('Missing or damaged original document')
        if (f.get('document_sha256'),f.get('source_url'),f.get('retrieved_at')) != (d['sha256'],d['url'],d['retrieved_at']):
            raise ValueError('Fact evidence does not match stored original')

    def _fact(self, fid):
        row=self.db.execute('SELECT * FROM fact WHERE id=?',(fid,)).fetchone()
        if not row:
            raise ValueError('Unknown fact')
        f=json.loads(row['payload'])
        if V.digest(f) != row['sha256']:
            raise ValueError('Fact content hash mismatch')
        self._check_document(f)
        return f

    def review_fact(self, fid, status, reviewer, reason, official_hosts):
        text(reviewer,'reviewer'); text(reason,'reason')
        if status not in ('approved','rejected','revoked'):
            raise ValueError('Invalid review status')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            f=self._fact(fid)
            if status == 'approved' and self.db.execute('SELECT 1 FROM fact WHERE supersedes=?',(fid,)).fetchone():
                raise ValueError('Superseded fact cannot be approved')
            f['verification_status']='source_verified'
            if status == 'approved':
                issues=V.validate(f,official_hosts)
                if issues:
                    raise V.ReleaseBlocked(Counter(issues))
            cur=self.db.execute('INSERT INTO review(fact_id,fact_sha256,status,reviewer,reason,reviewed_at) VALUES(?,?,?,?,?,?)',
                                (fid,V.digest(f),status,reviewer,reason,now()))
            self._audit('fact.'+status,fid,reviewer,{'review_seq':cur.lastrowid})
        return cur.lastrowid

    def create_release(self, fact_ids, actor, official_hosts):
        if not isinstance(fact_ids,list) or not fact_ids or len(set(fact_ids)) != len(fact_ids):
            raise ValueError('Nonempty unique fact IDs required')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            facts,reviews,seqs=[],[],[]
            for fid in fact_ids:
                if self.db.execute('SELECT 1 FROM fact WHERE supersedes=?',(fid,)).fetchone():
                    raise ValueError('Superseded fact cannot be released')
                f=self._fact(fid); f['verification_status']='source_verified'; facts.append(f)
                row=self.db.execute('SELECT * FROM review WHERE fact_id=? ORDER BY seq DESC LIMIT 1',(fid,)).fetchone()
                if row:
                    reviews.append(dict(row)); seqs.append((fid,row['seq']))
            payload=V.build_release(facts,reviews,official_hosts)
            encoded=encode(payload); rid='release_'+uuid.uuid4().hex
            self.db.execute('INSERT INTO release VALUES(?,?,?,?)',(rid,encoded,hashlib.sha256(encoded.encode()).hexdigest(),now()))
            self.db.executemany('INSERT INTO release_item VALUES(?,?,?)',[(rid,fid,seq) for fid,seq in seqs])
            self._audit('release.created',rid,actor,{'fact_count':len(facts)})
        return rid,payload

    def summary(self):
        return {'schema_version':self.db.execute('PRAGMA user_version').fetchone()[0],
                'counts':{t:self.db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in TABLES}}


def main():
    p=argparse.ArgumentParser(description='Initialize/open a local private research DB and report counts only')
    p.add_argument('database',type=Path)
    args=p.parse_args()
    try:
        with ResearchStore(args.database) as store:
            print(encode(store.summary()))
    except (OSError,ValueError,sqlite3.Error):
        print(encode({'status':'blocked','reason':'invalid_database_or_schema'})); return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
