import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect, test, vi} from 'vitest';

let compiledPanel;
const compile = () => compiledPanel ||= execFileSync(process.execPath, ['-e', `
 const {createRequire}=require('node:module');
 const esbuild=createRequire(require.resolve('vite'))('esbuild');
 process.stdout.write(esbuild.transformSync(require('node:fs').readFileSync(process.argv[1],'utf8'),
 {loader:'jsx',jsxFactory:'React.createElement',jsxFragment:'React.Fragment'}).code);
`, resolve('../design/Velllum/uploads/components/browser-panel.jsx')], {encoding:'utf8'});

async function mountPanel(api, state) {
  window.VellumApi = {browser:api};
  Function('React','window',compile())(React,window);
  const container = document.createElement('div');container.className='body'; document.body.append(container);
  const root = createRoot(container);
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const onHide = vi.fn();
  await act(async()=>root.render(React.createElement(window.VellumUI.BrowserPanel,
    {state,onRefresh:async()=>state,onHide})));
  return {container, onHide, cleanup:async()=> {await act(async()=>root.unmount());container.remove();}};
}
const manualState = () => ({running:true,available:true,control:'user',session_id:'session',active_tab_id:'tab',downloads:[],
  tabs:[{id:'tab',active:true,title:'Fixture',url:'https://example.com/'}]});
const sampleFrame = {frame_id:'session:tab:1',tab_id:'tab',width:900,height:700,data_url:'data:image/jpeg;base64,aQ=='};

test('Electron mounts native content without opening a stream or requesting frames',async()=>{
  const api=await autocompleteApi();
  api.frame=vi.fn(async()=>sampleFrame);api.stream=vi.fn(()=>()=>{});
  const native={mount:vi.fn(async data=>data.prepare_only ? {still:sampleFrame.data_url} : {}),subscribe:vi.fn(()=>()=>{})};
  window.VellumDesktop={browser:native};
  const panel=await mountPanel(api,{...manualState(),render_transport:'native',native_target_id:'owned-guest'});
  try {
    expect(native.mount).toHaveBeenCalledWith(expect.objectContaining({visible:true,target_id:'owned-guest'}));
    expect(api.frame).not.toHaveBeenCalled();expect(api.stream).not.toHaveBeenCalled();
    expect(panel.container.querySelector('[aria-label="Embedded browser page"]')).not.toBeNull();
    expect(panel.container.querySelector('img[alt="Live view of the dedicated browser tab"]')).toBeNull();
    await act(async()=>panel.container.classList.add('browser-resizing'));
    expect(native.mount).toHaveBeenLastCalledWith(expect.objectContaining({prepare_only:true}));
    expect(panel.container.querySelector('img[alt="Page beneath browser menu"]')).not.toBeNull();
    await act(async()=>await new Promise(resolve=>setTimeout(resolve,55)));
    expect(native.mount).toHaveBeenLastCalledWith(expect.objectContaining({visible:false}));
    await act(async()=>panel.container.classList.remove('browser-resizing'));
    expect(native.mount).toHaveBeenLastCalledWith(expect.objectContaining({visible:true}));
  } finally {await panel.cleanup();delete window.VellumDesktop;}
  expect(native.mount).toHaveBeenLastCalledWith({visible:false});
});

test('a silent live stream falls back to frames so cursor updates keep arriving',async()=>{
  const api=await autocompleteApi();
  vi.useFakeTimers({toFake:['setTimeout','clearTimeout','Date']});
  api.stream=receive=>{setTimeout(()=>receive(sampleFrame),10);return ()=>{};};
  api.frame=vi.fn(async()=>({...sampleFrame,pointer:{tab_id:'tab',x:300,y:240,action:'scroll'}}));
  const panel=await mountPanel(api,{...manualState(),control:'agent'});
  try {
    await act(async()=>await vi.advanceTimersByTimeAsync(100));
    api.frame.mockClear();
    await act(async()=>await vi.advanceTimersByTimeAsync(2400));
    expect(api.frame).toHaveBeenCalled();
    expect(panel.container.querySelector('[aria-label="Agent cursor: scroll"]')).not.toBeNull();
  } finally {await panel.cleanup();vi.useRealTimers();}
});

