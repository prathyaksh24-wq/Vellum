import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
const require=createRequire(import.meta.url),rootPath=resolve(dirname(fileURLToPath(import.meta.url)),'../..');
const original=globalThis.Uint8Array;let pageCode,localCode,selectCode,morphicCode;
try{
  globalThis.Uint8Array=new TextEncoder().encode('').constructor;
  const esbuild=createRequire(require.resolve('vite'))('esbuild');
  const compile=name=>esbuild.transformSync(readFileSync(resolve(rootPath,'design/Velllum/uploads/components/'+name),'utf8'),{loader:'jsx'}).code;
  morphicCode=compile('morphic-ui.js');pageCode=compile('music-page.jsx');localCode=compile('local-music.jsx');selectCode=compile('v-select.jsx');
}finally{globalThis.Uint8Array=original;}
let root,host,api,music,Player,props,localState;
const song=(id,name)=>({id,uri:'spotify:track:'+id,name,kind:'track',artists:['Artist'],artwork_url:'https://images.example/'+id,playable:true,duration_ms:180000});
const playlist=(id,name)=>({id,uri:'spotify:playlist:'+id,name,kind:'playlist',artists:[],artwork_url:'',playable:true});
const album=(id,name)=>({...playlist(id,name),kind:'album',uri:'spotify:album:'+id,artists:['Artist']});
const textButton=text=>[...host.querySelectorAll('button')].find(node=>node.textContent===text);
const click=async label=>act(async()=>host.querySelector('[aria-label="'+label+'"]').click());
const press=async text=>act(async()=>{const provider={Spotify:'spotify','Apple Music':'apple','Local files':'local'}[text],trigger=host.querySelector('[aria-label="Music provider"]');if(provider && trigger){trigger.click();[...host.querySelectorAll('#music-provider-list [role="option"]')].find(node=>node.querySelector('.v-select-option-copy > span')?.textContent===text).click();}else textButton(text).click();});
const navigate=async text=>act(async()=>[...host.querySelectorAll('.mw-nav button')].find(node=>node.textContent===text).click());
const input=async(label,value)=>act(async()=>{
  const node=host.querySelector('[aria-label="'+label+'"]');
  Object.getOwnPropertyDescriptor(node.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set.call(node,value);
  node.dispatchEvent(new Event('input',{bubbles:true}));
});
async function render(overrides={}){
  Object.assign(music,overrides);
  await act(async()=>root.render(React.createElement(Player,{...props,music})));
}
async function openPlaylist(){
  await render();await navigate('Playlists');await act(async()=>host.querySelector('.music-collection-card:last-child').click());
}
async function editablePlaylist(){
  const browse=api.spotifyBrowse.getMockImplementation();
  api.spotifyBrowse.mockImplementation(args=>args.kind==='playlist_details'?Promise.resolve({items:[{...playlist('Tamil','Tamil'),editable:true,description:'My songs'}]}):browse(args));
  await openPlaylist();
}
beforeEach(()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  vi.stubGlobal('matchMedia',vi.fn(query=>({matches:false,media:query,addEventListener:vi.fn(),removeEventListener:vi.fn()})));
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  api={
    capabilities:vi.fn(async()=>({features:{spotify:{enabled:true,endpoints:{browse:'browse',search:'search'}}}})),
    spotifyBrowse:vi.fn(async args=>args.kind==='liked'?{items:[song('Liked','Liked song')],total:55,next_offset:null}:args.kind==='albums'?{items:[album('Night','Night Drive'),album('Harbor','Glass Harbor')],total:2,next_offset:null}:args.kind.endsWith('_tracks')?{items:[song('First','First song'),song('Second','Second song')],total:2,next_offset:null}:args.kind==='playlist_details'?{items:[{...playlist('Tamil','Tamil'),editable:false}]}:{items:[playlist('Emoji','🌙✨'),playlist('Tamil','Tamil')],total:2,next_offset:null}),
    spotifySearch:vi.fn(async()=>({items:[song('Ride','Ride')],total:1})),
    spotifyPlaylistEdit:vi.fn(async()=>({status:'confirmation_required',message:'Rename Tamil to Road Trip?',confirmation:{token:'review'}})),
    spotifyPlaylistConfirm:vi.fn(async()=>({status:'applied',message:'Renamed Tamil to Road Trip.',result:{playlist_id:'Tamil',name:'Road Trip',operation:'update_details'}})),
    spotifyPlaylistCancel:vi.fn(async()=>({status:'cancelled'})),
  };
  localState={collections:[],jobs:[],player:{revision:0,queue:[],observed:{},volume:.7},downloader_available:true};
  window.VellumApi={plugins:api,localMusic:{library:vi.fn(async()=>localState),action:vi.fn(async()=>({status:'applied',message:'Imported song list',result:{collection_id:'saved'}})),upload:vi.fn(),exportUrl:id=>'http://127.0.0.1/export/'+id},
    appActions:{dispatch:vi.fn(async()=>({status:'applied',message:'Playlist links added'})),catalog:vi.fn(async()=>({actions:[{id:'spotify.playlist.edit'},{id:'spotify.playlists.link'},...['playlist','file','playback'].map(name=>({id:'local_music.'+name}))]}))}};
  window.VellumLocalMusicPlayback={start:vi.fn(()=>({wake:vi.fn()})),subscribe:vi.fn(()=>()=>{})};
  window.React=React;window.VellumUI={};new Function('React',morphicCode)(React);new Function('React',selectCode)(React);new Function('React',localCode)(React);new Function('React',pageCode)(React);Player=window.VellumUI.MusicPage;
  music={player:{track:song('Ride','Ride'),artists:['Artist'],is_playing:true,duration_ms:180000,progress_ms:84000,device:{volume_percent:25}},playback:{ready:true},upcoming:[],busy:false,error:'',run:vi.fn(async()=>true),refresh:vi.fn(),enable:vi.fn()};
  props={spotify:{connected:true,product:'premium',account_name:'Listener',web_playback_ready:true},onReconnect:vi.fn(),onCloseMusic:vi.fn(),onRefreshConnection:vi.fn(),onAskMusic:vi.fn()};
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});

