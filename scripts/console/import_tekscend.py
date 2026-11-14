"""Exact-document EDINET adapter. Source checks never imply deployment approval."""
import argparse, hashlib, json, re, subprocess
from pathlib import Path
from decimal import Decimal
from service import ConsoleStore, ROOT, R


def check_page(text, contract):
    compact=re.sub(r'\s+','',text)
    for token in ('E40985',contract['table'],'単位：百万円'):
        if token not in compact:raise ValueError('Entity, table or unit mismatch')
    for year in contract['years']:
        for token in (f'{year-1}年4月1日',f'{year}年3月31日'):
            if token not in compact:raise ValueError('Fiscal period mismatch')
    for row in contract['rows'].values():
        lines=[line for line in text.splitlines() if re.match(r'^\s*'+re.escape(row['label'])+r'\s',line)]
        if len(lines)!=1:raise ValueError('Missing or ambiguous source row')
        # An optional note column (5,26) precedes revenue; take exactly the final
        # three whitespace-separated cells, never a substring within a number.
        cells=lines[0].split()[-3:]
        if [s.replace(',','') for s in cells]!=row['values']:
            raise ValueError('Source values/column order mismatch')


def extract(pdf, contract):
    body=Path(pdf).read_bytes()
    if hashlib.sha256(body).hexdigest()!=contract['document_sha256']:
        raise ValueError('Source PDF hash differs from checked contract')
    def page(n):
        return subprocess.run(['pdftotext','-f',str(n),'-l',str(n),'-layout',str(Path(pdf).resolve()),'-'],check=True,capture_output=True,text=True,timeout=60).stdout
    check_page(page(contract['page']),contract)
    basis=re.sub(r'\s+','',page(159))
    for token in ('IFRS','2022年4月1日','2025年3月31日','初めて適用'):
        if token not in basis:raise ValueError('IFRS transition basis mismatch')
    return body


def ingest(store,pdf,approve=False):
    c=json.loads((ROOT/'data/public/tekscend-source-contract.json').read_text())
    body=extract(pdf,c)
    found=store.db.execute("SELECT entity_id FROM identifier WHERE namespace='EDINET' AND value='E40985'").fetchone()
    eid=found['entity_id'] if found else store.add_entity(c['entity'],'JP','curated-edinet-import')
    if not found:
        store.add_identifier(eid,'EDINET','E40985','curated-edinet-import')
        store.metadata(eid,dict(category='소재',market='미확인',population='new',process='포토',business_type='해외 본사',source_url=c['source_url'],source_ref=c['verification_note'],classification_status='candidate'),'curated-edinet-import')
    found=store.db.execute('SELECT id FROM document WHERE url=? AND sha256=?',(c['source_url'],c['document_sha256'])).fetchone()
    did=found['id'] if found else store.add_document(c['source_url'],body,R.now(),'curated-edinet-import',store.hosts)
    ids=[]
    for metric,row in c['rows'].items():
        for year,value in zip(c['years'],row['values']):
            fid=f'tekscend-ifrs-{year}-{metric}-{c["document_sha256"][:12]}';ids.append(fid)
            if store.db.execute('SELECT 1 FROM fact WHERE id=?',(fid,)).fetchone():continue
            f={k:c[k] for k in ('scope','currency','accounting_standard','raw_unit','unit_multiplier')}
            f.update(fact_id=fid,entity_id=eid,reporting_entity_id=eid,document_id=did,metric=metric,fiscal_end_year=year,fiscal_year_label=f'Year ended March 31, {year}',period_start=f'{year-1}-04-01',period_end=f'{year}-03-31',raw_value=value,value_native=str(Decimal(value)*Decimal(c['unit_multiplier'])),source_locator={'type':'pdf','page':c['page'],'table':c['table'],'row':row['label'],'column':f'{year}年3月31日'})
            store.action('fact',{'fact':f},'curated-edinet-import')
            if approve:store.review_fact(fid,'approved','curated-source-operator',c['verification_note'],store.hosts)
    return {'entity_id':eid,'fact_ids':ids,'approval_requested':approve}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--database',required=True,type=Path);p.add_argument('--pdf',required=True,type=Path);p.add_argument('--approve-source-checked',action='store_true')
    a=p.parse_args()
    with ConsoleStore(a.database) as s:print(json.dumps(ingest(s,a.pdf,a.approve_source_checked)))
