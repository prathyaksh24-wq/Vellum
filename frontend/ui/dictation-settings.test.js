import {beforeEach,afterEach,test,expect,vi} from 'vitest';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
const compile=path=>execFileSync(process.execPath,['-e',`
  const {createRequire}=require('node:module');
  const esbuild=createRequire(require.resolve('vite'))('esbuild');
  process.stdout.write(esbuild.transformSync(require('node:fs').readFileSync(process.argv[1],'utf8'),{loader:'jsx'}).code);
`,resolve(path)],{encoding:'utf8'});
const compiled=compile('../design/Velllum/uploads/components/dictation-settings.jsx');
const selectCompiled=compile('../design/Velllum/uploads/components/v-select.jsx');
let host,root,view,onAction,onConfirm,onCancel;
const entry={id:'a'.repeat(32),created_at:'2026-10-19T12:00:00Z',text:'Kannada with 22 piece',language:'kn',requested_language:'kn',duration_seconds:4.5,model:'openai/whisper-large-v3-turbo',has_recording:true};
beforeEach(async()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  view={settings:{language:'auto',save_history:true,dictionary:[],hold_shortcut:'',toggle_shortcut:'Ctrl+Shift+D'},available_languages:['en','kn','ta'],items:[entry],language_counts:{kn:1},total:1,offset:0,limit:30};
  window.VellumApi={voice:{languageName:code=>({kn:'Kannada',en:'English',ta:'Tamil',auto:'Auto detect'})[code] || code,
    dictationPreferences:vi.fn(async()=>view),dictationHistory:vi.fn(async()=>view),downloadDictation:vi.fn(async()=>{})}};
  Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:vi.fn(async()=>{})}});
  onAction=vi.fn(async(id,args)=>{
    if(id==='dictation.settings.update')return {status:'applied',result:{dictation_settings:{...view.settings,...args.patch}}};
    return {status:'confirmation_required',confirmation:{token:'bound-delete'},request:{action_id:id,arguments:args}};
  });
  onConfirm=vi.fn(async()=>{view={...view,items:[],language_counts:{},total:0};return {status:'applied'};});
  onCancel=vi.fn(async()=>({status:'cancelled'}));
  Function('React','window',selectCompiled)(React,window);
  Function('React','window',compiled)(React,window);
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  await act(async()=>{root.render(React.createElement(window.VellumUI.Dictation.Settings,{onAction,onConfirm,onCancel}));});
  await act(async()=>{await new Promise(resolve=>setTimeout(resolve,10));});
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();});
const button=text=>[...host.querySelectorAll('button')].find(node=>node.textContent===text);
test('loads completed text and languages without triggering a mutation, and copies exact text',async()=>{
  expect(host.textContent).toContain(entry.text);expect(host.textContent).toContain('Kannada');
  expect(onAction).not.toHaveBeenCalled();
  await act(async()=>host.querySelector('[aria-label="Copy dictation"]').click());
  expect(navigator.clipboard.writeText).toHaveBeenCalledWith(entry.text);
  expect(host.querySelector('[aria-label="Copied"]')).toBeTruthy();
});
test('explicit language and history switch dispatch typed actions',async()=>{
  await act(async()=>host.querySelector('[aria-label="Dictation language"][role="combobox"]').click());
  await act(async()=>host.querySelector('#dictation-language-list [role="option"]:nth-child(3)').click());
  expect(onAction).toHaveBeenLastCalledWith('dictation.settings.update',{patch:{language:'kn'}});
  expect(host.querySelector('[aria-label="Dictation language"][role="combobox"]').textContent).toBe('Kannada');
  await act(async()=>host.querySelector('[role="switch"]').click());
  expect(onAction).toHaveBeenLastCalledWith('dictation.settings.update',{patch:{save_history:false}});
  expect(host.querySelector('[role="switch"]').getAttribute('aria-checked')).toBe('false');
  expect(host.textContent).toContain(entry.text);
});
test('deleting one record remains pending until confirmation and refreshes only after success',async()=>{
  await act(async()=>host.querySelector('[aria-label="Recording options"]').click());
  await act(async()=>button('Delete recording').click());
  expect(onAction).toHaveBeenLastCalledWith('dictation.history.delete',{entry_id:entry.id});
  expect(onConfirm).not.toHaveBeenCalled();expect(host.textContent).toContain(entry.text);
  await act(async()=>button('Delete permanently').click());
  expect(onConfirm).toHaveBeenCalledTimes(1);expect(host.textContent).not.toContain(entry.text);
});
test('clear-history cancellation does not remove any records',async()=>{
  await act(async()=>button('Clear history').click());
  expect(onAction).toHaveBeenLastCalledWith('dictation.history.delete',{all:true});
  await act(async()=>button('Keep history').click());
  expect(onCancel).toHaveBeenCalledTimes(1);expect(onConfirm).not.toHaveBeenCalled();
  expect(host.textContent).toContain(entry.text);
});


