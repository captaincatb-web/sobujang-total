"""Complete annual native-currency panels, with explicit exclusion reasons."""
from datetime import date
from decimal import Decimal,localcontext


def assess(rows):
    reasons=[]
    expected={(y,m) for y in (2023,2024,2025) for m in ('revenue','operating_income')}
    cells={(r.get('fiscal_end_year'),r.get('metric')):r for r in rows}
    if len(rows)!=6 or set(cells)!=expected:return ['incomplete_or_duplicate_series']
    keys={(r.get('scope'),r.get('currency'),r.get('accounting_standard')) for r in rows}
    if len(keys)!=1:reasons.append('mixed_basis')
    if any(r.get('scope') not in ('standalone','consolidated') for r in rows):reasons.append('combined_or_carve_out')
    if any(r.get('comparison_eligible',True) is not True for r in rows):reasons.append('operator_hold')
    if any(r.get('metric_basis','reported')!='reported' for r in rows):reasons.append('nonstandard_metric')
    periods=[]
    try:
        for year in (2023,2024,2025):
            rev,op=cells[year,'revenue'],cells[year,'operating_income']
            start,end=(date.fromisoformat(rev[k]) for k in ('period_start','period_end'))
            periods.append((start,end))
            if end.year!=year or not 350<=(end-start).days+1<=380:reasons.append('nonannual_period')
            if any(rev[k]!=op[k] for k in ('period_start','period_end')):reasons.append('metric_period_mismatch')
        if len({end.month for start,end in periods})!=1:reasons.append('changed_year_end')
        if any((periods[i][0]-periods[i-1][1]).days!=1 for i in (1,2)):reasons.append('noncontiguous_periods')
    except (ValueError,TypeError,KeyError):reasons.append('invalid_period')
    return sorted(set(reasons))


def comparison_results(facts):
    grouped={}
    for f in facts:
        if f['verified']:grouped.setdefault(f['entity_id'],[]).append(f['payload'])
    out=[];excluded=[]
    for eid,rows in grouped.items():
        reasons=assess(rows)
        if reasons:
            excluded.append({'entity_id':eid,'reasons':reasons});continue
        cells={(r['fiscal_end_year'],r['metric']):r for r in rows}
        first=rows[0];series={}
        for metric in ('revenue','operating_income'):
            vals=[Decimal(cells[y,metric]['value_native']) for y in (2023,2024,2025)]
            with localcontext() as ctx:
                ctx.prec=220
                growth=[None]+[str(((vals[i]/vals[i-1]-1)*100).quantize(Decimal('.01'))) if vals[i-1]>0 else None for i in (1,2)]
            series[metric]={'values':[str(v) for v in vals],'yoy_percent':growth}
        out.append({'entity_id':eid,'currency':first['currency'],'scope':first['scope'],'accounting_standard':first['accounting_standard'],'years':[2023,2024,2025],'series':series})
    return {'panels':out,'excluded':excluded}


def panels(facts):return comparison_results(facts)['panels']
