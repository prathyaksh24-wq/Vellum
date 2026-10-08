import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect, test, vi} from 'vitest';

const compile = () => execFileSync(process.execPath, ['-e', `
 const {createRequire}=require('node:module');
 const esbuild=createRequire(require.resolve('vite'))('esbuild');
 process.stdout.write(esbuild.transformSync(require('node:fs').readFileSync(process.argv[1],'utf8'),
 {loader:'jsx',jsxFactory:'React.createElement',jsxFragment:'React.Fragment'}).code);
`, resolve('../design/Velllum/uploads/components/browser-panel.jsx')], {encoding:'utf8'});

async function mountPanel(api, state) {
  window.VellumApi = {browser:api};
  Function('React','window',compile())(React,window);
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  await act(async()=>root.render(React.createElement(window.VellumUI.BrowserPanel,
    {state,onRefresh:async()=>state,onHide:vi.fn()})));
  return {container, cleanup:async()=> {await act(async()=>root.unmount());container.remove();}};
}
const manualState = () => ({running:true,available:true,control:'user',session_id:'session',active_tab_id:'tab',downloads:[],
  tabs:[{id:'tab',active:true,title:'Fixture',url:'https://example.com/'}]});
const sampleFrame = {frame_id:'session:tab:1',tab_id:'tab',width:900,height:700,data_url:'data:image/jpeg;base64,aQ=='};

test('Escape reaches the browser page without bubbling to Vellum global shortcuts', async()=> {
  const api = {frame:async()=>sampleFrame,control:vi.fn(async()=>({status:'applied'}))};
  const globalShortcut = vi.fn();
  window.addEventListener('keydown',globalShortcut);
  const panel = await mountPanel(api,manualState());
  try {
    await act(async()=>panel.container.querySelector('.browser-screen').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true})));
    expect(api.control).toHaveBeenCalledWith(expect.objectContaining({operation:'press',key:'Escape'}),undefined);
    expect(globalShortcut).not.toHaveBeenCalled();
  } finally {window.removeEventListener('keydown',globalShortcut);await panel.cleanup();}
});

test('New tab focuses an empty address immediately while creation is pending', async()=> {
  let finish;
  const api = {frame:async()=>sampleFrame,control:vi.fn(()=>new Promise(resolve=> {finish=resolve;}))};
  const panel = await mountPanel(api,manualState());
  try {
    await act(async()=>panel.container.querySelector('[title="New tab"]').click());
    const address = panel.container.querySelector('[aria-label="Browser address"]');
    expect(document.activeElement).toBe(address);
    expect(address.value).toBe('');
  } finally {await act(async()=>finish?.({status:'applied'}));await panel.cleanup();}
});

test('Alt+W closes the inner tab and Alt+L focuses its address', async()=> {
  const api = {frame:async()=>sampleFrame,control:vi.fn(async()=>({status:'applied'}))};
  const panel = await mountPanel(api,manualState());
  try {
    const screen=panel.container.querySelector('.browser-screen');
    await act(async()=>screen.dispatchEvent(new KeyboardEvent('keydown',{key:'l',altKey:true,bubbles:true,cancelable:true})));
    expect(document.activeElement).toBe(panel.container.querySelector('[aria-label="Browser address"]'));
    await act(async()=>screen.dispatchEvent(new KeyboardEvent('keydown',{key:'w',altKey:true,bubbles:true,cancelable:true})));
    expect(api.control).toHaveBeenCalledWith(expect.objectContaining({operation:'close_tab',tab_id:'tab'}),undefined);
  } finally {await panel.cleanup();}
});

