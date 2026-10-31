import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';

const require=createRequire(import.meta.url),base='../design/Velllum/uploads/components/';
const original=globalThis.Uint8Array;
let compiled;
try{globalThis.Uint8Array=new TextEncoder().encode('').constructor;compiled=createRequire(require.resolve('vite'))('esbuild').transformSync(readFileSync(base+'plugin-workspace.jsx','utf8'),{loader:'jsx'}).code;}finally{globalThis.Uint8Array=original;}
let root,host,onState,onAdd,onConfirm,items;
const fixture=()=>[
 {id:'linear',name:'Linear',description:'Real issue tracking',enabled:true,installed:true,configured:true,status:'ready',manageable:true,apps:[{name:'Linear',description:'Workspace app'}],mcp_connectors:[{name:'linear'}]},
 {id:'custom-demo',name:'Demo',description:'Personal tools',enabled:false,installed:false,manageable:true,apps:[],mcp_connectors:[]},
 {id:'core',name:'Core',description:'Required tools',enabled:true,installed:true,required:true,protected:true,manageable:true},
];
const click=async node=>{expect(node).toBeTruthy();await act(async()=>node.click());};
const button=text=>[...host.querySelectorAll('button')].find(n=>n.textContent===text);
const fill=async(node,value)=>{await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(node,value);node.dispatchEvent(new Event('input',{bubbles:true}));});};
async function render(extra={}){function Owner(){const [apps,setApps]=React.useState(items);return React.createElement(window.VellumUI.PluginWorkspace,{apps,mode:'manage',onAdd,onConfirmAdd:onConfirm,onCancelAdd:vi.fn(async()=>({status:'cancelled'})),onSkillAction:vi.fn(),onRetry:vi.fn(),...extra,onPluginState:async(id,enabled)=>{const receipt=await onState(id,enabled);if(receipt.status==='applied')setApps(old=>old.map(p=>p.id===id?{...p,...receipt.result.plugin}:p));return receipt;}});}await act(async()=>root.render(React.createElement(Owner)));}
beforeEach(()=>{globalThis.IS_REACT_ACT_ENVIRONMENT=true;window.VellumUI={};Function(readFileSync(base+'plugin-design-assets.js','utf8'))();window.VellumApi={plugins:{skillsCatalog:vi.fn(async()=>({items:[],next_cursor:null})),skillDetail:vi.fn(async()=>({name:'real-skill',description:'Actual description',skill_md:'# Actual source',read_only:true}))}};Function('React',compiled)(React);host=document.createElement('div');document.body.append(host);root=createRoot(host);items=fixture();onState=vi.fn(async(id,enabled)=>({status:'applied',result:{plugin:{id,enabled}}}));onAdd=vi.fn(async()=>({status:'confirmation_required',message:'Review this change',confirmation:{token:'fixture'}}));onConfirm=vi.fn(async()=>({status:'applied'}));});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();});

