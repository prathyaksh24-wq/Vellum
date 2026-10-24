import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';

const require=createRequire(import.meta.url);
const source=readFileSync(resolve(dirname(fileURLToPath(import.meta.url)),'../../design/Velllum/uploads/components/product-hunt.jsx'),'utf8');
const original=globalThis.Uint8Array;let code;
try{globalThis.Uint8Array=new TextEncoder().encode('').constructor;const esbuild=createRequire(require.resolve('vite'))('esbuild');code=esbuild.transformSync(source,{loader:'jsx'}).code;}finally{globalThis.Uint8Array=original;}
let host,root,api,status;
const secret='fixture-secret-not-for-actions';
const button=name=>[...host.querySelectorAll('button')].find(x=>x.textContent===name);
const click=async node=>{expect(node).toBeTruthy();await act(async()=>node.click());};
const flush=async()=>{await act(async()=>{});};
const render=async props=>{new Function('React','window',code)(React,window);await act(async()=>root.render(React.createElement(window.VellumUI.ProductHuntWorkspace,props)));};
const enter=async()=>{const field=host.querySelector('input[type=password]');await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(field,secret);field.dispatchEvent(new Event('input',{bubbles:true}));});};
beforeEach(()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  status={enabled:true,configured:false,connected:false,status:'not_connected',message:'Connect Product Hunt to read launches.'};
  api={plugins:{productHuntStatus:vi.fn(async()=>status),productHuntStage:vi.fn(async()=>({credential_id:'opaque-reference-with-no-secret-value'})),productHuntDiscard:vi.fn(async()=>({discarded:true})),productHuntRead:vi.fn(async()=>({posts:[]}))},appActions:{
    dispatch:vi.fn(async()=>({status:'confirmation_required',confirmation:{token:'confirmation-1'}})),
    confirm:vi.fn(async()=>{status={enabled:true,configured:true,connected:true,status:'ready',message:'Verified access.',verified_at:'2026-10-22T12:00:00Z'};return {status:'applied',result:{connection:status}};}),
    cancel:vi.fn(async()=>({status:'cancelled'})),
  }};window.VellumApi=api;window.VellumUI={};
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();});

test('shows setup, privacy boundary and a masked token field, with no connected claim',async()=>{
  await render();expect(host.textContent).toContain('Connect Product Hunt');expect(host.textContent).not.toContain('Connected to Product Hunt');
  expect(host.querySelector('input').type).toBe('password');expect(host.querySelector('a[href*=applications]')).not.toBeNull();
  expect(button('Read recent launches')).toBeUndefined();
});

test('only an opaque reference reaches the confirmed App Action and token draft is cleared',async()=>{
  await render();await enter();await click(button('Review connection'));
  expect(api.plugins.productHuntStage).toHaveBeenCalledWith(secret);
  expect(JSON.stringify(api.appActions.dispatch.mock.calls)).not.toContain(secret);
  expect(api.appActions.confirm).not.toHaveBeenCalled();expect(host.querySelector('input').value).toBe('');
  expect(host.textContent).not.toContain('Connected to Product Hunt');
  await click(button('Verify and connect'));await flush();
  expect(host.textContent).toContain('Connected to Product Hunt');expect(host.textContent).toContain('Ask Vellum');
  expect(api.plugins.productHuntDiscard).toHaveBeenCalled();
});

test('cancel discards staging and never verifies the credential',async()=>{
  await render();await enter();await click(button('Review connection'));await click(button('Cancel'));
  expect(api.appActions.confirm).not.toHaveBeenCalled();expect(api.appActions.cancel).toHaveBeenCalled();
  expect(api.plugins.productHuntDiscard).toHaveBeenCalledWith('opaque-reference-with-no-secret-value');
  expect(host.textContent).not.toContain('Connected to Product Hunt');
});

