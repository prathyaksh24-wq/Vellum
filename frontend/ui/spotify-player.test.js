import React, {act, useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {afterEach, beforeEach, expect, test, vi} from 'vitest';

const html = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../design/Velllum/uploads/Vellum Default Re-designed.html'), 'utf8');
const source = html.slice(html.indexOf('const SpotifyPlayer ='), html.indexOf('const SettingsModal ='));
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

async function renderPlayer(queue, sdk = false) {
  const current = track('spotify:track:current', 'Current song');
  const api = {player:vi.fn(async details => ({track:current, is_playing:true, repeat:'off', ...(details ? {queue} : {})}))};
  let emitState;
  window.VellumSpotifyPlayback = {create:options => {
    emitState = options.onPlayer;
    return {prepare:vi.fn(async () => {}), dispose:vi.fn()};
  }};
  const plugins = {capabilities:vi.fn(async () => ({features:{spotify:{enabled:true,endpoints:{playback_token:'token'}}}}))};
  const Player = new Function('React','useState','useRef','useEffect','SpotifyAPI','API','I','fmtSpotifyTime',
    compiled + '; return SpotifyPlayer;')(React,useState,useRef,useEffect,api,{plugins},() => null,() => '0:00');
  await act(async () => root.render(React.createElement(Player, {spotify:{connected:true,web_playback_ready:sdk}})));
  await act(async () => host.querySelector('[aria-label="Open Spotify player"]').click());
  return {...api, emitState};
}

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove(); vi.useRealTimers();
});

test('Up next shows distinct upcoming songs rather than copies of the current song', async () => {
  const current = track('spotify:track:current','Current song'), next = track('spotify:track:next','Next song');
  await renderPlayer([current,current,next,next]);
  expect([...host.querySelectorAll('.spotify-queue-row span')].map(row => row.textContent)).toEqual(['Next song']);
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
