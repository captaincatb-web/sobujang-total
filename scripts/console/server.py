"""Loopback-only local console; --preview serves only a checked-in public snapshot."""
import argparse, hmac, json, os, secrets, sqlite3, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from service import ConsoleStore, ROOT, DEFAULT_HOSTS

STATIC=ROOT/'console'
LIMIT=32*1024*1024

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass # never log tokens, evidence or financial payloads
    def send(self,status,body,kind='application/json; charset=utf-8'):
        raw=json.dumps(body,ensure_ascii=False,allow_nan=False).encode() if isinstance(body,(dict,list)) else body
        self.send_response(status); self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers();self.wfile.write(raw)
    def authorized(self):
        if self.server.preview:return True
        host=self.headers.get('Host','');expected=f'127.0.0.1:{self.server.server_port}'
        if host!=expected:return False
        origin=self.headers.get('Origin')
        if origin and origin!='http://'+expected:return False
        token=self.headers.get('Authorization','').removeprefix('Bearer ')
        return bool(token) and hmac.compare_digest(token,self.server.token)
    def do_GET(self):
        path=urlsplit(self.path).path
        if path.startswith('/api/'):
            if not self.authorized():return self.send(401,{'error':'로컬 실행 시 표시된 세션 키를 입력하세요.'})
            if self.server.preview:
                if path=='/api/snapshot':return self.send(200,(STATIC/'snapshot.json').read_bytes())
                return self.send(403,{'error':'읽기 전용 미리보기입니다.'})
            with ConsoleStore(self.server.dbpath,self.server.hosts) as s:
                if path=='/api/snapshot':return self.send(200,s.snapshot())
                if path=='/api/document':
                    did=parse_qs(urlsplit(self.path).query).get('id',[''])[0]
                    d=s.db.execute('SELECT body FROM document WHERE id=?',(did,)).fetchone()
                    if not d:return self.send(404,{'error':'원문을 찾지 못했습니다.'})
                    # Download only; do not execute untrusted HTML in the console origin.
                    return self.send(200,d['body'],'application/octet-stream')
            return self.send(404,{'error':'not_found'})
        files={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/style.css':'style.css','/world.svg':'world.svg'}
        if path not in files:return self.send(404,{'error':'not_found'})
        file=STATIC/files[path]
        if not file.exists():return self.send(404,{'error':'not_found'})
        mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml'}
        self.send(200,file.read_bytes(),mime[file.suffix])
    def do_POST(self):
        if self.server.preview:return self.send(403,{'error':'읽기 전용 미리보기에서는 수정할 수 없습니다. 로컬 앱을 실행하세요.'})
        if not self.authorized():return self.send(401,{'error':'세션 또는 요청 출처를 확인하세요.'})
        action=urlsplit(self.path).path.removeprefix('/api/')
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<=0 or n>LIMIT:return self.send(413,{'error':'요청은 32MB 이하로 제한됩니다.'})
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.send(415,{'error':'JSON 요청이 필요합니다.'})
            data=json.loads(self.rfile.read(n))
            if not isinstance(data,dict):raise ValueError('JSON 객체가 필요합니다.')
            with ConsoleStore(self.server.dbpath,self.server.hosts) as s:result=s.action(action,data)
            self.send(200,result)
        except (ValueError,KeyError,TypeError,sqlite3.Error) as e:
            # Integrity errors must not disclose SQL or private identifiers.
            message=str(e) if isinstance(e,ValueError) else '필수 입력, 중복 또는 연결된 자료를 확인하세요.'
            self.send(400,{'error':message})
        except Exception:
            self.send(500,{'error':'처리를 완료하지 못했습니다. 원본은 삭제되지 않았습니다.'})


def make_server(dbpath,port=8765,preview=False,hosts=None):
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.preview=preview;server.dbpath=dbpath;server.hosts=hosts or DEFAULT_HOSTS;server.token=secrets.token_urlsafe(32)
    return server


def main():
    p=argparse.ArgumentParser();p.add_argument('--host',choices=['127.0.0.1'],default='127.0.0.1');p.add_argument('--strictPort',action='store_true');p.add_argument('--database',type=Path);p.add_argument('--port',type=int,default=int(os.environ.get('PORT','8765')));p.add_argument('--preview',action='store_true');p.add_argument('--policy',type=Path);args=p.parse_args()
    hosts=DEFAULT_HOSTS
    if args.policy:hosts=json.loads(args.policy.read_text())['official_hosts']
    if not args.preview:
        if not args.database:p.error('--database 를 저장소 밖 경로로 지정하세요.')
        with ConsoleStore(args.database,hosts) as s:
            if not s.summary()['counts']['entity']:s.import_master(json.loads((ROOT/'data/public/legacy-master.json').read_text()),'legacy-import')
    server=make_server(args.database,args.port,args.preview,hosts)
    print(f'Local: http://127.0.0.1:{server.server_port}',flush=True)
    if not args.preview:print('Session key (local operator): '+server.token,flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
