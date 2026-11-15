"""Consistent SQLite backup/restore to new external paths; never overwrite."""
import argparse,hashlib,os,sqlite3
from pathlib import Path
from service import ROOT


def external(path):
    p=Path(path).resolve()
    if p.is_relative_to(ROOT):raise ValueError('Database/backup must remain outside repository')
    return p


def verify(path):
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite integrity check failed')
        if db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Foreign key check failed')
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'entity','document','fact','review','audit_event'}<=tables:raise ValueError('Not a research database')
        for sha,body in db.execute('SELECT sha256,body FROM document'):
            if hashlib.sha256(body).hexdigest()!=sha:raise ValueError('Document bytes/hash mismatch')


def copy_database(source,destination):
    source,destination=external(source),external(destination)
    if not source.is_file():raise ValueError('Source database not found')
    # Exclusive create protects existing databases, including empty files.
    fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    try:
        with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src:
            with sqlite3.connect(destination) as dst:src.backup(dst)
        verify(destination)
    except Exception:
        destination.unlink(missing_ok=True);raise
    return {'path':str(destination),'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'integrity':'ok'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('operation',choices=['backup','restore']);p.add_argument('source',type=Path);p.add_argument('destination',type=Path)
    a=p.parse_args();print(copy_database(a.source,a.destination))
