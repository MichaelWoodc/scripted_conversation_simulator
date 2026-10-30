"""Serve the practice site locally, reading the latest answer WAVs in place."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
import argparse
import json
import mimetypes
import re
import sys

from build_site import build, make_catalog
from project_paths import DIST


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(DIST),**kwargs)

    def end_headers(self):
        self.send_header('Cache-Control','no-cache')
        self.send_header('X-Content-Type-Options','nosniff')
        super().end_headers()

    def do_GET(self):
        path=unquote(urlsplit(self.path).path).lstrip('/')
        if path=='catalog.json':
            catalog,self.server.media=make_catalog()
            payload=json.dumps(catalog,ensure_ascii=False).encode('utf-8')
            self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            return
        if path.startswith('media/'):
            wav=self.server.media.get(path)
            if wav is None or not wav.exists(): self.send_error(404);return
            size=wav.stat().st_size;start=0;end=size-1
            requested=self.headers.get('Range')
            if requested:
                match=re.fullmatch(r'bytes=(\d+)-(\d*)',requested)
                if not match: self.send_error(416);return
                start=int(match[1]);end=min(int(match[2]) if match[2] else end,end)
                if start>end: self.send_error(416);return
            self.send_response(206 if requested else 200)
            self.send_header('Content-Type','audio/wav');self.send_header('Accept-Ranges','bytes')
            self.send_header('Content-Length',str(end-start+1))
            if requested:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            try:
                with wav.open('rb') as source:
                    source.seek(start);left=end-start+1
                    while left:
                        chunk=source.read(min(left,64*1024))
                        if not chunk:break
                        self.wfile.write(chunk);left-=len(chunk)
            except (BrokenPipeError,ConnectionResetError):pass
            return
        super().do_GET()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    _,media=build()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server.media=media
    print(f'Practice site: http://localhost:{args.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
