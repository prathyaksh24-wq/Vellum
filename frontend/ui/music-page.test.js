import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {afterEach, beforeEach, expect, test, vi} from 'vitest';

const require = createRequire(import.meta.url);
const path = resolve(dirname(fileURLToPath(import.meta.url)), '../../design/Velllum/uploads/components/music-page.jsx');
const uint = globalThis.Uint8Array;
let compiled;
try {
  globalThis.Uint8Array = new TextEncoder().encode('').constructor;
  compiled = createRequire(require.resolve('vite'))('esbuild').transformSync(readFileSync(path,'utf8'),{loader:'jsx'}).code;
} finally {globalThis.Uint8Array = uint;}
let root, host, api, music, Player, images;
const song = (id, name) => ({id,uri:'spotify:track:' + id,name,kind:'track',artists:['Artist'],artwork_url:'https://images.example/' + id,playable:true});
const playlist = (id,name) => ({id,uri:'spotify:playlist:' + id,name,kind:'playlist',artists:[],artwork_url:'',playable:true});
const click = async label => act(async () => host.querySelector('[aria-label="' + label + '"]').click());
const textButton = text => [...host.querySelectorAll('button')].find(b => b.textContent === text);
async function render(overrides = {}) {
  Object.assign(music,overrides);
  await act(async () => root.render(React.createElement(Player,{spotify:{connected:true,web_playback_ready:true},music,onReconnect:vi.fn()})));
}
beforeEach(async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  images = [];
  vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({clearRect:vi.fn(),drawImage:vi.fn()});
  vi.stubGlobal('Image',class {constructor() { images.push(this); }});
  api = {
    capabilities:vi.fn(async () => ({features:{spotify:{enabled:true,endpoints:{browse:'browse',search:'search'}}}})),
    spotifyBrowse:vi.fn(async args => args.kind === 'liked' ? {items:[song('Liked','Liked song')],total:55,next_offset:null} : args.kind.endsWith('_tracks') ? {items:[song('First','First song'),song('Second','Second song')],total:2,next_offset:null} : {items:[playlist('Emoji','🌙✨'),playlist('Tamil','Tamil')],total:2,next_offset:null}),
    spotifySearch:vi.fn(async () => ({items:[song('Ride','Ride')],total:1})),
    spotifyPlaylistEdit:vi.fn(async () => ({status:'confirmation_required',message:'Rename Tamil to Road Trip?',confirmation:{token:'review'}})),
    spotifyPlaylistConfirm:vi.fn(async () => ({status:'applied',message:'Renamed Tamil to Road Trip.',result:{playlist_id:'Tamil',name:'Road Trip',operation:'update_details'}})),
    spotifyPlaylistCancel:vi.fn(async () => ({status:'cancelled'})),
  };
  window.VellumApi = {plugins:api,appActions:{catalog:vi.fn(async () => ({actions:[{id:'spotify.playlist.edit'}]}))}}; window.VellumUI = {};
  new Function('React',compiled)(React); Player = window.VellumUI.MusicPage;
  music = {player:{track:song('Ride','Ride'),artwork_url:'https://images.example/Ride',artists:['Twenty One Pilots'],album:'Blurryface',is_playing:true,duration_ms:214000,progress_ms:84000,device:{volume_percent:25}},
    playback:{ready:true},upcoming:[],busy:false,error:'',run:vi.fn(async () => true),refresh:vi.fn(),enable:vi.fn()};
});

const inputValue = async (label,value) => act(async () => {
  const input = host.querySelector('[aria-label="'+label+'"]');
  const prototype = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype,'value').set.call(input,value);
  input.dispatchEvent(new Event('input',{bubbles:true}));
});
async function editablePlaylist() {
  const browse=api.spotifyBrowse.getMockImplementation();
  api.spotifyBrowse.mockImplementation(args => args.kind === 'playlist_details' ? Promise.resolve({items:[{...playlist('Tamil','Tamil'),description:'My songs',editable:true}]}) : browse(args));
  await render();await act(async () => host.querySelector('.music-collection-card:last-child').click());
}

test('editing stays unavailable when the backend action catalog does not expose it',async () => {
  window.VellumApi.appActions.catalog.mockResolvedValue({actions:[]});
  await editablePlaylist();
  expect(textButton('Edit playlist').disabled).toBe(true);
  expect(textButton('Remove from library').disabled).toBe(true);
  expect(host.querySelector('[aria-label="Remove First song from playlist"]').disabled).toBe(true);
  expect(api.spotifyPlaylistEdit).not.toHaveBeenCalled();
});