test('handoff home has the music sidebar, real album grid and single bottom player',async()=>{
  await render();expect(host.querySelector('.mw-sidebar')).toBeTruthy();expect(host.querySelectorAll('.mw-player')).toHaveLength(1);
  expect([...host.querySelectorAll('.mw-home-albums .mw-cover-grid b')].map(node=>node.textContent)).toEqual(['Night Drive','Glass Harbor']);
  expect(host.querySelector('.music-record')).toBeNull();expect(host.querySelector('canvas')).toBeNull();
});
test('Apple changes the accent and shows its future integration without exposing Spotify data',async()=>{
  await render();await press('Apple Music');
  expect(host.querySelector('.mw-workspace').dataset.musicTheme).toBe('Apple Music');
  expect(host.textContent).toContain('integration will be added later');expect(host.textContent).not.toContain('Night Drive');
  expect(host.querySelector('[aria-label="Play music"]').disabled).toBe(true);expect(music.run).not.toHaveBeenCalled();
  await press('Open local library');expect(host.querySelector('.mw-workspace').dataset.musicTheme).toBe('Midnight');
});
test('appearance follows Vellum background instead of assigning provider background tokens',()=>{
  const css=readFileSync(resolve(rootPath,'design/Velllum/uploads/components/music-page.css'),'utf8');
  expect(css).toContain('background:transparent');expect(css).toContain('--mw-text:var(--txt2');
  expect(css).not.toContain('--mw-bg:#FFFFFF');expect(css).toContain('grid-template-columns:232px minmax(0,1fr)');
});
test('collection selection is read-only and playing retains the exact source position',async()=>{
  await openPlaylist();expect(music.run).not.toHaveBeenCalled();expect(host.querySelector('.music-detail h1').textContent).toBe('Tamil');
  await click('Play Second song by Artist');expect(music.run).toHaveBeenCalledWith({action:'play',context_uri:'spotify:playlist:Tamil',offset_position:1});
});
test('complete song sorting retains original source positions',async()=>{
  const browse=api.spotifyBrowse.getMockImplementation();
  api.spotifyBrowse.mockImplementation(args=>args.kind==='playlist_tracks'?Promise.resolve(args.offset?{items:[{...song('A','A song'),position:50}],total:51,next_offset:null}:{items:[{...song('Z','Z song'),position:0}],total:51,next_offset:50}):browse(args));
  await openPlaylist();await click('Sort playlist songs');await press('Title A–Z');
  expect([...host.querySelectorAll('.music-track-title b')].map(node=>node.textContent)).toEqual(['A song','Z song']);
  await click('Play A song by Artist');expect(music.run).toHaveBeenCalledWith({action:'play',context_uri:'spotify:playlist:Tamil',offset_position:50});
});
test('collection sorting fetches later pages and refresh restores provider ordering',async()=>{
  const browse=api.spotifyBrowse.getMockImplementation();
  api.spotifyBrowse.mockImplementation(args=>args.kind==='playlists'?Promise.resolve(args.offset?{items:[playlist('A','A playlist')],total:2,next_offset:null}:{items:[playlist('Z','Z playlist')],total:2,next_offset:20}):browse(args));
  await render();await navigate('Playlists');await click('Sort music collection');await press('Name A–Z');
  expect([...host.querySelectorAll('.music-collection-card b')].map(node=>node.textContent)).toEqual(['A playlist','Z playlist']);
  await click('Refresh music collection');expect(host.querySelector('[aria-label="Sort music collection"]').textContent).toContain('Spotify order');
});
test('rename reviews the exact playlist and saves only after confirmation',async()=>{
  await editablePlaylist();await press('Edit playlist');await input('Playlist name','Road Trip');
  await act(async()=>host.querySelector('.music-playlist-editor form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(api.spotifyPlaylistEdit).toHaveBeenCalledWith({operation:'update_details',playlist_id:'Tamil',name:'Road Trip',description:'My songs'});
  expect(api.spotifyPlaylistConfirm).not.toHaveBeenCalled();await press('Save change');
  expect(api.spotifyPlaylistConfirm).toHaveBeenCalledWith(expect.objectContaining({confirmation:{token:'review'}}),expect.objectContaining({playlist_id:'Tamil',name:'Road Trip'}));
  expect(host.querySelector('.music-playlist-editor')).toBeNull();expect(host.textContent).toContain('Renamed Tamil');
});
test('a followed playlist can be removed with review but cannot be renamed',async()=>{
  await openPlaylist();expect(textButton('Edit playlist').disabled).toBe(true);await press('Remove from library');
  expect(api.spotifyPlaylistEdit).toHaveBeenCalledWith({operation:'remove',playlist_id:'Tamil'});await press('Cancel change');
  expect(api.spotifyPlaylistCancel).toHaveBeenCalledOnce();expect(api.spotifyPlaylistConfirm).not.toHaveBeenCalled();
});
test('song edits retain exact URI and do not start playback',async()=>{
  await editablePlaylist();await click('Remove First song from playlist');expect(api.spotifyPlaylistEdit).toHaveBeenCalledWith({operation:'remove_items',playlist_id:'Tamil',uris:['spotify:track:First']});
  await press('Cancel change');await press('Edit playlist');await input('Search songs to add','Ride');
  await act(async()=>host.querySelector('.music-add-song').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));await click('Add Ride to playlist');
  expect(api.spotifyPlaylistEdit).toHaveBeenLastCalledWith({operation:'add_items',playlist_id:'Tamil',uris:['spotify:track:Ride']});expect(music.run).not.toHaveBeenCalled();
});
test('failed confirmation preserves the unsaved editor and provider message',async()=>{
  await editablePlaylist();await press('Edit playlist');await input('Playlist name','Road Trip');
  await act(async()=>host.querySelector('.music-playlist-editor form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  api.spotifyPlaylistConfirm.mockResolvedValue({status:'failed',message:'Playlist changed; refresh and retry.'});await press('Save change');
  expect(host.textContent).toContain('Playlist changed; refresh and retry.');expect(host.querySelector('[aria-label="Playlist name"]').value).toBe('Road Trip');
});
test('editor controls require discovery in the App Action catalog',async()=>{
  window.VellumApi.appActions.catalog.mockResolvedValue({actions:[]});await editablePlaylist();
  expect(textButton('Edit playlist').disabled).toBe(true);expect(textButton('Remove from library').disabled).toBe(true);
});
test('liked songs remain a collection with playback restricted to returned tracks',async()=>{
  await render();await navigate('Playlists');await press('Liked Songs55 songs');
  expect(music.run).not.toHaveBeenCalled();await click('Play Liked Songs');
  expect(music.run).toHaveBeenCalledWith({action:'play',uris:['spotify:track:Liked']});
});
test('duplicate tracks and pagination retain exact positions',async()=>{
  const browse=api.spotifyBrowse.getMockImplementation();api.spotifyBrowse.mockImplementation(args=>args.kind==='playlist_tracks'?Promise.resolve(args.offset?{items:[{...song('Same','Repeated'),position:50}],total:51,next_offset:null}:{items:[{...song('Same','Repeated'),position:0}],total:51,next_offset:50}):browse(args));
  await openPlaylist();await press('Load more songs');expect(host.querySelectorAll('.music-track-row')).toHaveLength(2);
  await act(async()=>host.querySelectorAll('.music-track-row')[1].click());expect(music.run).toHaveBeenCalledWith({action:'play',context_uri:'spotify:playlist:Tamil',offset_position:50});
});
test('closing a loading collection ignores its late response',async()=>{
  let resolveTracks;const browse=api.spotifyBrowse.getMockImplementation();
  api.spotifyBrowse.mockImplementation(args=>args.kind==='playlist_tracks'?new Promise(resolve=>{resolveTracks=resolve;}):browse(args));
  await openPlaylist();await press('Back to your collection');await act(async()=>resolveTracks({items:[song('Old','Old song')],total:1,next_offset:null}));
  expect(host.querySelector('.music-detail')).toBeNull();
});
test('a restricted playlist keeps exact playback and a sandboxed Spotify view',async()=>{
  const browse=api.spotifyBrowse.getMockImplementation();api.spotifyBrowse.mockImplementation(args=>args.kind==='playlist_tracks'?Promise.reject(Object.assign(new Error('Restricted'),{status:403})):browse(args));
  await openPlaylist();expect(host.querySelectorAll('.music-track-row')).toHaveLength(0);
  expect(host.querySelector('iframe').getAttribute('src')).toBe('https://open.spotify.com/embed/playlist/Tamil?theme=0');
  await press('Play in Vellum');expect(music.run).toHaveBeenCalledWith({action:'play',context_uri:'spotify:playlist:Tamil'});
});
test('search submits through the catalog adapter and albums open without autoplay',async()=>{
  api.spotifySearch.mockResolvedValue({items:[album('Night','Night Drive')],total:1});
  await render();await input('Search songs, artists, albums','Night');
  await act(async()=>host.querySelector('.music-search').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  await press('Albums');expect(api.spotifySearch).toHaveBeenLastCalledWith({query:'Night',kind:'album'},expect.any(AbortSignal));
  await act(async()=>host.querySelector('.mw-top-result').click());expect(music.run).not.toHaveBeenCalled();await click('Play Night Drive');
  expect(music.run).toHaveBeenCalledWith({action:'play',context_uri:'spotify:album:Night'});
});
test('volume and seek dispatch once on commit and show measured volume',async()=>{
  await render();const volume=host.querySelector('[aria-label="Music volume"]');
  await act(async()=>{volume.value='80';volume.dispatchEvent(new KeyboardEvent('keyup',{key:'ArrowRight',bubbles:true}));});
  expect(music.run).toHaveBeenCalledWith({action:'set_volume',volume_percent:80});
  await render({player:{...music.player,device:{volume_percent:80}}});expect(host.querySelector('output').textContent).toBe('80%');
  const seek=host.querySelector('[aria-label="Music playback position"]');await act(async()=>{seek.value='10000';seek.dispatchEvent(new KeyboardEvent('keyup',{key:'ArrowLeft',bubbles:true}));});
  expect(music.run).toHaveBeenLastCalledWith({action:'seek',position_ms:10000});
});
test('pause state and previous/next controls use the existing player',async()=>{
  await render({player:{...music.player,is_playing:false}});await click('Previous song');expect(music.run).toHaveBeenLastCalledWith({action:'previous'});
  await click('Next song');expect(music.run).toHaveBeenLastCalledWith({action:'next'});await click('Play music');expect(music.run).toHaveBeenLastCalledWith({action:'play'});
});
test('mute restores the measured pre-mute volume',async()=>{
  await render();await click('Mute music');expect(music.run).toHaveBeenLastCalledWith({action:'set_volume',volume_percent:0});
  await render({player:{...music.player,device:{volume_percent:0}}});await click('Unmute music');expect(music.run).toHaveBeenLastCalledWith({action:'set_volume',volume_percent:25});
});
test('queue selection starts at the selected upcoming position',async()=>{
  await render({upcoming:[song('One','One'),song('Two','Two'),song('Three','Three')]});await click('Open music queue');
  expect(host.querySelectorAll('.music-queue-item')).toHaveLength(3);await act(async()=>host.querySelectorAll('.music-queue-item')[1].click());
  expect(music.run).toHaveBeenCalledWith({action:'play',uris:['spotify:track:Two','spotify:track:Three']});
});
test('local first run shows the three handoff choices and no empty player bar',async()=>{
  await render();await press('Local files');expect(host.textContent).toContain('Add your music');expect(host.querySelectorAll('.mw-add-card')).toHaveLength(3);
  expect(host.querySelector('.mw-player')).toBeNull();expect(host.textContent).not.toContain('Download missing YouTube');
});
test('returning local users see their library and missing audio stays unplayable',async()=>{
  localState.collections=[{id:'owned',name:'My playlist',entries:[{id:'one',title:'Owned song',artist:'Artist',available:true},{id:'missing',title:'Missing song',available:false}]}];
  await render();await press('Local files');expect(host.textContent).toContain('Your music');expect(host.textContent).toContain('1 of 2 songs matched');
  expect(host.querySelector('[aria-label="Play local Missing song"]').disabled).toBe(true);await press('Play available songs');
  expect(window.VellumApi.localMusic.action).toHaveBeenCalledWith('playback',{action:'play',entry_ids:['one'],position:0});
});
test('settings changes only music accents while preserving host background',async()=>{
  await render();await navigate('Settings');await click('Match my service');
  const select=host.querySelector('[aria-label="Music theme"]');await act(async()=>{select.value='Ocean';select.dispatchEvent(new Event('change',{bubbles:true}));});
  expect(host.querySelector('.mw-workspace').dataset.musicTheme).toBe('Ocean');expect(document.documentElement.dataset.theme).not.toBe('Ocean');
  expect(host.querySelector('[aria-label="Audio quality"]').disabled).toBe(true);
});
test('subscription-lapsed state offers metadata preservation without playing',async()=>{
  props.spotify.product='free';await render();expect(host.textContent).toContain('Your Spotify subscription ended');
  expect(host.querySelector('[aria-label="Play music"]').disabled).toBe(true);await press('Save playlists to Local');expect(host.textContent).toContain('Audio is never copied');
});
test('Sources uses existing Spotify connection and keeps Apple integration deferred',async()=>{
  await render();await navigate('Sources');expect(host.textContent).toContain('Integration coming later.');
  await press('Manage connection');expect(props.onReconnect).toHaveBeenCalledOnce();await press('Sync now');expect(props.onRefreshConnection).toHaveBeenCalledOnce();
});
test('unavailable playback exposes the existing enable action',async()=>{
  await render({playback:{ready:false,status:'unsupported',message:'Widevine unavailable'}});expect(host.textContent).toContain('Widevine unavailable');
  await press('Enable playback');expect(music.enable).toHaveBeenCalledOnce();
});
test('failed reads are visible without manufacturing a successful empty library',async()=>{
  api.spotifyBrowse.mockRejectedValue(new Error('Spotify rate limit; try later'));await render();expect(host.textContent).toContain('Spotify rate limit; try later');
  await navigate('Playlists');expect(host.textContent).not.toContain('No saved playlists');
});

test('public playlist rows keep exact positions and disclose incomplete metadata',async()=>{
  const browse=api.spotifyBrowse.getMockImplementation();api.spotifyBrowse.mockImplementation(args=>args.kind==='playlist_tracks'?Promise.resolve({items:[{...song('Public','Public song'),position:7}],total:1,next_offset:null,source:'public_embed',completeness:'unknown',note:'Public view may omit songs.'}):browse(args));
  await openPlaylist();expect(host.textContent).toContain('1 visible songs');expect(host.querySelector('.mw-public-source')).toBeNull();
  await click('Play Public song by Artist');expect(music.run).toHaveBeenCalledWith({action:'play',context_uri:'spotify:playlist:Tamil',offset_position:7});
});
test('playlist links use an exact typed action instead of matching names',async()=>{
  await render();await navigate('Sources');await input('Spotify playlist links','https://open.spotify.com/playlist/AAAAAAAAAAAAAAAAAAAAAA https://open.spotify.com/playlist/BBBBBBBBBBBBBBBBBBBBBB');
  await act(async()=>host.querySelector('.mw-playlist-links').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(window.VellumApi.appActions.dispatch).toHaveBeenCalledWith({action_id:'spotify.playlists.link',arguments:{uris:['spotify:playlist:AAAAAAAAAAAAAAAAAAAAAA','spotify:playlist:BBBBBBBBBBBBBBBBBBBBBB']}},{source:'ui'});
});
test('album art uses the canonical player cover while opening Lyrics retains it',async()=>{
  await render({player:{...music.player,artwork_url:'https://images.example/canonical.jpg'}});
  expect(host.querySelector('.mw-player-info img').src).toBe('https://images.example/canonical.jpg');
  await click('Open music queue');await press('Lyrics');expect(host.querySelector('.mw-now-cover').src).toBe('https://images.example/canonical.jpg');
});

test('pending controls retain their normal opacity instead of flashing dark',async()=>{
  const style=document.createElement('style');style.textContent=readFileSync(resolve(rootPath,'design/Velllum/uploads/components/music-page.css'),'utf8');document.head.append(style);
  try{await render({busy:true});expect(getComputedStyle(host.querySelector('[aria-label="Pause music"]')).opacity).toBe('1');}
  finally{style.remove();}
});
test('Recently played snapshots retain the canonical artwork artist and duration',async()=>{
  await render({player:{track:{id:'First',uri:'spotify:track:First',name:'First recording'},artwork_url:'https://images.example/first.jpg',artists:['First artist'],duration_ms:201000,is_playing:true,device:{volume_percent:50}}});
  await render({player:{...music.player,track:song('Next','Next recording'),artwork_url:'https://images.example/next.jpg',artists:['Next artist']}});
  const row=[...host.querySelectorAll('.mw-recent-tracks .mw-result-row')].find(row=>row.textContent.includes('First recording'));
  expect(row.querySelector('img')?.src).toBe('https://images.example/first.jpg');expect(row.textContent).toContain('First artist');expect(row.textContent).toContain('3:21');
});
test('linked-playlist artwork can load independently after text rows appear',async()=>{
  const id='A'.repeat(22),browse=api.spotifyBrowse.getMockImplementation();
  api.spotifyTrackArtwork=vi.fn(async()=>({id,artwork_url:'https://images.example/public-track.jpg'}));
  api.spotifyBrowse.mockImplementation(args=>args.kind==='playlist_tracks'?Promise.resolve({items:[{...song(id,'Public song'),artwork_url:''}],total:1,next_offset:null,source:'public_embed',note:'Songs shown by Spotify’s public playlist view.'}):browse(args));
  await openPlaylist();expect(host.querySelector('.music-track-title img')?.src).toBe('https://images.example/public-track.jpg');
  expect(host.textContent).not.toContain('Songs shown by Spotify’s public playlist view.');
});
test('Ask Vellum is absent from the music sidebar',async()=>{
  await render();expect([...host.querySelectorAll('.mw-nav button')].map(button=>button.textContent)).not.toContain('Ask Vellum');
});
test('the canonical now-playing cover remains visible in Settings and Sources',async()=>{
  await render({player:{...music.player,artwork_url:'https://images.example/current.jpg'}});
  for(const screen of ['Settings','Sources']){await navigate(screen);expect(host.querySelector('.mw-player-info img')?.src).toBe('https://images.example/current.jpg');expect(host.querySelectorAll('.mw-player')).toHaveLength(1);}
});
test('a pending Sources sync retains the control appearance',async()=>{
  const style=document.createElement('style');style.textContent=readFileSync(resolve(rootPath,'design/Velllum/uploads/components/music-page.css'),'utf8');document.head.append(style);
  let finish;const browse=api.spotifyBrowse.getMockImplementation();
  try{
    await render();await navigate('Sources');api.spotifyBrowse.mockImplementation(args=>args.kind==='playlists'?new Promise(resolve=>{finish=resolve;}):browse(args));
    await press('Sync now');expect(textButton('Sync now').disabled).toBe(true);expect(getComputedStyle(textButton('Sync now')).opacity).toBe('1');
    await act(async()=>finish({items:[],total:0,next_offset:null}));
  }finally{style.remove();}
});


test.each(['Settings','Sources'])('sidebar playlist navigation leaves %s and opens the selected songs',async screen=>{
  await render();await navigate(screen);
  await act(async()=>[...host.querySelectorAll('.mw-sidebar-playlists button')].find(node=>node.textContent==='Tamil').click());
  expect(host.querySelector('.music-detail h1')?.textContent).toBe('Tamil');
  expect(host.querySelectorAll('.music-track-row')).toHaveLength(2);
});

test('recently played shows the current individual track immediately',async()=>{
  await render();const row=host.querySelector('.mw-recent-tracks .mw-result-row');
  expect(row?.textContent).toContain('Ride');expect(row?.textContent).toContain('Artist');
});

test('home offers saved playlists and more than five saved albums',async()=>{
  const browse=api.spotifyBrowse.getMockImplementation();api.spotifyBrowse.mockImplementation(args=>args.kind==='albums'?Promise.resolve({items:Array.from({length:8},(_,i)=>album('A'+i,'Album '+i)),total:8,next_offset:null}):browse(args));
  await render();expect(host.querySelector('.mw-home-playlists')?.textContent).toContain('Tamil');expect(host.querySelectorAll('.mw-home-albums .music-collection-card')).toHaveLength(8);
  expect(host.querySelector('.mw-brand')).toBeNull();
});


test('accepted file imports open Imported files instead of leaving the add screen visible',async()=>{
  window.VellumApi.localMusic.upload.mockImplementation(async()=>{localState.collections=[{id:'imports',name:'Imported files',entries:[{id:'owned',title:'My WAV song',artist:'Me',available:true}]}];return {status:'applied',message:'Audio added',result:{entry_id:'owned'}};});
  await render();await press('Local files');await navigate('Add music');
  const node=host.querySelector('[aria-label="Choose local audio files"]');Object.defineProperty(node,'files',{value:[new File(['audio'],'song.wav',{type:'audio/wav'})],configurable:true});
  await act(async()=>node.dispatchEvent(new Event('change',{bubbles:true})));
  expect(host.querySelector('.mw-local-library')?.textContent).toContain('My WAV song');expect(host.querySelector('.mw-add-page')).toBeNull();
});


test('playlist artwork warms before offscreen rows intersect',async()=>{
  const prior=globalThis.IntersectionObserver;
  globalThis.IntersectionObserver=class {observe(){}disconnect(){}};
  const id='A'.repeat(22),browse=api.spotifyBrowse.getMockImplementation();api.spotifyTrackArtwork=vi.fn(async()=>({id,artwork_url:'https://images.example/cover'}));
  api.spotifyBrowse.mockImplementation(args=>args.kind==='playlist_tracks'?Promise.resolve({items:[{...song(id,'Song'),artwork_url:''}],total:1,next_offset:null}):browse(args));
  try{await openPlaylist();expect(api.spotifyTrackArtwork).toHaveBeenCalledWith(id);}finally{globalThis.IntersectionObserver=prior;}
});

test('outer navigation is retained and its Music image has bounded icon dimensions',()=>{
  const html=readFileSync(resolve(rootPath,'design/Velllum/uploads/Vellum Default Re-designed.html'),'utf8');
  expect(html).toContain('className="main-sidebar-slot"');expect(html).toContain('data-collapsible="offcanvas"');expect(html).toContain('data-pinned={sidebarPinned}');
  const style=document.createElement('style');style.textContent=readFileSync(resolve(rootPath,'design/Velllum/uploads/components/music-page.css'),'utf8');document.head.append(style);
  const icon=document.createElement('img');icon.className='music-nav-icon';host.append(icon);
  try{expect(getComputedStyle(icon).width).toBe('18px');expect(getComputedStyle(icon).height).toBe('18px');}finally{style.remove();}
});


test('search suggests songs and artists while typing without submitting or playing',async()=>{
  await render();await navigate('Search');
  vi.useFakeTimers();
  try{
    await input('Search songs, artists, albums','Ri');
    expect(api.spotifySearch).not.toHaveBeenCalled();
    await act(async()=>vi.advanceTimersByTimeAsync(300));
    expect(api.spotifySearch).toHaveBeenCalledWith(expect.objectContaining({query:'Ri',kind:'track'}),expect.anything());
    expect(api.spotifySearch).toHaveBeenCalledWith(expect.objectContaining({query:'Ri',kind:'artist'}),expect.anything());
    expect(host.querySelector('#mw-search-suggestions')?.textContent).toContain('Ride');expect(music.run).not.toHaveBeenCalled();
  }finally{vi.useRealTimers();}
});

test('local song rows and player show the supplied embedded cover',async()=>{
  localState.collections=[{id:'imports',name:'Imported files',entries:[{id:'owned',title:'My song',artist:'Me',available:true,artwork_url:'https://images.example/embedded.png'}]}];
  localState.player.observed={entry_id:'owned'};
  await render();await press('Local files');
  expect(host.querySelector('.mw-local-song img')?.src).toBe('https://images.example/embedded.png');
  expect(host.querySelector('.mw-player-info img')?.src).toBe('https://images.example/embedded.png');
});


test('suggestion keyboard selection searches a song without autoplay',async()=>{
  api.spotifySearch.mockImplementation(async args=>({items:args.kind==='artist'?[{...song('Person','Artist match'),uri:'spotify:artist:Person',kind:'artist'}]:[song('Ride','Ride')]}));
  await render();await navigate('Search');vi.useFakeTimers();
  try{
    await input('Search songs, artists, albums','Ri');await act(async()=>vi.advanceTimersByTimeAsync(300));
    expect(host.querySelector('#mw-search-suggestions').textContent).toContain('Artist match');
    const node=host.querySelector('[aria-label="Search songs, artists, albums"]');
    await act(async()=>node.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true})));
    expect(node.getAttribute('aria-activedescendant')).toBe('mw-suggestion-0');
    await act(async()=>node.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true})));
    expect(host.querySelector('#mw-search-suggestions')).toBeNull();expect(api.spotifySearch).toHaveBeenLastCalledWith({query:'Ride',kind:'track'},expect.anything());expect(music.run).not.toHaveBeenCalled();
  }finally{vi.useRealTimers();}
});

