import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {resolve} from 'node:path';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
const require=createRequire(import.meta.url),original=globalThis.Uint8Array;let compiled;
try{globalThis.Uint8Array=new TextEncoder().encode('').constructor;compiled=createRequire(require.resolve('vite'))('esbuild').transformSync(readFileSync(resolve('../design/Velllum/uploads/components/local-music.jsx'),'utf8'),{loader:'jsx'}).code;}
finally{globalThis.Uint8Array=original;}
let root,host,api,state;
const button=text=>[...host.querySelectorAll('button')].find(item=>item.textContent===text);
const setInput=async(selector,value)=>act(async()=>{
  const node=host.querySelector(selector);Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(node,value);node.dispatchEvent(new Event('input',{bubbles:true}));
});
function Harness({view='home'}){
  const local=window.VellumUI.useLocalMusic({active:true});
  return React.createElement(React.Fragment,null,
    React.createElement('input',{type:'file',ref:local.audioInput,onChange:local.files,'aria-label':'Audio file'}),
    local.error&&React.createElement('p',{role:'alert'},local.error),
    local.notice&&React.createElement('p',{role:'status'},local.notice),
    React.createElement(window.VellumUI.LocalMusicContent,{local,view,onNavigate:vi.fn(),Icon:()=>React.createElement('svg'),Artwork:()=>React.createElement('span',{className:'music-artwork'})}));
}
beforeEach(()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  state={collections:[{id:'playlist',name:'Road Trip',completeness:'unknown',note:'Public snapshot',entries:[{id:'missing',title:'Song without audio',artist:'Artist',provider:'spotify',source_url:'https://open.spotify.com/track/AAAAAAAAAAAAAAAAAAAAAA',available:false},{id:'ready',title:'Owned song',artist:'Artist',provider:'local',available:true}]}],jobs:[],player:{revision:0,queue:[],observed:{}},downloader_available:true};
  api={library:vi.fn(async()=>state),action:vi.fn(async()=>({status:'applied',message:'Updated',result:{collection_id:'playlist'}})),upload:vi.fn(async()=>({status:'applied',message:'Audio added'})),exportUrl:id=>'http://127.0.0.1/export/'+id};
  window.VellumApi={localMusic:api,appActions:{catalog:vi.fn(async()=>({actions:['file','playlist','playback'].map(name=>({id:'local_music.'+name}))}))}};
  window.VellumLocalMusicPlayback={start:vi.fn(()=>({wake:vi.fn()})),subscribe:vi.fn(()=>()=>{})};
  new Function('React',compiled)(React);host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();});
async function render(view){await act(async()=>root.render(React.createElement(Harness,{view})));}

test('local library distinguishes references from audio and plays only ready entries',async()=>{
  await render();expect(host.textContent).toContain('1 of 2 songs matched');expect(host.querySelector('[aria-label="Play local Song without audio"]').disabled).toBe(true);
  await act(async()=>button('Play available songs').click());expect(api.action).toHaveBeenCalledWith('playback',{action:'play',entry_ids:['ready'],position:0});
});
test('match screen preserves unknown completeness and missing-song actions',async()=>{
  await render('import');expect(host.textContent).toContain('Playlist completeness: unknown');expect(host.textContent).toContain('1 of 2');
  expect(host.querySelector('[aria-label="Import audio for Song without audio"]')).toBeTruthy();expect(api.action).not.toHaveBeenCalled();
});
test('playlist import uses the typed metadata action without acquiring audio',async()=>{
  await render('import');await setInput('#mw-playlist-link','https://open.spotify.com/playlist/AAAAAAAAAAAAAAAAAAAAAA');
  await act(async()=>host.querySelector('.mw-import-source').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(api.action).toHaveBeenCalledWith('playlist',{url:'https://open.spotify.com/playlist/AAAAAAAAAAAAAAAAAAAAAA'});expect(api.upload).not.toHaveBeenCalled();
});
test('adding a file to a missing occurrence retains the exact selected entry',async()=>{
  await render('import');await act(async()=>host.querySelector('[aria-label="Import audio for Song without audio"]').click());
  const file=new File(['audio'],'owned.wav',{type:'audio/wav'}),node=host.querySelector('[aria-label="Audio file"]');
  Object.defineProperty(node,'files',{value:[file],configurable:true});
  await act(async()=>node.dispatchEvent(new Event('change',{bubbles:true})));
  expect(api.upload).toHaveBeenCalledWith(file,'missing');expect(api.action).not.toHaveBeenCalled();
});
test('disabled plugin has unavailable controls and does not start the audio owner',async()=>{
  window.VellumApi.appActions.catalog.mockResolvedValue({actions:[]});await render('add');
  expect(button('Choose files').disabled).toBe(true);expect(button('Import list').disabled).toBe(true);expect(window.VellumLocalMusicPlayback.start).not.toHaveBeenCalled();
});
test('failed action shows its receipt without claiming success',async()=>{
  api.action.mockResolvedValue({status:'failed',message:'Source unavailable'});await render();await act(async()=>button('Play available songs').click());
  expect(host.querySelector('[role=alert]').textContent).toBe('Source unavailable');expect(host.textContent).not.toContain('Updated');
});
test('streaming-service links import metadata and never become downloads',async()=>{
  const open=vi.spyOn(window,'open').mockImplementation(()=>null);await render('add');await setInput('[aria-label="Link"]','https://music.apple.com/us/album/example/123');
  await act(async()=>host.querySelector('.mw-add-card form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(open).not.toHaveBeenCalled();expect(api.action).toHaveBeenCalledWith('playlist',{url:'https://music.apple.com/us/album/example/123'});expect(host.textContent).not.toContain('Download');
});
test('unimplemented direct audio shows an honest state instead of adding a fake song',async()=>{
  await render('add');await setInput('[aria-label="Link"]','https://example.test/owned.mp3');
  await act(async()=>host.querySelector('.mw-add-card form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(host.querySelector('[role=alert]').textContent).toContain('not connected yet');expect(api.action).not.toHaveBeenCalled();
});