test('refresh resets a complete sorted collection before fetching its first page',async () => {
  await render();await click('Sort music collection');await act(async () => textButton('Name A–Z').click());
  await click('Refresh music collection');
  expect(host.querySelector('[aria-label="Sort music collection"]').textContent).toContain('Spotify order');
});

test('collection sort fetches later pages before ordering all playlist names',async () => {
  const browse=api.spotifyBrowse.getMockImplementation();
  api.spotifyBrowse.mockImplementation(args => args.kind==='playlists' ? Promise.resolve(args.offset ? {items:[playlist('A','A playlist')],next_offset:null,total:2} : {items:[playlist('Z','Z playlist')],next_offset:20,total:2}) : browse(args));
  await render();await click('Sort music collection');await act(async () => textButton('Name A–Z').click());
  expect(api.spotifyBrowse).toHaveBeenCalledWith({kind:'playlists',offset:20,limit:50},expect.any(AbortSignal));
  expect([...host.querySelectorAll('.music-collection-card b')].map(e => e.textContent)).toEqual(['Liked Songs','A playlist','Z playlist']);
  expect(music.run).not.toHaveBeenCalled();expect(api.spotifyPlaylistEdit).not.toHaveBeenCalled();
});

test('song sorting keeps exact original positions when playing a reordered row',async () => {
  const browse=api.spotifyBrowse.getMockImplementation();
  api.spotifyBrowse.mockImplementation(args => args.kind==='playlist_tracks' ? Promise.resolve(args.offset ? {items:[{...song('A','A song'),position:50}],next_offset:null,total:51} : {items:[{...song('Z','Z song'),position:0}],next_offset:50,total:51}) : browse(args));
  await render();await act(async () => host.querySelector('.music-collection-card:last-child').click());
  await click('Sort playlist songs');await act(async () => textButton('Title A–Z').click());
  expect([...host.querySelectorAll('.music-track-title b')].map(e => e.textContent)).toEqual(['A song','Z song']);
  await click('Play A song by Artist');
  expect(music.run).toHaveBeenCalledWith({action:'play',context_uri:'spotify:playlist:Tamil',offset_position:50});
  await click('Sort playlist songs');await act(async () => textButton('Playlist order').click());
  expect([...host.querySelectorAll('.music-track-title b')].map(e => e.textContent)).toEqual(['Z song','A song']);
});