test('settings projects installed plugins and protects required controls',async()=>{await render();expect(host.querySelector('[aria-label="Enable Linear"]')).toBeTruthy();expect(host.querySelector('[aria-label="Enable Demo"]')).toBeNull();expect(host.querySelector('[aria-label="Enable Core"]').disabled).toBe(true);expect(host.textContent).not.toContain('pr@example.com');});
test('enablement follows applied receipts and failed changes keep their state',async()=>{await render();await click(host.querySelector('[aria-label="Enable Linear"]'));expect(onState).toHaveBeenCalledWith('linear',false);expect(host.querySelector('[aria-label="Enable Linear"]').getAttribute('aria-checked')).toBe('false');onState.mockResolvedValue({status:'failed',message:'Provider busy'});await click(host.querySelector('[aria-label="Enable Linear"]'));expect(host.querySelector('[role="alert"]').textContent).toContain('Provider busy');expect(host.querySelector('[aria-label="Enable Linear"]').getAttribute('aria-checked')).toBe('false');});
test('directory searches actual catalog and offers installation for uninstalled plugins',async()=>{await render({mode:'directory'});expect(host.querySelector('[aria-label="Customize"]')).toBeTruthy();expect(host.querySelector('[aria-label="Install Demo"]')).toBeTruthy();await fill(host.querySelector('input[type="search"]'),'no match');expect(host.querySelectorAll('.r')).toHaveLength(0);expect(host.textContent).toContain('No plugins match this search');});
test('MCP creation requires a backend review and never pretends connection success',async()=>{await render();await click(host.querySelector('.addb'));await click(button('Add MCP server'));await fill(host.querySelector('input[placeholder="Custom Tool"]'),'Demo tools');await fill(host.querySelector('input[aria-label="Server URL"]'),'https://example.com/mcp');await click(host.querySelector('input[type="checkbox"]'));await click(button('Create as a plugin'));expect(onAdd).toHaveBeenCalledWith('plugin.add',{kind:'mcp',name:'Demo tools',description:'',transport:'http',url:'https://example.com/mcp'});expect(onConfirm).not.toHaveBeenCalled();expect(host.querySelector('[aria-label="Review change"]')).toBeTruthy();await click(button('Confirm'));expect(onConfirm).toHaveBeenCalledOnce();});
test('SKILL.md reader displays the actual backend file',async()=>{window.VellumApi.plugins.skillsCatalog.mockResolvedValue({items:[{name:'real-skill',description:'Actual description',is_external:true}],next_cursor:null});await render({initialRoute:{v:'settings',tab:'skills'}});await click(host.querySelector('.sr2'));expect(window.VellumApi.plugins.skillDetail).toHaveBeenCalledWith('real-skill',expect.anything());expect(host.querySelector('.md').textContent).toContain('# Actual source');expect(host.querySelector('[aria-label="Enable real-skill"]').disabled).toBe(true);});
test('uninstall is a reviewed registry operation and cannot delete source files directly',async()=>{await render({initialRoute:{v:'settings',p:'linear'}});await click(button('Uninstall'));expect(host.querySelector('[aria-label="Uninstall Linear"]')).toBeTruthy();await click([...host.querySelectorAll('[aria-label="Uninstall Linear"] button')].find(b=>b.textContent==='Uninstall'));expect(onAdd).toHaveBeenCalledWith('plugin.uninstall',{plugin_id:'linear'});expect(onConfirm).toHaveBeenCalledOnce();});


test('anonymous MCP verification uses the live catalog without inventing account sign-in',async()=>{
  items=[{id:'gitmcp',name:'GitMCP',description:'Public repository documentation',enabled:true,installed:true,configured:true,manageable:true,mcp_connectors:[{name:'gitmcp'}],metadata:{connection:{anonymous:true,auth_type:'None',configured:true}}}];
  window.VellumApi.plugins.connectorTools=vi.fn().mockResolvedValue({tools:[{name:'fetch_generic_documentation',read_only:true}]});
  await render({initialRoute:{v:'settings',p:'gitmcp'}});
  expect(host.textContent).toContain('No sign-in or API key required');
  expect(window.VellumApi.plugins.connectorTools).not.toHaveBeenCalled();
  await click(button('Verify connection'));
  expect(window.VellumApi.plugins.connectorTools).toHaveBeenCalledWith('gitmcp','gitmcp');
  expect(host.textContent).toContain('Connected · 1 published tools available');
  expect(host.textContent).not.toContain('Connect another account');
});

