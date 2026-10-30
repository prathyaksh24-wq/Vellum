import React, {act, useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import * as ReactDOM from 'react-dom';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {afterEach, beforeEach, expect, test, vi} from 'vitest';

const html = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../design/Velllum/uploads/Vellum Default Re-designed.html'), 'utf8');
const musicCss=readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../design/Velllum/uploads/components/music-page.css'),'utf8');
const browserCss=readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../design/Velllum/uploads/components/browser-panel.css'),'utf8');
const source = html.slice(html.indexOf('let dockLastHiddenAt ='), html.indexOf('/* closes on a document-level')) +
  html.slice(html.indexOf('const DockMusicMarquee ='), html.indexOf('const SettingsModal ='));
const require = createRequire(import.meta.url);
// jsdom and Node use different typed-array realms; esbuild runs in Node's realm.
const browserUint8Array = globalThis.Uint8Array;
let compiled;
try {
  globalThis.Uint8Array = new TextEncoder().encode('').constructor;
  const {transformSync} = createRequire(require.resolve('vite'))('esbuild');
  compiled = transformSync(source, {loader:'jsx'}).code;
} finally { globalThis.Uint8Array = browserUint8Array; }
let root, host;
const track = (uri, name) => ({uri, name, artists:[{name:'Artist'}]});

async function renderPlayer(queue, sdk = false, options = {}) {
  const current = track('spotify:track:current', 'Current song');
  const api = {action:vi.fn(async () => ({})),player:vi.fn(async details => ({track:current, is_playing:true, repeat:'off', ...(details ? {queue} : {})}))};
  let emitState;
  const dispose=vi.fn();
  window.VellumSpotifyPlayback = {beginRequest:vi.fn(() => ({ready:Promise.resolve()})),create:vi.fn(options => {
    emitState = options.onPlayer;
    return {prepare:vi.fn(async () => {}), dispose};
  })};
  const plugins = {capabilities:vi.fn(async () => ({features:{spotify:{enabled:true,endpoints:{playback_token:'token'}}}}))};
  const iconNames=['IcPencilSq','IcSearch','IcLibrary','IcTerminal','IcSettings','IcPin','IcCheck'];
  const {Player,GlobalDock} = new Function('React','useState','useRef','useEffect','SpotifyAPI','API','I','fmtSpotifyTime','ReactDOM','AGENTS',...iconNames,
    compiled + '; return {Player:SpotifyPlayer,GlobalDock};')(React,useState,useRef,useEffect,api,{plugins,localMusic:options.localApi},() => null,() => '0:00',ReactDOM,[],...iconNames.map(() => () => null));
  const renderDock=(music,musicOpen,onDismissMusic) => React.createElement(GlobalDock, {
    side:options.dockSide || 'top',locked:false,view:'chat',agents:[],music,musicOpen,onDismissMusic,
    onLockedChange:vi.fn(),onNewChat:vi.fn(),onSearch:vi.fn(),onNav:vi.fn(),onCoding:vi.fn(),onOpenAgent:vi.fn(),onSettings:vi.fn(),
    ...options.dockProps,
  });
  const props={spotify:{connected:true,web_playback_ready:sdk},renderDock,...options};
  await act(async () => root.render(React.createElement(Player, props)));
  if (options.open !== false) {
    await act(async () => host.querySelector('[aria-label="Show dock"]').click());
    await act(async () => host.querySelector('[aria-label="Open Spotify player"]').click());
  }
  return {...api, emitState, Player, dispose, props};
}

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove(); vi.useRealTimers();
  vi.restoreAllMocks(); vi.unstubAllGlobals();
});

function marqueeMeasurements() {
  let available=100;
  const observers=[];
  vi.spyOn(HTMLElement.prototype,'clientWidth','get').mockImplementation(function() {return this.classList.contains('spotify-marquee') ? available : 0;});
  vi.spyOn(HTMLElement.prototype,'scrollWidth','get').mockImplementation(function() {return this.classList.contains('spotify-marquee-copy') ? this.textContent.length*7 : 0;});
  vi.stubGlobal('ResizeObserver',class {constructor(callback){this.callback=callback;this.disconnect=vi.fn();observers.push(this);}observe(){}});
  return {observers,resize:width=>{available=width;observers.forEach(observer=>observer.callback());}};
}

