"""Offline fail-closed release preflight. Not wired to legacy publishing.

Policy and review manifest must come from a trusted operator. A digest binds
approval to content; it does not authenticate a reviewer or verify a source.
"""
import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import re
from collections import Counter
from decimal import Decimal, localcontext
from pathlib import Path
from urllib.parse import urlsplit

VERSION = 1
TEXT_FIELDS = ('fact_id', 'entity_id', 'reporting_entity_id', 'metric', 'accounting_standard',
               'fiscal_year_label', 'period_start', 'period_end', 'scope', 'currency',
               'raw_value', 'raw_unit', 'unit_multiplier', 'value_native', 'document_id',
               'document_sha256', 'source_url', 'retrieved_at', 'reported_or_derived', 'verification_status')
LOCATORS = {'pdf': ('page', 'table', 'row', 'column'),
            'xbrl': ('concept', 'context', 'unit', 'dimensions'),
            'html': ('table', 'row', 'column')}
PUBLIC = ('metric', 'accounting_standard', 'fiscal_year_label', 'period_start', 'period_end',
          'fiscal_end_year', 'scope', 'currency', 'raw_value', 'raw_unit', 'unit_multiplier',
          'value_native', 'document_sha256', 'source_url', 'retrieved_at', 'reported_or_derived')


OPTIONAL_PUBLIC = ('comparison_eligible', 'metric_basis')


