import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
const require=createRequire(import.meta.url);
const source=readFileSync(resolve(dirname(fileURLToPath(import.meta.url)),'../../design/Velllum/uploads/components/linear.jsx'),'utf8');
const original=globalThis.Uint8Array;let code;
try{globalThis.Uint8Array=new TextEncoder().encode('').constructor;code=createRequire(require.resolve('vite'))('esbuild').transformSync(source,{loader:'jsx'}).code;}finally{globalThis.Uint8Array=original;}
let host,root,api,status;
const button=name=>[...host.querySelectorAll('button')].find(x=>x.textContent===name);
const click=async node=>{expect(node).toBeTruthy();await act(async()=>node.click());};
const enter=async(node,value)=>{await act(async()=>{Object.getOwnPropertyDescriptor(node.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set.call(node,value);node.dispatchEvent(new Event('input',{bubbles:true}));});};
const render=async props=>{new Function('React','window',code)(React,window);await act(async()=>root.render(React.createElement(window.VellumUI.LinearWorkspace,props)));};
beforeEach(()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;host=document.createElement('div');document.body.append(host);root=createRoot(host);
  status={enabled:true,configured:false,connected:false,status:'not_connected',mcp_tool_count:68};
  api={plugins:{linearStatus:vi.fn(async()=>status),linearMcpRead:vi.fn(async()=>({tool_name:'list_issues',result:'{}'})),linearMcpTools:vi.fn(async()=>({tools:[{name:'list_issues',description:'Read issues',read_only:true,input_schema:{type:'object'}},{name:'save_issue',description:'Create or update an issue',read_only:false,input_schema:{type:'object'}}]})),linearOAuthStatus:vi.fn(async()=>({flow_id:'flow',status:'pending'}))},appActions:{dispatch:vi.fn(async()=>({status:'confirmation_required',message:'Confirm issueUpdate in Workspace',confirmation:{token:'confirm'}})),confirm:vi.fn(async()=>{status={...status,connected:true,configured:true};return {status:'applied',result:{connection:status}};}),cancel:vi.fn(async()=>({status:'cancelled'}))}};
  window.VellumApi=api;window.VellumUI={};
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.useRealTimers();});
test('shows official MCP connection controls without custom GraphQL tools',async()=>{
  await render();expect(host.textContent).toContain('68 official MCP tools');expect(host.textContent).not.toContain('query fields');expect(button('Browse API')).toBeFalsy();expect(button('Sign in with Linear')).toBeTruthy();expect(api.plugins.linearMcpRead).not.toHaveBeenCalled();
});
test('has no API key field or replacement option',async()=>{
  await render();expect(host.querySelector('input[type=password]')).toBeNull();expect(button('Review connection')).toBeFalsy();
  status={...status,configured:true,connected:true,auth_type:'oauth'};await render();expect(button('Replace key')).toBeFalsy();
});
test('disconnect requires the existing confirmed App Action',async()=>{
  status={...status,configured:true,connected:true,auth_type:'oauth'};await render();await click(button('Disconnect'));
  expect(api.appActions.dispatch.mock.calls[0][0].action_id).toBe('linear.connection.disconnect');expect(api.appActions.confirm).not.toHaveBeenCalled();
  await click(button('Confirm disconnect'));expect(api.appActions.confirm).toHaveBeenCalled();
});
test('reads issues explicitly and escapes provider content',async()=>{
  status={...status,configured:true,connected:true};api.plugins.linearMcpRead.mockResolvedValue({data:{title:'<img src=x onerror=alert(1)>'}});await render();expect(api.plugins.linearMcpRead).not.toHaveBeenCalled();await click(button('Read recent issues'));expect(host.querySelector('[aria-label="Linear API result"]').textContent).toContain('<img src=x');expect(host.querySelector('img')).toBeNull();
});
test('browses actual MCP tool details and labels writes as confirmation required',async()=>{
  status={...status,configured:true,connected:true};await render();await click(button('Browse tools'));
  expect(host.textContent).toContain('list_issues');expect(host.textContent).toContain('save_issue');expect(host.querySelector('.linear-operations img').getAttribute('src')).toContain('assets/plugins/linear.png');expect(host.textContent).toContain('Confirmation required');expect(api.plugins.linearMcpRead).not.toHaveBeenCalled();expect(api.appActions.dispatch).not.toHaveBeenCalled();
});
test('recent-issues control uses the official MCP read contract',async()=>{
  status={...status,configured:true,connected:true};await render();await click(button('Read recent issues'));
  expect(api.plugins.linearMcpRead).toHaveBeenCalledWith({tool_name:'list_issues',arguments:{limit:5,orderBy:'createdAt',fields:['id','title','url']}});expect(api.appActions.dispatch).not.toHaveBeenCalled();
});
test('OAuth uses the user-driven App Action and provider link without entering a key',async()=>{
  api.appActions.dispatch.mockResolvedValue({status:'applied',result:{flow_id:'flow',authorization_url:'https://linear.app/oauth/authorize?state=test'}});
  await render();await click(button('Sign in with Linear'));
  expect(api.appActions.dispatch.mock.calls[0][0].action_id).toBe('linear.connection.oauth.start');expect(host.querySelector('a[href*="oauth/authorize"]').href).toBe('https://linear.app/oauth/authorize?state=test');expect(api.appActions.confirm).not.toHaveBeenCalled();
  await click(button('Cancel sign-in'));expect(api.appActions.dispatch.mock.calls[1][0].action_id).toBe('linear.connection.oauth.cancel');
});
test('OAuth completion refreshes the connected identity and stops polling',async()=>{
  vi.useFakeTimers();api.appActions.dispatch.mockResolvedValue({status:'applied',result:{flow_id:'flow',authorization_url:'https://linear.app/oauth/authorize'}});
  api.plugins.linearOAuthStatus.mockImplementation(async()=>{status={...status,configured:true,connected:true,auth_type:'oauth'};return {flow_id:'flow',status:'connected',message:'Connected'};});
  await render();await click(button('Sign in with Linear'));await act(async()=>vi.advanceTimersByTimeAsync(1500));
  expect(host.textContent).toContain('Connected to Linear');expect(button('Reconnect with Linear')).toBeTruthy();await act(async()=>vi.advanceTimersByTimeAsync(3000));expect(api.plugins.linearOAuthStatus).toHaveBeenCalledTimes(1);
});
test('disabled plugin blocks OAuth and pending disconnect is cancelled on unmount',async()=>{
  status={...status,configured:true,connected:true};await render({enabled:false});expect(button('Reconnect with Linear').disabled).toBe(true);
  await render({enabled:true});await click(button('Disconnect'));await act(async()=>root.render(null));expect(api.appActions.cancel).toHaveBeenCalled();
});
test('OAuth return resumes status polling after navigation',async()=>{
  vi.useFakeTimers();window.history.replaceState({},'', '?view=apps&linear_oauth=returned-flow');
  api.plugins.linearOAuthStatus.mockResolvedValue({flow_id:'returned-flow',status:'failed',message:'Sign-in did not complete.'});
  await render();await act(async()=>vi.advanceTimersByTimeAsync(1500));expect(api.plugins.linearOAuthStatus).toHaveBeenCalledWith('returned-flow');
  expect(host.textContent).toContain('Sign-in did not complete.');expect(button('Sign in with Linear').disabled).toBe(false);
  window.history.replaceState({},'', '/');
});
test('expired OAuth return offers another sign-in instead of staying disabled',async()=>{
  vi.useFakeTimers();window.history.replaceState({},'', '?linear_oauth=expired-flow');api.plugins.linearOAuthStatus.mockRejectedValue(new Error('expired'));
  await render();await act(async()=>vi.advanceTimersByTimeAsync(1500));expect(button('Sign in with Linear').disabled).toBe(false);expect(host.querySelector('[role=alert]')).toBeTruthy();window.history.replaceState({},'', '/');
});
test('readable issue preview shows title, description and named workspace fields',async()=>{
  new Function('React','window',code)(React,window);
  const review={heading:'Create issue in Linear',confirm_label:'Create issue',title:'New plugin page for Vellum',
    description:'Redesigned browsing and added real logos.',workspace:'Pratyakksh',
    fields:[{label:'Team',value:'Vellum'},{label:'Status',value:'Done'},{label:'Labels',value:'Design, UI'}]};
  await act(async()=>root.render(React.createElement(window.VellumUI.LinearActionReview,{review})));
  expect(host.querySelector('h3').textContent).toBe('Create issue in Linear');
  expect(host.querySelector('.linear-review-title').textContent).toBe(review.title);
  expect(host.textContent).toContain(review.description);expect(host.textContent).toContain('Done');expect(host.textContent).toContain('Design, UI');
  expect(host.textContent).not.toContain('save_issue');expect(host.textContent).not.toContain('Inputs:');
  expect(host.querySelector('img').getAttribute('src')).toContain('assets/plugins/linear.png');
});
test('issue preview escapes content and makes unchanged descriptions explicit',async()=>{
  new Function('React','window',code)(React,window);
  const review={heading:'Update issue in Linear',title:'<img src=x onerror=alert(1)>',description:'',
    description_note:'Existing description will stay as it is.',workspace:'Workspace',fields:[]};
  await act(async()=>root.render(React.createElement(window.VellumUI.LinearActionReview,{review})));
  expect(host.textContent).toContain('<img src=x');expect(host.querySelector('img[onerror]')).toBeNull();
  expect(host.textContent).toContain('Existing description will stay as it is.');
});
