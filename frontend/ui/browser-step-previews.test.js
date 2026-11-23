import React,{act} from 'react';
import ReactDOM from 'react-dom';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';

const components=resolve(dirname(fileURLToPath(import.meta.url)),'../../design/Velllum/uploads/components');
const load=name=>Function('window',readFileSync(resolve(components,name),'utf8'))(window);
const image=letter=>'/api/browser/step-previews/'+letter.repeat(32)+'.jpg';
let clock=Date.parse('2026-11-22T09:00:00Z');
const step=(id,url,title,picture)=>{clock+=5000;return [
  {id,type:'tool_call_started',name:'browser_navigate',status:'in_progress',label:'Opening '+title,at:new Date(clock).toISOString(),metadata:{input:{url}}},
  {id,type:'tool_call_completed',name:'browser_navigate',status:'completed',label:'Opened '+title,at:new Date(clock+2000).toISOString(),metadata:{output:'ok',preview:{id,url,title,image:picture}}},
];};
const message={id:'m1',text:'Here is the video.',streaming:false,responseStatus:'done',trace:{startedAt:Date.now()-5000,completedAt:Date.now()},
  activity:[...step('s1','https://www.youtube.com/','YouTube',image('a')),...step('s2','https://www.youtube.com/watch?v=x','A video - YouTube',image('b')),
    // A preview whose image is not a saved step preview is ignored.
    ...step('s3','https://example.com/','Forged','//evil.test/x.jpg')]};

let host,root;
beforeEach(()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  window.React=React;window.ReactDOM=ReactDOM;
  window.VellumApi={client:{backendBase:()=>'http://127.0.0.1:8000'}};
  window.VellumUI={useResponsePreferences:()=>({work_steps:true,memory_steps:true,thinking:true,citations:'auto',style:'plain'}),
    useStreamingText:text=>({text,animated:false,pending:false,finish(){}}),AnswerMarkdown:({text})=>React.createElement('p',null,text),ThinkingOrb:()=>null};
  load('response-progress.js');load('agent-response.js');
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();document.body.innerHTML='';});

const button=label=>document.querySelector(`[aria-label="${label}"]`);

test('a finished reply shows the last page as a card that opens it in the browser',async()=>{
  await act(async()=>root.render(React.createElement(window.VellumUI.StreamingResponse,{msg:message,actions:null})));
  const card=host.querySelector('.agent-browser-card');
  expect(card.querySelector('strong').textContent).toBe('A video - YouTube');
  expect(card.textContent).toContain('youtube.com, opened in Browser');
  expect(card.querySelector('img').getAttribute('src')).toBe('http://127.0.0.1:8000'+image('b'));
  const opened=vi.fn();window.addEventListener('vellum:open-browser-page',event=>opened(event.detail.url));
  await act(async()=>[...card.querySelectorAll('button')].find(node=>node.textContent==='Open').click());
  expect(opened).toHaveBeenCalledWith('https://www.youtube.com/watch?v=x');
});

test('browser steps carry thumbnails that peek on hover and open a full view with paging',async()=>{
  await act(async()=>root.render(React.createElement(window.VellumUI.StreamingResponse,{msg:message,actions:null})));
  await act(async()=>host.querySelector('.agent-work-heading').click());
  const thumbs=[...host.querySelectorAll('.agent-step-thumb')];
  expect(thumbs).toHaveLength(2);
  expect(document.body.innerHTML).not.toContain('evil.test');
  await act(async()=>thumbs[0].dispatchEvent(new MouseEvent('mouseover',{bubbles:true})));
  expect(document.querySelector('.agent-step-peek').textContent).toContain('1 of 2');
  await act(async()=>thumbs[0].click());
  const viewer=()=>document.querySelector('.agent-preview-viewer');
  expect(viewer().textContent).toContain('1 of 2');
  expect(viewer().querySelector('img').getAttribute('src')).toBe('http://127.0.0.1:8000'+image('a'));
  await act(async()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true})));
  expect(viewer().textContent).toContain('2 of 2');
  expect(button('Next preview').disabled).toBe(true);
  await act(async()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
  expect(viewer()).toBeNull();
});
