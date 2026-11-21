import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';

const require=createRequire(import.meta.url),rootPath=resolve(dirname(fileURLToPath(import.meta.url)),'../..');
const original=globalThis.Uint8Array;let componentsCode,pageCode;
try{
  globalThis.Uint8Array=new TextEncoder().encode('').constructor;
  const esbuild=createRequire(require.resolve('vite'))('esbuild');
  const load=name=>esbuild.transformSync(readFileSync(resolve(rootPath,'design/Velllum/uploads/components/'+name),'utf8'),{loader:'jsx'}).code;
  componentsCode=load('analytics-components.jsx');pageCode=load('analytics-page.jsx');
}finally{globalThis.Uint8Array=original;}

const shape={response_id:'resp_1',thread_id:'t1',ts:new Date().toISOString(),context_window:32000,input_used:9100,input_limit:27000,
  output_reserved:3400,safety_margin:1600,layers:{instructions:4000,tool_schemas:3000,personal_memory:600,retrieved_history:0,compacted_history:0,recent_conversation:1500},
  compacted:false,removed_messages:0};
const trace={run:{response_id:'resp_abc12345',thread_id:'t1',status:'completed',started_at:new Date().toISOString(),completed_at:null,event_count:9,tool_count:1,source_count:2},
  duration_ms:4200,precise:true,stats:{events:9,tool_calls:1,agents:1,sources:2,errors:0},context:shape,
  spans:[{id:'s1',parent:null,kind:'thinking',name:'',label:'Thinking...',start_ms:0,end_ms:300,status:'completed',count:1},
    {id:'s2',parent:null,kind:'agent',name:'MusicAgent',label:'Calling MusicAgent',start_ms:300,end_ms:3000,status:'completed',count:1},
    {id:'s3',parent:'s2',kind:'tool',name:'spotify_playback',label:'Using spotify_playback',start_ms:500,end_ms:2500,status:'failed',count:1},
    {id:'p4',parent:'s2',kind:'source',name:'',label:'Found 2 sources',start_ms:2600,end_ms:2700,status:'completed',count:2},
    {id:'s5',parent:null,kind:'answer',name:'',label:'Writing answer...',start_ms:3000,end_ms:4200,status:'completed',count:1}]};
const turns={turns:20,previous_turns:10,tokens:50000,previous_tokens:40000,cost_usd:0.12,previous_cost_usd:0,success_rate:.95,turns_with_tools:10,
  outcomes:{completed:19,failed:1},latency:{first_token_p50_ms:900,first_token_p95_ms:30000,total_p50_ms:1200,total_p95_ms:40000},
  providers:{ollama:18,openrouter:2},privacy:{GREEN:18,YELLOW:2},tools:[{name:'music_agent',turns:6},{name:'web_search',turns:3}],
  models:[{model:'ollama/gemma4:12b',provider:'ollama',turns:18,input:40000,output:6000,cost_usd:0,p50_first_token_ms:800},
    {model:'qwen/qwen3.5-35b-a3b',provider:'openrouter',turns:2,input:3000,output:1000,cost_usd:.12,p50_first_token_ms:300}],
  daily:[{day:'2026-11-17',turns:12,failed:1,input:20000,output:3000,p50_total_ms:1000},{day:'2026-11-18',turns:8,failed:0,input:23000,output:4000,p50_total_ms:1300}]};

let root,host;
const render=async element=>act(async()=>root.render(element));
const A=()=>window.VellumUI.Analytics;
beforeEach(()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  window.VellumUI={};
  window.VellumApi={observability:{threadContext:vi.fn(async()=>({thread_id:'t1',latest:shape,history:[],compactions:0})),
    summary:vi.fn(async period=>({period,turns,context:{turns:3,avg_fill:.3,peak_fill:.5,compactions:1,near_limit:0,avg_layers:shape.layers,latest:shape},
      recent_runs:[trace.run],runs:{total:1},usage:{}})),
    trace:vi.fn(async()=>trace),streamUrl:()=>'about:blank'}};
  globalThis.EventSource=class{constructor(){this.listeners={};}addEventListener(){}removeEventListener(){}close(){}};
  new Function('React',componentsCode)(React);
  new Function('React',pageCode)(React);
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});