test('rename reviews the exact playlist and saves only after confirmation',async () => {
  await editablePlaylist();await act(async () => textButton('Edit playlist').click());
  await inputValue('Playlist name','Road Trip');
  await act(async () => host.querySelector('.music-playlist-editor form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(api.spotifyPlaylistEdit).toHaveBeenCalledWith({operation:'update_details',playlist_id:'Tamil',name:'Road Trip',description:'My songs'});
  expect(api.spotifyPlaylistConfirm).not.toHaveBeenCalled();expect(host.textContent).toContain('Rename Tamil to Road Trip?');
  await act(async () => textButton('Save change').click());
  expect(api.spotifyPlaylistConfirm).toHaveBeenCalledWith(expect.objectContaining({confirmation:{token:'review'}}),{operation:'update_details',playlist_id:'Tamil',name:'Road Trip',description:'My songs'});
  expect(api.spotifyBrowse).toHaveBeenCalledWith({kind:'playlist_details',source_id:'Tamil'});
  expect(host.querySelector('.music-playlist-editor')).toBeNull();expect(host.textContent).toContain('Renamed Tamil to Road Trip.');
});

test('followed playlist exposes removal but no editable name controls',async () => {
  await render();await act(async () => host.querySelector('.music-collection-card:last-child').click());
  expect(textButton('Edit playlist').disabled).toBe(true);expect(host.querySelector('.music-song-remove')).toBeNull();
  await act(async () => textButton('Remove from library').click());
  expect(api.spotifyPlaylistEdit).toHaveBeenCalledWith({operation:'remove',playlist_id:'Tamil'});
  await act(async () => textButton('Cancel change').click());
  expect(api.spotifyPlaylistCancel).toHaveBeenCalled();expect(api.spotifyPlaylistConfirm).not.toHaveBeenCalled();
});

test('remove-song and add-song buttons capture the selected URI without playing it',async () => {
  await editablePlaylist();await click('Remove First song from playlist');
  expect(api.spotifyPlaylistEdit).toHaveBeenCalledWith({operation:'remove_items',playlist_id:'Tamil',uris:['spotify:track:First']});
  await act(async () => textButton('Cancel change').click());
  await act(async () => textButton('Edit playlist').click());await inputValue('Search songs to add','Ride');
  await act(async () => host.querySelector('.music-add-song').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  await click('Add Ride to playlist');
  expect(api.spotifyPlaylistEdit).toHaveBeenLastCalledWith({operation:'add_items',playlist_id:'Tamil',uris:['spotify:track:Ride']});
  expect(music.run).not.toHaveBeenCalled();
});

test('failed confirmation shows provider error and retains the unsaved editor',async () => {
  await editablePlaylist();await act(async () => textButton('Edit playlist').click());await inputValue('Playlist name','Road Trip');
  await act(async () => host.querySelector('.music-playlist-editor form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  api.spotifyPlaylistConfirm.mockResolvedValue({status:'failed',message:'Playlist changed; refresh and retry.'});
  await act(async () => textButton('Save change').click());
  expect(host.textContent).toContain('Playlist changed; refresh and retry.');expect(host.querySelector('[aria-label="Playlist name"]').value).toBe('Road Trip');
  expect(api.spotifyPlaylistConfirm).toHaveBeenCalledTimes(1);
});

test('collection refresh updates liked count and cover as well as playlist cards',async () => {
  await render();const browse=api.spotifyBrowse.getMockImplementation();
  api.spotifyBrowse.mockImplementation(args => args.kind==='liked' ? Promise.resolve({items:[song('NewLiked','New liked')],total:56}) : browse(args));
  await click('Refresh music collection');
  expect(host.textContent).toContain('56 songs');
  expect(host.querySelector('.music-collection-card:first-child img').src).toBe('https://images.example/NewLiked');
});
afterEach(async () => {await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals();});

test('pause freezes the existing record and resuming keeps that record node',async () => {
  await render(); const record = host.querySelector('.music-record');
  expect(record.style.animationPlayState).toBe('running');
  await render({player:{...music.player,is_playing:false}});
  expect(host.querySelector('.music-record')).toBe(record);
  expect(record.style.animationPlayState).toBe('paused');
  await render({player:{...music.player,is_playing:true}});
  expect(record.style.animationPlayState).toBe('running');
});
test('a track change clears old pixels and only the newest artwork may fill the label',async () => {
  await render(); const first = images.at(-1);
  await render({player:{...music.player,track:song('New','New song'),artwork_url:'https://images.example/New'}});
  expect(first.onload).toBe(null);
  expect(host.querySelector('canvas').classList.contains('ready')).toBe(false);
  await act(async () => images.at(-1).onload());
  expect(host.querySelector('canvas').classList.contains('ready')).toBe(true);
  expect(host.querySelector('canvas').getAttribute('aria-label')).toBe('Pixelated cover for New song');
  expect(host.querySelector('.music-current-track img').getAttribute('src')).toBe('https://images.example/New');
});
test('emoji playlists open before playing and library pagination keeps all unique cards',async () => {
  api.spotifyBrowse.mockImplementation(async args => args.kind === 'liked' ? {items:[],total:0,next_offset:null} : args.kind === 'playlist_tracks' ? {items:[song('First','First song')],total:1,next_offset:null} : args.offset ? {items:[playlist('Emoji','🌙✨'),playlist('Later','Later page')],total:3,next_offset:null} : {items:[playlist('Emoji','🌙✨')],total:3,next_offset:20});
  await render();
  await act(async () => host.querySelector('.music-collection-card:last-child').click());
  expect(music.run).not.toHaveBeenCalled();
  expect(api.spotifyBrowse).toHaveBeenCalledWith({kind:'playlist_tracks',source_id:'Emoji',offset:0,limit:50},expect.any(AbortSignal));
  await click('Play 🌙✨');
  expect(music.run).toHaveBeenCalledWith({action:'play',context_uri:'spotify:playlist:Emoji'});
  await act(async () => textButton('Back to your collection').click());
  await act(async () => textButton('Load more').click());
  expect([...host.querySelectorAll('.music-collection-card b')].map(e => e.textContent)).toEqual(['Liked Songs','🌙✨','Later page']);
});

test.each([403,404])('an unexposed playlist keeps exact-context Play without inventing tracks for %s',async status => {
  const browse=api.spotifyBrowse.getMockImplementation();
  api.spotifyBrowse.mockImplementation(args => args.kind === 'playlist_tracks' ? Promise.reject(Object.assign(new Error('Denied'),{status})) : browse(args));
  await render(); await act(async () => host.querySelector('.music-collection-card:last-child').click());
  expect(host.textContent).toContain(status === 403 ? 'Spotify will not share' : 'Spotify has not exposed');
  expect(host.querySelectorAll('.music-track-row')).toHaveLength(0);
  expect(host.querySelector('[aria-label="Play Tamil"]').disabled).toBe(false);
  await click('Play Tamil');
  expect(music.run).toHaveBeenCalledWith({action:'play',context_uri:'spotify:playlist:Tamil'});
  expect(host.querySelector('.music-error a').href).toBe('https://open.spotify.com/playlist/Tamil');
});

test('paused Music-page previous and next dispatch navigation without restarting the song',async () => {
  await render({player:{...music.player,is_playing:false}});
  await click('Next song'); await click('Previous song'); await click('Play music');
  expect(music.run.mock.calls.map(([body]) => body)).toEqual([{action:'next'},{action:'previous'},{action:'play'}]);
});

test('pending transport controls keep their visual opacity instead of flashing dim',async () => {
  await render({busy:true});
  expect(host.querySelector('.music-page').dataset.controlBusy).toBe('true');
  const css=readFileSync(path.replace('.jsx','.css'),'utf8');
  const rule=css.split('\n').find(line => line.startsWith('.music-page[data-control-busy='));
  const style=document.createElement('style');style.textContent=rule;document.head.append(style);
  try {expect(getComputedStyle(host.querySelector('[aria-label="Next song"]')).opacity).toBe('1');}
  finally {style.remove();}
});

test('a linked Spotify mix opens its exact collection without substituting a saved name',async () => {
  api.spotifySearch.mockResolvedValue({items:[playlist('PersonalMix','Spotify playlist link')],total:1});
  await render();
  const input=host.querySelector('[aria-label="Search songs, artists, albums"]');
  await act(async () => {Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'https://open.spotify.com/playlist/PersonalMix');input.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async () => host.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  await act(async () => host.querySelector('.music-result').click());
  await click('Play Spotify playlist link');
  expect(music.run).toHaveBeenCalledWith({action:'play',context_uri:'spotify:playlist:PersonalMix'});
});
test('Liked Songs opens a song list with a Play button and no separate tab',async () => {
  await render(); await act(async () => textButton('Liked Songs55 songs').click());
  expect(api.spotifyBrowse).toHaveBeenCalledWith({kind:'liked',offset:0,limit:50},expect.any(AbortSignal));
  expect(music.run).not.toHaveBeenCalled();
  expect(host.querySelectorAll('.music-track-row')).toHaveLength(1);
  await click('Play Liked Songs');
  expect(music.run).toHaveBeenCalledWith({action:'play',uris:['spotify:track:Liked']});
});
test('volume and seek keyboard gestures dispatch once and display measured state',async () => {
  await render();
  const volume=host.querySelector('[aria-label="Music volume"]');
  await act(async () => {volume.value='80';volume.dispatchEvent(new KeyboardEvent('keyup',{key:'ArrowRight',bubbles:true}));});
  expect(music.run).toHaveBeenCalledTimes(1);
  expect(music.run).toHaveBeenCalledWith({action:'set_volume',volume_percent:80});
  await render({player:{...music.player,device:{volume_percent:80}}});
  expect(host.querySelector('output').textContent).toBe('80%');
  const seek=host.querySelector('[aria-label="Music playback position"]');
  await act(async () => {seek.value='10000';seek.dispatchEvent(new KeyboardEvent('keyup',{key:'ArrowLeft',bubbles:true}));});
  expect(music.run).toHaveBeenLastCalledWith({action:'seek',position_ms:10000});
});
test('mute/unmute restores the measured pre-mute level',async () => {
  await render();await click('Mute music');
  expect(music.run).toHaveBeenLastCalledWith({action:'set_volume',volume_percent:0});
  await render({player:{...music.player,device:{volume_percent:0}}});await click('Unmute music');
  expect(music.run).toHaveBeenLastCalledWith({action:'set_volume',volume_percent:25});
});
test('unavailable providers disclose their connection state and never control Spotify',async () => {
  await render();await act(async () => textButton('Apple Music').click());
  expect(host.textContent).toContain('This service is not connected to Vellum yet.');
  expect(host.querySelector('.music-record')).toBe(null);expect(music.run).not.toHaveBeenCalled();
});
test('a failed library read shows its error rather than a fabricated empty count',async () => {
  api.spotifyBrowse.mockRejectedValue(new Error('Spotify rate limit; try later'));
  await render();expect(host.textContent).toContain('Spotify rate limit; try later');
  expect(host.textContent).not.toContain('No saved playlists');
});
test('changing search types fetches the selected category and albums play by context',async () => {
  await render();
  const input=host.querySelector('[aria-label="Search songs, artists, albums"]');
  const setValue=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
  await act(async () => {setValue.call(input,'Blurryface');input.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async () => host.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  api.spotifySearch.mockResolvedValue({items:[{id:'BF',uri:'spotify:album:BF',name:'Blurryface',kind:'album',artists:['Twenty One Pilots'],playable:true}],total:1});
  await act(async () => textButton('Albums').click());
  expect(api.spotifySearch).toHaveBeenLastCalledWith({query:'Blurryface',kind:'album'},expect.any(AbortSignal));
  await act(async () => host.querySelector('.music-result').click());
  expect(music.run).not.toHaveBeenCalled();
  await click('Play Blurryface');
  expect(music.run).toHaveBeenCalledWith({action:'play',context_uri:'spotify:album:BF'});
});

test('grid and list collection views open the same saved identity',async () => {
  await render();
  expect(textButton('Liked songs')).toBeUndefined();
  await click('List view');
  expect(host.querySelectorAll('.music-collection-list .music-collection-card')).toHaveLength(3);
  await act(async () => host.querySelector('.music-collection-list .music-collection-card:last-child').click());
  expect(host.querySelector('.music-detail h2').textContent).toBe('Tamil');
  expect(music.run).not.toHaveBeenCalled();
  await click('Play Second song by Artist');
  expect(music.run).toHaveBeenCalledWith({action:'play',context_uri:'spotify:playlist:Tamil',offset_position:1});
});

test('detail pagination preserves duplicate songs and exact source positions',async () => {
  api.spotifyBrowse.mockImplementation(async args => args.kind === 'playlist_tracks' ? args.offset ? {items:[{...song('Same','Repeated'),position:50}],total:51,next_offset:null} : {items:[{...song('Same','Repeated'),position:0}],total:51,next_offset:50} : args.kind === 'liked' ? {items:[],total:0,next_offset:null} : {items:[playlist('Dup','Repeats')],total:1,next_offset:null});
  await render();await act(async () => host.querySelector('.music-collection-card:last-child').click());
  await act(async () => textButton('Load more songs').click());
  expect(host.querySelectorAll('.music-track-row')).toHaveLength(2);
  await act(async () => host.querySelectorAll('.music-track-row')[1].click());
  expect(music.run).toHaveBeenCalledWith({action:'play',context_uri:'spotify:playlist:Dup',offset_position:50});
});

test('closing a loading collection prevents a stale response from reopening it',async () => {
  let resolveFirst;
  api.spotifyBrowse.mockImplementation(args => args.kind === 'playlist_tracks' ? new Promise(resolve => {resolveFirst=resolve;}) : Promise.resolve(args.kind === 'liked' ? {items:[],total:0,next_offset:null} : {items:[playlist('Slow','Slow playlist')],total:1,next_offset:null}));
  await render();await act(async () => host.querySelector('.music-collection-card:last-child').click());
  await act(async () => textButton('Back to your collection').click());
  await act(async () => resolveFirst({items:[song('Old','Old song')],total:1,next_offset:null}));
  expect(host.querySelector('.music-detail')).toBeNull();
  expect(host.querySelector('.music-collection')).not.toBeNull();
});

test('the full queue can be expanded and selecting a row plays from that position',async () => {
  const upcoming=['One','Two','Three','Four','Five'].map(id => song(id,id));
  await render({upcoming});
  expect(host.querySelectorAll('.music-queue-item')).toHaveLength(3);
  await act(async () => textButton('See queue').click());
  expect(host.querySelectorAll('.music-queue-item')).toHaveLength(5);
  await act(async () => host.querySelectorAll('.music-queue-item')[3].click());
  expect(music.run).toHaveBeenCalledWith({action:'play',uris:['spotify:track:Four','spotify:track:Five']});
});


test('missing artwork stays a square thumbnail instead of stretching across list rows',async () => {
  const style=document.createElement('style');
  style.textContent=readFileSync(resolve(dirname(path),'music-page.css'),'utf8');document.head.append(style);
  try {
    await render();await click('List view');
    const placeholder=host.querySelector('.music-collection-list .music-artwork-empty');
    const measured=getComputedStyle(placeholder);
    expect(measured.width).toBe('56px');expect(measured.height).toBe('56px');
    expect(measured.flexGrow).toBe('0');expect(measured.flexShrink).toBe('0');
    expect(measured.display).toBe('flex');
  } finally {style.remove();}
});
