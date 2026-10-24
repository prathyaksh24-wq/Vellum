import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
const require=createRequire(import.meta.url);
const source=readFileSync(resolve(dirname(fileURLToPath(import.meta.url)),'../../design/Velllum/uploads/components/google-connections.jsx'),'utf8');
const original=globalThis.Uint8Array;let code;
try{globalThis.Uint8Array=new TextEncoder().encode('').constructor;code=createRequire(require.resolve('vite'))('esbuild').transformSync(source,{loader:'jsx'}).code;}finally{globalThis.Uint8Array=original;}
let host,root,api,status;
const button=name=>[...host.querySelectorAll('button')].find(item=>item.textContent===name);
const click=async node=>{expect(node).toBeTruthy();await act(async()=>node.click());};
const render=async props=>{new Function('React','window',code)(React,window);await act(async()=>root.render(React.createElement(window.VellumUI.GoogleConnections,props)));};
beforeEach(()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  status={configured:true,connected:false,email:'',services:['drive','gmail','calendar','contacts'].map(id=>({id,name:({drive:'Google Drive',gmail:'Gmail',calendar:'Google Calendar',contacts:'Google Contacts'})[id],enabled:id==='calendar',authorized:false,status:id==='calendar'?'not_connected':'disabled'}))};
  api={plugins:{googleStatus:vi.fn(async()=>status),googleOAuthStatus:vi.fn(async()=>({status:'pending'}))},appActions:{dispatch:vi.fn(async()=>({status:'applied',result:{flow:{flow_id:'test-flow',status:'pending',authorization_url:'https://accounts.google.com/o/oauth2/v2/auth?state=test'}}})),confirm:vi.fn(async()=>({status:'applied'})),cancel:vi.fn(async()=>({status:'cancelled'}))}};
  api.plugins.navigateToGoogle=vi.fn();
  api.plugins.googleCatalog=vi.fn(async()=>({total:1,operation_count:79,methods:[{method_id:'gmail.users.messages.send',description:'Send a message.',read_only:false}],source:'https://gmail.googleapis.com/$discovery/rest?version=v1',revision:'20261019'}));
  window.VellumApi=api;window.VellumUI={};
  HTMLDialogElement.prototype.showModal=vi.fn(function(){this.setAttribute('open','');});
  HTMLDialogElement.prototype.close=vi.fn(function(){this.removeAttribute('open');});
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.useRealTimers();delete window.VellumDesktop;window.history.replaceState({},'', '/');});
test('Google chooser shows all four real marks and independently selectable services',async()=>{
  await render();await click(button('Connect Google'));
  const dialog=host.querySelector('dialog');
  expect(dialog.getAttribute('aria-labelledby')).toBe('google-chooser-title');
  const inputs=[...dialog.querySelectorAll('input[role=switch]')];
  expect(inputs).toHaveLength(4);expect(inputs.every(item=>item.checked)).toBe(true);
  expect(dialog.querySelector('img[src*=googledrive]')).toBeTruthy();expect(dialog.querySelector('img[src*=gmail]')).toBeTruthy();
  await click(inputs[2]);await click(inputs[3]);await click(button('Install selected plugins'));
  const request=api.appActions.dispatch.mock.calls[0][0];
  expect(request.action_id).toBe('google.connection.configure');expect(request.arguments.services).toEqual(['drive','gmail']);
  expect(request.arguments).not.toHaveProperty('token');
  expect(host.querySelector('dialog')).toBeNull();
  expect(api.plugins.navigateToGoogle).toHaveBeenCalledWith(expect.objectContaining({flow_id:'test-flow',authorization_url:expect.stringContaining('https://accounts.google.com/')}));
  expect(host.querySelector('a[href^="https://accounts.google.com"]')?.textContent).toBe('Continue to Google');
  expect(api.appActions.confirm).not.toHaveBeenCalled();
});
test('existing selections are preserved and disabled services are labelled Off',async()=>{
  status={...status,connected:true,email:'chosen@example.test',services:status.services.map(item=>({...item,enabled:item.id==='gmail',authorized:item.id==='gmail',status:item.id==='gmail'?'connected':'disabled'}))};
  await render();expect(host.textContent).toContain('chosen@example.test');expect(host.textContent).toContain('Off');
  await click(button('Choose Google plugins'));
  expect([...host.querySelectorAll('input')].map(item=>item.checked)).toEqual([false,true,false,false]);
  expect(host.textContent).toContain('Turning a service off keeps its existing Google permission');
});

test('desktop install asks the backend to open the default browser',async()=>{
  window.VellumDesktop={invoke:vi.fn()};
  await render();await click(button('Connect Google'));await click(button('Install selected plugins'));
  expect(api.appActions.dispatch.mock.calls[0][0].arguments.open_browser).toBe(true);
  expect(api.plugins.navigateToGoogle).toHaveBeenCalledOnce();
});

