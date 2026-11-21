import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';

const require=createRequire(import.meta.url),rootPath=resolve(dirname(fileURLToPath(import.meta.url)),'../..');
const original=globalThis.Uint8Array;let pageCode,analyticsCode;
try{
  globalThis.Uint8Array=new TextEncoder().encode('').constructor;
  const esbuild=createRequire(require.resolve('vite'))('esbuild');
  pageCode=esbuild.transformSync(readFileSync(resolve(rootPath,'design/Velllum/uploads/components/memory-page.jsx'),'utf8'),{loader:'jsx'}).code;
  analyticsCode=esbuild.transformSync(readFileSync(resolve(rootPath,'design/Velllum/uploads/components/analytics-components.jsx'),'utf8'),{loader:'jsx'}).code;
}finally{globalThis.Uint8Array=original;}
const chatCode=readFileSync(resolve(rootPath,'design/Velllum/uploads/components/agent-response.js'),'utf8');

let root,host,api,onMemoryAction,onOpenChat,stream;
const summary={sections:[{title:'Overview',body:'You build Vellum, a local-first assistant.'},{title:'Work style',body:'You prefer concise answers.'}],
  dive_deeper:['How should Vellum handle long projects?'],updated_at:new Date(Date.now()-2*3600e3).toISOString(),generated_by:'model'};
