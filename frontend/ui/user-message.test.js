import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {afterEach,expect,test,vi} from 'vitest';

const require=createRequire(import.meta.url);
const html=readFileSync('../design/Velllum/uploads/Vellum Default Re-designed.html','utf8');
const source=html.slice(html.indexOf('const userMessageTime ='),html.indexOf('const MsgActions ='));
const originalUint8Array=globalThis.Uint8Array;
let compiled;
try {globalThis.Uint8Array=new TextEncoder().encode('').constructor;compiled=createRequire(require.resolve('vite'))('esbuild').transformSync(source,{loader:'jsx'}).code;}
finally {globalThis.Uint8Array=originalUint8Array;}
const originalClipboard=Object.getOwnPropertyDescriptor(navigator,'clipboard');
const Icon=()=>null;
const {UserMessage,userMessageTime}=Function('React','useState','useRef','useEffect','useLayoutEffect','IcFile','IcCopy','IcCheck',compiled+';return {UserMessage,userMessageTime};')(React,React.useState,React.useRef,React.useEffect,React.useLayoutEffect,Icon,Icon,Icon);
let root,host;
async function mount(props){
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  window.VellumUI={AppIcon:Icon};
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  await act(async()=>root.render(React.createElement(UserMessage,props)));
}
afterEach(async()=>{await act(async()=>root?.unmount());host?.remove();vi.restoreAllMocks();if(originalClipboard)Object.defineProperty(navigator,'clipboard',originalClipboard);else delete navigator.clipboard;});

test('sent time uses the recorded day and survives later renders',()=>{
  const date=new Date(2026,10,11,11,27);
  const message={sent_at:date.toISOString()};
  const stamp=userMessageTime(message,new Date(2026,10,12,9));
  expect(stamp.iso).toBe(message.sent_at);
  expect(stamp.label).toContain(date.toLocaleDateString(undefined,{weekday:'long'}));
  expect(stamp.label).toContain(date.toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'}));
  expect(userMessageTime(message,date).label).toMatch(/^Today /);
  expect(userMessageTime({})).toBeNull();
  expect(userMessageTime({sent_at:'invalid'})).toBeNull();
});

test('copy writes the request and reports actual clipboard success',async()=>{
  const writeText=vi.fn(async()=>{});
  Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText}});
  await mount({msg:{id:'u',text:'Copy this',sent_at:'2026-11-11T05:57:00Z'},onEdit:vi.fn()});
  await act(async()=>host.querySelector('[aria-label="Copy message"]').click());
  expect(writeText).toHaveBeenCalledWith('Copy this');
  expect(host.querySelector('[role="status"]').textContent).toBe('Message copied');
});

test('edit saves the chosen request and preserves the displayed sent time',async()=>{
  const onEdit=vi.fn(async()=>{});
  const msg={id:'u',text:'Original',sent_at:'2026-11-11T05:57:00Z'};
  await mount({msg,onEdit});
  await act(async()=>host.querySelector('[aria-label="Edit message"]').click());
  const input=host.querySelector('textarea');
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,'Corrected');input.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async()=>host.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(onEdit).toHaveBeenCalledWith('u','Corrected');
  expect(host.querySelector('textarea')).toBeNull();
  expect(host.querySelector('time').dateTime).toBe('2026-11-11T05:57:00.000Z');
});

test('failed save leaves the draft open; streaming disables editing',async()=>{
  await mount({msg:{id:'u',text:'Original'},onEdit:async()=>{throw Error('Stale request');}});
  await act(async()=>host.querySelector('[aria-label="Edit message"]').click());
  const input=host.querySelector('textarea');
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,'Corrected');input.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async()=>host.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(host.querySelector('[role="alert"]').textContent).toBe('Stale request');
  expect(host.querySelector('textarea').value).toBe('Corrected');
  await act(async()=>root.render(React.createElement(UserMessage,{key:'busy',msg:{id:'b',text:'Busy'},busy:true,onEdit:vi.fn()})));
  expect(host.querySelector('[aria-label="Edit message"]').disabled).toBe(true);
});
