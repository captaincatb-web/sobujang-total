"""Import the existing comparison's derived data into an isolated review queue.

No primary-document fabrication, FX back-calculation, name-based entity merging,
or inherited approvals. Original bytes and JSON pointers remain traceable.
"""
import argparse,hashlib,json
from pathlib import Path

FILES=('pair-roster.json','growth-companies.json','pair-extra.json','pair-parent-consolidated.json')
HEAD='2884b108bec8fd321ea120513934019db72a7d8f'
BASE=f'https://github.com/captaincatb-web/Sangsaengnews/blob/{HEAD}/site/data/'
SCHEMA='''
CREATE TABLE IF NOT EXISTS legacy_source(sha256 TEXT PRIMARY KEY,url TEXT NOT NULL,body BLOB NOT NULL,imported_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS legacy_observation(id TEXT PRIMARY KEY,source_sha256 TEXT NOT NULL REFERENCES legacy_source(sha256),json_pointer TEXT NOT NULL,name TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS legacy_binding(seq INTEGER PRIMARY KEY AUTOINCREMENT,observation_id TEXT NOT NULL REFERENCES legacy_observation(id),entity_id TEXT NOT NULL REFERENCES entity(id),actor TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL);
'''

def initialize(db):
    db.executescript(SCHEMA)
    for t in ('legacy_source','legacy_observation','legacy_binding'):
        for op in ('UPDATE','DELETE'):
            db.execute(f'CREATE TRIGGER IF NOT EXISTS immutable_{t}_{op} BEFORE {op} ON {t} BEGIN SELECT RAISE(ABORT,"append-only table"); END')


def records(filename,data):
    if filename=='pair-roster.json':
        for gi,g in enumerate(data['groups']):
            for ii,item in enumerate(g['items']):
                for side in ('dom','glo'):
                    for ei,e in enumerate(item[side]):
                        yield f'/groups/{gi}/items/{ii}/{side}/{ei}',e['n'],'roster',dict(e,group=g['g'],item=item['i'],side=side)
    elif filename=='growth-companies.json':
        for mi,m in enumerate(data['modes']):
            for ri,r in enumerate(m['rows']):yield f'/modes/{mi}/rows/{ri}',r['n'],'converted',dict(r,mode=m['id'],display_unit=data['unit'],years=data['years'])
    elif filename=='pair-extra.json':
        for i,r in enumerate(data['rows']):yield f'/rows/{i}',r['n'],'converted',dict(r,display_unit=data['unit'],years=[2023,2024,2025])
    else:
        for i,r in enumerate(data['companies']):yield f'/companies/{i}',r['name'],'native_reference',dict(r,years=data['years'])


def import_files(store,directory,prefix=''):
    # Parse every file before writing; preserve mode duplicates instead of guessing identity.
    staged=[]
    for fn in FILES:
        body=(Path(directory)/(prefix+fn)).read_bytes();data=json.loads(body);sha=hashlib.sha256(body).hexdigest()
        staged.append((fn,body,sha,list(records(fn,data))))
    inserted=0
    with store.db:
        for fn,body,sha,rows in staged:
            if store.db.execute('SELECT 1 FROM legacy_source WHERE sha256=?',(sha,)).fetchone():continue
            store.db.execute('INSERT INTO legacy_source VALUES(?,?,?,?)',(sha,BASE+fn,body,store.clock()))
            for pointer,name,kind,payload in rows:
                oid='legacy_'+hashlib.sha256((sha+pointer).encode()).hexdigest()[:24]
                store.db.execute('INSERT INTO legacy_observation VALUES(?,?,?,?,?,?)',(oid,sha,pointer,name,kind,json.dumps(payload,ensure_ascii=False,allow_nan=False)));inserted+=1
        if inserted:store._audit('legacy.comparison_imported','comparison','legacy-import',{'observations':inserted,'source_commit':HEAD})
    return {'inserted':inserted}


def inventory(store,private=False):
    rows=[]
    for r in store.db.execute('SELECT o.*,s.url FROM legacy_observation o JOIN legacy_source s ON o.source_sha256=s.sha256'):
        p=json.loads(r['payload']);binding=store.db.execute('SELECT entity_id FROM legacy_binding WHERE observation_id=? ORDER BY seq DESC LIMIT 1',(r['id'],)).fetchone()
        out={k:r[k] for k in ('id','name','kind','json_pointer','source_sha256','url')}
        out.update(scope=p.get('s',p.get('scope','')),currency=p.get('currency','KRW' if r['kind']=='converted' else ''),unit=p.get('display_unit',p.get('unit','')),mode=p.get('mode',''),status='legacy_unverified',entity_id=binding['entity_id'] if binding else None)
        out['gaps']=['원문 바이트·해시','표 위치','회계기준 재확인']+(['원통화 값·환율 근거','회계기간'] if r['kind']=='converted' else [])
        if r['kind']=='roster':out['gaps']=['법인 식별·관계 확인']
        if private:out['original']=p
        rows.append(out)
    return rows


def main():
    from service import ConsoleStore
    p=argparse.ArgumentParser();p.add_argument('--database',type=Path,required=True);p.add_argument('--directory',type=Path,required=True);p.add_argument('--prefix',default='');args=p.parse_args()
    with ConsoleStore(args.database) as s:print(json.dumps(import_files(s,args.directory,args.prefix)))
if __name__=='__main__':main()
