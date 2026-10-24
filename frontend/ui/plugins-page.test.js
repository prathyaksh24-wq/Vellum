import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {dirname, resolve} from 'node:path';
import {afterEach, beforeEach, expect, test, vi} from 'vitest';

const require = createRequire(import.meta.url);
const html = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../design/Velllum/uploads/Vellum Default Re-designed.html'), 'utf8');
const source = new DOMParser().parseFromString(html,'text/html').querySelector('script[type="text/babel"]:not([src])').textContent;
const helpers = source.slice(source.indexOf('const CONNECTOR_STATUS_LABELS'),source.indexOf('const YouTubeIntelligenceStatus'));
const component = source.slice(source.indexOf('const BackendConnectorsView'),source.indexOf('const ArchiveView'));
const originalUint8Array = globalThis.Uint8Array;
let compiled;
try {
  globalThis.Uint8Array = new TextEncoder().encode('').constructor;
  compiled = createRequire(require.resolve('vite'))('esbuild').transformSync(helpers+'\n'+component+'\nreturn BackendConnectorsView;', {loader:'jsx'}).code;
} finally {globalThis.Uint8Array = originalUint8Array;}
const Icon = () => React.createElement('svg',{'aria-hidden':true});
const names = ['ConnLogo','IcGrid','IcSparkle','IcMcp','IcCheck','IcChevR','IcSearch','IcX','IcExternal','DiscordWorkspace','CalendarWorkspace','YouTubeIntelligenceStatus'];
const mocks = names.map(name => name === 'ConnLogo' ? props=>React.createElement('img',{'data-logo-owner':props.c.id,alt:''}) : name === 'CalendarWorkspace' ? props=>React.createElement('button',{onClick:()=>props.onStatus({connected:true,enabled:true,status:'ready'})},'Fixture calendar connected') : name==='YouTubeIntelligenceStatus' ? ()=>React.createElement('div',null,'YouTube intelligence') : Icon);
const api = {plugins:{discordInstall:vi.fn()}};
const View = new Function('React','useState','useRef','useEffect','API',...names,compiled)(React,React.useState,React.useRef,React.useEffect,api,...mocks);
const fixture = () => [
  {id:'ready',name:'Ready plugin',description:'Search documents.',status:'ready',enabled:true,manageable:true,apps:[{id:'reader',name:'Reader',description:'Read documents.'}],skills:[{id:'read',name:'Document skill'}]},
  {id:'agent-reach',name:'Agent-Reach',description:'Read posts.',status:'missing_twitter_cli',enabled:true,manageable:true,mcp_connectors:[{id:'x',name:'X server'}]},
  {id:'off',name:'Disabled plugin',status:'ready',enabled:false,manageable:true},
  {id:'required',name:'Required plugin',status:'ready',enabled:true,manageable:true,required:true},
  {id:'google-calendar',name:'Google Calendar',status:'not_connected',enabled:true,manageable:true},
  {id:'youtube',name:'YouTube',status:'ready',enabled:true,manageable:true},
];
let host,root,onPluginState,onOpenSkills;
const button = text => [...host.querySelectorAll('button')].find(b=>b.textContent===text);
const click = async target => {expect(target).toBeTruthy(); await act(async()=>target.click());};
const row = name => [...host.querySelectorAll('.plugin-row')].find(b=>b.querySelector('.plugin-row-name').textContent===name);
async function render(apps=fixture(),extra={}) {
  function Owner(){const [items,setItems]=React.useState(apps);return React.createElement(View,{apps:items,onOpenSkills,...extra,onPluginState:async(id,enabled)=>{
    const receipt=await onPluginState(id,enabled);
    if(receipt.status==='applied')setItems(old=>old.map(p=>p.id===id?{...p,...receipt.result.plugin}:p));
    return receipt;
  }});}
  await act(async()=>root.render(React.createElement(Owner)));
}
beforeEach(()=>{
  window.VellumUI={};
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  onOpenSkills=vi.fn();
  onPluginState=vi.fn(async(id,enabled)=>({status:'applied',result:{plugin:{id,enabled}}}));
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();});

