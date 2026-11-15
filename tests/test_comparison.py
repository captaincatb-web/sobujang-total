import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/console'))
from comparison import comparison_results

class ComparabilityTests(unittest.TestCase):
    def setUp(self):
        self.rows=[{'verified':True,'entity_id':'synthetic','payload':{'metric':m,'fiscal_end_year':y,'period_start':f'{y}-01-01','period_end':f'{y}-12-31','scope':'consolidated','currency':'JPY','accounting_standard':'IFRS','value_native':'100'}} for y in (2023,2024,2025) for m in ('revenue','operating_income')]
    def test_standard_series(self):self.assertEqual(len(comparison_results(self.rows)['panels']),1)
    def test_explicit_hold_and_adjusted(self):
        for key,value,reason in [('comparison_eligible',False,'operator_hold'),('metric_basis','adjusted','nonstandard_metric'),('metric_basis','issuer_defined','nonstandard_metric'),('scope','combined','combined_or_carve_out')]:
            with self.subTest(key=key,value=value):
                self.setUp();self.rows[0]['payload'][key]=value;r=comparison_results(self.rows)
                self.assertEqual(r['panels'],[]);self.assertIn(reason,r['excluded'][0]['reasons'])
    def test_nine_month_period(self):
        for row in self.rows[:2]:row['payload']['period_start']='2023-04-01'
        self.assertIn('nonannual_period',comparison_results(self.rows)['excluded'][0]['reasons'])
    def test_annual_duration_alone_does_not_allow_gap(self):
        for row in self.rows[2:4]:row['payload']['period_start']='2024-01-03'
        self.assertIn('noncontiguous_periods',comparison_results(self.rows)['excluded'][0]['reasons'])
    def test_unverified_values_never_compared(self):
        self.rows[0]['verified']=False
        self.assertEqual(comparison_results(self.rows)['panels'],[])

if __name__=='__main__':unittest.main()