test('compact dock labels get an accessible marquee; expanded labels stay static', async () => {
  marqueeMeasurements();
  const api=await renderPlayer([],true);
  const song=track('spotify:track:long','A Very Long Song Title That Does Not Fit');
  await act(async () => api.emitState({track:song,artists:['An Artist Name That Does Not Fit'],is_playing:true}));
  const labels=host.querySelectorAll('.spotify-player-pill .spotify-marquee');
  expect([...labels].map(label=>label.classList.contains('has-marquee'))).toEqual([true,true]);
  expect([...labels].map(label=>label.dataset.playing)).toEqual(['true','true']);
  expect([...labels].every(label=>label.querySelector('[aria-hidden="true"]'))).toBe(true);
  expect(host.querySelector('.spotify-panel-copy b').textContent).toBe(song.name);
  expect(host.querySelector('.spotify-player-panel .spotify-marquee')).toBe(null);
  expect(host.querySelector('.spotify-player-pill button button')).toBe(null);
});

test('playback pauses and resumes the same marquee track without moving or recreating controls', async () => {
  marqueeMeasurements();
  const api=await renderPlayer([],true,{open:false});
  await act(async () => api.emitState({track:track('spotify:track:long','A Very Long Song Title That Does Not Fit'),is_playing:true}));
  const trackNode=host.querySelector('b .spotify-marquee-track'),button=host.querySelector('[aria-label="Pause Spotify"]');
  await act(async () => api.emitState({is_playing:false}));
  expect(host.querySelector('b .spotify-marquee-track')).toBe(trackNode);
  expect(host.querySelector('b.spotify-marquee').dataset.playing).toBe('false');
  expect(host.querySelector('[aria-label="Play Spotify"]')).toBe(button);
  await act(async () => api.emitState({is_playing:true}));
  expect(host.querySelector('b .spotify-marquee-track')).toBe(trackNode);
  expect(host.querySelector('b.spotify-marquee').dataset.playing).toBe('true');
  expect(window.VellumSpotifyPlayback.create).toHaveBeenCalledTimes(1);
});

test('short labels scroll with a full viewport between copies and remeasure when dock space changes', async () => {
  const sizes=marqueeMeasurements();
  const api=await renderPlayer([],true,{open:false});
  await act(async () => api.emitState({track:track('spotify:track:short','SOS'),artists:['SZA'],is_playing:true}));
  const title=host.querySelector('b.spotify-marquee');
  expect(title.classList.contains('has-marquee')).toBe(true);
  expect(title.dataset.playing).toBe('true');
  expect(title.style.getPropertyValue('--spotify-marquee-gap')).toBe('107px');
  expect(title.closest('.spotify-now').style.getPropertyValue('--spotify-marquee-distance')).toBe('128px');
  expect(title.querySelector('[aria-hidden="true"]').textContent).toBe('SOS');
  await act(async () => sizes.resize(200));
  expect(title.closest('.spotify-now').style.getPropertyValue('--spotify-marquee-distance')).toBe('228px');
  await act(async () => sizes.resize(0));
  expect(host.querySelector('.has-marquee')).toBe(null);
  await act(async () => sizes.resize(100));
  expect(title.classList.contains('has-marquee')).toBe(true);
  await act(async () => api.emitState({track:track('spotify:track:long','A Very Long Song Title That Does Not Fit')}));
  expect(host.querySelector('b.spotify-marquee').style.getPropertyValue('--spotify-marquee-gap')).toBe('28px');
});

test('different title and artist lengths share travel distance, timing and playback phase', async () => {
  marqueeMeasurements();
  const api=await renderPlayer([],true,{open:false});
  for (const [name,artist] of [['SOS','An Artist Name That Is Much Longer'],['A Song Title That Is Much Longer','SZA'],['SOS','SZA']]) {
    await act(async () => api.emitState({track:track('spotify:track:sync',name),artists:[artist],is_playing:true}));
    const now=host.querySelector('.spotify-now');
    const distance=Number.parseFloat(now.style.getPropertyValue('--spotify-marquee-distance'));
    const duration=Number.parseFloat(now.style.getPropertyValue('--spotify-marquee-duration'));
    expect(distance).toBe(Math.max(100,name.length*7,artist.length*7)+28);
    expect(duration).toBe(Math.max(12,distance/20));
    const labels=[...now.querySelectorAll('.spotify-marquee')];
    for (const label of labels) {
      const textWidth=label.querySelector('.spotify-marquee-copy').textContent.length*7;
      expect(textWidth+Number.parseFloat(label.style.getPropertyValue('--spotify-marquee-gap'))).toBe(distance);
      expect(label.style.getPropertyValue('--spotify-marquee-duration')).toBe('');
      expect(label.dataset.playing).toBe('true');
    }
    const tracks=[...now.querySelectorAll('.spotify-marquee-track')];
    await act(async () => api.emitState({is_playing:false}));
    expect([...now.querySelectorAll('.spotify-marquee')].map(label=>label.dataset.playing)).toEqual(['false','false']);
    await act(async () => api.emitState({is_playing:true}));
    expect([...now.querySelectorAll('.spotify-marquee-track')]).toEqual(tracks);
  }
});