test('plugin sidebar hide and show are driven by the applied visibility owner',async()=> {
  const visibility=vi.fn();
  function Owner(){const [visible,setVisible]=React.useState(true);return React.createElement(window.VellumUI.PluginWorkspace,{apps:items,mode:'directory',sidebarVisible:visible,onSidebarVisibility:async next=>{visibility(next);setVisible(next);return {status:'applied'};}});}
  await act(async()=>root.render(React.createElement(Owner)));
  await click(host.querySelector('[aria-label="Hide plugin sidebar"]'));
  expect(host.querySelector('[aria-label="Customize"]').getAttribute('aria-hidden')).toBe('true');
  expect(visibility).toHaveBeenLastCalledWith(false);
  await click(host.querySelector('[aria-label="Show plugin sidebar"]'));
  expect(host.querySelector('[aria-label="Customize"]')).toBeTruthy();
  expect(visibility).toHaveBeenLastCalledWith(true);
  expect(onState).not.toHaveBeenCalled();
});

test('Discord opens backend-owned bot consent without claiming it connected',async()=>{
  items=[{id:'discord',name:'Discord',enabled:true,installed:true,manageable:true}];
  window.VellumApi.plugins.discordStatus=vi.fn().mockResolvedValue({configured:true,connected:false});
  window.VellumApi.plugins.discordInstall=vi.fn().mockResolvedValue({authorization_url:'https://discord.com/oauth2/authorize?client_id=123&scope=bot'});
  const popup={location:{href:''},close:vi.fn()};
  vi.spyOn(window,'open').mockReturnValue(popup);
  await render({initialRoute:{v:'settings',p:'discord'}});
  await click(button('Install bot'));
  expect(window.VellumApi.plugins.discordInstall).toHaveBeenCalledOnce();
  expect(popup.location.href).toBe('https://discord.com/oauth2/authorize?client_id=123&scope=bot');
  expect(host.textContent).not.toContain('Discord bot connection verified.');
  expect(onAdd).not.toHaveBeenCalled();
  window.VellumApi.plugins.discordStatus.mockResolvedValue({configured:true,connected:true});
  await click(button('Verify connection'));
  expect(host.textContent).toContain('Discord bot connection verified.');
});

test.each(['https://discord.com.attacker.invalid/oauth2/authorize','http://discord.com/oauth2/authorize','https://discord.com:8443/oauth2/authorize','https://user@discord.com/oauth2/authorize','https://discord.com/other'])('Discord rejects an untrusted install URL: %s',async authorization_url=>{
  items=[{id:'discord',name:'Discord',enabled:true,installed:true,manageable:true}];
  window.VellumApi.plugins.discordStatus=vi.fn().mockResolvedValue({configured:true,connected:false});
  window.VellumApi.plugins.discordInstall=vi.fn().mockResolvedValue({authorization_url});
  const popup={location:{href:''},close:vi.fn()};
  vi.spyOn(window,'open').mockReturnValue(popup);
  await render({initialRoute:{v:'settings',p:'discord'}});
  await click(button('Install bot'));
  expect(popup.close).toHaveBeenCalledOnce();
  expect(popup.location.href).toBe('');
  expect(host.textContent).toContain('Discord returned an invalid bot authorization URL.');
});

test('Discord workspace reads wait for explicit disclosure',async()=>{
  items=[{id:'discord',name:'Discord',enabled:true,installed:true,manageable:true}];
  const renderDiscord=vi.fn(()=>React.createElement('p',null,'Existing Discord workspace'));
  await render({mode:'directory',initialRoute:{v:'detail',p:'discord'},renderDiscord});
  expect(renderDiscord).not.toHaveBeenCalled();
  const disclosure=host.querySelector('details');
  await act(async()=>{disclosure.open=true;disclosure.dispatchEvent(new Event('toggle'));});
  expect(host.textContent).toContain('Existing Discord workspace');
});

test('included MCP server opens its own published-catalog dialog',async()=>{
  await render({mode:'directory',initialRoute:{v:'detail',p:'linear'}});
  expect(host.querySelector('[aria-label="MCP servers"]')).toBeTruthy();
  await click(host.querySelector('[aria-label="Open MCP server linear"]'));
  expect(host.querySelector('[aria-label="Linear MCP server"]')).toBeTruthy();
});

