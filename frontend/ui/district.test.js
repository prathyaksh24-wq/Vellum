import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
const require=createRequire(import.meta.url);
const source=readFileSync(resolve(dirname(fileURLToPath(import.meta.url)),'../../design/Velllum/uploads/components/district.jsx'),'utf8');
const original=globalThis.Uint8Array;let code;
try{globalThis.Uint8Array=new TextEncoder().encode('').constructor;code=createRequire(require.resolve('vite'))('esbuild').transformSync(source,{loader:'jsx'}).code;}finally{globalThis.Uint8Array=original;}
let host,root,api,status,popup;
const button=name=>[...host.querySelectorAll('button')].find(node=>node.textContent===name);
const click=async node=>{expect(node).toBeTruthy();await act(async()=>node.click());};
const render=async()=>{new Function('React','window',code)(React,window);await act(async()=>root.render(React.createElement(window.VellumUI.DistrictConnection)));};
beforeEach(()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;host=document.createElement('div');document.body.append(host);root=createRoot(host);
  status={enabled:true,configured:false,connected:false,oauth_available:true,mcp_tool_count:0};
  popup={location:{href:''},close:vi.fn()};vi.spyOn(window,'open').mockReturnValue(popup);
  vi.spyOn(window,'focus').mockImplementation(()=>{});
  api={plugins:{districtStatus:vi.fn(async()=>status),districtOAuthWindowUrl:vi.fn(id=>'http://127.0.0.1:8000/api/plugins/district/oauth/open?flow_id='+id),districtMcpTools:vi.fn(async()=>({tools:[]})),districtOAuthStatus:vi.fn(async()=>({flow_id:'fixture',status:'pending',message:'Continue to District'}))},
    appActions:{dispatch:vi.fn(async()=>({status:'applied',result:{flow_id:'fixture',status:'pending',authorization_url:'https://mcp-server.district.in/authorize?fixture=1',message:'Continue to District'}})),confirm:vi.fn(async()=>({status:'applied'})),cancel:vi.fn(async()=>({status:'cancelled'}))}};
  window.VellumApi=api;window.VellumUI={WebSearchSettings:()=>null};
  delete window.VellumDesktop;
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();});
test('shows District’s real logo and OAuth connection without a credential input',async()=>{
  await render();expect(button('Sign in with District')).toBeTruthy();expect(host.querySelector('input[type=password]')).toBeNull();
    expect(host.querySelector('a[href^="https://chatgpt.com/plugins/"]')).not.toBeNull();expect(host.textContent).toContain('Each user signs in with their own District account.');
  expect(host.querySelector('img[alt=District]').getAttribute('src')).toContain('assets/plugins/district.png');
});
test('reserves a popup before the asynchronous OAuth request and navigates it afterward',async()=>{
  await render();await click(button('Sign in with District'));
  expect(window.open.mock.invocationCallOrder[0]).toBeLessThan(api.appActions.dispatch.mock.invocationCallOrder[0]);
  expect(api.appActions.dispatch.mock.calls[0][0].action_id).toBe('district.connection.oauth.start');
  expect(api.appActions.dispatch.mock.calls[0][0].arguments.return_url).not.toContain('?view=');
  expect(popup.location.href).toBe('https://mcp-server.district.in/authorize?fixture=1');
});

test('a blocked popup still leaves a usable OAuth continuation link',async()=>{
  window.open.mockReturnValue(null);await render();await click(button('Sign in with District'));
  expect(host.querySelector('a[href^="http://127.0.0.1:8000/api/plugins/district/oauth/open"]').textContent).toContain('Continue to District');
});
test('verified sign-in closes the OAuth popup and focuses the original app',async()=>{
  api.plugins.districtOAuthStatus.mockImplementation(async()=>{status={...status,configured:true,connected:true};return {flow_id:'fixture',status:'connected',message:'Connected to District.'};});
  await render();await click(button('Sign in with District'));
  expect(popup.close).toHaveBeenCalledOnce();expect(window.focus).toHaveBeenCalled();
  expect(host.textContent).toContain('Connected to District');
});
test('desktop sign-in uses only the server-owned OAuth launch route',async()=>{
  window.VellumDesktop={runtime:'electron'};
  api.plugins.districtOAuthWindowUrl=vi.fn(id=>'http://127.0.0.1:8000/api/plugins/district/oauth/open?flow_id='+id);
  await render();await click(button('Sign in with District'));
  expect(window.open.mock.invocationCallOrder[0]).toBeGreaterThan(api.appActions.dispatch.mock.invocationCallOrder[0]);
  expect(window.open.mock.calls[0][0]).toBe('http://127.0.0.1:8000/api/plugins/district/oauth/open?flow_id=fixture');
  expect(api.appActions.dispatch.mock.calls[0][0].arguments.popup).toBe(true);
});
test('disconnect uses the existing reviewed App Action instead of removing authorization immediately',async()=>{
  status={...status,configured:true,connected:true,account_name:'Fixture',login:'fixture'};
  api.appActions.dispatch.mockResolvedValue({status:'confirmation_required',confirmation:{token:'review'},message:'Review disconnect'});
  await render();await click(button('Disconnect'));
  expect(api.appActions.confirm).not.toHaveBeenCalled();expect(button('Confirm disconnect')).toBeTruthy();
  await click(button('Confirm disconnect'));expect(api.appActions.confirm).toHaveBeenCalledOnce();
});