test('clicking the page takes ownership and retains the click; typing is batched', async () => {
  vi.useFakeTimers();
  const calls = [];
  const state = {running:true, available:true, control:'agent', session_id:'session', active_tab_id:'tab', downloads:[],
    tabs:[{id:'tab',active:true,title:'Fixture',url:'https://example.com/'}]};
  const frame = {frame_id:'session:tab:1',tab_id:'tab',width:900,height:700,data_url:'data:image/jpeg;base64,aQ=='};
  const api = {frame:vi.fn(async()=>frame),point:()=>({x:100,y:100}),control:vi.fn(async payload=> {
    calls.push(payload); if(payload.operation==='click' && payload.take_control) state.control='user';
    return {status:'applied'};
  })};
  window.VellumApi = {browser:api};
  Function('React','window',compile())(React,window);
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const render = () => root.render(React.createElement(window.VellumUI.BrowserPanel,
    {state:{...state},onRefresh:async()=> {render(); return state;},onHide:vi.fn()}));
  try {
    await act(async()=>render());
    const screen = container.querySelector('.browser-screen');
    await act(async()=>screen.dispatchEvent(new MouseEvent('pointerdown',{bubbles:true,clientX:100,clientY:100,button:0})));
    expect(calls).toEqual([expect.objectContaining({operation:'click',take_control:true,frame_id:frame.frame_id})]);
    calls.length = 0;
    await act(async()=> {
      for (const key of 'hello brave') screen.dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true}));
      await vi.advanceTimersByTimeAsync(80);
    });
    expect(calls.filter(call=>call.operation==='type')).toEqual([expect.objectContaining({text:'hello brave'})]);
    calls.length = 0;
    await act(async()=> {
      screen.dispatchEvent(new KeyboardEvent('keydown',{key:'a',bubbles:true,cancelable:true}));
      const paste = new Event('paste',{bubbles:true,cancelable:true});
      Object.defineProperty(paste,'clipboardData',{value:{getData:()=> ' pasted'}});
      screen.dispatchEvent(paste);
      screen.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
    });
    expect(calls.map(call=>[call.operation,call.text||call.key])).toEqual([['type','a'],['type',' pasted'],['press','Enter']]);
  } finally {
    await act(async()=>root.unmount()); container.remove(); vi.useRealTimers();
  }
});

test('native home never streams frames or forwards typing, and switching engines preserves the search draft', async () => {
  vi.resetModules();
  window.VellumApi = {client:{request:vi.fn()},appActions:{dispatch:vi.fn()}};
  await import('../../design/Velllum/uploads/api/browser.js');
  const api = window.VellumApi.browser;
  api.frame = vi.fn(); api.stream = vi.fn();
  const state = {...manualState(),preferences:{...api.defaultPreferences},tabs:[{id:'tab',active:true,title:'New tab',url:'about:blank'}]};
  const rootContainer = document.createElement('div'); document.body.append(rootContainer);
  const root = createRoot(rootContainer);
  Function('React','window',compile())(React,window);
  const render = () => root.render(React.createElement(window.VellumUI.BrowserPanel,{state:{...state},
    onRefresh:async()=>{render();return state;},onHide:vi.fn()}));
  api.control = vi.fn(async payload => {
    if (payload.operation === 'preferences') state.preferences = {...state.preferences,...payload};
    return {status:'applied'};
  });
  try {
    await act(async()=>render());
    const search = rootContainer.querySelector('[aria-label="Search with Google"]');
    await act(async()=> {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(search,'browser tools');
      search.dispatchEvent(new Event('input',{bubbles:true}));
      search.dispatchEvent(new KeyboardEvent('keydown',{key:'a',bubbles:true,cancelable:true}));
    });
    expect(api.frame).not.toHaveBeenCalled(); expect(api.stream).not.toHaveBeenCalled(); expect(api.control).not.toHaveBeenCalled();
    await act(async()=>rootContainer.querySelector('[aria-label="Choose search engine"]').click());
    expect(rootContainer.querySelectorAll('[role="menuitemradio"]')).toHaveLength(5);
    await act(async()=>Array.from(rootContainer.querySelectorAll('[role="menuitemradio"]')).find(el=>el.textContent==='Brave').click());
    const braveSearch = rootContainer.querySelector('[aria-label="Search with Brave"]');
    expect(braveSearch.value).toBe('browser tools');
    expect(rootContainer.querySelector('.browser-home').dataset.engine).toBe('brave');
    await act(async()=>rootContainer.querySelector('.browser-home-search').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
    expect(api.control).toHaveBeenLastCalledWith({operation:'navigate',url:'https://search.brave.com/search?q=browser%20tools'},undefined);
    await act(async()=>rootContainer.querySelector('[title="Expand browser"]').click());
    expect(rootContainer.querySelector('.browser-expanded')).not.toBeNull();
    await act(async()=>rootContainer.querySelector('[title="Restore split view"]').click());
    expect(rootContainer.querySelector('.browser-expanded')).toBeNull();
    expect(braveSearch.value).toBe('browser tools');
  } finally {await act(async()=>root.unmount());rootContainer.remove();}
});