test('keyed MCP setup sends only an opaque staged reference to the action runtime',async()=>{
  items=[{id:'context7',name:'Context7',enabled:true,installed:true,manageable:true}];
  window.VellumApi.plugins.keyedMcpStatus=vi.fn().mockResolvedValue({configured:false,connected:false,configured_key_available:true});
  window.VellumApi.plugins.keyedMcpStage=vi.fn().mockResolvedValue({credential_id:'opaque-reference-for-this-connection'});
  window.VellumApi.plugins.keyedMcpDiscard=vi.fn().mockResolvedValue({discarded:true});
  window.VellumApi.appActions={dispatch:vi.fn().mockResolvedValue({status:'applied',result:{connection:{configured:true,connected:true}}}),cancel:vi.fn()};
  await render({initialRoute:{v:'settings',p:'context7'}});
  await fill(host.querySelector('input[type="password"]'),'fixture-key-private');
  await act(async()=>host.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(window.VellumApi.plugins.keyedMcpStage).toHaveBeenCalledWith('context7','fixture-key-private');
  expect(window.VellumApi.appActions.dispatch).toHaveBeenCalledWith(expect.objectContaining({action_id:'context7.connection.connect',arguments:{credential_id:'opaque-reference-for-this-connection'}}),{source:'ui'});
  expect(JSON.stringify(window.VellumApi.appActions.dispatch.mock.calls)).not.toContain('fixture-key-private');
  expect(host.querySelector('input[type="password"]').value).toBe('');
  expect(window.VellumApi.plugins.keyedMcpDiscard).toHaveBeenCalledWith('context7','opaque-reference-for-this-connection');
});

test('redesigned Linear dialog exposes continuation and cancels the actual owner flow',async()=>{
  const resume=vi.fn(),cancel=vi.fn(),run=vi.fn();
  window.VellumUI.LinearWorkspace=({render})=>render({status:{configured:true,connected:false,reconnect_required:true},flow:{flow_id:'actual-flow',status:'pending'},connect:vi.fn(),run,continueSignIn:resume,cancelSignIn:cancel});
  await render({initialRoute:{v:'settings',p:'linear'}});
  await click(button('Continue to Linear'));
  expect(resume).toHaveBeenCalledOnce();
  await click(button('Cancel sign-in'));
  expect(cancel).toHaveBeenCalledOnce();
  expect(run).not.toHaveBeenCalled();
});


test.each(['settings','detail'])('YouTube connection in plugin %s opens the shared agent OAuth UI',async v=>{
  items=[{id:'youtube',name:'YouTube',description:'Creator uploads',enabled:true,installed:true,manageable:true}];
  window.VellumApi.plugins.youtubeStatus=vi.fn().mockResolvedValue({configured:true,connected:true,status:'authorization_required',authorization_required:true,channel_title:'My channel'});
  const open=vi.fn();window.addEventListener('vellum:youtube-connection-open',open);
  try{
    await render({mode:v==='detail'?'directory':'manage',initialRoute:{v,p:'youtube'}});
    expect(host.textContent).toContain('My channel');
    expect(host.querySelector('[role=alert]').textContent).toContain('Reconnect');
    await click(button('Reconnect with Google'));
    expect(open).toHaveBeenCalledOnce();expect(onAdd).not.toHaveBeenCalled();
  }finally{window.removeEventListener('vellum:youtube-connection-open',open);}
});

test('YouTube plugin shows the known Google grant deadline without claiming a permanent connection',async()=>{
  items=[{id:'youtube',name:'YouTube',enabled:true,installed:true,manageable:true}];
  window.VellumApi.plugins.youtubeStatus=vi.fn().mockResolvedValue({configured:true,connected:true,status:'ready',channel_title:'My channel',authorization_expires_at:'2026-11-05T12:13:01+00:00',authorization_expiring:false});
  await render({initialRoute:{v:'settings',p:'youtube'}});
  expect(host.textContent).toContain('Google access expires');
  expect(button('Manage Google connection')).toBeTruthy();
});