const topics=[{topic:'Preferences',count:3,last_learned:'2026-11-15T10:00:00',origins:{stated:2,inferred:1},items:[
  // The backend sends SQLite integers for these flags.
  {id:1,text:'Prefers concise answers.',kind:'preference',origin:'stated',status:'saved',pinned:0,suppressed:0,created_at:'2026-11-15T10:00:00'},
  {id:2,text:'Likes dark themes.',kind:'preference',origin:'inferred',status:'saved',pinned:0,suppressed:1,created_at:'2026-11-14T10:00:00'},
  {id:3,text:'Uses Windows.',kind:'fact',origin:'inferred',status:'archived',pinned:false,suppressed:false,created_at:'2026-10-01T10:00:00'},
]},{topic:'Projects',count:1,last_learned:'2026-11-10T10:00:00',origins:{imported:1},items:[
  {id:4,text:'Works on Vellum.',kind:'fact',origin:'imported',status:'active',pinned:false,suppressed:false,created_at:'2026-11-10T10:00:00'},
]}];
const button=text=>[...host.querySelectorAll('button')].find(node=>node.textContent.trim()===text);
const click=async node=>act(async()=>{node.click();});
const input=async(label,value)=>act(async()=>{
  const node=host.ownerDocument.querySelector('[aria-label="'+label+'"]');
  Object.getOwnPropertyDescriptor(node.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set.call(node,value);
  node.dispatchEvent(new Event('input',{bubbles:true}));
});
const submit=async label=>act(async()=>{host.ownerDocument.querySelector('[aria-label="'+label+'"]').closest('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));});
const render=async element=>act(async()=>root.render(element));
const page=(props={})=>React.createElement(window.VellumUI.MemoryPage,{onMemoryAction,onOpenChat,onOpenSettings:vi.fn(),...props});

beforeEach(()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  stream=null;
  api={
    memoryAboutYouStream:vi.fn(options=>new Promise(resolveStream=>{stream={options,resolve:resolveStream};})),
    memorySuppress:vi.fn(async()=>({suppressed:[2]})),
    memoryFeedback:vi.fn(async()=>({memory:{id:1}})),
    memoryUndoSave:vi.fn(async()=>({memory:{id:9}})),
    memoryAsk:vi.fn(async()=>({reply:'Updated your preferences.',applied:[{op:'add',memory:{id:7,title:'Prefers metric units'}}],
      needs_confirmation:[{op:'delete',memory_id:3,text:'Uses Windows.'}],planner:'model'})),
    memoryTopics:vi.fn(async()=>({topics})),
    memoryGrowth:vi.fn(async()=>({day_number:0,first_day:null,counts:{known:0},series:[],milestones:[]})),
    memoryImportPrompt:vi.fn(async()=>({prompt:'List what you know about me in five categories.'})),
    memoryImportPlan:vi.fn(async()=>({items:[{kind:'preference',text:'Prefers tea.',category:'preferences'},{kind:'fact',text:'Lives near the sea.',category:'identity'}],
      dropped:{sensitive:1,instruction_like:0,links_removed:0,duplicate:2,unparsed:0},truncated:false,count:2})),
    memoryExport:vi.fn(),
  };
  window.VellumApi={settings:api};
  onMemoryAction=vi.fn(async actionId=>({status:'applied',action_id:actionId,result:actionId==='memory.import.apply'?{saved:2}:{}}));
  onOpenChat=vi.fn();
  window.VellumUI={};window.React=React;
  new Function('React',analyticsCode)(React);
  new Function('React',pageCode)(React);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();});

test('About you shows Generating, streams the draft, then the cached summary with Dive deeper prompts',async()=>{
  await render(page());
  expect(host.textContent).toContain('Generating');
  expect(api.memoryAboutYouStream).toHaveBeenCalledWith(expect.objectContaining({force:false}));
  await act(async()=>{stream.options.onEvent('status',{status:'generating'});stream.options.onEvent('delta',{text:'### Overview\nYou build '});stream.options.onEvent('delta',{text:'Vellum.'});});
  expect(host.querySelector('.mp-summary h3').textContent).toBe('Overview');
  expect(host.querySelector('.mp-summary p').textContent).toBe('You build Vellum.');
  await act(async()=>stream.resolve(summary));
  expect([...host.querySelectorAll('.mp-summary h3')].map(node=>node.textContent)).toEqual(['Overview','Work style','Dive deeper']);
  expect(host.querySelector('.mp-updated').textContent).toBe('Updated 2h ago');
  await click(host.querySelector('.mp-dive-link'));
  expect(onOpenChat).toHaveBeenCalledWith('How should Vellum handle long projects?');
});

test('the summary menu refreshes with force and offers delete-and-turn-off behind a confirmation',async()=>{
  await render(page());
  await act(async()=>stream.resolve(summary));
  await click(host.querySelector('[aria-label="Summary options"]'));
  expect([...host.querySelectorAll('[role="menuitem"]')].map(node=>node.textContent)).toEqual(['About memory','Refresh','Export','Delete and turn off memory']);
  await click(button('Refresh'));
  expect(api.memoryAboutYouStream).toHaveBeenLastCalledWith(expect.objectContaining({force:true}));
  await act(async()=>stream.resolve(summary));
  await click(host.querySelector('[aria-label="Summary options"]'));
  await click(button('Delete and turn off memory'));
  expect(host.textContent).toContain('permanently deletes 4 saved memories');
  expect(onMemoryAction).not.toHaveBeenCalled();
  await click(button('Delete and turn off'));
  expect(onMemoryAction).toHaveBeenNthCalledWith(1,'memory.settings.update',{patch:{memory_enabled:false}},{confirmedFromUi:true});
  expect(onMemoryAction.mock.calls.filter(call=>call[0]==='memory.entry.delete').map(call=>call[1].memory_id)).toEqual([1,2,3,4]);
});

test('selecting summary text offers a correction or never mentioning it again',async()=>{
  await render(page());
  await act(async()=>stream.resolve(summary));
  const rect={top:100,left:40,width:80,height:16};
  const selection=vi.spyOn(window,'getSelection');
  const selectSummaryText=async()=>{
    const article=host.querySelector('.mp-summary');
    selection.mockReturnValue({toString:()=>'local-first assistant',rangeCount:1,anchorNode:article.querySelector('p').firstChild,
      getRangeAt:()=>({getBoundingClientRect:()=>rect}),removeAllRanges:vi.fn()});
    await act(async()=>article.dispatchEvent(new MouseEvent('mouseup',{bubbles:true})));
  };
  await selectSummaryText();
  expect(host.querySelector('.mp-chip').textContent).toContain('Make a correction');
  await click(button('Correct'));
  await input('Correction','It is a privacy-first desktop agent');
  await submit('Correction');
  expect(onMemoryAction).toHaveBeenCalledWith('memory.correction.create',{correction:'It is a privacy-first desktop agent',selection:'local-first assistant'},undefined);
  expect(api.memoryAboutYouStream).toHaveBeenCalledTimes(2);
  await act(async()=>stream.resolve(summary));
  await selectSummaryText();
  await click(button('Don’t mention this again'));
  expect(api.memorySuppress).toHaveBeenCalledWith({selection:'local-first assistant'});
  expect(host.textContent).toContain('Vellum won’t bring that up again.');
});

test('Ask or update shows the reply and routes deletions through the confirmed delete action',async()=>{
  await render(page());
  await act(async()=>stream.resolve(summary));
  await input('Ask or update','Remember I use metric units and forget that I use Windows');
  await submit('Ask or update');
  expect(api.memoryAsk).toHaveBeenCalledWith('Remember I use metric units and forget that I use Windows');
  expect(host.textContent).toContain('Updated your preferences.');
  expect(host.textContent).toContain('Added Prefers metric units');
  expect(host.textContent).toContain('Delete “Uses Windows.”?');
  await click(button('Delete'));
  expect(onMemoryAction).toHaveBeenCalledWith('memory.entry.delete',{memory_id:3},undefined);
  expect(host.textContent).not.toContain('Delete “Uses Windows.”?');
});

test('Topics shows origin chips, dims paused and archived items, and edits through App Actions',async()=>{
  await render(page());
  await click(button('Topics'));
  const cards=[...host.querySelectorAll('.mp-topic-card')];
  expect(cards.map(card=>card.querySelector('b').textContent)).toEqual(['Preferences','Projects']);
  expect([...cards[0].querySelectorAll('.mp-origin')].map(node=>node.textContent)).toEqual(['Stated 2','Inferred 1']);
  expect(cards[1].querySelector('.mp-origin').textContent).toBe('Imported 1');
  await click(cards[0]);
  const items=[...host.querySelectorAll('.mp-item')];
  expect(items.map(item=>item.classList.contains('is-dim'))).toEqual([false,true,true]);
  // Integer 0 flags must not render as a stray "0".
  expect(items[0].querySelector('.mp-item-meta').childNodes).toHaveLength(2);
  expect(items[0].querySelector('.mp-item-meta').textContent).not.toMatch(/0$/);
  expect(items[1].textContent).toContain('Not used');
  expect(items[2].textContent).toContain('Archived');
  await click([...items[0].querySelectorAll('button')].find(node=>node.textContent==='Stop using'));
  expect(onMemoryAction).toHaveBeenCalledWith('memory.entry.suppress',{memory_id:1,suppressed:true},undefined);
  await click([...items[1].querySelectorAll('button')].find(node=>node.textContent==='Use again'));
  expect(onMemoryAction).toHaveBeenCalledWith('memory.entry.suppress',{memory_id:2,suppressed:false},undefined);
  expect(api.memoryTopics.mock.calls.length).toBeGreaterThan(1);
  expect(host.querySelector('[aria-label="Tell Vellum what to change"]')).toBeTruthy();
});

test('Growth explains day zero, then shows day N, the known-facts line and milestones',async()=>{
  await render(page());
  await click(button('Growth'));
  expect(host.textContent).toContain('Vellum is just getting to know you.');
  api.memoryGrowth.mockResolvedValue({day_number:4,first_day:'2026-11-14',week_delta:5,counts:{known:6,archived:1,topics:['Preferences','Projects'],recalls:9},
    series:[{day:'2026-11-14',known:1,added:1,by_origin:{stated:1}},{day:'2026-11-15',known:3,added:2,by_origin:{inferred:2}},
      {day:'2026-11-16',known:3,added:0,by_origin:{}},{day:'2026-11-17',known:6,added:3,by_origin:{imported:3}}],
    topics:[{topic:'Preferences',count:4},{topic:'Projects',count:2}],
    recall:{total:9,used:2,used_recently:2,top:[{id:1,title:'Prefers concise answers.',topic:'Preferences',use_count:7,last_used_at:new Date().toISOString()}]},
    ledger:[{id:3,event:'deleted',verb:'Deleted',count:1,reason:'',before:'',after:'',at:new Date().toISOString(),memory_id:null,title:'',topic:'',origin:''},
      {id:2,event:'filtered',verb:'Filtered out',count:38,reason:'Not a durable memory: request',before:'',after:'Archived',at:new Date().toISOString(),memory_id:null,title:'',topic:'',origin:''},
      {id:1,event:'promoted',verb:'Confirmed',count:1,reason:'',before:'Pending',after:'Saved',at:new Date().toISOString(),memory_id:1,title:'Prefers concise answers.',topic:'Preferences',origin:'stated'}],
    milestones:[{kind:'correction',text:'Took your first correction on board',day:'2026-11-17',day_number:4}]});
  await act(async()=>window.dispatchEvent(new CustomEvent('vellum:memory-changed')));
  expect(host.querySelector('.mp-growth h2').textContent).toBe('Day 4');
  expect(host.querySelector('.av-growth svg').getAttribute('aria-label')).toBe('Known memories went from 1 to 6');
  expect(host.querySelector('.mp-stats').textContent).toContain('+5 this week');
  expect(host.querySelector('.mp-recalled li').textContent).toContain('used 7×');
  const ledger=[...host.querySelectorAll('.av-ledger-list li')].map(node=>node.textContent);
  expect(ledger[0]).toContain('Deleteda memory');
  expect(ledger[1]).toContain('Filtered out 38non-memories');
  expect(ledger[2]).toContain('Pending→Saved');
  expect(host.querySelector('.mp-milestones li').textContent).toBe('Day 4Took your first correction on board');
});

test('settings rows save each memory preference and the import dialog reviews before adding',async()=>{
  const onMemorySettings=vi.fn(),onOpenMemory=vi.fn();
  await render(React.createElement(window.VellumUI.MemorySettings,{settings:{memory_enabled:true,include_sensitive:false},onMemorySettings,onMemoryAction,onOpenMemory}));
  const switches=[...host.querySelectorAll('[role="switch"]')];
  expect(switches.map(node=>node.getAttribute('aria-label'))).toEqual(['Enable memory','Reference chat history','Generate memory from chats','Include sensitive topics','Automatically manage memory']);
  expect(host.textContent).toContain('Archives guesses after 30 days, removes them after 90; keeps what you told Vellum');
  await click(switches[0]);await click(switches[3]);await click(switches[4]);
  expect(onMemorySettings.mock.calls.map(call=>call[0])).toEqual([{memory_enabled:false},{include_sensitive:true},{auto_archive_enabled:false}]);
  await click(button('Open'));
  expect(onOpenMemory).toHaveBeenCalled();
  await click(button('Start import'));
  expect(host.textContent).toContain('List what you know about me in five categories.');
  expect(button('Add to memory').disabled).toBe(true);
  await input('Paste your memory details','## Preferences\n- [unknown] - Prefers tea.');
  await click(button('Add to memory'));
  expect(api.memoryImportPlan).toHaveBeenCalledWith('## Preferences\n- [unknown] - Prefers tea.');
  expect(host.textContent).toContain('2 memories will be added.');
  expect([...host.querySelectorAll('.mp-import-skipped li')].map(node=>node.textContent)).toEqual(['1 sensitive details','2 already in memory']);
  expect(onMemoryAction).not.toHaveBeenCalled();
  await click(button('Add 2 to memory'));
  expect(onMemoryAction).toHaveBeenCalledWith('memory.import.apply',{items:expect.any(Array)},{confirmedFromUi:true});
  expect(host.textContent).toContain('Added 2 memories.');
});

test('a chat turn shows "Recalled from memory" with feedback, and saved memories can be undone',async()=>{
  window.VellumUI={...window.VellumUI,useResponsePreferences:()=>({thinking:false}),responseProgress:()=>({active:false,state:'base'}),responseModel:()=>({})};
  new Function(chatCode)();
  const msg={id:'m1',streaming:false,responseStatus:'done',activity:[
    {id:'r1',type:'memory_recall',name:'memory',status:'completed',label:'Recalled 2 memories',
      metadata:{memories:[{id:1,title:'Prefers concise answers',topic:'Preferences',origin:'stated'},{id:4,title:'Works on Vellum',topic:'Projects',origin:'imported'}]}},
    {id:'s1',type:'memory_save',name:'memory',status:'completed',label:'Saved to memory · Uses metric units',metadata:{text:'I use metric units.',kind:'preference',thread_id:'t1'}},
    {id:'h1',type:'tool_call',name:'conversation_history',status:'completed',label:'conversation_history'},
  ]};
  expect(window.VellumUI.recalledMemories(msg).map(memory=>memory.id)).toEqual([1,4]);
  await render(React.createElement(window.VellumUI.MemoryRecall,{msg}));
  expect(host.textContent).toBe('Recalled from memory2');
  await click(host.querySelector('.agent-citations-heading'));
  expect(host.querySelector('.agent-memory-meta').textContent).toBe('Preferences · Stated');
  await click(button('Relevant'));
  expect(api.memoryFeedback).toHaveBeenCalledWith(1,true);
  expect(host.textContent).toContain('Marked relevant');
  await click([...host.querySelectorAll('.agent-memory-row')][1].querySelector('button:last-child'));
  expect(api.memorySuppress).toHaveBeenCalledWith({memory_id:4});
  await render(React.createElement(window.VellumUI.AgentActivity,{msg,defaultOpen:true}));
  expect([...host.querySelectorAll('.agent-row-label')].map(node=>node.textContent)).toEqual(['Recalled 2 memories','Saved to memory · Uses metric units','Searched past chats']);
  await click(button('Undo'));
  expect(api.memoryUndoSave).toHaveBeenCalledWith('I use metric units.','t1');
  expect(host.textContent).toContain('Removed from memory');
});
