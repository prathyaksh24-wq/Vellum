import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {createPortal} from 'react-dom';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {afterEach,expect,test,vi} from 'vitest';
const require=createRequire(import.meta.url),original=globalThis.Uint8Array;
function load(file){let code;try{globalThis.Uint8Array=new TextEncoder().encode('').constructor;code=createRequire(require.resolve('vite'))('esbuild').transformSync(readFileSync('../design/Velllum/uploads/components/'+file,'utf8'),{loader:'jsx'}).code;}finally{globalThis.Uint8Array=original;}Function('React','ReactDOM',code)(React,{createPortal});}
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


test('workspace add tab stays outside the scroll strip and focus previews actual pane content',async()=>{
  vi.useFakeTimers();
  try {
    window.VellumUI={AppIcon:()=>null};load('workspace-controller.jsx');
    const tabs=Array.from({length:12},(_,index)=>({id:'tab-'+index,kind:'launcher',title:'New tab '+index}));
    const open=vi.fn();
    await mount(React.createElement(window.VellumUI.WorkspacePaneTabs,{controller:{trigger:React.createRef()},workspace:{tabs,activeId:'tab-0',open,select:vi.fn(),close:vi.fn(),layout:vi.fn(),hide:vi.fn()}}));
    const plus=host.querySelector('[aria-label="New workspace tab"]');
    expect(plus.parentElement.classList.contains('workspace-pane-tabs')).toBe(true);
    expect(plus.closest('[role=tablist]')).toBeNull();
    const content=document.createElement('div');content.dataset.workspaceItem='tab-0';content.textContent='Current pane contents';host.append(content);
    await act(async()=>host.querySelector('[role=tab]').focus());
    await act(async()=>vi.advanceTimersByTimeAsync(120));
    expect(document.querySelector('[role=tooltip]').textContent).toContain('Current pane contents');
    await act(async()=>plus.click());
    expect(open).toHaveBeenCalledWith('launcher','split');
  } finally {vi.useRealTimers();}
});


test('side-chat draft renders the real input immediately and keeps its view identity',async()=>{
  window.VellumUI={AppIcon:()=>null};load('workspace-content.jsx');
  const renderChat=(chat,itemId)=>React.createElement('div',{key:itemId},React.createElement('h1',null,'Side chat'),React.createElement('textarea',{'aria-label':'Side chat input','data-chat-id':chat.id}));
  const item={id:'opening-view',kind:'chat',reference_id:''};
  const properties={items:[item],activeId:item.id,visible:true,chats:[],library:[],renderChat};
  await mount(React.createElement(window.VellumUI.WorkspaceContent,properties));
  const input=host.querySelector('[aria-label="Side chat input"]');
  input.value='Keep my draft';
  expect(host.textContent).not.toContain('Opening conversation');
  await act(async()=>root.render(React.createElement(window.VellumUI.WorkspaceContent,{...properties,items:[{...item,reference_id:'saved'}],chats:[{id:'saved',temporary_side_chat:true,messages:[]}]})));
  expect(host.querySelector('[aria-label="Side chat input"]')).toBe(input);
  expect(input.value).toBe('Keep my draft');
});
