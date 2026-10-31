import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';

const compiled=execFileSync(process.execPath,['-e',`
  const {createRequire}=require('node:module');
  const esbuild=createRequire(require.resolve('vite'))('esbuild');
  process.stdout.write(process.argv.slice(1).map(file=>esbuild.transformSync(require('node:fs').readFileSync(file,'utf8'),{loader:'jsx'}).code).join(';'));
`,...['morphic-ui.js','v-select.jsx','browser-settings.jsx'].map(name=>resolve('../design/Velllum/uploads/components/'+name))],{encoding:'utf8'});
const defaults={location:'ask',camera:'ask',microphone:'ask',notifications:'block',javascript:'allow',images:'allow',popups:'block',third_party_cookies:'allow'};
let host,root,view,onAction,onConfirm,onCancel,settings;
beforeEach(async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  view={running:false,history:[],downloads:[],activity:[],download_directory:'C:\\Downloads',
    preferences:{search_engine:'google',suggestions_enabled:true,agent_enabled:true,agent_browsing:'allow',agent_downloads:'ask',
      agent_history:'allow',agent_screenshots:'allow',show_full_url:true,web_link_destination:'default',local_link_destination:'default',
      download_directory:'',ask_download_location:false,expire_site_permissions:true,active_profile_id:'default',
      profiles:[{id:'default',name:'Personal',site_defaults:defaults,site_rules:[]}]}};
  settings=vi.fn(async () => structuredClone(view));
  window.VellumUI={...(window.VellumUI || {}),BrowserCursorGraphic:()=>React.createElement('svg',{'aria-hidden':true})};
  window.VellumApi={browser:{settings,engines:[{id:'google',name:'Google'},{id:'brave',name:'Brave'}],control:vi.fn()}};
  onAction=vi.fn(async (action,args) => {
    if(action==='browser.settings.data')return {status:'confirmation_required',message:'Clear selected browsing data?',confirmation:{token:'bound-token'}};
    if(args.operation==='preferences')Object.assign(view.preferences,args.patch);
    if(args.operation==='create_profile')view.preferences.profiles.push({id:'a'.repeat(32),name:args.name,site_defaults:defaults,site_rules:[]});
    return {status:'applied'};
  });
  onConfirm=vi.fn(async () => ({status:'applied'}));onCancel=vi.fn();
  window.React=React;Function('React','window',compiled)(React,window);
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  await act(async () => root.render(React.createElement(window.VellumUI.BrowserSettings,{onAction,onConfirm,onCancel})));
});
afterEach(async () => {await act(async () => root.unmount());host.remove();});
const button=text=>[...host.querySelectorAll('button')].find(node=>node.textContent===text);
const click=async node=>act(async () => node.click());
const choose=async(label,text)=>{const trigger=host.querySelector(`[aria-label="${label}"]`),control=trigger.closest('.v-select');await click(trigger);await click([...control.querySelectorAll('[role="option"]')].find(node=>node.querySelector('.v-select-option-copy > span')?.textContent===text));};
const type=async (label,value)=>act(async () => {
  const input=host.querySelector(`[aria-label="${label}"]`);
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,value);
  input.dispatchEvent(new Event('input',{bubbles:true}));
});
test('settings load does not open a session and creating a profile uses the canonical action',async () => {
  expect(window.VellumApi.browser.control).not.toHaveBeenCalled();
  expect(onAction).not.toHaveBeenCalled();
  await type('New profile name','Work');
  await act(async () => host.querySelector('.bs-add').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(onAction).toHaveBeenCalledWith('browser.settings.manage',{operation:'create_profile',name:'Work',profile_id:'default'});
  expect(host.textContent).toContain('Work');expect(view.preferences.active_profile_id).toBe('default');
});
test('browser agent switch persists its actual preference',async () => {
  await click(host.querySelector('[aria-label="Enable BrowserAgent"]'));
  expect(onAction).toHaveBeenCalledWith('browser.settings.manage',{operation:'preferences',patch:{agent_enabled:false},profile_id:'default'});
  expect(host.querySelector('[aria-label="Enable BrowserAgent"]').getAttribute('aria-checked')).toBe('false');
});

test('cursor style and routine permissions save through the canonical settings action',async()=>{
  await choose('Routine browser interactions','Ask for each action');
  expect(onAction).toHaveBeenCalledWith('browser.settings.manage',{operation:'preferences',patch:{agent_interactions:'ask'},profile_id:'default'});
  await click(button('Cursor'));
  await click(host.querySelector('[aria-label="Mint cursor"]'));
  expect(onAction).toHaveBeenCalledWith('browser.settings.manage',{operation:'preferences',patch:{cursor_style:'mint'},profile_id:'default'});
  expect(host.querySelector('[aria-label="Mint cursor"]').getAttribute('aria-pressed')).toBe('true');
});
test('clearing data presents the server confirmation and executes only after Confirm',async () => {
  await click(button('History & downloads'));await click(button('Clear browsing data'));await click(button('Clear selected data…'));
  expect(onConfirm).not.toHaveBeenCalled();expect(host.querySelector('[role="alertdialog"]')).not.toBeNull();
  expect(onAction).toHaveBeenCalledWith('browser.settings.data',{operation:'clear_data',data_types:['history'],profile_id:'default'});
  await click(button('Confirm'));expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({confirmation:{token:'bound-token'}}));
  expect(host.querySelector('[role="alertdialog"]')).toBeNull();
});
test('failed preference save retains the old value and gives a recovery error',async () => {
  onAction.mockResolvedValue({status:'failed',message:'Storage is unavailable. Try again.'});
  await click(host.querySelector('[aria-label="Enable BrowserAgent"]'));
  expect(host.querySelector('[aria-label="Enable BrowserAgent"]').getAttribute('aria-checked')).toBe('true');
  expect(host.querySelector('[role="alert"]').textContent).toContain('Storage is unavailable');
});
test('site permissions are staged until Save and WebMCP is labelled unavailable',async () => {
  await click(button('Site access'));
  await choose('Camera permission','Block');
  expect(onAction).not.toHaveBeenCalled();
  await click(button('Save website permissions'));
  expect(onAction).toHaveBeenCalledWith('browser.settings.manage',expect.objectContaining({operation:'site_defaults',defaults:expect.objectContaining({camera:'block'})}));
  expect(host.textContent).toContain('Website-provided agent tools are not connected');
});
test('web and local URL destinations remain independent and reject unsafe protocols',() => {
  window.VellumApi={client:{request:vi.fn()}};
  Function('window',readFileSync(resolve('../design/Velllum/uploads/api/browser.js'),'utf8'))(window);
  const prefs={web_link_destination:'vellum',local_link_destination:'default'};
  expect(window.VellumApi.browser.linkDestination('https://example.com',prefs)).toBe('vellum');
  expect(window.VellumApi.browser.linkDestination('http://localhost:5173/page',prefs)).toBe('default');
  expect(window.VellumApi.browser.linkDestination('http://[::1]:8000',prefs)).toBe('default');
  expect(() => window.VellumApi.browser.linkDestination('javascript:alert(1)',prefs)).toThrow();
});
