import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync,existsSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {afterEach,beforeEach,expect,test} from 'vitest';

const require=createRequire(import.meta.url);
const uploads=resolve(dirname(fileURLToPath(import.meta.url)),'../../design/Velllum/uploads');
const source=readFileSync(resolve(uploads,'Vellum Default Re-designed.html'),'utf8');
const jsx=source.slice(source.indexOf('const SIMPLE_ICON_ROOT'),source.indexOf('function mcp('));
const originalUint8Array=globalThis.Uint8Array;
let compiled;
try{
  globalThis.Uint8Array=new TextEncoder().encode('').constructor;
  compiled=createRequire(require.resolve('vite'))('esbuild').transformSync(jsx+'\nreturn {ConnLogo,connectorIconSource,CONNECTOR_LOCAL_LOGOS};',{loader:'jsx'}).code;
}finally{globalThis.Uint8Array=originalUint8Array;}
const {ConnLogo,connectorIconSource,CONNECTOR_LOCAL_LOGOS}=new Function('React','useState','useEffect',compiled)(React,React.useState,React.useEffect);
let host,root;
beforeEach(()=>{globalThis.IS_REACT_ACT_ENVIRONMENT=true;host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
const render=async c=>act(async()=>root.render(React.createElement(ConnLogo,{c,size:24})));

test('every registered local logo ships as a real asset',()=>{
  for(const [id,file] of Object.entries(CONNECTOR_LOCAL_LOGOS)){
    expect(existsSync(resolve(uploads,'assets/plugins',file)),id).toBe(true);
    expect(connectorIconSource({id}),id).toBe('assets/plugins/'+file);
  }
});
test('publisher logos take precedence and name aliases work for app plugin IDs',()=>{
  expect(connectorIconSource({id:'design-partner'})).toBe('assets/plugins/design-partner.png');
  expect(connectorIconSource({id:'unknown-app-id',name:'Product Hunt'})).toBe('assets/plugins/producthunt.svg');
  expect(connectorIconSource({id:'github'})).toBe('assets/plugins/github.png');
});
test('plugins without a logo have an intentional lettermark, without a generic symbol',async()=>{
  await render({id:'reading-room',name:'Reading Room'});
  expect(host.querySelector('.plugin-lettermark').textContent).toBe('RR');
  expect(host.querySelector('svg,img')).toBeNull();
});
test('broken logo images use the same fallback and recover for another plugin',async()=>{
  await render({id:'github',name:'GitHub'});
  await act(async()=>host.querySelector('img').dispatchEvent(new Event('error')));
  expect(host.querySelector('.plugin-lettermark').textContent).toBe('GI');
  await render({id:'spotify',name:'Spotify'});
  expect(host.querySelector('img').getAttribute('src')).toBe('assets/plugins/spotify.svg');
});
