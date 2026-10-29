import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
const require=createRequire(import.meta.url);
const source=readFileSync(resolve(dirname(fileURLToPath(import.meta.url)),'../../design/Velllum/uploads/components/slack.jsx'),'utf8');
const original=globalThis.Uint8Array;let code;
try{globalThis.Uint8Array=new TextEncoder().encode('').constructor;code=createRequire(require.resolve('vite'))('esbuild').transformSync(source,{loader:'jsx'}).code;}finally{globalThis.Uint8Array=original;}
let host,root,api,status,popup;
const button=name=>[...host.querySelectorAll('button')].find(node=>node.textContent===name);
const click=async node=>{expect(node).toBeTruthy();await act(async()=>node.click());};
const render=async()=>{new Function('React','window',code)(React,window);await act(async()=>root.render(React.createElement(window.VellumUI.SlackConnection)));};
beforeEach(()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;host=document.createElement('div');document.body.append(host);root=createRoot(host);
  status={enabled:true,configured:false,connected:false,oauth_available:true,app_id:'A12345678',client_id:'12345678.12345678',mcp_tool_count:0};
  popup={location:{href:''},close:vi.fn()};vi.spyOn(window,'open').mockReturnValue(popup);
  vi.spyOn(window,'focus').mockImplementation(()=>{});
  api={plugins:{slackStatus:vi.fn(async()=>status),slackSetup:vi.fn(async()=>({callback_url:'http://localhost:8000/api/plugins/slack/oauth/callback',manifest:{display_information:{name:'Vellum'}}})),slackOAuthWindowUrl:vi.fn(id=>'http://127.0.0.1:8000/api/plugins/slack/oauth/open?flow_id='+id),slackMcpTools:vi.fn(async()=>({tools:[]})),slackOAuthStatus:vi.fn(async()=>({flow_id:'fixture',status:'pending',message:'Continue to Slack'}))},
    appActions:{dispatch:vi.fn(async()=>({status:'applied',result:{flow_id:'fixture',status:'pending',authorization_url:'https://slack.com/oauth/v2_user/authorize?fixture=1',message:'Continue to Slack'}})),confirm:vi.fn(async()=>({status:'applied'})),cancel:vi.fn(async()=>({status:'cancelled'}))}};
  window.VellumApi=api;window.VellumUI={};
  delete window.VellumDesktop;
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();});
test('shows the real Slack identity and the official MCP connection without a credential input',async()=>{
  await render();expect(button('Sign in with Slack')).toBeTruthy();expect(host.querySelector('input[type=password]')).toBeNull();
  expect(host.textContent).toContain('official MCP server');expect(host.textContent).toContain('Copy app manifest');
  expect(host.querySelector('img[alt=Slack]').getAttribute('src')).toContain('assets/plugins/slack.png');
});
test('reserves a popup before the asynchronous OAuth request and navigates it afterward',async()=>{
  await render();await click(button('Sign in with Slack'));
  expect(window.open.mock.invocationCallOrder[0]).toBeLessThan(api.appActions.dispatch.mock.invocationCallOrder[0]);
  expect(api.appActions.dispatch.mock.calls[0][0].action_id).toBe('slack.connection.oauth.start');
  expect(api.appActions.dispatch.mock.calls[0][0].arguments.return_url).not.toContain('?view=');
  expect(popup.location.href).toBe('https://slack.com/oauth/v2_user/authorize?fixture=1');
});

test('saves only the public app registration through its typed App Action',async()=>{
  await render();await click(button('Save app registration'));
  expect(api.appActions.dispatch.mock.calls[0][0]).toMatchObject({action_id:'slack.connection.configure',arguments:{app_id:'A12345678',client_id:'12345678.12345678'}});
  expect(host.textContent).toContain('client secret');
});
test('a blocked popup still leaves a usable OAuth continuation link',async()=>{
  window.open.mockReturnValue(null);await render();await click(button('Sign in with Slack'));
  expect(host.querySelector('a[href^="https://slack.com/oauth/v2_user/authorize"]').textContent).toContain('Continue to Slack');
});
test('verified sign-in closes the OAuth popup and focuses the original app',async()=>{
  api.plugins.slackOAuthStatus.mockImplementation(async()=>{status={...status,configured:true,connected:true};return {flow_id:'fixture',status:'connected',message:'Connected to Slack.'};});
  await render();await click(button('Sign in with Slack'));
  expect(popup.close).toHaveBeenCalledOnce();expect(window.focus).toHaveBeenCalled();
  expect(host.textContent).toContain('Connected to Slack');
});
test('desktop sign-in uses only the server-owned OAuth launch route',async()=>{
  window.VellumDesktop={runtime:'electron'};
  api.plugins.slackOAuthWindowUrl=vi.fn(id=>'http://127.0.0.1:8000/api/plugins/slack/oauth/open?flow_id='+id);
  await render();await click(button('Sign in with Slack'));
  expect(window.open.mock.invocationCallOrder[0]).toBeGreaterThan(api.appActions.dispatch.mock.invocationCallOrder[0]);
  expect(window.open.mock.calls[0][0]).toBe('http://127.0.0.1:8000/api/plugins/slack/oauth/open?flow_id=fixture');
  expect(api.appActions.dispatch.mock.calls[0][0].arguments.popup).toBe(true);
});
test('disconnect uses the existing reviewed App Action instead of removing authorization immediately',async()=>{
  status={...status,configured:true,connected:true,account_name:'Fixture',login:'fixture'};
  api.appActions.dispatch.mockResolvedValue({status:'confirmation_required',confirmation:{token:'review'},message:'Review disconnect'});
  await render();await click(button('Disconnect'));
  expect(api.appActions.confirm).not.toHaveBeenCalled();expect(button('Confirm disconnect')).toBeTruthy();
  await click(button('Confirm disconnect'));expect(api.appActions.confirm).toHaveBeenCalledOnce();
});