test('downloads the selected recording and expands full text without mutating history',async()=>{
  await act(async()=>host.querySelector('[aria-label="Recording options"]').click());
  await act(async()=>button('Download recording').click());
  expect(window.VellumApi.voice.downloadDictation).toHaveBeenCalledWith(entry.id);
  await act(async()=>host.querySelector('[aria-label="Read transcript"]').click());
  expect(host.querySelector('.dictation-full-transcript').textContent).toBe(entry.text);
  expect(onAction).not.toHaveBeenCalled();
});

test('dictionary changes save through the settings owner and retain failed edits',async()=>{
  await act(async()=>button('Add entry').click());
  const input=host.querySelector('[aria-label="Dictionary word 1"]');
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'Vellum');input.dispatchEvent(new Event('input',{bubbles:true}));});
  onAction.mockResolvedValueOnce({status:'failed',message:'Try again.'});
  await act(async()=>button('Save words').click());
  expect(onAction).toHaveBeenLastCalledWith('dictation.settings.update',{patch:{dictionary:['Vellum']}});
  expect(input.value).toBe('Vellum');expect(button('Save words')).toBeTruthy();
  await act(async()=>button('Save words').click());
  expect(button('Save words')).toBeFalsy();
});

test('captures and persists a shortcut without running it during editing',async()=>{
  await act(async()=>host.querySelector('[aria-label="Set single-tap shortcut"]').click());
  const input=host.querySelector('[data-shortcut-capture]');
  await act(async()=>input.dispatchEvent(new KeyboardEvent('keydown',{key:'q',code:'KeyQ',ctrlKey:true,altKey:true,bubbles:true,cancelable:true})));
  expect(input.value).toBe('Ctrl+Alt+Q');
  await act(async()=>button('Save').click());
  expect(onAction).toHaveBeenLastCalledWith('dictation.settings.update',{patch:{toggle_shortcut:'Ctrl+Alt+Q'}});
});

test('configured shortcuts toggle, hold and double tap through the composer event',async()=>{
  await act(async()=>root.unmount());root=createRoot(host);
  view.settings={...view.settings,hold_shortcut:'Ctrl+Alt+Space',toggle_shortcut:'Ctrl+Alt+Q'};
  function Harness(){window.VellumUI.Dictation.useShortcuts();return null;}
  await act(async()=>root.render(React.createElement(Harness)));
  const commands=[],listen=e=>commands.push(e.detail);window.addEventListener('vellum-composer',listen);
  const key=(type,code,options={})=>window.dispatchEvent(new KeyboardEvent(type,{code,ctrlKey:true,altKey:true,bubbles:true,cancelable:true,...options}));
  try {
    key('keydown','KeyQ');expect(commands.pop()).toBe('dictation');
    key('keydown','Space');expect(commands.pop()).toBe('dictation-start');
    key('keyup','Space');key('keydown','Space');key('keyup','Space');
    await new Promise(resolve=>setTimeout(resolve,350));expect(commands).toEqual([]);
    key('keydown','Space');expect(commands.pop()).toBe('dictation-stop');
    key('keydown','Space');key('keyup','Space');
    await new Promise(resolve=>setTimeout(resolve,350));expect(commands).toEqual(['dictation-start','dictation-stop']);
  }finally{window.removeEventListener('vellum-composer',listen);}
});
