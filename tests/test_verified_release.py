"""Synthetic facts only. These fixtures do not describe any real company."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'growth'))
import verified_release as V
import ingest_overseas_csv as I


def fact(**changes):
    row = dict(fact_id='fixture-1', entity_id='internal-entity', reporting_entity_id='internal-entity',
               metric='revenue', accounting_standard='IFRS', fiscal_year_label='FY2024',
               period_start='2024-04-01', period_end='2025-03-31', fiscal_end_year=2025,
               scope='consolidated', currency='JPY', raw_value='12.34', raw_unit='million JPY',
               unit_multiplier='1000000', value_native='12340000', document_id='fixture-doc',
               document_sha256='a' * 64, source_url='https://filings.example.org/report.pdf',
               source_locator=dict(type='pdf', page=3, table='Income', row='Revenue', column='FY2024'),
               retrieved_at='2026-11-14T10:00:00Z', reported_or_derived='reported',
               verification_status='source_verified')
    row.update(changes)
    return row


def approval(row, **changes):
    review = dict(fact_id=row['fact_id'], fact_sha256=V.digest(row), status='approved',
                  reviewer='fixture-reviewer', reviewed_at='2026-11-14T11:00:00Z')
    review.update(changes)
    return review


def release(rows, reviews=None):
    return V.build_release(rows, reviews if reviews is not None else [approval(r) for r in rows],
                           ['filings.example.org'])


class VerifiedRelease(unittest.TestCase):
    def blocked(self, rows, code, reviews=None):
        with self.assertRaises(V.ReleaseBlocked) as caught:
            release(rows, reviews)
        self.assertIn(code, caught.exception.counts)

    def test_exact_decimal_and_fiscal_end_year(self):
        r = release([fact()])['facts'][0]
        self.assertEqual(r['value_native'], '12340000')
        self.assertEqual(r['fiscal_end_year'], 2025)
        self.assertEqual(r['fiscal_year_label'], 'FY2024')

    def test_zero_is_real_and_missing_is_not_zero(self):
        self.assertEqual(release([fact(raw_value='0', value_native='0')])['facts'][0]['value_native'], '0')
        self.blocked([fact(raw_value='')], 'missing_or_invalid:raw_value')

    def test_reject_bad_units_and_floats(self):
        for value in ('NaN', 'Infinity', '1e6', 1000000):
            with self.subTest(value=value):
                self.assertTrue(V.validate(fact(unit_multiplier=value), ['filings.example.org']))
        for value in ('0', '-1'):
            self.blocked([fact(unit_multiplier=value)], 'invalid_unit_multiplier')

    def test_unit_mismatch(self):
        self.blocked([fact(value_native='1234')], 'unit_conversion_mismatch')

    def test_large_decimal_preserved(self):
        value = '123456789012345678901234567890.12'
        self.assertEqual(release([fact(raw_value=value, unit_multiplier='1', value_native=value)])['facts'][0]['value_native'], value)

    def test_short_period_and_wrong_year(self):
        self.blocked([fact(period_start='2024-07-01')], 'not_annual_comparable')
        self.blocked([fact(fiscal_end_year=2024)], 'invalid_fiscal_end_year')

    def test_52_and_53_week_years(self):
        for start in ('2024-04-02', '2024-03-26'):
            self.assertEqual(len(release([fact(period_start=start)])['facts']), 1)

    def test_source_host_and_url(self):
        for url in ('http-not-url', 'http://filings.example.org/a', 'https://filings.example.org.evil.test/a',
                    'https://filings.example.org@evil.test/a', 'https://filings.example.org:8080/a',
                    'https://127.0.0.1/a', 'https://filings.example.org/white space'):
            with self.subTest(url=url):
                self.blocked([fact(source_url=url)], 'source_not_allowed')

    def test_evidence_locator_required(self):
        self.blocked([fact(source_locator={})], 'invalid_locator')
        self.blocked([fact(source_locator=dict(type='pdf', page=0, table='x', row='x', column='x'))], 'invalid_locator:page')

    def test_xbrl_total_only(self):
        loc = dict(type='xbrl', concept='ifrs:Revenue', context='FY', unit='JPY', dimensions={})
        self.assertEqual(len(release([fact(source_locator=loc)])['facts']), 1)
        loc['dimensions'] = {'segment': 'chip'}
        self.blocked([fact(source_locator=loc)], 'invalid_locator:dimensions')

    def test_unverified_and_derived_blocked(self):
        self.blocked([fact(verification_status='unverified')], 'not_source_verified')
        self.blocked([fact(reported_or_derived='derived')], 'derived_not_supported')

    def test_missing_rejected_or_revoked_approval(self):
        row = fact()
        self.blocked([row], 'missing_or_stale_approval', [])
        for status in ('rejected', 'revoked', 'pending'):
            self.blocked([row], 'missing_or_stale_approval', [approval(row, status=status)])

    def test_changed_fact_invalidates_approval(self):
        row = fact(); old = approval(row)
        row['source_locator']['page'] = 4
        self.blocked([row], 'missing_or_stale_approval', [old])

    def test_reviewer_and_timezone_required(self):
        row = fact()
        self.blocked([row], 'invalid_review_metadata', [approval(row, reviewer='')])
        self.blocked([row], 'invalid_review_metadata', [approval(row, reviewed_at='2026-11-14T11:00:00')])

    def test_duplicate_reviews_and_active_facts(self):
        row = fact()
        self.blocked([row], 'duplicate_review', [approval(row), approval(row)])
        self.blocked([row, fact(fact_id='fixture-2')], 'duplicate_active_fact')

    def test_mixed_scope_and_currency(self):
        a = fact(); b = fact(fact_id='fixture-2', metric='operating_income', scope='standalone')
        self.blocked([a, b], 'mixed_scope')
        b['scope'] = a['scope']; b['currency'] = 'USD'
        self.blocked([a, b], 'inconsistent_period_currency_document')

    def test_cross_document_pair_blocked(self):
        self.blocked([fact(), fact(fact_id='fixture-2', metric='operating_income', document_id='different')],
                     'inconsistent_period_currency_document')

    def test_projection_drops_private_fields(self):
        row = fact(private_note='DO_NOT_EXPORT', business_number='DO_NOT_EXPORT')
        row['source_locator']['private_note'] = 'DO_NOT_EXPORT'
        result = json.dumps(release([row]))
        for private in ('DO_NOT_EXPORT', 'fixture-reviewer', 'internal-entity'):
            self.assertNotIn(private, result)

    def test_all_or_nothing_and_no_mutation(self):
        rows = [fact(), fact(fact_id='fixture-2', verification_status='unverified')]
        before = copy.deepcopy(rows)
        self.blocked(rows, 'not_source_verified')
        self.assertEqual(rows, before)

    def test_deterministic_order(self):
        rows = [fact(), fact(fact_id='fixture-2', metric='operating_income')]
        self.assertEqual(release(rows), release(list(reversed(rows))))

    def test_malformed_and_empty_inputs(self):
        for rows in ([], None, [None], [{'source_locator': []}]):
            with self.assertRaises(V.ReleaseBlocked):
                V.build_release(rows, [], ['filings.example.org'])

    def test_cli_counts_only_and_nonzero_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'input.json'
            row = fact(private_note='DO_NOT_LOG')
            payload = dict(facts=[row], reviews=[approval(row)], official_hosts=['filings.example.org'])
            path.write_text(json.dumps(payload))
            cmd = [sys.executable, str(ROOT / 'scripts/growth/verified_release.py'), str(path)]
            good = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(good.returncode, 0)
            self.assertNotIn('DO_NOT_LOG', good.stdout)
            payload['reviews'] = []; path.write_text(json.dumps(payload))
            bad = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(bad.returncode, 1)
            self.assertEqual(list(Path(folder).iterdir()), [path])


class LegacyIngestHardening(unittest.TestCase):
    def row(self, **changes):
        row = {'목록표기': 'SYNTHETIC ONLY', '기간시작': '2024-01-01', '기간종료': '2024-12-31',
               '출처URL': 'https://example.org/report', '쪽/표위치': 'p3 table 1',
               '연결/개별': '개별', '통화': 'KRW', '금액단위': '백만', '매출': '1,234', '영업이익': '0'}
        row.update(changes)
        return row

    def test_reject_missing_evidence_bad_scope_currency_and_unit(self):
        for change in ({'쪽/표위치': ''}, {'연결/개별': ''}, {'통화': ''}, {'금액단위': '-1'},
                       {'금액단위': '0'}, {'금액단위': 'NaN'}, {'금액단위': 'Infinity'},
                       {'출처URL': 'http-not-url'}, {'출처URL': 'https://user:pass@example.org/a'}):
            with self.subTest(change=change):
                self.assertEqual(I.convert([self.row(**change)], {})[0], [])

    def test_preserve_raw_inputs_and_no_implicit_verification(self):
        row = I.convert([self.row()], {})[0][0]
        self.assertEqual(row['raw_revenue'], '1,234')
        self.assertEqual(row['raw_unit'], '백만')
        self.assertEqual(row['op_income_krw'], 0)
        self.assertEqual(row['verification_status'], 'unverified')
        self.assertEqual(set(row), set(I.OUT_COLS))

    def test_standalone_alias_not_mixed(self):
        rows = [self.row(), self.row(**{'연결/개별': '별도', '기간시작': '2023-01-01', '기간종료': '2023-12-31'})]
        accepted, _ = I.convert(rows, {})
        self.assertEqual(len(accepted), 2)
        self.assertEqual({r['scope'] for r in accepted}, {'개별'})

    def test_overflow_and_bad_fx_do_not_emit_nonfinite(self):
        self.assertEqual(I.convert([self.row(매출='9' * 400)], {})[0], [])
        row = self.row(통화='JPY')
        rates = {'JPY': [(dt, float('nan')) for dt in [__import__('datetime').date(2024, 1, 1)]]}
        accepted, _ = I.convert([row], rates)
        self.assertEqual(accepted[0]['revenue_krw'], '')


if __name__ == '__main__':
    unittest.main()