test('failed browser launch keeps the pending flow and a working retry link',async()=>{
  api.plugins.navigateToGoogle.mockImplementation(()=>{throw new Error('Use Continue to Google to retry.');});
  await render();await click(button('Connect Google'));await click(button('Install selected plugins'));
  expect(host.querySelector('[role=alert]').textContent).toContain('Continue to Google');
  expect(host.querySelector('a[href^="https://accounts.google.com"]')).toBeTruthy();
});
test('empty selection saves without forcing authorization',async()=>{
  api.appActions.dispatch.mockResolvedValue({status:'applied',result:{connection:status}});
  const onChanged=vi.fn();await render({onChanged});await click(button('Connect Google'));
  for(const input of [...host.querySelectorAll('input')])await click(input);
  await click(button('Save with all services off'));
  expect(api.appActions.dispatch.mock.calls[0][0].arguments.services).toEqual([]);expect(onChanged).toHaveBeenCalled();
});
test('changing accounts uses the same chooser with explicit Google sign-in',async()=>{
  status={...status,connected:true,services:status.services.map(item=>({...item,authorized:true,enabled:true,status:'connected'}))};
  await render();await click(button('Change account'));
  expect(host.textContent).toContain('Choose your preferred Google account');await click(button('Install selected plugins'));
  expect(api.appActions.dispatch.mock.calls[0][0].arguments.force_signin).toBe(true);
});

test('enabling changes requests broader consent explicitly and preserves existing connection',async()=>{
  status={...status,connected:true,services:status.services.map(item=>({...item,authorized:true,enabled:true,can_write:false,status:'connected'}))};
  await render();await click(button('Enable changes'));
  expect(host.querySelector('select[aria-label="Access for selected services"]').value).toBe('manage');
  expect(host.textContent).toContain('permanent deletion');
  await click(button('Install selected plugins'));
  expect(api.appActions.dispatch.mock.calls[0][0].arguments.access).toBe('manage');
});

test('published API operations are browsable without executing a write',async()=>{
  await render();await click(button('Browse API operations'));
  expect(api.plugins.googleCatalog).toHaveBeenCalledWith(expect.objectContaining({service:'gmail'}));
  expect(host.textContent).toContain('gmail.users.messages.send');
  expect(host.textContent).toContain('Requires review');
  expect(api.appActions.dispatch).not.toHaveBeenCalled();
});

test('Google write review displays readable account and changes without interpreting provider HTML',async()=>{
  await render();
  await act(async()=>root.render(React.createElement(window.VellumUI.GoogleActionReview,{review:{service:'gmail',heading:'Send email',account:'fixture@example.test',warning:'Review before sending.',fields:[{label:'To',value:'friend@example.test'},{label:'Subject',value:'Fixture hello'},{label:'Message',value:'<img src=x onerror=alert(1)>Hello'}]}})));
  expect(host.textContent).toContain('friend@example.test');expect(host.textContent).toContain('Fixture hello');
  expect(host.querySelector('img[src=x]')).toBeNull();
});
test('connection error keeps selection and enables retry',async()=>{
  api.appActions.dispatch.mockResolvedValue({status:'failed',message:'Google application not configured.'});
  await render();await click(button('Connect Google'));await click(host.querySelector('input'));
  await click(button('Install selected plugins'));
  expect(host.querySelector('dialog [role=alert]').textContent).toContain('not configured');
  expect(host.querySelector('input').checked).toBe(false);expect(button('Install selected plugins').disabled).toBe(false);
});
test('disconnect is reviewed and uses bound confirmation',async()=>{
  status={...status,connected:true};
  api.appActions.dispatch.mockResolvedValue({status:'confirmation_required',confirmation:{token:'review'}});
  await render();await click(button('Disconnect Google'));
  expect(api.appActions.confirm).not.toHaveBeenCalled();
  expect(host.textContent).toContain('All four Google services will be switched off');
  await click(button('Confirm disconnect'));
  expect(api.appActions.confirm.mock.calls[0][0]).toBe('review');
});
test('pending disconnect is cancelled when leaving the page',async()=>{
  status={...status,connected:true};api.appActions.dispatch.mockResolvedValue({status:'confirmation_required',confirmation:{token:'review'}});
  await render();await click(button('Disconnect Google'));
  await act(async()=>root.render(null));expect(api.appActions.cancel).toHaveBeenCalledWith('review',{source:'ui'});
});
test('status failure offers refresh without inventing a connection',async()=>{
  api.plugins.googleStatus.mockRejectedValue(new Error('Backend unavailable'));
  await render();expect(host.querySelector('[role=alert]').textContent).toContain('Backend unavailable');expect(button('Connect Google').disabled).toBe(true);
  api.plugins.googleStatus.mockResolvedValue(status);await click(button('Refresh status'));expect(button('Connect Google').disabled).toBe(false);
});
test('OAuth return checks the saved flow and refreshes authoritative status',async()=>{
  vi.useFakeTimers();window.history.replaceState({},'', '/?view=apps&google_oauth=flow-return');
  api.plugins.googleOAuthStatus.mockResolvedValue({flow_id:'flow-return',status:'connected',message:'Google connected. Permission still needed for Drive.'});
  const changed=vi.fn();await render({onChanged:changed});
  expect(api.plugins.googleOAuthStatus).toHaveBeenCalledWith('flow-return');expect(changed).toHaveBeenCalled();
  expect(window.location.search).not.toContain('google_oauth');expect(host.textContent).toContain('Permission still needed for Drive');
});
