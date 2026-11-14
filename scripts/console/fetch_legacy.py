"""Download only four pinned public source files; no latest-branch surprises."""
import argparse,json,urllib.request
from pathlib import Path
from legacy_compare import FILES,HEAD
from service import ROOT

def main():
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args();target=a.directory.expanduser().resolve()
    if target==ROOT or ROOT in target.parents:p.error('원본 자료는 저장소 밖에 보관하세요.')
    target.mkdir(parents=True,exist_ok=True)
    for fn in FILES:
        out=target/fn
        if out.exists():raise ValueError('기존 파일을 덮어쓰지 않습니다: '+str(out))
        url=f'https://raw.githubusercontent.com/captaincatb-web/Sangsaengnews/{HEAD}/site/data/{fn}'
        with urllib.request.urlopen(url,timeout=60) as response:body=response.read(8*1024*1024+1)
        if len(body)>8*1024*1024:raise ValueError('Source too large')
        json.loads(body)
        with out.open('xb') as f:f.write(body)
        out.chmod(0o600)
    print('Downloaded 4 pinned sources to '+str(target))
if __name__=='__main__':main()
