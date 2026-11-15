"""Refresh approved committed snapshot only; no automatic source approval."""
import datetime,hashlib,json,urllib.request
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1]
SOURCE='https://raw.githubusercontent.com/captaincatb-web/sobujang-total/codex/primary-source-verification/console/snapshot.json'
HOSTS={'ourbrand.asml.com','www.asml.com','disclosure2dl.edinet-fsa.go.jp','www.sec.gov','data.sec.gov','dart.fss.or.kr','opendart.fss.or.kr','disclosure2.edinet-fsa.go.jp'}
def validate(data):
    if data.get('mode')!='preview' or data.get('events') or data.get('relations'):raise ValueError('Private or unsupported snapshot')
    if any('original' in r for r in data.get('legacy',[])):raise ValueError('Unverified legacy payload')
    ids={c['id'] for c in data['companies']}
    for f in data['facts']:
        p=f['payload'];u=urlsplit(p['source_url'])
        if f.get('verified') is not True or f['status']!='approved' or f['entity_id'] not in ids:raise ValueError('Unapproved fact')
        if u.scheme!='https' or u.hostname not in HOSTS or u.username or u.password:raise ValueError('Source host not allowed')
        if Decimal(p['raw_value'])*Decimal(p['unit_multiplier'])!=Decimal(p['value_native']):raise ValueError('Unit mismatch')
        if p['fiscal_end_year'] not in [2023,2024,2025] or p['reported_or_derived']!='reported':raise ValueError('Unsupported fact')
        if len(p['document_sha256'])!=64 or not p.get('source_locator'):raise ValueError('Missing evidence')
        if any(k in f for k in ['review','private_note']) or any(k in p for k in ['private_note','reviewer']):raise ValueError('Private fields')
    for s in data['sites']:
        if s.get('status')!='approved':raise ValueError('Unapproved site')
    return data

def main():
    with urllib.request.urlopen(SOURCE,timeout=60) as r:body=r.read(10_000_001)
    if len(body)>10_000_000:raise ValueError('Snapshot too large')
    data=validate(json.loads(body));target=ROOT/'snapshot.json'
    old=json.loads(target.read_text());changed=data!=old
    if changed:
        temp=target.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');temp.replace(target)
    status={'last_success_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_url':SOURCE,'source_sha256':hashlib.sha256(body).hexdigest(),'data_changed':changed,'schedule_kst':'매일 오전 7시','note':'승인 스냅샷 동기화 · 공시 자동 검증 아님'}
    (ROOT/'update-status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'updated':changed,'facts':len(data['facts'])}))
if __name__=='__main__':main()
