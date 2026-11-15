import sys,tempfile,unittest,sqlite3
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/console'))
from service import ConsoleStore,ROOT
from backup import copy_database

class BackupTests(unittest.TestCase):
    def test_round_trip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'live.sqlite';backup=Path(d)/'backup.sqlite';restored=Path(d)/'restored.sqlite'
            with ConsoleStore(source) as s:eid=s.add_entity('Synthetic backup test','KR','test')
            self.assertEqual(copy_database(source,backup)['integrity'],'ok');copy_database(backup,restored)
            with ConsoleStore(restored) as s:self.assertEqual(s.db.execute('SELECT legal_name FROM entity WHERE id=?',(eid,)).fetchone()[0],'Synthetic backup test')
            with self.assertRaises(FileExistsError):copy_database(source,backup)
            self.assertEqual(backup.stat().st_mode&0o777,0o600)
    def test_invalid_database_does_not_leave_backup(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'invalid';target=Path(d)/'out'
            with sqlite3.connect(source) as c:c.execute('CREATE TABLE wrong(x)')
            with self.assertRaises(ValueError):copy_database(source,target)
            self.assertFalse(target.exists())
    def test_repository_destination_rejected(self):
        with self.assertRaises(ValueError):copy_database('/nonexistent',ROOT/'private.sqlite')

if __name__=='__main__':unittest.main()
