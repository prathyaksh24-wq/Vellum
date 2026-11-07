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
function Harness({view='playlist'}){
  const local=window.VellumUI.useLocalMusic({active:true});
  return React.createElement(React.Fragment,null,
    React.createElement('input',{type:'file',ref:local.audioInput,onChange:local.files,'aria-label':'Audio file'}),
    local.error&&React.createElement('p',{role:'alert'},local.error),
    local.notice&&React.createElement('p',{role:'status'},local.notice),
    React.createElement(window.VellumUI.LocalMusicContent,{local,view,onNavigate:vi.fn(),Icon:()=>React.createElement('svg'),Artwork:()=>React.createElement('span',{className:'music-artwork'})}));
}
beforeEach(()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  state={collections:[{id:'playlist',name:'Road Trip',completeness:'unknown',note:'Public snapshot',entries:[{id:'missing',title:'Song without audio',artist:'Artist',provider:'spotify',source_url:'https://open.spotify.com/track/AAAAAAAAAAAAAAAAAAAAAA',available:false},{id:'ready',title:'Owned song',artist:'Artist',provider:'local',available:true}]}],jobs:[],player:{revision:0,queue:[],observed:{}},downloader_available:true,mp3_available:true};
  api={library:vi.fn(async()=>state),action:vi.fn(async()=>({status:'applied',message:'Updated',result:{collection_id:'playlist'}})),upload:vi.fn(async()=>({status:'applied',message:'Audio added'})),exportUrl:id=>'http://127.0.0.1/export/'+id};
  window.VellumApi={localMusic:api,appActions:{catalog:vi.fn(async()=>({actions:['file','playlist','playback','download','job','remove','refresh'].map(name=>({id:'local_music.'+name}))}))}};
  window.VellumLocalMusicPlayback={start:vi.fn(()=>({wake:vi.fn()})),subscribe:vi.fn(()=>()=>{})};
  new Function('React',compiled)(React);host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();});
async function render(view){await act(async()=>root.render(React.createElement(Harness,{view})));}

test('local library distinguishes references from audio and plays only ready entries',async()=>{
  await render();expect(host.textContent).toContain('2 songs · 1 ready');expect(host.querySelector('[aria-label="Play local Song without audio"]').disabled).toBe(true);
  await act(async()=>button('Play playlist').click());expect(api.action).toHaveBeenCalledWith('playback',{action:'play',entry_ids:['ready'],position:0});
});
test('downloads show measured progress and stay staged until explicit import',async()=>{
  state.collections=[];
  state.pending_imports=[{id:'draft',name:'Road Trip',completeness:'complete',entries:[
    {id:'song',title:'A song',artist:'An artist',provider:'youtube',available:false},
  ]}];
  state.jobs=[{id:'job',entry_id:'song',status:'running',stage:'downloading',progress:42}];
  await render('import');
  expect(host.textContent).toContain('Road Trip');
  expect(host.textContent).toContain('Downloading 42%');
  expect(host.querySelector('progress').value).toBe(42);
  expect(button('Import playlist').disabled).toBe(true);
  expect(api.action).not.toHaveBeenCalled();
  state.jobs[0]={id:'job',entry_id:'song',status:'running',stage:'converting',progress:75};
  await render('import');
  expect(host.textContent).toContain('Converting to MP3 75%');
  state.jobs[0].status='complete';
  state.pending_imports[0].entries[0].available=true;
  await render('import');
  expect(button('Import playlist').disabled).toBe(false);
  await act(async()=>button('Import playlist').click());
  expect(api.action).toHaveBeenCalledWith('playlist',{pending_import_id:'draft'});
});
test.each([
  'https://open.spotify.com/playlist/AAAAAAAAAAAAAAAAAAAAAA',
  'https://music.apple.com/us/album/example/123',
  'https://music.youtube.com/watch?v=abcdefghijk',
])('pasted link queues MP3s through the typed playlist action (%s)',async url=>{
  await render('add');
  await setInput('#mw-playlist-link',url);
  expect(button('Convert to MP3').disabled).toBe(false);
  expect(host.querySelector('input[type="checkbox"]')).toBeNull();
  await act(async()=>host.querySelector('.mw-import-source').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(api.action).toHaveBeenCalledWith('playlist',{url,download_mp3:true,auto_import:true});
  expect(api.upload).not.toHaveBeenCalled();
});
test('an existing reference-only playlist can queue missing audio',async()=>{
  await render('import');
  await act(async()=>button('Download missing MP3s').click());
  expect(api.action).toHaveBeenCalledWith('download',{collection_id:'playlist'});
});
test('disabled plugin leaves local import unavailable',async()=>{
  window.VellumApi.appActions.catalog.mockResolvedValue({actions:[]});
  await render('add');
  expect(button('Choose files').disabled).toBe(true);
  expect(button('Choose playlist file').disabled).toBe(true);
  expect(window.VellumLocalMusicPlayback.start).not.toHaveBeenCalled();
});
test('failed action shows its receipt without claiming success',async()=>{
  api.action.mockResolvedValue({status:'failed',message:'Source unavailable'});await render();await act(async()=>button('Play playlist').click());
  expect(host.querySelector('[role=alert]').textContent).toBe('Source unavailable');expect(host.textContent).not.toContain('Updated');
});

test('songs and playlists have removal controls through the registered action',async()=>{
  await render();
  await act(async()=>host.querySelector('[aria-label="Remove Owned song from playlist"]').click());
  expect(api.action).toHaveBeenLastCalledWith('remove',{entry_id:'ready'});
  await act(async()=>host.querySelector('summary').click());
  await act(async()=>button('Remove playlist').click());
  expect(api.action).toHaveBeenLastCalledWith('remove',{collection_id:'playlist'});
});

test('staged downloads can be removed while their jobs are running',async()=>{
  state.pending_imports=[{id:'draft',name:'A download',entries:[{id:'downloading',title:'Downloading song',provider:'youtube',available:false}]}];
  state.jobs=[{id:'job',entry_id:'downloading',status:'running',stage:'downloading'}];
  await render('import');
  await act(async()=>host.querySelector('summary').click());
  await act(async()=>button('Remove playlist').click());
  expect(api.action).toHaveBeenLastCalledWith('remove',{collection_id:'draft'});
});

test('home lists playlists vertically and moves destructive actions into their menu',async()=>{
  await render('home');
  expect(host.querySelector('.mw-library-list')).toBeTruthy();
  expect(host.querySelectorAll('.mw-library-open')).toHaveLength(1);
  expect(host.querySelectorAll('.mw-local-song')).toHaveLength(0);
  expect(host.querySelector('details').open).toBe(false);
});

test('the Add music page provides a direct return to the library',async()=>{
  await render('add');
  expect(host.querySelector('.mw-add-back').textContent).toContain('Back to your music');
});

test('the paste-link flow starts conversion and automatic import without OAuth',async()=>{
  window.VellumApi.appActions.dispatch=vi.fn();
  vi.spyOn(window,'open').mockReturnValue(null);
  await render('add');
  const url='https://music.youtube.com/playlist?list=PLabcdefghijk';
  await setInput('#mw-playlist-link',url);
  await act(async()=>host.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(api.action).toHaveBeenCalledWith('playlist',{url,download_mp3:true,auto_import:true});
  expect(window.open).not.toHaveBeenCalled();
  expect(window.VellumApi.appActions.dispatch).not.toHaveBeenCalled();
});