test('live pointer moves even when page pixels and frame identity are unchanged',async()=>{
  const api=await autocompleteApi();
  let publish;
  api.stream=(receive)=>{publish=receive;return ()=>{};};
  api.frame=async()=>sampleFrame;
  const panel=await mountPanel(api,{...manualState(),control:'agent'});
  try {
    await act(async()=>publish({...sampleFrame,pointer:{tab_id:'tab',x:100,y:120,action:'click'}}));
    const cursor=panel.container.querySelector('.browser-agent-pointer');
    const initial=cursor.style.left;
    await act(async()=>publish({...sampleFrame,pointer:{tab_id:'tab',x:500,y:300,action:'click'}}));
    expect(panel.container.querySelector('.browser-agent-pointer')).toBe(cursor);
    expect(cursor.style.left).not.toBe(initial);
    expect(panel.container.querySelector('img[alt="Live view of the dedicated browser tab"]').getAttribute('src')).toBe(sampleFrame.data_url);
    await act(async()=>publish({...sampleFrame,pointer:null}));
    expect(panel.container.querySelector('.browser-agent-pointer')).toBeNull();
  } finally {await panel.cleanup();}
});

test('agent pointer is visible on its current tab and yields on takeover',async()=>{
  const api=await autocompleteApi();
  api.frame=async()=>({...sampleFrame,pointer:{tab_id:'tab',x:180,y:140,action:'click'}});
  const panel=await mountPanel(api,{...manualState(),control:'agent',preferences:{...api.defaultPreferences,cursor_style:'mint'}});
  try {
    await act(async()=>await new Promise(resolve=>setTimeout(resolve,20)));
    expect(panel.container.querySelector('[aria-label="Agent cursor: click"]')).not.toBeNull();
    expect(window.VellumUI.browserPointerLayout({...sampleFrame,pointer:{x:180,y:140}},450,350,{cursor_style:'custom',cursor_hotspot_x:2,cursor_hotspot_y:3})).toEqual({width:450,height:350,x:88,y:67});
  } finally {await panel.cleanup();}
});

test('browser divider supports keyboard resize and restores the default split',async()=>{
  Function('React','window',compile())(React,window);
  const container=document.createElement('div');document.body.append(container);
  const root=createRoot(container),changed=vi.fn();globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  await act(async()=>root.render(React.createElement(window.VellumUI.BrowserSplitter,{value:38,onChange:changed})));
  try {
    const handle=container.querySelector('[role="separator"]');
    await act(async()=>handle.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true})));
    expect(changed).toHaveBeenLastCalledWith(40);
    await act(async()=>handle.dispatchEvent(new MouseEvent('dblclick',{bubbles:true})));
    expect(changed).toHaveBeenLastCalledWith(38);
    await act(async()=>handle.dispatchEvent(new MouseEvent('pointerdown',{button:0,clientX:300,bubbles:true})));
    expect(container.classList.contains('browser-resizing')).toBe(true);
    await act(async()=>root.render(React.createElement(window.VellumUI.BrowserSplitter,{value:38,onChange:value=>changed(value)})));
    expect(container.classList.contains('browser-resizing')).toBe(true);
    await act(async()=>window.dispatchEvent(new MouseEvent('pointerup',{button:0,clientX:300,bubbles:true})));
    expect(container.classList.contains('browser-resizing')).toBe(false);
  } finally {await act(async()=>root.unmount());container.remove();}
});

async function autocompleteApi() {
  vi.resetModules();
  window.VellumApi = {client:{request:vi.fn(async()=>({items:[]}))},appActions:{dispatch:vi.fn()}};
  await import('../../design/Velllum/uploads/api/browser.js');
  const api = window.VellumApi.browser;
  api.frame = async()=>sampleFrame;
  api.control = vi.fn(async()=>({status:'applied'}));
  api.suggestions = vi.fn(async()=>({items:[{title:'Watch history - YouTube',url:'https://www.youtube.com/feed/history'}]}));
  return api;
}

test('address suggestions complete a local URL and keyboard selection switches the existing tab', async()=> {
  const api = await autocompleteApi();
  const state = {...manualState(),preferences:api.defaultPreferences};
  state.tabs.push({id:'youtube',active:false,title:'YouTube',url:'https://www.youtube.com/'});
  const panel = await mountPanel(api,state);
  try {
    const input = panel.container.querySelector('[aria-label="Browser address"]');
    await act(async()=>input.focus());
    await act(async()=> {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'yo');
      input.setSelectionRange(2,2);
      input.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:'o'}));
    });
    expect(input.value).toBe('youtube.com/');
    expect(panel.container.querySelector('[role="listbox"]')).not.toBeNull();
    expect(panel.container.querySelector('[role="option"] [class="browser-suggestion-hint"]').textContent).toBe('Switch to tab');
    await act(async()=>input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true})));
    expect(api.control).toHaveBeenCalledWith({operation:'select_tab',tab_id:'youtube'},undefined);
    expect(panel.container.querySelector('[role="listbox"]')).toBeNull();
  } finally {await panel.cleanup();}
});