test('cells are shared out by size and every non-empty part gets at least one',()=>{
  const cells=A().allocateCells(A().contextSegments({...shape,layers:{...shape.layers,personal_memory:10}}),32000,192);
  expect(cells).toHaveLength(192);
  expect(cells.filter(key=>key==='instructions')).toHaveLength(24);
  expect(cells).toContain('personal_memory');
  expect(cells.filter(key=>key==='free').length).toBeGreaterThan(80);
});

test('the context window card shows the fill and swaps the headline for a hovered part',async()=>{
  await render(React.createElement(A().ContextWindowCard,{shape,model:'ollama/gemma4:12b'}));
  expect(host.querySelector('.av-ctx-headline').textContent).toBe('9.1Kof 32K tokens28%');
  expect(host.querySelector('.av-chip').textContent).toBe('gemma4:12b');
  const tools=[...host.querySelectorAll('.av-ctx-rows li')].find(li=>li.textContent.startsWith('Tools'));
  await act(async()=>tools.dispatchEvent(new MouseEvent('mouseover',{bubbles:true})));
  expect(host.querySelector('.av-ctx-headline').textContent).toBe('3KTools9%');
  expect(host.querySelector('.av-ctx-foot').textContent).toContain('18K left before compaction');
});

test('the composer meter reads this chat and opens on /context',async()=>{
  await render(React.createElement(A().ContextMeter,{threadId:'t1',refreshKey:'idle',openSignal:0}));
  expect(window.VellumApi.observability.threadContext).toHaveBeenCalledWith('t1');
  expect(host.querySelector('.av-meter-btn').textContent).toBe('28%');
  expect(host.querySelector('.av-meter-pop')).toBeNull();
  await render(React.createElement(A().ContextMeter,{threadId:'t1',refreshKey:'idle',openSignal:1}));
  expect(host.querySelector('.av-meter-pop .av-ctx')).toBeTruthy();
});

test('the trace nests tool calls under their sub-agent and collapses them',async()=>{
  await render(React.createElement(A().TraceWaterfall,{trace}));
  const names=()=>[...host.querySelectorAll('.av-trace-label')].map(node=>node.textContent);
  expect(names()).toEqual(['Planning','MusicAgent','Spotify playback','Found 2 sources','Answer']);
  expect(host.querySelector('.av-trace-stats').textContent).toContain('Duration4.2s');
  expect(host.querySelector('.av-trace-row.failed .av-flag').textContent).toBe('failed');
  await act(async()=>host.querySelector('.av-twist').click());
  expect(names()).toEqual(['Planning','MusicAgent','Answer']);
});

test('model usage compares with the previous period and switches metric',async()=>{
  await render(React.createElement(A().ModelUsage,{turns,periodLabel:'Last 7 days'}));
  expect(host.querySelector('.av-usage-head strong').textContent).toBe('50K');
  expect(host.querySelector('.av-delta').textContent).toContain('+25%');
  expect([...host.querySelectorAll('.av-usage-x b')].map(node=>node.textContent)).toEqual(['gemma4:12b','qwen3.5-35b-a3b']);
  await act(async()=>[...host.querySelectorAll('.av-seg button')].find(node=>node.textContent==='Turns').click());
  expect(host.querySelector('.av-usage-head strong').textContent).toBe('20');
  expect(host.querySelector('.av-usage-tasks li').textContent).toBe('Music agent60%');
});

