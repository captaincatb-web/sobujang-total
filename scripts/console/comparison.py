"""Complete annual native-currency panels; never sum currencies or legal entities."""
from decimal import Decimal,localcontext

def panels(facts):
    grouped={}
    for f in facts:
        if f['verified']:grouped.setdefault(f['entity_id'],[]).append(f['payload'])
    out=[]
    for eid,rows in grouped.items():
        keys={(r['scope'],r['currency'],r['accounting_standard']) for r in rows}
        cells={(r['fiscal_end_year'],r['metric']):r for r in rows}
        expected={(y,m) for y in (2023,2024,2025) for m in ('revenue','operating_income')}
        if len(keys)!=1 or len(rows)!=6 or set(cells)!=expected:continue
        periods=[cells[y,'revenue'] for y in (2023,2024,2025)]
        if any(cells[y,'revenue']['period_start']!=cells[y,'operating_income']['period_start'] or cells[y,'revenue']['period_end']!=cells[y,'operating_income']['period_end'] for y in (2023,2024,2025)):continue
        # Different fiscal month ends (including changed year ends) are not a balanced panel.
        if len({r['period_end'][5:7] for r in periods})!=1:continue
        scope,currency,standard=next(iter(keys));series={}
        for metric in ('revenue','operating_income'):
            vals=[Decimal(cells[y,metric]['value_native']) for y in (2023,2024,2025)]
            with localcontext() as ctx:
                ctx.prec=220
                growth=[None]+[str(((vals[i]/vals[i-1]-1)*100).quantize(Decimal('.01'))) if vals[i-1]>0 else None for i in (1,2)]
            series[metric]={'values':[str(v) for v in vals],'yoy_percent':growth}
        out.append({'entity_id':eid,'currency':currency,'scope':scope,'accounting_standard':standard,'years':[2023,2024,2025],'series':series})
    return out
