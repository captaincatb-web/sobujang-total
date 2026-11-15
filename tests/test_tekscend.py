"""Offline synthetic adversarial fixtures, not published financial data."""
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/console'))
import import_tekscend as T
from service import ConsoleStore,ROOT

class SourceTests(unittest.TestCase):
    def setUp(self):
        self.c=json.loads((ROOT/'data/public/tekscend-source-contract.json').read_text())
        self.c['rows']={'revenue':{'label':'売上収益','values':['1','2','3']},'operating_income':{'label':'営業利益','values':['4','5','6']}}
        self.text='E40985 連結損益計算書 単位：百万円\n2022年4月1日 2023年3月31日 2023年4月1日 2024年3月31日 2024年4月1日 2025年3月31日\n売上収益 5,26 1 2 3\n営業利益 4 5 6\n'
    def test_note_column_not_a_value(self):T.check_page(self.text,self.c)
    def test_wrong_unit_entity_period_and_column(self):
        for old,new in [('百万円','千円'),('E40985','E00000'),('2022年4月1日','2022年7月1日'),('1 2 3','3 2 1')]:
            with self.subTest(old=old),self.assertRaises(ValueError):T.check_page(self.text.replace(old,new),self.c)
    def test_duplicate_row_blocked(self):
        with self.assertRaises(ValueError):T.check_page(self.text+'営業利益 4 5 6\n',self.c)
    def test_changed_document_blocked_before_parsing(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'doc.pdf';p.write_bytes(b'SYNTHETIC')
            with patch.object(T.subprocess,'run') as run,self.assertRaises(ValueError):T.extract(p,self.c)
            run.assert_not_called()
    def test_candidate_then_rerun_never_auto_approves(self):
        with tempfile.TemporaryDirectory() as d,ConsoleStore(Path(d)/'store.sqlite') as s:
            folder=Path(d)/'data/public';folder.mkdir(parents=True)
            self.c['document_sha256']=hashlib.sha256(b'SYNTHETIC TEST ONLY').hexdigest()
            (folder/'tekscend-source-contract.json').write_text(json.dumps(self.c))
            with patch.object(T,'ROOT',Path(d)),patch.object(T,'extract',return_value=b'SYNTHETIC TEST ONLY'):
                result=T.ingest(s,'unused')
                self.assertEqual(len(result['fact_ids']),6)
                self.assertEqual(len(s.snapshot(False)['facts']),0)
                T.ingest(s,'unused',True)
                self.assertEqual(s.db.execute('SELECT count(*) FROM fact').fetchone()[0],6)
                self.assertEqual(len(s.snapshot(False)['facts']),0)
                self.assertEqual(s.db.execute('SELECT count(*) FROM review').fetchone()[0],0)

if __name__=='__main__':unittest.main()
