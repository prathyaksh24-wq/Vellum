import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';

const require=createRequire(import.meta.url);
function compile(source){const original=globalThis.Uint8Array;try{globalThis.Uint8Array=new TextEncoder().encode('').constructor;return createRequire(require.resolve('vite'))('esbuild').transformSync(source,{loader:'jsx'}).code;}finally{globalThis.Uint8Array=original;}}
const source=compile(readFileSync('../design/Velllum/uploads/components/vellum-face.jsx','utf8'));
let host,root,motion,visibility;
const button=text=>[...host.querySelectorAll('button')].find(item=>item.textContent===text);
const fill=async(label,value)=>{const input=host.querySelector(`[aria-label="${label}"]`);await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));});};
beforeEach(()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  motion={matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()};
  vi.stubGlobal('matchMedia',()=>motion);
  vi.stubGlobal('requestAnimationFrame',vi.fn(()=>1));vi.stubGlobal('cancelAnimationFrame',vi.fn());
  vi.stubGlobal('IntersectionObserver',class{observe(){}disconnect(){}});
  visibility=vi.spyOn(document,'hidden','get').mockReturnValue(false);
  Function('React',source)(React);host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();localStorage.clear();});

test('arbitrary colors preview immediately but persist only after Apply',async()=>{
  const save=vi.fn(async()=>({status:'applied'}));
  await act(async()=>root.render(React.createElement(window.VellumUI.FaceSettings,{onDeviceSettings:save})));
  expect(host.querySelector('input[type="color"]').value).toBe('#06a3ff');
  await fill('Face color','#7b42d9');
  expect(host.querySelector('.face-live-preview').style.getPropertyValue('--vellum-face-color')).toBe('#7b42d9');
  expect(save).not.toHaveBeenCalled();
  await act(async()=>button('Apply color').click());
  expect(save).toHaveBeenCalledExactlyOnceWith({face_color:'#7b42d9'});
  expect(host.querySelector('[role="status"]').textContent).toBe('Color saved on this device.');
});

test('invalid hex keeps the last valid preview and disables saving',async()=>{
  const save=vi.fn();await act(async()=>root.render(React.createElement(window.VellumUI.FaceSettings,{onDeviceSettings:save})));
  await fill('Face hex color','#aabbcc');await fill('Face hex color','#zzzzzz');
  expect(host.querySelector('.face-live-preview').style.getPropertyValue('--vellum-face-color')).toBe('#aabbcc');
  expect(host.querySelector('[role="alert"]').textContent).toContain('six-digit');expect(button('Apply color').disabled).toBe(true);expect(save).not.toHaveBeenCalled();
});

test('failed writes retain the preview for retry and Reset restores default blue',async()=>{
  const save=vi.fn().mockResolvedValueOnce({status:'failed',message:'Please retry'}).mockResolvedValueOnce({status:'applied'});
  await act(async()=>root.render(React.createElement(window.VellumUI.FaceSettings,{color:'#aabbcc',onDeviceSettings:save})));
  await fill('Face hex color','#000000');await act(async()=>button('Apply color').click());
  expect(host.querySelector('[role="status"]').textContent).toBe('Please retry');expect(button('Apply color').disabled).toBe(false);
  await act(async()=>button('Reset to blue').click());expect(host.querySelector('input[type="color"]').value).toBe('#06a3ff');
  await act(async()=>button('Apply color').click());expect(save).toHaveBeenLastCalledWith({face_color:'#06a3ff'});
});

test('Glow Orange previews the supplied icon and saves the original face color',async()=>{
  const save=vi.fn(async()=>({status:'applied'}));
  await act(async()=>root.render(React.createElement(window.VellumUI.FaceSettings,{onDeviceSettings:save})));
  await act(async()=>button('Glow Orange').click());
  expect(host.querySelector('input[type="color"]').value).toBe('#f45434');
  expect(host.querySelector('img[alt="Glow orange desktop icon"]').getAttribute('src')).toBe('assets/brand/vellum-icon-orange.png');
  expect(save).not.toHaveBeenCalled();
  await act(async()=>button('Apply color').click());
  expect(save).toHaveBeenCalledExactlyOnceWith({face_color:'#f45434'});
});

test('preview changes are discarded when Settings remounts without Apply',async()=>{
  await act(async()=>root.render(React.createElement(window.VellumUI.FaceSettings,{color:'#aabbcc'})));
  await fill('Face hex color','#ff8800');
  await act(async()=>root.render(null));await act(async()=>root.render(React.createElement(window.VellumUI.FaceSettings,{color:'#aabbcc'})));
  expect(host.querySelector('input[type="color"]').value).toBe('#aabbcc');
});

test('faces have unique SVG references, keyboard interaction, and reduced-motion stillness',async()=>{
  await act(async()=>root.render(React.createElement('div',null,React.createElement(window.VellumUI.VellumFace),React.createElement(window.VellumUI.VellumFace,{interactive:false}))));
  const ids=[...host.querySelectorAll('[id]')].map(item=>item.id);expect(new Set(ids).size).toBe(ids.length);
  expect(host.querySelector('[role="button"]').tabIndex).toBe(0);expect(host.querySelector('[role="img"]').hasAttribute('tabindex')).toBe(false);
  expect(requestAnimationFrame).not.toHaveBeenCalled();
  await act(async()=>host.querySelector('[role="button"]').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true})));
  expect(requestAnimationFrame).not.toHaveBeenCalled();
});

test('animation pauses in hidden documents and stops on unmount',async()=>{
  motion.matches=false;
  await act(async()=>root.render(React.createElement(window.VellumUI.VellumFace)));
  expect(requestAnimationFrame).toHaveBeenCalledOnce();
  visibility.mockReturnValue(true);await act(async()=>document.dispatchEvent(new Event('visibilitychange')));
  expect(cancelAnimationFrame).toHaveBeenCalledWith(1);
  requestAnimationFrame.mockClear();await act(async()=>root.render(null));
  expect(motion.removeEventListener).toHaveBeenCalledWith('change',expect.any(Function));
});

test('face color survives a receipt and reload through the existing settings owner',async()=>{
  Function(readFileSync('../design/Velllum/uploads/components/app-action-runtime.js','utf8'))();
  const AppActions=window.VellumUI.AppActions;
  const runtime=AppActions.createDeviceSettingsRuntime({storage:localStorage,client:{dispatch:vi.fn()}});
  expect(runtime.snapshot().values.face_color).toBe('#06a3ff');
  runtime.applyReceipt({status:'applied',result:{device_settings_patch:{version:1,base_revision:0,revision:1,values:{face_color:'#abcdef'}}}});
  const reloaded=AppActions.createDeviceSettingsRuntime({storage:localStorage,client:{}});
  expect(reloaded.snapshot()).toMatchObject({revision:1,values:{face_color:'#abcdef',accent:'default',background:'galaxy'}});
});