def digest(fact):
    return hashlib.sha256(json.dumps(fact, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def number(value):
    if not isinstance(value, str) or len(value) > 100 or not re.fullmatch(r'-?\d+(?:\.\d+)?', value):
        raise ValueError('Expected a plain decimal string of at most 100 characters')
    return Decimal(value)


def timestamp(value):
    try:
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).utcoffset() is not None
    except (ValueError, TypeError, AttributeError):
        return False


def source_url(value, hosts):
    if not isinstance(value, str) or re.search(r'[\s\\\x00-\x1f]', value):
        return False
    try:
        u = urlsplit(value)
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.port not in (None, 443):
            return False
        try:
            ipaddress.ip_address(u.hostname)
            return False
        except ValueError:
            pass
        return u.hostname in hosts and '.' in u.hostname
    except ValueError:
        return False


def validate(fact, hosts):
    if not isinstance(fact, dict):
        return ['fact_not_object']
    errors = ['missing_or_invalid:' + k for k in TEXT_FIELDS
              if not isinstance(fact.get(k), str) or not fact[k].strip()]
    if errors:
        return errors
    if 'comparison_eligible' in fact and type(fact['comparison_eligible']) is not bool:
        errors.append('invalid_comparison_eligibility')
    if 'metric_basis' in fact and fact['metric_basis'] not in ('reported','adjusted','issuer_defined'):
        errors.append('invalid_metric_basis')
    if fact['metric'] not in ('revenue', 'operating_income'):
        errors.append('invalid_metric')
    if fact['scope'] not in ('standalone', 'consolidated', 'combined', 'carve_out'):
        errors.append('invalid_scope')
    if fact['reported_or_derived'] != 'reported':
        errors.append('derived_not_supported')
    if fact['verification_status'] != 'source_verified':
        errors.append('not_source_verified')
    if not re.fullmatch('[A-Z]{3}', fact['currency']):
        errors.append('invalid_currency_format')
    try:
        start, end = (dt.date.fromisoformat(fact[k]) for k in ('period_start', 'period_end'))
        if not 350 <= (end - start).days + 1 <= 380:
            errors.append('not_annual_comparable')
        if type(fact.get('fiscal_end_year')) is not int or fact['fiscal_end_year'] != end.year or end.year not in (2023, 2024, 2025):
            errors.append('invalid_fiscal_end_year')
    except (ValueError, TypeError):
        errors.append('invalid_period')
    try:
        raw, multiplier, native = (number(fact[k]) for k in ('raw_value', 'unit_multiplier', 'value_native'))
        if multiplier <= 0:
            errors.append('invalid_unit_multiplier')
        with localcontext() as ctx:
            ctx.prec = 220
            if raw * multiplier != native:
                errors.append('unit_conversion_mismatch')
    except ValueError:
        errors.append('invalid_decimal')
    if not source_url(fact['source_url'], hosts):
        errors.append('source_not_allowed')
    if not re.fullmatch('[0-9a-f]{64}', fact['document_sha256']):
        errors.append('invalid_document_hash')
    if not timestamp(fact['retrieved_at']):
        errors.append('invalid_retrieved_at')
    loc = fact.get('source_locator')
    if not isinstance(loc, dict) or not isinstance(loc.get('type'), str) or loc['type'] not in LOCATORS:
        errors.append('invalid_locator')
    else:
        for key in LOCATORS[loc['type']]:
            if key == 'page':
                valid = type(loc.get(key)) is int and loc[key] >= 1
            elif key == 'dimensions':
                valid = loc.get(key) == {}  # only total-company XBRL facts
            else:
                valid = isinstance(loc.get(key), str) and bool(loc[key].strip())
            if not valid:
                errors.append('invalid_locator:' + key)
    return errors


class ReleaseBlocked(ValueError):
    def __init__(self, counts):
        self.counts = dict(counts)
        super().__init__('Release blocked: ' + json.dumps(self.counts, sort_keys=True))


def build_release(facts, reviews, official_hosts):
    """All-or-nothing fact release, without FX/aggregation or implicit approvals.

    Missing years/metrics may remain absent. This is NOT a balanced-panel export.
    Exactly one current review per fact; audit history is resolved upstream.
    """
    if not isinstance(facts, list) or not facts:
        raise ReleaseBlocked({'empty_or_invalid_facts': 1})
    if not isinstance(reviews, list) or not isinstance(official_hosts, list) or not official_hosts or any(not isinstance(h, str) for h in official_hosts):
        raise ReleaseBlocked({'invalid_review_or_policy': 1})
    errors, review_map = Counter(), {}
    for review in reviews:
        if not isinstance(review, dict) or not isinstance(review.get('fact_id'), str):
            errors['invalid_review'] += 1
            continue
        if review['fact_id'] in review_map:
            errors['duplicate_review'] += 1
        review_map[review['fact_id']] = review
    ids, identities, scopes, periods, safe = set(), set(), {}, {}, []
    for fact in facts:
        issues = validate(fact, official_hosts)
        errors.update(issues)
        if issues:
            continue
        fid = fact['fact_id']
        if fid in ids:
            errors['duplicate_fact_id'] += 1
        ids.add(fid)
        identity = tuple(fact[k] for k in ('reporting_entity_id', 'metric', 'period_start', 'period_end', 'scope', 'currency', 'accounting_standard'))
        if identity in identities:
            errors['duplicate_active_fact'] += 1
        identities.add(identity)
        scopes.setdefault(fact['reporting_entity_id'], set()).add(fact['scope'])
        key = (fact['reporting_entity_id'], fact['fiscal_end_year'])
        periods.setdefault(key, set()).add(tuple(fact[k] for k in ('period_start', 'period_end', 'currency', 'document_id', 'document_sha256', 'accounting_standard')))
        review = review_map.get(fid, {})
        try:
            sha = digest(fact)
        except (ValueError, TypeError):
            errors['non_json_fact'] += 1
            continue
        if review.get('status') != 'approved' or review.get('fact_sha256') != sha:
            errors['missing_or_stale_approval'] += 1
        if not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip() or not timestamp(review.get('reviewed_at')):
            errors['invalid_review_metadata'] += 1
        loc = fact['source_locator']
        safe.append({**{k: fact[k] for k in PUBLIC + OPTIONAL_PUBLIC if k in fact}, 'fact_sha256': sha,
                     'source_locator': {k: loc[k] for k in ('type',) + LOCATORS[loc['type']]}})
    errors['mixed_scope'] += sum(len(v) > 1 for v in scopes.values())
    errors['inconsistent_period_currency_document'] += sum(len(v) > 1 for v in periods.values())
    errors = {k: v for k, v in errors.items() if v}
    if errors:
        raise ReleaseBlocked(errors)
    return {'contract_version': VERSION, 'purpose': 'verified_annual_native_facts',
            'facts': sorted(safe, key=lambda x: x['fact_sha256'])}


def main():
    parser = argparse.ArgumentParser(description='Offline release preflight: counts only; no data writes')
    parser.add_argument('input', type=Path)
    args = parser.parse_args()
    try:
        p = json.loads(args.input.read_text(encoding='utf-8'))
        release = build_release(p.get('facts'), p.get('reviews'), p.get('official_hosts'))
    except ReleaseBlocked as exc:
        print(json.dumps({'status': 'blocked', 'errors': exc.counts}, sort_keys=True))
        return 1
    except (OSError, ValueError, TypeError, AttributeError):
        print(json.dumps({'status': 'blocked', 'errors': {'invalid_input': 1}}))
        return 1
    print(json.dumps({'status': 'passed', 'facts': len(release['facts']), 'contract_version': VERSION}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