test('music is inside the navigation dock and its pause button does not expand it', async () => {
  const api=await renderPlayer([],false,{open:false});
  const trigger=host.querySelector('[aria-label="Open Spotify player"]');
  expect(trigger.closest('[aria-label="Quick actions"]')).not.toBe(null);
  expect(trigger.getAttribute('aria-expanded')).toBe('false');
  await act(async () => host.querySelector('[aria-label="Pause Spotify"]').click());
  expect(api.action).toHaveBeenCalledExactlyOnceWith({action:'pause'});
  expect(trigger.getAttribute('aria-expanded')).toBe('false');
  expect(host.querySelector('[role="dialog"]')).toBe(null);
});

test('served external styles do not displace the dock player into the old floating corner', async () => {
  await renderPlayer([],false,{open:false});
  const style=document.createElement('style');
  style.textContent='.spotify-player-shell{position:relative;top:auto;right:auto;bottom:auto;left:auto}'+musicCss+browserCss;
  document.head.append(style);
  try {
    const shell=host.querySelector('.spotify-player-shell');
    for(const side of ['top','bottom','left','right']) {
      shell.className='spotify-player-shell side-'+side;
      expect(getComputedStyle(shell).bottom).toBe('auto');
      expect(getComputedStyle(shell).right).toBe('auto');
    }
  } finally {style.remove();}
});

test('an expanded player keeps the auto-hide dock open until outside dismissal', async () => {
  await renderPlayer([]);
  const shell=host.querySelector('.dock-shell');
  await act(async () => {shell.dispatchEvent(new MouseEvent('mouseout',{bubbles:true,relatedTarget:document.body})); await vi.advanceTimersByTimeAsync(1000);});
  expect(host.querySelector('.dock-layer').classList.contains('open')).toBe(true);
  expect(host.querySelector('[role="dialog"]')).not.toBe(null);
  await act(async () => document.body.dispatchEvent(new Event('pointerdown',{bubbles:true})));
  expect(host.querySelector('[role="dialog"]')).toBe(null);
  expect(host.querySelector('.dock-layer').classList.contains('open')).toBe(false);
});