test('groups real readiness and keeps unrelated intelligence out of the catalog',async()=>{
  await render();
  expect(host.querySelectorAll('.plugin-row')).toHaveLength(6);
  expect(host.querySelector('[aria-label="Needs setup"]').textContent).toContain('Agent-Reach');
  expect(row('Agent-Reach').textContent).toContain('Install twitter-cli');
  expect(row('Google Calendar').textContent).toContain('Needs setup');
  expect(host.querySelector('[aria-label="Disabled"]').textContent).toContain('Disabled plugin');
  expect(host.textContent).not.toContain('Active');
  expect(host.textContent).not.toContain('YouTube intelligence');
});

test('filters, searches, clears and explains no matches',async()=>{
  await render();
  await click(button('Needs setup'));
  expect(host.querySelectorAll('.plugin-row')).toHaveLength(2);
  const input=host.querySelector('input');
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'no match');input.dispatchEvent(new Event('input',{bubbles:true}));});
  expect(host.querySelectorAll('.plugin-row')).toHaveLength(0);
  expect(host.querySelector('[role="status"]').textContent).toContain('No matching plugins');
  await click(button('Clear filters'));
  expect(input.value).toBe('');
  expect(host.querySelectorAll('.plugin-row')).toHaveLength(6);
});

test('opens full details, shows only included content, and restores keyboard focus',async()=>{
  await render();
  await click(row('Ready plugin'));
  expect(host.querySelector('.plugins-grid')).toBeNull();
  expect(document.activeElement).toBe(host.querySelector('h1'));
  expect(host.querySelector('[aria-label="Apps"]').textContent).toContain('Reader');
  expect(host.querySelector('[aria-label="Skills"]').textContent).toContain('Document skill');
  expect(host.querySelector('[aria-label="MCP servers"]')).toBeNull();
  await click(button('Back to plugins'));
  expect(document.activeElement).toBe(row('Ready plugin'));
});

test('content navigation resets status filters and retains parent context',async()=>{
  await render();await click(button('Disabled'));
  await click([...host.querySelectorAll('.plugin-tab')].find(b=>b.textContent.startsWith('Apps')));
  expect(host.querySelectorAll('.plugin-row')).toHaveLength(1);
  await click(row('Reader'));
  expect(host.textContent).toContain('Included with Ready plugin');
  expect(button('Disable plugin')).toBeUndefined();
  await click(button('Back to apps'));
  await click(button('Open Skills Hub'));
  expect(onOpenSkills).toHaveBeenCalledOnce();
});

test('applies plugin changes only through an applied owner receipt',async()=>{
  await render();await click(row('Ready plugin'));
  await click(button('Disable plugin'));
  expect(onPluginState).toHaveBeenCalledWith('ready',false);
  expect(button('Enable plugin')).toBeTruthy();
  expect(host.querySelector('[role="status"]').textContent).toContain('Disabled');
  await click(button('Back to plugins'));
  expect(host.querySelector('[aria-label="Disabled"]').textContent).toContain('Ready plugin');
});

test('failed receipts preserve enabled state and explain the failure',async()=>{
  onPluginState.mockResolvedValue({status:'failed',message:'Plugin is busy. Try again.'});
  await render();await click(row('Ready plugin'));await click(button('Disable plugin'));
  expect(host.querySelector('[role="alert"]').textContent).toContain('Plugin is busy. Try again.');
  expect(button('Disable plugin')).toBeTruthy();
});

test('required plugins cannot be disabled and technical details start collapsed',async()=>{
  await render();await click(row('Required plugin'));
  expect(button('Required').disabled).toBe(true);
  expect(onPluginState).not.toHaveBeenCalled();
  await click(button('Back to plugins'));await click(row('Agent-Reach'));
  expect(host.querySelector('details').open).toBe(false);
  expect(host.querySelector('details').textContent).toContain('X server');
});