test('search suggestion uses the selected engine and Escape dismisses only the suggestions', async()=> {
  const api = await autocompleteApi();
  const panel = await mountPanel(api,{...manualState(),preferences:{...api.defaultPreferences,search_engine:'brave'}});
  try {
    const input = panel.container.querySelector('[aria-label="Browser address"]');
    await act(async()=>input.focus());
    await act(async()=> {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'browser shortcuts');
      input.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText'}));
    });
    await act(async()=>input.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true})));
    expect(panel.container.querySelector('[role="listbox"]')).toBeNull();
    expect(panel.onHide).not.toHaveBeenCalled();
    await act(async()=>input.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true})));
    await act(async()=>input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true})));
    expect(api.control).toHaveBeenCalledWith({operation:'navigate',url:'https://search.brave.com/search?q=browser%20shortcuts'},undefined);
  } finally {await panel.cleanup();}
});

test('the close control dismisses immediately and closes the owned session', async()=> {
  const api = await autocompleteApi();
  const panel = await mountPanel(api,manualState());
  try {
    await act(async()=>panel.container.querySelector('[aria-label="Close browser panel"]').click());
    expect(panel.onHide).toHaveBeenCalledOnce();
    expect(api.control).toHaveBeenCalledWith({operation:'close'},undefined);
  } finally {await panel.cleanup();}
});

test('address candidates prioritize open tabs, deduplicate history and reject unsafe URLs', async()=> {
  const api = await autocompleteApi();
  const url = 'https://www.youtube.com/';
  const items = api.addressSuggestions('yo',[{id:'yt',title:'YouTube',url}],api.defaultPreferences.shortcuts,
    [{title:'Visited YouTube',url},{title:'Unsafe',url:'https://user:secret@example.com/'}],api.defaultPreferences);
  expect(items.filter(item=>item.url===url)).toEqual([{title:'YouTube',url,tab_id:'yt',kind:'tab'}]);
  expect(items.at(-1)).toMatchObject({kind:'search',url:'https://www.google.com/search?q=yo'});
});

test('a tab close button targets that tab without dismissing the whole panel', async()=> {
  const api = await autocompleteApi();
  const state = manualState(); state.tabs.push({id:'other',active:false,title:'Other',url:'about:blank'});
  const panel = await mountPanel(api,state);
  try {
    await act(async()=>panel.container.querySelector('[aria-label="Close Fixture"]').click());
    expect(api.control).toHaveBeenCalledWith({operation:'close_tab',tab_id:'tab'},undefined);
    expect(panel.onHide).not.toHaveBeenCalled();
  } finally {await panel.cleanup();}
});

test('history arrival keeps a completed shortcut selected and deletion does not reinsert its suffix', async()=> {
  vi.useFakeTimers();
  const api = await autocompleteApi();
  const panel = await mountPanel(api,{...manualState(),preferences:api.defaultPreferences});
  try {
    const input = panel.container.querySelector('[aria-label="Browser address"]');
    await act(async()=>input.focus());
    const edit = inputType => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'yo');
      input.setSelectionRange(2,2);
      input.dispatchEvent(new InputEvent('input',{bubbles:true,inputType}));
    };
    await act(async()=>edit('insertText'));
    expect(input.value).toBe('youtube.com/');
    await act(async()=>vi.advanceTimersByTimeAsync(100));
    const selected = panel.container.querySelector('[role="option"][aria-selected="true"]');
    expect(selected.querySelector('small').textContent).toBe('www.youtube.com/');
    await act(async()=>edit('deleteContentBackward'));
    await act(async()=>vi.advanceTimersByTimeAsync(100));
    expect(input.value).toBe('yo');
  } finally {await panel.cleanup();vi.useRealTimers();}
});

test('new tabs focus the address without suggestions until typing, and clearing hides them', async()=> {
  vi.useFakeTimers();
  const api = await autocompleteApi();
  const panel = await mountPanel(api,{...manualState(),preferences:api.defaultPreferences});
  try {
    await act(async()=>panel.container.querySelector('[title="New tab"]').click());
    const input = panel.container.querySelector('[aria-label="Browser address"]');
    await act(async()=>vi.advanceTimersByTimeAsync(100));
    expect(document.activeElement).toBe(input);
    expect(panel.container.querySelector('[role="listbox"]')).toBeNull();
    expect(api.suggestions).not.toHaveBeenCalled();
    const edit = value => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,value);
      input.setSelectionRange(value.length,value.length);
      input.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText'}));
    };
    await act(async()=>edit('anime'));
    expect(panel.container.querySelector('[role="listbox"]')).not.toBeNull();
    await act(async()=>edit(''));
    expect(panel.container.querySelector('[role="listbox"]')).toBeNull();
  } finally {await panel.cleanup();vi.useRealTimers();}
});