test('keyboard focus keeps the dock open and Escape restores focus to the player trigger', async () => {
  await renderPlayer([]);
  await act(async () => host.querySelector('[aria-label="Spotify volume"]').focus());
  await act(async () => {host.querySelector('.dock-shell').dispatchEvent(new MouseEvent('mouseout',{bubbles:true,relatedTarget:document.body})); await vi.advanceTimersByTimeAsync(1000);});
  expect(host.querySelector('.dock-layer').classList.contains('open')).toBe(true);
  await act(async () => document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
  expect(host.querySelector('[role="dialog"]')).toBe(null);
  expect(document.activeElement).toBe(host.querySelector('[aria-label="Open Spotify player"]'));
  const outside=document.createElement('button');document.body.append(outside);
  await act(async () => {outside.focus();await vi.advanceTimersByTimeAsync(400);});
  expect(host.querySelector('.dock-layer').classList.contains('open')).toBe(false);
  outside.remove();
});

test.each(['top','bottom','left','right'])('the %s dock owns the player and its expanded controls', async dockSide => {
  await renderPlayer([],false,{dockSide});
  const dock=host.querySelector('.dock-layer');
  expect(dock.dataset.dockSide).toBe(dockSide);
  expect(dock.querySelector('.spotify-player-shell').classList.contains('side-'+dockSide)).toBe(true);
  expect(dock.querySelector('[aria-label="Music playback controls"]')).not.toBe(null);
});

test('Open Music closes the compact controls and uses existing navigation', async () => {
  const onOpenMusic=vi.fn();
  await renderPlayer([],false,{onOpenMusic});
  await act(async () => host.querySelector('.spotify-open-page').click());
  expect(onOpenMusic).toHaveBeenCalledTimes(1);
  expect(host.querySelector('[role="dialog"]')).toBe(null);
});

test('hiding the dock and disconnecting Spotify preserve navigation without recreating the controller', async () => {
  const api=await renderPlayer([],true);
  await act(async () => document.body.dispatchEvent(new Event('pointerdown',{bubbles:true})));
  await act(async () => {host.querySelector('.dock-shell').dispatchEvent(new MouseEvent('mouseout',{bubbles:true,relatedTarget:document.body}));await vi.advanceTimersByTimeAsync(400);});
  expect(api.dispose).not.toHaveBeenCalled();
  expect(window.VellumSpotifyPlayback.create).toHaveBeenCalledTimes(1);
  await act(async () => root.render(React.createElement(api.Player,{...api.props,spotify:{connected:false}})));
  expect(host.querySelector('[aria-label="Search chats"]')).not.toBe(null);
  expect(host.querySelector('.spotify-player-pill')).toBe(null);
  expect(api.dispose).toHaveBeenCalledTimes(1);
});

test('Up next shows distinct upcoming songs rather than copies of the current song', async () => {
  const current = track('spotify:track:current','Current song'), next = track('spotify:track:next','Next song');
  await renderPlayer([current,current,next,next]);
  expect([...host.querySelectorAll('.spotify-queue-row span')].map(row => row.textContent)).toEqual(['Next song']);
});

test('an applied transport action releases controls before a slow queue read finishes', async () => {
  const api=await renderPlayer([]);
  let finish;
  api.player.mockImplementation(() => new Promise(resolve => {finish=resolve;}));
  await act(async () => host.querySelector('[aria-label="Pause"]').click());
  await act(async () => host.querySelector('[aria-label="Next track"]').click());
  expect(api.action.mock.calls.map(([body]) => body.action)).toEqual(['pause','next']);
  await act(async () => finish({track:track('spotify:track:next','Next song'),is_playing:true}));
});

test('an open player refreshes the queue on its regular poll', async () => {
  const api = await renderPlayer([track('spotify:track:next','Next song')]);
  api.player.mockClear();
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(api.player).toHaveBeenCalledWith(true);
});

test('an older HTTP snapshot cannot overwrite a newer SDK song and queue', async () => {
  const api = await renderPlayer([track('spotify:track:next','Next song')], true);
  let finish;
  api.player.mockImplementationOnce(() => new Promise(resolve => {finish=resolve;}));
  await act(async () => {vi.advanceTimersByTime(5000);});
  await act(async () => api.emitState({track:track('spotify:track:new','New song'),queue:[track('spotify:track:fresh','Fresh next')],device:{}}));
  await act(async () => finish({track:track('spotify:track:current','Current song'),queue:[track('spotify:track:old','Old next')]}));
  expect(host.querySelector('.spotify-now b').textContent).toBe('New song');
  expect(host.querySelector('.spotify-queue-row span').textContent).toBe('Fresh next');
});

test('SDK volume changes update the range without a track event', async () => {
  const api=await renderPlayer([],true);
  await act(async () => api.emitState({device:{id:'vellum',volume_percent:23}}));
  expect(host.querySelector('[aria-label="Spotify volume"]').value).toBe('23');
  expect(host.querySelector('.spotify-now b').textContent).toBe('Current song');
});

test('a later poll cannot replace fresh local SDK song or volume with remote lag', async () => {
  const api=await renderPlayer([],true);
  await act(async () => api.emitState({track:track('spotify:track:hindi','Hindi song'),device:{id:'vellum',volume_percent:23},queue:[track('spotify:track:next','Real next')]}));
  api.player.mockResolvedValue({track:track('spotify:track:sza','SOS'),device:{id:'vellum',volume_percent:50},queue:[]});
  await act(async () => window.dispatchEvent(new Event('vellum:spotify-player-refresh')));
  expect(host.querySelector('.spotify-now b').textContent).toBe('Hindi song');
  expect(host.querySelector('[aria-label="Spotify volume"]').value).toBe('23');
  expect(host.querySelector('.spotify-queue-row span').textContent).toBe('Real next');
});

test('switching between the Music page and chat retains one playback controller and snapshot', async () => {
  const api=await renderPlayer([],true);
  api.player.mockResolvedValue({track:track('spotify:track:current','Current song'),device:{id:'vellum'},is_playing:true});
  const target=document.createElement('div'); host.append(target);
  window.VellumUI={MusicPage:({music}) => React.createElement('p',null,music.player?.track?.name)};
  const props={...api.props,musicPageTarget:target,compactVisible:false};
  await act(async () => root.render(React.createElement(api.Player,props)));
  await act(async () => api.emitState({track:track('spotify:track:live','Live song'),device:{id:'vellum'},is_playing:true}));
  expect(target.textContent).toBe('Live song');
  expect(host.querySelector('.spotify-player-pill')).toBe(null);
  await act(async () => root.render(React.createElement(api.Player,{...props,musicPageTarget:null,compactVisible:true})));
  expect(host.querySelector('.spotify-now b').textContent).toBe('Live song');
  expect(host.querySelector('.spotify-now').closest('[aria-label="Quick actions"]')).not.toBe(null);
  expect(window.VellumSpotifyPlayback.create).toHaveBeenCalledTimes(1);
  expect(api.dispose).not.toHaveBeenCalled();
});


test('local playback appears in the Dynamic Island without a connected Spotify account',async()=>{
  let emit;const previous=window.VellumLocalMusicPlayback;
  const pause=vi.fn(),wake=vi.fn();window.VellumLocalMusicPlayback={subscribe:vi.fn(listener=>{emit=listener;return ()=>{};}),start:vi.fn(()=>({wake})),pause};
  const localApi={library:vi.fn(async()=>({collections:[{entries:[{id:'owned',title:'Owned recording',artist:'Local artist',available:true,artwork_url:'https://images.example/local.jpg'}]}]})),action:vi.fn(async()=>({status:'applied'}))};
  try{
    const api=await renderPlayer([],false,{open:false,spotify:{connected:false},localApi});
    expect(emit).toBeTypeOf('function');
    await act(async()=>emit({queue:['owned'],index:0,volume:.7,observed:{entry_id:'owned',playing:true,seconds:12,duration:120}}));
    expect(host.querySelector('.spotify-now')?.textContent).toContain('Owned recording');expect(host.querySelector('svg[aria-label="Local music"]')).toBeTruthy();expect(host.querySelector('svg[aria-label="Spotify"]')).toBeNull();
    await act(async()=>host.querySelector('[aria-label="Pause local music"]').click());
    expect(localApi.action).toHaveBeenCalledWith('playback',{action:'pause'});expect(api.action).not.toHaveBeenCalled();
    await act(async()=>host.querySelector('[aria-label="Open local music player"]').click());
    expect(host.textContent).not.toContain('Allow playback in Vellum');
    const seek=host.querySelector('[aria-label="Local music playback position"]');seek.value='36000';
    await act(async()=>seek.dispatchEvent(new MouseEvent('mouseup',{bubbles:true})));
    expect(localApi.action).toHaveBeenLastCalledWith('playback',{action:'seek',seconds:36});
    const volume=host.querySelector('[aria-label="Local music volume"]');volume.value='30';
    await act(async()=>volume.dispatchEvent(new KeyboardEvent('keyup',{key:'ArrowRight',bubbles:true})));
    expect(localApi.action).toHaveBeenLastCalledWith('playback',{action:'volume',volume:.3});
    await act(async()=>host.querySelector('[aria-label="Change repeat mode"]').click());
    expect(localApi.action).toHaveBeenLastCalledWith('playback',{action:'repeat',repeat:'all'});
    await act(async()=>host.querySelector('[aria-label="Next track"]').click());
    expect(localApi.action).toHaveBeenLastCalledWith('playback',{action:'next'});
    expect(api.action).not.toHaveBeenCalled();expect(window.VellumSpotifyPlayback.create).not.toHaveBeenCalled();
    expect(localApi.library).toHaveBeenCalledTimes(1);
    await act(async()=>emit({queue:['owned'],index:0,volume:.7,observed:{entry_id:'owned',playing:false,seconds:37,duration:120}}));
    expect(localApi.library).toHaveBeenCalledTimes(1);
  }finally{window.VellumLocalMusicPlayback=previous;}
});
