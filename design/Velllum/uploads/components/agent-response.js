/* beUI response composition adapted to Vellum's existing React/stylesheet entry.
 * References: beui.dev/components/agents/{agent-activity,loading-states,citations,streaming-response}
 * All content comes from the chat adapter; this module never generates activity.
 */
(function () {
  const h = (...args) => window.React.createElement(...args);
  const terminal = value => ['completed','complete','done','failed','error','blocked','cancelled','interrupted','waiting'].includes(value);
  const time = value => {const n = typeof value === 'number' ? value : Date.parse(value); return Number.isFinite(n) ? n : null;};
  const duration = seconds => {const n = Math.max(0, Math.round(seconds || 0)); return n < 60 ? `${n}s` : `${Math.floor(n/60)}m ${n%60}s`;};
  const safeUrl = value => /^https?:\/\//i.test(String(value || '')) ? value : undefined;
  function Icon({kind='step', size=15}) {
    const paths = {
      chevron:'m6 9 6 6 6-6', search:'m21 21-4.4-4.4 M19 11a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
      tool:'m14 6 4 4 M6 14l-3 7 7-3 11-11-4-4Z',
      agent:'M5 8h14v12H5Z M9 12h.01 M15 12h.01 M9 16h6 M12 8V4 M10 4h4',
      source:'M12 3v18 M3 12h18 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0 M12 3c5 5 5 13 0 18 M12 3c-5 5-5 13 0 18',
      book:'M12 6C8 3 4 3 2 4v15c4-1 7 0 10 2 3-2 6-3 10-2V4c-3-1-6 0-10 2Z M12 6v15',
      step:'m5 12 4 4L19 6', reasoning:'M9 18h6 M9 21h6 M8 14a6 6 0 1 1 8 0l-1 2H9Z',
      external:'M14 3h7v7 M21 3 10 14 M10 3H3v18h18v-7',
      error:'M12 8v5 M12 17h.01 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
    };
    return h('svg',{width:size,height:size,viewBox:'0 0 24 24',fill:'none',stroke:'currentColor',strokeWidth:1.5,strokeLinecap:'round',strokeLinejoin:'round','aria-hidden':true},h('path',{d:paths[kind] || paths.step}));
  }
  function itemKind(item) {
    const type = item.type || '';
    if (/sub.?agent|delegat/.test(type+' '+(item.name || ''))) return 'agent';
    if (/source/.test(type)) return item.source?.source_type === 'book' ? 'book' : 'source';
    if (/reason|thinking/.test(type)) return 'reasoning';
    if (/search/.test(item.name || '')) return 'search';
    if (/tool|function/.test(type)) return 'tool';
    return 'step';
  }
  function activityItems(msg) {
    const rows = new Map();
    for (const item of [...(msg.trace?.steps || []), ...(msg.activity || [])]) {
      if (!item || /^(thinking|thinking_started|final_answer_delta|final_answer_started|final_answer_completed)$/.test(item.type || '') || item.id === 'thinking') continue;
      const id = item.id || `${item.type}-${item.name || item.label}`;
      rows.set(id, {...rows.get(id),...item,id});
    }
    return [...rows.values()];
  }
  function responseSources(msg) {
    const result=[],seen=new Set();
    const add=(source,index)=>{
      if(!source || typeof source!=='object')return;
      if(source.source_type==='web' && source.url && result.some(item=>item.source_type==='web' && item.url===source.url))return;
      const anchor=source.evidence?.id || source.id || '';
      const same=result.find(item=>anchor ? (item.evidence?.id || item.id)===anchor && (!source.source_index || source.source_index===item.source_index)
        : item.url===source.url && item.title===source.title && item.snippet===source.snippet && JSON.stringify(item.evidence || null)===JSON.stringify(source.evidence || null) && (!source.source_index || source.source_index===item.source_index));
      if(same)return;
      const numbered={...source,source_index:source.source_index || index};
      const key=JSON.stringify([numbered.source_index,anchor,source.url,source.evidence || null,source.title]);
      if(seen.has(key))return;
      seen.add(key);result.push(numbered);
    };
    const direct=msg.sources?.length?msg.sources:msg.trace?.sources || [];
    direct.forEach((source,index)=>add(source,index+1));
    const next=()=>Math.max(0,...result.map(source=>Number(source.source_index) || 0))+1;
    activityItems(msg).forEach(item=>{if(item.source)add(item.source,next());});
    return result;
  }
  function Preview({label,value}) {
    if (value === undefined || value === null || value === '') return null;
    return h('div',{className:'agent-detail-block'},h('div',{className:'agent-detail-label'},label),
      h('pre',null,typeof value === 'string' ? value : JSON.stringify(value,null,2)));
  }
  function ActivityRow({item, runStatus}) {
    const [open,setOpen] = window.React.useState(false);
    const region = 'activity-' + window.React.useId().replace(/:/g,'');
    const meta = item.metadata || {}, status = terminal(item.status) ? item.status : runStatus === 'cancelled' ? 'cancelled' : runStatus === 'error' ? 'interrupted' : runStatus === 'done' ? 'interrupted' : 'in_progress';
    const failed = ['failed','error','blocked','interrupted'].includes(status);
    const start = time(item.at), end = time(item.updatedAt), seconds = start !== null && end !== null ? (end-start)/1000 : null;
    return h('div',{className:'agent-activity-row' + (open ? ' is-open' : ''),'data-status':status},
      h('button',{type:'button',className:'agent-activity-trigger','aria-expanded':open,'aria-controls':region,onClick:()=>setOpen(!open)},
        h('span',{className:'agent-row-icon' + (!terminal(status) ? ' is-active' : '')},h(Icon,{kind:failed ? 'error' : itemKind(item)})),
        h('span',{className:'agent-row-label'},item.label || item.name || 'Activity'),
        meta.agent && h('span',{className:'agent-row-agent'},meta.agent),
        h('span',{className:'agent-row-status'},status === 'in_progress' ? 'Running' : status === 'waiting' ? 'Needs input' : status === 'completed' ? (seconds > 0 ? duration(seconds) : 'Done') : status),
        h('span',{className:'agent-chevron'},h(Icon,{kind:'chevron',size:12}))),
      open && h('div',{id:region,className:'agent-activity-detail'},
        meta.reported_after_completion && h('p',{className:'agent-report-note'},'Reported by the specialist after completion.'),
        h(Preview,{label:'Input',value:meta.input ?? item.input}),
        h(Preview,{label:item.type === 'reasoning_summary' ? 'Reasoning summary' : 'Details',value:item.detail}),
        h(Preview,{label:'Result',value:meta.output}),
        meta.cache_status && h('p',null,`Cache: ${meta.cache_status}`),
        item.source && h(SourceDetails,{source:item.source}),
        item.events?.length > 0 && h('ol',{className:'agent-event-history'},item.events.map((event,index)=>h('li',{key:index},
          h('span',null,event.label || event.type || 'Activity'),h('span',null,event.status || ''),
          time(event.at) !== null && h('time',null,new Date(time(event.at)).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})))))));
  }
  function ResponseProgress({msg}) {
    const progress=window.VellumUI.responseProgress(msg),identity=window.VellumUI.responseModel(msg);
    const items=window.VellumUI.workItems(msg),steps=items.filter(item=>!['model_reasoning','reasoning_summary'].includes(item.type));
    const hasReasoning=items.some(item=>['model_reasoning','reasoning_summary'].includes(item.type) && String(item.detail || '').trim());
    const hasDetails=steps.length>0 || hasReasoning;
    const [expanded,setExpanded]=window.React.useState(null);
    const region='response-work-'+window.React.useId().replace(/:/g,'');
    const viewport=window.React.useRef(null),following=window.React.useRef(true);
    const open=expanded ?? (progress.active || msg.responseStatus==='error');
    const [now,setNow]=window.React.useState(Date.now());
    window.React.useEffect(()=>{
      if(!progress.active)return;
      const timer=setInterval(()=>setNow(Date.now()),1000);
      return()=>clearInterval(timer);
    },[progress.active]);
    window.React.useEffect(()=>{
      if(open && progress.active && following.current && viewport.current)viewport.current.scrollTop=viewport.current.scrollHeight;
    },[open,progress.active,msg.activity,msg.trace]);
    if((!progress.active && !hasDetails) || msg.voice)return null;
    const started=time(msg.trace?.startedAt),finished=time(msg.trace?.completedAt),elapsed=started===null?0:((finished || now)-started)/1000;
    const stopped=['cancelled','interrupted'].includes(msg.responseStatus || msg.trace?.status);
    const label=progress.active?progress.label:stopped?'Stopped':msg.responseStatus==='error'?'Response interrupted':elapsed>=1?'Worked for '+duration(elapsed):'Work details';
    const heading=[
      progress.active && !progress.failed ? h(window.VellumUI.ThinkingOrb,{key:'orb',state:progress.state,size:24,className:'agent-thinking-orb'}) : h('span',{key:'status',className:'agent-work-status'},h(Icon,{kind:progress.failed || msg.responseStatus==='error'?'error':stopped?'step':'step',size:16})),
      h('span',{key:'label',className:'agent-progress-label',role:'status','aria-live':'polite'},label),
      progress.active && elapsed>=1 && h('span',{key:'time',className:'agent-elapsed','aria-hidden':true},duration(elapsed)),
      hasDetails && h('span',{key:'chevron',className:'agent-work-chevron'},h(Icon,{kind:'chevron',size:12}))
    ];
    return h('section',{className:'agent-work','data-state':open?'open':'closed','data-vendor':identity.vendor,'data-model':identity.id,'data-provider':identity.provider,'data-orb-state':progress.state},
      hasDetails?h('button',{type:'button',className:'agent-progress agent-work-heading','aria-expanded':open,'aria-controls':region,onClick:()=>setExpanded(!open)},...heading):h('div',{className:'agent-progress'},...heading),
      open && hasDetails && h('div',{id:region,className:'agent-work-viewport',ref:viewport,onScroll:event=>{const el=event.currentTarget;following.current=el.scrollHeight-el.scrollTop-el.clientHeight<24;}},
        h('ol',{className:'agent-work-steps','aria-label':'Work steps'},steps.map((item,index)=>{
          const failed=['failed','error','blocked'].includes(item.status),running=progress.active && !terminal(item.status);
          const status=failed?'failed':running?'running':terminal(item.status)?item.status:'interrupted';
          const input=item.metadata?.input;
          const query=input && typeof input==='object' && (input.query || input.search_query);
          const link=safeUrl(item.source?.url);
          const current=running && !progress.failed && steps.filter(step=>!terminal(step.status)).at(-1)?.id===item.id;
          return h('li',{key:item.id,className:'agent-work-step','data-status':status,'data-current':current,'data-retrospective':!!item.metadata?.reported_after_completion,style:progress.active?{'--work-enter-delay':Math.min(index*35,140)+'ms'}:undefined},
            h('span',{className:'agent-work-marker','aria-hidden':true},h(Icon,{kind:failed?'error':itemKind(item),size:14})),
            h('div',{className:'agent-work-copy'},link?h('a',{href:link,target:'_blank',rel:'noopener noreferrer',className:'agent-work-source'},window.VellumUI.workLabel(item),h(Icon,{kind:'external',size:11})):h('span',null,window.VellumUI.workLabel(item)),
              typeof query==='string' && h('span',{className:'agent-work-query'},query)),
            h('span',{className:'agent-work-step-status'},failed?'Failed':status==='cancelled'?'Stopped':status==='interrupted'?'Interrupted':''));
        })),h(ThoughtProcess,{msg})));
  }
  function AgentActivity({msg,defaultOpen=false}) {
    const prefs=window.VellumUI.useResponsePreferences();
    const [open,setOpen] = window.React.useState(defaultOpen), [now,setNow] = window.React.useState(Date.now());
    const viewport = window.React.useRef(null), following = window.React.useRef(true), previouslyWorking = window.React.useRef(msg.streaming);
    const progress=window.VellumUI.responseProgress(msg), identity=window.VellumUI.responseModel(msg);
    const allItems=activityItems(msg);
    const items = allItems.filter(item=>!['model_reasoning','reasoning_summary'].includes(item.type)), working = progress.active;
    const hasReasoning=prefs.thinking && allItems.some(item=>['model_reasoning','reasoning_summary'].includes(item.type) && String(item.detail || '').trim());
    const hasDetails=items.length>0 || hasReasoning;
    const status = msg.responseStatus || msg.trace?.status || (working ? 'thinking' : 'done');
    const hasFailure = items.some(item=>['failed','error','blocked'].includes(item.status));
    const expanded = open || status === 'error';
    const region = 'agent-log-' + window.React.useId().replace(/:/g,'');
    window.React.useEffect(()=>{
      if (!working) return;
      const timer=setInterval(()=>setNow(Date.now()),1000);
      return ()=>clearInterval(timer);
    },[working]);
    window.React.useEffect(()=>{
      if (previouslyWorking.current && !working) setOpen(status === 'error');
      previouslyWorking.current=working;
    },[working,status]);
    window.React.useEffect(()=>{
      if (working && viewport.current && following.current && !viewport.current.querySelector('.is-open')) viewport.current.scrollTop=viewport.current.scrollHeight;
    },[working,items.length,msg.activity,msg.trace]);
    const started=time(msg.trace?.startedAt), completed=time(msg.trace?.completedAt);
    const elapsed=started === null ? 0 : ((completed || now)-started)/1000;
    const label=working ? progress.label : status === 'cancelled' ? 'Stopped' : status === 'error' ? 'Response interrupted' : items.length ? `${items.length} ${items.length === 1 ? 'activity' : 'activities'}${hasFailure ? ' · includes failed actions' : ''}` : 'Reasoning details';
    if (!working && !hasDetails) return null;
    if (working && !hasDetails && msg.suppressActivity) return null;
    return h('div',{className:'agent-activity','data-state':working?'working':expanded?'open':'closed','data-orb-state':working?progress.state:undefined,'data-model':identity.id,'data-provider':identity.provider,'data-vendor':identity.vendor,'aria-busy':working},
      h('button',{type:'button',className:'agent-activity-heading','aria-expanded':expanded,'aria-controls':hasDetails?region:undefined,disabled:!hasDetails,
        onClick:()=>{setOpen(!open); if(viewport.current)viewport.current.scrollTop=0;}},
        working && h(window.VellumUI.ThinkingOrb,{state:progress.state,size:24,className:'agent-thinking-orb'}),
        h('span',{className:'agent-progress-label'},label),
        elapsed >= 1 && h('span',{className:'agent-elapsed'},duration(elapsed)),
        hasDetails && h('span',{className:'agent-chevron'},h(Icon,{kind:'chevron',size:12}))),
      expanded && hasDetails && h('div',{id:region,className:'agent-activity-viewport',ref:viewport,
        onScroll:event=>{const el=event.currentTarget; following.current=el.scrollHeight-el.scrollTop-el.clientHeight<30;},
        'aria-label':'Response details'},h(ThoughtProcess,{msg}),
        h('div',{role:'list','aria-label':'Agent activity'},items.map(item=>h('div',{key:item.id,role:'listitem'},h(ActivityRow,{item,runStatus:status}))))));
  }
  function SourceDetails({source}) {
    const evidence=source.evidence || {};
    return h('div',{className:'agent-source-details'},
      (evidence.chapter || evidence.section) && h('p',null,[evidence.chapter,evidence.section].filter(Boolean).join(' · ')),
      evidence.edition_id && h('p',null,`Edition: ${evidence.edition_id}`),
      evidence.locator && h('p',null,`${evidence.locator_type === 'file_page' ? 'File page' : 'Location'}: ${evidence.locator}`),
      (evidence.quote || source.snippet) && h('blockquote',null,evidence.quote || source.snippet),
      evidence.id && h('p',{className:'agent-evidence-state'},evidence.validated ? 'Validated source span' : 'Source span has not been validated'),
      safeUrl(source.url) && h('a',{href:source.url,target:'_blank',rel:'noopener noreferrer'},'Open source',h(Icon,{kind:'external',size:12})));
  }
  function ThoughtProcess({msg}) {
    const prefs=window.VellumUI.useResponsePreferences();
    const [open,setOpen]=window.React.useState(false);
    const region='thought-'+window.React.useId().replace(/:/g,'');
    const items=activityItems(msg).filter(item=>['model_reasoning','reasoning_summary'].includes(item.type) && String(item.detail || '').trim());
    if(!items.length || !prefs.thinking)return null;
    return h('section',{className:'agent-thought-process'},
      h('button',{type:'button',className:'agent-thought-heading','aria-expanded':open,'aria-controls':region,onClick:()=>setOpen(!open)},
        h(Icon,{kind:'reasoning'}),items.some(item=>item.type==='model_reasoning')?'Thought process':'Reasoning summary',h(Icon,{kind:'chevron',size:12})),
      open && h('div',{id:region,className:'agent-thought-text'},items.map(item=>h(window.VellumUI.AnswerMarkdown,{key:item.id,text:item.detail || ''}))));
  }
  function Citations({sources=[],idPrefix,activeId,onActivate}) {
    const [open,setOpen]=window.React.useState(false);
    const region=idPrefix+'-sources';
    window.React.useEffect(()=>{if(activeId)setOpen(true);},[activeId]);
    window.React.useEffect(()=>{
      if(open && activeId) document.getElementById(idPrefix+'-'+activeId)?.scrollIntoView?.({block:'nearest',behavior:'instant'});
    },[open,activeId,idPrefix]);
    if(!sources.length)return null;
    return h('div',{className:'agent-citations'},
      h('button',{type:'button',className:'agent-citations-heading','aria-expanded':open,'aria-controls':region,onClick:()=>{setOpen(!open);if(open)onActivate(null);}},
        h('span',{className:'agent-source-stack','aria-hidden':true},sources.slice(0,3).map((source,index)=>h('span',{key:source.id || source.url || index},
          safeUrl(source.favicon_url) && source.source_type === 'web'
            ? h('img',{src:source.favicon_url,alt:'',width:16,height:16,referrerPolicy:'no-referrer'})
            : h(Icon,{kind:source.source_type==='book'?'book':'source',size:14})))),
        'Sources',h('span',{className:'agent-source-count'},sources.length),h(Icon,{kind:'chevron',size:12})),
      open && h('div',{id:region,className:'agent-source-list'},sources.map((source,index)=>{
        const id=String(source.id || source.source_index || index+1), expanded=activeId === id;
        return h('div',{key:id,id:idPrefix+'-'+id,className:'agent-citation-row'},
          h('button',{type:'button',className:'agent-citation-trigger','aria-expanded':expanded,'aria-controls':idPrefix+'-'+id+'-detail',onClick:()=>onActivate(expanded?null:id)},
            h(Icon,{kind:source.source_type==='book' || source.domain==='book'?'book':'source'}),
            h('span',{className:'agent-citation-title'},source.title || source.domain || source.url || 'Source'),
            h('span',{className:'agent-citation-domain'},source.domain || source.source_type || ''),
            h('span',{className:'agent-citation-index'},source.source_index || index+1)),
          expanded && h('div',{id:idPrefix+'-'+id+'-detail',className:'agent-citation-detail'},h(SourceDetails,{source})));
      })));
  }
  function StreamingResponse({msg,actions,onOpenActivity}) {
    const prefs=window.VellumUI.useResponsePreferences();
    const reveal=window.VellumUI.useStreamingText(msg.text || '',!!msg.streaming,prefs.speed);
    const responseRef=window.React.useRef(null),following=window.React.useRef(true);
    window.React.useLayoutEffect(()=>{
      const box=responseRef.current?.closest('.msgs');if(!box)return;
      const track=()=>{following.current=box.scrollHeight-box.scrollTop-box.clientHeight<160;};
      track();box.addEventListener('scroll',track,{passive:true});return()=>box.removeEventListener('scroll',track);
    },[]);
    window.React.useLayoutEffect(()=>{
      const root=responseRef.current,box=root?.closest('.msgs');
      if(reveal.animated && following.current && box && !root.querySelector('.is-open,.agent-thought-heading[aria-expanded="true"]'))box.scrollTop=box.scrollHeight;
    },[reveal.text,reveal.animated]);
    const [activeId,setActiveId]=window.React.useState(null);
    const sources=responseSources(msg);
    const isLinked=source=>reveal.text.includes('['+source.source_index+']') || (source.url && reveal.text.includes(source.url)) || source.claims?.some(claim=>claim.text && reveal.text.includes(claim.text));
    const shownSources=sources.filter(source=>String(source.id || source.source_index)===activeId || prefs.citations==='always' || (prefs.citations==='auto' && isLinked(source)));
    const generatedId=window.React.useId();
    const prefix='response-'+String(msg.id || generatedId).replace(/[^\w-]/g,'-');
    const status=msg.responseStatus || msg.trace?.status || (msg.streaming ? 'answering':'done');
    return h('div',{className:'agent-response',ref:responseRef,'data-status':status},
      h(ResponseProgress,{msg}),
      msg.text && h('div',{className:'agent-response-content agent-text-'+prefs.style,'aria-busy':!!msg.streaming || reveal.pending},
        h(window.VellumUI.AnswerMarkdown,{text:reveal.text,sources,idPrefix:prefix,onCitation:id=>setActiveId(id),animate:reveal.animated,pencil:prefs.pencil})),
      prefs.style==='ink' && shownSources.filter(source=>isLinked(source) && source.evidence?.quote).map(source=>h('aside',{key:source.id || source.source_index,className:'agent-provenance-note'},
        h('span',{className:'agent-detail-label'},'From '+(source.title || 'the book')),h('blockquote',null,source.evidence.quote))),
      !msg.streaming && reveal.pending && h('button',{type:'button',className:'agent-show-full',onClick:reveal.finish},'Show full response'),
      msg.error && h('div',{className:'agent-response-error',role:'alert'},h(Icon,{kind:'error'}),msg.error),
      h(Citations,{sources:shownSources,idPrefix:prefix,activeId,onActivate:setActiveId}),
      !msg.streaming && !reveal.pending && h('div',{className:'agent-response-actions'},actions));
  }
  function ActivityInspector({msg}) {
    const [activeId,setActiveId]=window.React.useState(null);
    const prefix='inspector-'+window.React.useId().replace(/:/g,'');
    return h('div',{className:'agent-response'},h(AgentActivity,{msg,defaultOpen:true}),
      h(Citations,{sources:msg.sources || msg.trace?.sources || [],idPrefix:prefix,activeId,onActivate:setActiveId}));
  }
  window.VellumUI={...window.VellumUI,AgentActivity,StreamingResponse,Citations,ActivityInspector,activityItems,responseSources};
})();