test('unvisited Spotify and new search terms appear without a history match', async()=> {
  vi.useFakeTimers();
  const api = await autocompleteApi();
  api.suggestions = vi.fn(async()=>({items:[],queries:['anime movies','anime news'],search_engine:'google'}));
  const panel = await mountPanel(api,{...manualState(),preferences:api.defaultPreferences});
  try {
    expect(api.addressSuggestions('spot',[],[],[],api.defaultPreferences)[0]).toMatchObject({kind:'website',url:'https://open.spotify.com/'});
    const input = panel.container.querySelector('[aria-label="Browser address"]');
    await act(async()=>input.focus());
    await act(async()=> {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'anime');
      input.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText'}));
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(Array.from(panel.container.querySelectorAll('[role="option"]')).map(el=>el.textContent)).toEqual(['animeSearch Google','anime moviesGoogle','anime newsGoogle']);
    await act(async()=>input.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true})));
    await act(async()=>input.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true})));
    await act(async()=>input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true})));
    expect(api.control).toHaveBeenCalledWith({operation:'navigate',url:'https://www.google.com/search?q=anime%20movies'},undefined);
  } finally {await panel.cleanup();vi.useRealTimers();}
});

test('mounting a closed session shows its homepage without starting Brave', async()=> {
  const api = await autocompleteApi();
  const state = {...manualState(),running:false,control:'closed',tabs:[],active_tab_id:''};
  const panel = await mountPanel(api,state);
  try {
    expect(panel.container.querySelector('[aria-label="Browser homepage"]')).not.toBeNull();
    expect(panel.container.textContent).not.toContain('Open browser');
    expect(panel.container.textContent).not.toContain('A browser for Vellum');
    expect(api.control).not.toHaveBeenCalled();
    await act(async()=>panel.container.querySelector('[aria-label="Close New tab"]').click());
    expect(panel.onHide).toHaveBeenCalledOnce();
    expect(api.control.mock.calls.map(call=>call[0].operation)).toEqual(['close']);
  } finally {await panel.cleanup();}
});

test('hover forwards the latest pointer position without clicking or taking ownership', async()=> {
  vi.useFakeTimers();
  const api = {frame:async()=>sampleFrame,point:(_rect,_frame,x,y)=>({x,y}),control:vi.fn(async()=>({status:'applied'}))};
  const panel = await mountPanel(api,manualState());
  try {
    const screen = panel.container.querySelector('.browser-screen');
    await act(async()=> {
      for (let x=100; x<110; x++) screen.dispatchEvent(new MouseEvent('pointermove',{bubbles:true,clientX:x,clientY:80}));
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(api.control).toHaveBeenCalledTimes(1);
    expect(api.control).toHaveBeenCalledWith(expect.objectContaining({operation:'hover',x:109,y:80,frame_id:sampleFrame.frame_id}),undefined);
    expect(api.control.mock.calls[0][0].take_control).toBeUndefined();
  } finally {await panel.cleanup();vi.useRealTimers();}
});

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

test('Alt+W closes the last browser tab and Alt+L focuses its address', async()=> {
  const api = {frame:async()=>sampleFrame,control:vi.fn(async()=>({status:'applied'}))};
  const panel = await mountPanel(api,manualState());
  try {
    const screen=panel.container.querySelector('.browser-screen');
    await act(async()=>screen.dispatchEvent(new KeyboardEvent('keydown',{key:'l',altKey:true,bubbles:true,cancelable:true})));
    expect(document.activeElement).toBe(panel.container.querySelector('[aria-label="Browser address"]'));
    await act(async()=>screen.dispatchEvent(new KeyboardEvent('keydown',{key:'w',altKey:true,bubbles:true,cancelable:true})));
    expect(api.control).toHaveBeenCalledWith({operation:'close'},undefined);
    expect(panel.onHide).toHaveBeenCalledOnce();
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
  window.VellumApi = {client:{request:vi.fn(async()=>({items:[]}))},appActions:{dispatch:vi.fn()}};
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
    expect(document.activeElement).toBe(braveSearch);
    expect(braveSearch.selectionStart).toBe('browser tools'.length);
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
