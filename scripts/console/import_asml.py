"""Reproducible curated source adapter; no inferred values, no implicit approval.

Requires the exact official PDF and pdftotext. Download it from the contract URL
outside the repository. A changed document is blocked, not silently accepted.
"""
import argparse, hashlib, json, re, subprocess
from decimal import Decimal
from pathlib import Path
from service import ConsoleStore, ROOT, R


def extract(pdf,contract):
    body=Path(pdf).read_bytes()
    if hashlib.sha256(body).hexdigest()!=contract['document_sha256']:
        raise ValueError('Source PDF hash differs from visually checked contract')
    page=str(contract['page'])
    result=subprocess.run(['pdftotext','-f',page,'-l',page,'-layout',str(Path(pdf).resolve()),'-'],check=True,capture_output=True,text=True,timeout=60)
    text=result.stdout
    if contract['table'] not in text or not re.search(r'2023\s+2024\s+2025',text):
        raise ValueError('Table title/year columns do not match')
    if 'in millions' not in text or 'Year ended December 31' not in text:
        raise ValueError('Unit or fiscal period not found')
    for row in contract['rows'].values():
        lines=[line for line in text.splitlines() if re.match(r'^\s*'+re.escape(row['label'])+r'\s',line)]
        if len(lines)!=1:raise ValueError('Ambiguous/missing source row')
        values=re.findall(r'\d[\d,]*\.\d+',lines[0])
        if [v.replace(',','') for v in values]!=row['values']:raise ValueError('Source values differ')
    return body


def ingest(store,pdf,approve=False):
    contract=json.loads((ROOT/'data/public/asml-source-contract.json').read_text())
    body=extract(pdf,contract)
    entity=store.db.execute("SELECT entity_id FROM identifier WHERE namespace='CIK' AND value='0000937966'").fetchone()
    eid=entity['entity_id'] if entity else store.add_entity(contract['entity'],'NL','curated-source-import')
    if not entity:
        store.add_identifier(eid,'CIK','0000937966','curated-source-import')
        store.metadata(eid,dict(category='장비',market='NASDAQ / Euronext',population='new',process='포토',business_type='해외 본사',source_url=contract['source_url'],source_ref='Annual Report 2025',classification_status='candidate'),'curated-source-import')
    doc=store.db.execute('SELECT id FROM document WHERE url=? AND sha256=?',(contract['source_url'],contract['document_sha256'])).fetchone()
    did=doc['id'] if doc else store.add_document(contract['source_url'],body,R.now(),'curated-source-import',store.hosts)
    ids=[]
    for metric,row in contract['rows'].items():
        for year,value in zip(contract['years'],row['values']):
            fid=f'asml-usgaap-{year}-{metric}-{contract["document_sha256"][:12]}'
            ids.append(fid)
            if store.db.execute('SELECT 1 FROM fact WHERE id=?',(fid,)).fetchone():continue
            f={k:contract[k] for k in ('scope','currency','accounting_standard','raw_unit','unit_multiplier')}
            f.update(fact_id=fid,entity_id=eid,reporting_entity_id=eid,document_id=did,metric=metric,fiscal_end_year=year,fiscal_year_label=str(year),period_start=f'{year}-01-01',period_end=f'{year}-12-31',raw_value=value,value_native=str(Decimal(value)*Decimal(contract['unit_multiplier'])).split('.')[0],source_locator={'type':'pdf','page':contract['page'],'table':contract['table'],'row':row['label'],'column':str(year)})
            store.action('fact',{'fact':f},'curated-source-import')
            # Only newly imported rows can be approved here. Never undo a revocation.
            if approve:store.review_fact(fid,'approved','curated-source-operator',contract['verification_note'],store.hosts)
    return {'entity_id':eid,'fact_ids':ids,'approval_requested':approve}


def main():
    p=argparse.ArgumentParser();p.add_argument('--database',type=Path,required=True);p.add_argument('--pdf',type=Path,required=True);p.add_argument('--approve-source-checked',action='store_true',help='Trusted operator acknowledges visual comparison of the exact source contract')
    args=p.parse_args()
    with ConsoleStore(args.database) as s:print(json.dumps(ingest(s,args.pdf,args.approve_source_checked)))

if __name__=='__main__':main()
