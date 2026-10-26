import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
const require=createRequire(import.meta.url);
const compile=name=>{
  const source=readFileSync(resolve(dirname(fileURLToPath(import.meta.url)),'../../design/Velllum/uploads/components/'+name+'.jsx'),'utf8');
  const original=globalThis.Uint8Array;
  try {globalThis.Uint8Array=new TextEncoder().encode('').constructor;return createRequire(require.resolve('vite'))('esbuild').transformSync(source,{loader:'jsx'}).code;}
  finally {globalThis.Uint8Array=original;}
};
const selector=compile('v-select'),settings=compile('web-search-settings');
let host,root,snapshot,api;
beforeEach(()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  snapshot={selected:'auto',active:'serpapi',automatic_fallback:true,providers:[{id:'serpapi',name:'SerpAPI',available:true},{id:'exa',name:'Exa',available:true},{id:'tavily',name:'Tavily',available:false}]};
  api={settings:{get:vi.fn(async()=>({web_search:snapshot}))},appActions:{dispatch:vi.fn(async request=>{snapshot={...snapshot,selected:request.arguments.provider,active:request.arguments.provider,automatic_fallback:false};return {status:'applied'};})}};
  window.VellumApi=api;window.VellumUI={};
  new Function('React','window',selector)(React,window);
  new Function('React','window',settings)(React,window);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();});
const render=async()=>{await act(async()=>root.render(React.createElement(window.VellumUI.WebSearchSettings)));};
test('uses the dark shared combobox rather than a native select and shows provider availability',async()=>{
  await render();expect(host.querySelector('select')).toBeNull();
  const trigger=host.querySelector('[role=combobox]');expect(trigger.getAttribute('aria-label')).toBe('Preferred web search provider');
  await act(async()=>trigger.click());expect(host.querySelector('[role=listbox]').getAttribute('aria-hidden')).toBe('false');
  expect(host.textContent).toContain('Needs connection');expect(host.textContent).toContain('Current provider: SerpAPI');
});
test('choosing Exa dispatches the canonical settings action and refreshes the saved selection',async()=>{
  await render();await act(async()=>host.querySelector('[role=combobox]').click());
  const option=[...host.querySelectorAll('[role=option]')].find(node=>node.textContent.includes('Exa'));
  await act(async()=>option.click());
  expect(api.appActions.dispatch.mock.calls[0][0]).toMatchObject({action_id:'settings.web_search.set',arguments:{provider:'exa'}});
  expect(host.textContent).toContain('An explicit choice uses only that provider.');
  expect(host.textContent).toContain('Current provider: Exa');
});
test('a failed settings action remains visible and does not imply the choice was saved',async()=>{
  api.appActions.dispatch.mockResolvedValue({status:'failed',message:'Configuration is read-only.'});
  await render();await act(async()=>host.querySelector('[role=combobox]').click());
  await act(async()=>[...host.querySelectorAll('[role=option]')].find(node=>node.textContent.includes('Exa')).click());
  expect(host.querySelector('[role=alert]').textContent).toContain('Configuration is read-only.');
  expect(host.textContent).toContain('Current provider: SerpAPI');
});