test('failed verification displays the actual failure and permits retry',async()=>{
  api.appActions.confirm.mockResolvedValue({status:'failed',message:'Product Hunt rejected the credential.'});
  await render();await enter();await click(button('Review connection'));await click(button('Verify and connect'));
  expect(host.querySelector('[role=alert]').textContent).toContain('rejected');expect(host.textContent).not.toContain('Connected to Product Hunt');
  expect(button('Review connection').disabled).toBe(true);
});

test('connected reads are explicit and external launch content stays escaped',async()=>{
  status={...status,configured:true,connected:true,status:'ready'};
  api.plugins.productHuntRead.mockResolvedValue({posts:[{id:'1',name:'<img src=x onerror=alert(1)>',tagline:'A tool',votesCount:2,commentsCount:1,url:'javascript:alert(1)'}]});
  await render();expect(api.plugins.productHuntRead).not.toHaveBeenCalled();await click(button('Read recent launches'));
  expect(host.textContent).toContain('<img src=x');expect(host.querySelector('img')).toBeNull();expect(host.querySelector('a[href^="javascript:"]')).toBeNull();
});

test('disabled plugin cannot start a connection and unmount cancels pending confirmation',async()=>{
  await render({enabled:false});await enter();expect(button('Review connection').disabled).toBe(true);
  await render({enabled:true});await enter();await click(button('Review connection'));
  await act(async()=>root.render(null));
  expect(api.appActions.cancel).toHaveBeenCalled();expect(api.plugins.productHuntDiscard).toHaveBeenCalled();
});

test('shows the three privilege levels without claiming unverified write access',async()=>{
  status={...status,configured:true,connected:true,status:'ready',account_access:'available',write_access:'approval_required'};
  await render();const privileges=host.querySelector('[aria-label="Product Hunt privileges"]');
  expect(privileges.textContent).toContain('Public');expect(privileges.textContent).toContain('Private');expect(privileges.textContent).toContain('Write');
  expect(privileges.textContent).toContain('Account reads verified');expect(privileges.textContent).toContain('Product Hunt approval required');
  expect(host.textContent).toContain('7 read operations');
});

test('reads private account data only after explicit request and does not turn an empty list into an absence claim',async()=>{
  status={...status,configured:true,connected:true,status:'ready'};
  api.plugins.productHuntRead.mockResolvedValue({operation:'account_posts',posts:[],data_visibility:'authenticated_account'});
  await render();expect(api.plugins.productHuntRead).not.toHaveBeenCalled();
  const select=host.querySelector('select');await act(async()=>{select.value='posts:voted';select.dispatchEvent(new Event('change',{bubbles:true}));});
  await click(button('Read account data'));
  expect(api.plugins.productHuntRead).toHaveBeenCalledWith({operation:'account_posts',account_feed:'voted',limit:5});
  expect(host.textContent).toContain('empty list or provider privacy restrictions');
});

test('follow review names the exact target and only confirms the bound action on request',async()=>{
  status={...status,configured:true,connected:true,status:'ready'};
  api.appActions.dispatch.mockResolvedValue({status:'confirmation_required',message:'Confirm following @maker on Product Hunt.',confirmation:{token:'follow-review'}});
  api.appActions.confirm.mockResolvedValue({status:'applied',result:{changed:true,following:true,user:{username:'maker'}}});
  await render();const field=host.querySelector('#producthunt-username');
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(field,'@maker');field.dispatchEvent(new Event('input',{bubbles:true}));});
  await click(button('Review follow'));
  expect(api.appActions.confirm).not.toHaveBeenCalled();
  expect(host.querySelector('[aria-label="Review Product Hunt action"]').textContent).toContain('@maker');
  expect(api.appActions.dispatch.mock.calls[0][0]).toMatchObject({action_id:'producthunt.user.follow',arguments:{username:'maker'}});
  await click(button('Confirm change'));
  expect(api.appActions.confirm).toHaveBeenCalledWith('follow-review',expect.objectContaining({action_id:'producthunt.user.follow',arguments:{username:'maker'}}),{source:'ui'});
  expect(host.querySelector('[role=alert]')).toBeNull();expect(host.textContent).toContain('Connected to Product Hunt');
});