test('late suggestions never replace a newer query or survive clearing search',async()=>{
  const waiting=[];api.spotifySearch.mockImplementation(args=>new Promise(resolve=>waiting.push({query:args.query,resolve})));
  await render();await navigate('Search');vi.useFakeTimers();
  try{
    await input('Search songs, artists, albums','old');await act(async()=>vi.advanceTimersByTimeAsync(300));
    await input('Search songs, artists, albums','new');await act(async()=>vi.advanceTimersByTimeAsync(300));
    await act(async()=>waiting.filter(row=>row.query==='new').forEach(row=>row.resolve({items:[song('New','New song')]})));
    await act(async()=>waiting.filter(row=>row.query==='old').forEach(row=>row.resolve({items:[song('Old','Old song')]})));
    expect(host.querySelector('#mw-search-suggestions').textContent).toContain('New song');expect(host.querySelector('#mw-search-suggestions').textContent).not.toContain('Old song');
    await click('Clear music search');expect(host.querySelector('#mw-search-suggestions')).toBeNull();
  }finally{vi.useRealTimers();}
});

test('local references without covers use track numbers without image lookups',async()=>{
  const id='Z'.repeat(22);api.spotifyTrackArtwork=vi.fn(async()=>({id,artwork_url:'https://images.example/reference.png'}));
  localState.collections=[{id:'list',name:'Imported list',entries:[{id:'reference',title:'Reference song',provider:'spotify',source_id:id,available:false}]}];
  await render();await press('Local files');expect(api.spotifyTrackArtwork).not.toHaveBeenCalled();expect(host.querySelector('.mw-song-index')?.textContent).toBe('1');expect(host.querySelector('.mw-local-song .music-artwork-empty')).toBeNull();
});


test('the Home search field suggests during typing without Enter or route changes',async()=>{
  await render();vi.useFakeTimers();
  try{await input('Search songs, artists, albums','Ri');await act(async()=>vi.advanceTimersByTimeAsync(300));expect(host.querySelector('#mw-search-suggestions')?.textContent).toContain('Ride');expect(music.run).not.toHaveBeenCalled();}finally{vi.useRealTimers();}
});

test('provider dropdown switches source and music sidebar can hide and reopen independently',async()=>{
  await render();const select=host.querySelector('[aria-label="Music provider"]');expect(select.closest('.mw-provider-control')).toBeTruthy();
  await press('Local files');
  expect(host.textContent).toContain('Add your music');
  await click('Hide music sidebar');expect(host.querySelector('.mw-sidebar').getAttribute('aria-hidden')).toBe('true');expect(host.querySelector('[aria-label="Show music sidebar"]')).toBeTruthy();
  await click('Show music sidebar');expect(host.querySelector('[aria-label="Music provider"]').textContent).toContain('Local files');expect(props.onCloseMusic).not.toHaveBeenCalled();
});