test('calendar status refresh and YouTube intelligence remain in their own details',async()=>{
  await render();await click(row('Google Calendar'));
  await click(button('Fixture calendar connected'));
  expect(host.querySelector('[role="status"]').textContent).toContain('Connected');
  await click(button('Back to plugins'));await click(row('YouTube'));
  expect(host.textContent).toContain('YouTube intelligence');
});

test('an empty installed catalog has a truthful empty state',async()=>{
  await render([]);
  expect(host.textContent).toContain('No plugins yet');
  expect(host.textContent).not.toContain('Ready to use');
});

test('loading and unavailable catalogs do not pretend to be empty installations',async()=>{
  await render([],{catalogState:{loading:true,error:''}});
  expect(host.textContent).toContain('Loading your plugins');
  expect(host.textContent).not.toContain('No plugins yet');
  const retry=vi.fn();
  await render([],{catalogState:{loading:false,error:'Could not load plugins.'},onRetry:retry});
  expect(host.querySelector('[role="alert"]').textContent).toContain('Could not load plugins.');
  await click(button('Try again'));
  expect(retry).toHaveBeenCalledOnce();
});

test('available publisher bundles keep the backend availability label',async()=>{
  await render([{id:'design-partner',name:'Design Partner',type:'bundle',status:'available',configured:true,enabled:true}]);
  expect(host.querySelector('[aria-label="Ready to use"]').textContent).toContain('Design Partner');
  expect(row('Design Partner').textContent).toContain('Available');
  await click(row('Design Partner'));
  expect(host.querySelector('[role="status"]').textContent).toContain('Installed and available');
});

test('directory groups actual categories and uses its own navigation',async()=>{
  await render(fixture(),{mode:'directory'});
  expect(host.querySelector('[aria-label="Customize"]')).toBeTruthy();
  expect(host.querySelector('[aria-label="Browse by category"]')).toBeTruthy();
  await click(button('MCP'));
  expect(host.querySelectorAll('.plugins-grid .plugin-row')).toHaveLength(5);
});

test('settings switches use applied receipts and do not nest controls inside row buttons',async()=>{
  await render();
  const control=host.querySelector('[role="switch"][aria-label="Enable Ready plugin"]');
  expect(control.closest('.plugin-row')).toBeNull();
  await click(control);
  expect(onPluginState).toHaveBeenCalledWith('ready',false);
  expect(host.querySelector('[aria-label="Enable Ready plugin"]').getAttribute('aria-checked')).toBe('false');
});

test('Spotify controls appear only inside Spotify details',async()=>{
  await render([...fixture(),{id:'spotify',name:'Spotify',enabled:true,status:'ready'}],{spotifyControls:React.createElement('div',null,'Spotify connection controls')});
  expect(host.textContent).not.toContain('Spotify connection controls');
  await click(row('YouTube'));expect(host.textContent).not.toContain('Spotify connection controls');
  await click(button('Back to plugins'));await click(row('Google Calendar'));
  expect(host.textContent).not.toContain('Spotify connection controls');
  await click(button('Back to plugins'));await click(row('Spotify'));
  expect(host.textContent).toContain('Spotify connection controls');
});

test('Skills tab embeds the canonical hub and owned skills can open its reader',async()=>{
  const renderSkills=vi.fn(skill=>React.createElement('div',null,skill?'Skill reader '+skill.name:'Canonical Skills Hub'));
  await render(fixture(),{renderSkills});
  await click(row('Ready plugin'));await click(button('View skill'));
  expect(host.textContent).toContain('Skill reader Document skill');
});

test.each(['gmail','google-drive','google-calendar','google-contacts','linear','spotify','youtube'])('tool rows keep their real provider identity for %s',async id=>{
  await render([{id,name:id,enabled:true,status:'ready',tools:[id+'_fixture_tool']}]);
  await click(row(id));
  const tools=host.querySelector('[aria-label="Tools"]');
  expect(tools.querySelector('img').getAttribute('data-logo-owner')).toBe(id);
  expect(tools.querySelector('svg')).toBeNull();
});
