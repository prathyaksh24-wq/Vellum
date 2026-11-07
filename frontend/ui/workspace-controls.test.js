import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {afterEach,expect,test,vi} from 'vitest';
const require=createRequire(import.meta.url),original=globalThis.Uint8Array;
function load(file){let code;try{globalThis.Uint8Array=new TextEncoder().encode('').constructor;code=createRequire(require.resolve('vite'))('esbuild').transformSync(readFileSync('../design/Velllum/uploads/components/'+file,'utf8'),{loader:'jsx'}).code;}finally{globalThis.Uint8Array=original;}Function('React',code)(React);}
let root,host;
async function mount(element){globalThis.IS_REACT_ACT_ENVIRONMENT=true;host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(element));}
afterEach(async()=>{await act(async()=>root?.unmount());host?.remove();delete window.VellumDesktop;});
test('full workspace always exposes restore and hide controls, including empty main chat',async()=>{
  window.VellumUI={AppIcon:()=>null};load('workspace-controller.jsx');const layout=vi.fn(),hide=vi.fn();
  await mount(React.createElement(window.VellumUI.WorkspaceToolbar,{controller:{trigger:React.createRef(),error:''},workspace:{mode:'full',visible:true,tabs:[{id:'one',kind:'launcher',title:'New tab'}],layout,hide},title:''}));
  await act(async()=>host.querySelector('[aria-label="Restore split view"]').click());expect(layout).toHaveBeenCalledWith('split');
  await act(async()=>host.querySelector('[aria-label="Hide workspace views"]').click());expect(hide).toHaveBeenCalledOnce();
});
test('workspace folders use the bounded native reader and chat files keep their previews',async()=>{
  window.VellumUI={AppIcon:()=>null};load('workspace-content.jsx');
  const read=vi.fn(async args=>args.operation==='list'
    ? {workspace_root:'C:\\Workspace',entries:[{name:'notes.txt',path:'notes.txt',directory:false}]}
    : {id:'notes.txt',name:'notes.txt',mime_type:'text/plain',text_content:'Local file fixture'});
  window.VellumDesktop={runtime:'electron',files:{read}};
  const items=[{id:'directory',kind:'directory',reference_id:'workspace'},{id:'files',kind:'files',reference_id:'library'}];
  await mount(React.createElement(window.VellumUI.WorkspaceContent,{items,activeId:'directory',directoryAvailable:true,visible:true,chats:[],library:[]}));
  expect(read).toHaveBeenCalledWith({operation:'list',relativePath:''});
  await act(async()=>[...host.querySelectorAll('button')].find(n=>n.textContent==='notes.txt').click());
  expect(read).toHaveBeenCalledWith({operation:'read',relativePath:'notes.txt'});
  expect(host.querySelector('pre').textContent).toBe('Local file fixture');
  await act(async()=>root.render(React.createElement(window.VellumUI.WorkspaceContent,{items,activeId:'files',directoryAvailable:true,visible:true,chats:[],library:[]})));
  expect(host.querySelector('[aria-label="Files and previews"]')).toBeTruthy();
  expect(read).toHaveBeenCalledTimes(2);
});
