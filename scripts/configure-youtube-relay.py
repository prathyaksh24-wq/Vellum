"""Prepare personal relay credentials locally; never print secret values."""
import argparse
import json
from pathlib import Path
import re
import secrets
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from agent.plugins.youtube_push import callback_origin

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--origin',default='',help='Activate this public HTTPS receiver origin after deployment.')
args=parser.parse_args()
origin=callback_origin(args.origin)
env_path=ROOT/'.env'
text=env_path.read_text(encoding='utf-8') if env_path.exists() else ''
match=re.search(r'^YOUTUBE_PUSH_RELAY_TOKEN=([A-Za-z0-9_-]{43})\s*$',text,re.M)
token=match.group(1) if match else secrets.token_urlsafe(32)

def setting(text,key,value):
    line=key+'='+value
    pattern=r'(?m)^'+re.escape(key)+r'=.*$'
    return re.sub(pattern,lambda _:line,text) if re.search(pattern,text) else text.rstrip('\n')+'\n'+line+'\n'

text=setting(text,'YOUTUBE_PUSH_RELAY_TOKEN',token)
if origin:text=setting(text,'YOUTUBE_PUSH_RELAY_BASE',origin)
env_path.write_text(text,encoding='utf-8')
secret_file=ROOT/'.api-runtime'/'youtube-relay-secrets.json'
secret_file.parent.mkdir(parents=True,exist_ok=True)
secret_file.write_text(json.dumps({'VELLUM_RELAY_TOKEN':token}),encoding='utf-8')
print('Prepared local receiver credential and ignored Wrangler secret file; no value was printed.')
if origin:print('Hosted origin configured. Restart Vellum backend to activate it.')