test('the analytics page loads the period summary and opens a run trace from Overview',async()=>{
  const onAction=vi.fn(async()=>({status:'applied'}));
  await render(React.createElement(window.VellumUI.AnalyticsPage,{control:{streaming:true},onAction}));
  expect(window.VellumApi.observability.summary).toHaveBeenCalledWith('7d');
  expect(host.querySelector('.av-stat-value').textContent).toBe('20');
  await act(async()=>host.querySelector('.av-recent .av-run').click());
  expect(window.VellumApi.observability.trace).toHaveBeenCalledWith('resp_abc12345');
  expect(host.querySelector('.av-trace')).toBeTruthy();
  await act(async()=>host.querySelector('.av-live').click());
  expect(onAction).toHaveBeenCalledWith('observability.stream.set',{enabled:false});
});

test('the trace shows a skeleton while loading, then drops rows in one by one',async()=>{
  await render(React.createElement(A().TraceWaterfall,{trace,loading:true}));
  expect(host.querySelector('.av-trace.is-loading')).toBeTruthy();
  expect(host.querySelectorAll('.av-skel').length).toBeGreaterThan(6);
  await render(React.createElement(A().TraceWaterfall,{trace,loading:false}));
  const slots=()=>[...host.querySelectorAll('.av-trace-row')].map(row=>row.style.getPropertyValue('--slot'));
  expect(slots()).toEqual(['0','1','2','3','4']);
  // A step that streams in later enters by itself instead of replaying the whole list.
  const more={...trace,spans:[...trace.spans,{id:'s6',parent:null,kind:'tool',name:'web_search',label:'',start_ms:4200,end_ms:4300,status:'completed',count:1}]};
  await render(React.createElement(A().TraceWaterfall,{trace:more,loading:false}));
  // Rows already on screen keep their slot, so re-renders never cut the stagger short.
  expect(slots()).toEqual(['0','1','2','3','4','0']);
});

test('a live run stretches open spans to now and marks the live edge',async()=>{
  vi.useFakeTimers({toFake:['Date','setInterval','clearInterval']});
  try{
    vi.setSystemTime(new Date(10_000));
    const live={...trace,run:{...trace.run,status:'in_progress'},origin_at_ms:4_000,duration_ms:1000,
      spans:[{id:'s1',parent:null,kind:'answer',name:'',label:'',start_ms:0,end_ms:1000,status:'in_progress',count:1}]};
    await render(React.createElement(A().TraceWaterfall,{trace:live}));
    expect(host.querySelector('.av-trace-stats').textContent).toContain('Duration6.0s');
    expect(host.querySelector('.av-now-tag')).toBeTruthy();
    await act(async()=>{vi.setSystemTime(new Date(11_800));vi.advanceTimersByTime(200);});
    expect(host.querySelector('.av-trace-stats').textContent).toContain('Duration8.0s');
  }finally{vi.useRealTimers();}
});

test('numbers count up to their value and land when motion is allowed; the toggle has a sliding highlight',async()=>{
  const realMatch=window.matchMedia,realRaf=globalThis.requestAnimationFrame;
  window.matchMedia=()=>({matches:false});
  // Each frame jumps 0.6 s ahead, so the 1.2 s count finishes in a few frames.
  let clock=performance.now();
  globalThis.requestAnimationFrame=cb=>setTimeout(()=>cb(clock+=600),0);
  try{
    await render(React.createElement(A().CountUp,{value:2480}));
    expect(host.querySelector('.av-count-up').textContent).toBe('0');
    await act(async()=>{await new Promise(r=>setTimeout(r,30));});
    const node=host.querySelector('.av-count-up');
    expect(node.textContent).toBe('2,480');
    expect(node.dataset.landed).toBe('true');
  }finally{window.matchMedia=realMatch;globalThis.requestAnimationFrame=realRaf;}
  await render(React.createElement(A().Segmented,{label:'Metric',value:'b',options:[['a','A'],['b','B']],onChange:()=>{}}));
  expect(host.querySelector('.av-seg-pill')).toBeTruthy();
});
