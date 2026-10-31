/* Presentation derived from this response's real lifecycle, never a timed stage loop. */
(function () {
  const ended=status=>['completed','complete','done','failed','error','blocked','cancelled','interrupted','waiting'].includes(status);
  const stamp=item=>{
    const value=item.updatedAt || item.metadata?.occurred_at || item.at;
    const n=typeof value==='number'?value:Date.parse(value);
    return Number.isFinite(n)?n:0;
  };
  const internal=/^(thinking|thinking_started|runtime_preparing|runtime_prepared|context_preparing|context_ready|context_compacted|tool_call_preparing|function_call_preparing|function_call_prepared|final_answer.*)$/;
  const human=value=>String(value || '').replace(/([a-z])([A-Z])/g,'$1 $2').replace(/[_:.]+/g,' ').replace(/\b\w/g,c=>c.toUpperCase()).replace(/\bWeb Search\b/g,'web search');
  const sourceName=source=>{
    if(source.source_type==='book')return source.title || 'book';
    const provider=source.provider_label || '';
    if(provider && !/^(web|search|source|serpapi|tavily|exa|brave|firecrawl)$/i.test(provider))return provider;
    if(source.domain && source.domain!=='web')return source.domain;
    try{return new URL(source.url).hostname.replace(/^www\./,'');}catch{return source.title || 'source';}
  };
  function workItems(msg) {
    const entries=new Map();
    for(const item of [...(msg.trace?.steps || []),...(msg.activity || [])]) {
      if(!item || internal.test(item.type || '') || item.id==='thinking')continue;
      const id=item.id || item.type+'-'+(item.name || '');
      entries.set(id,{...entries.get(id),...item});
    }
    const rows=[];
    for(const item of entries.values()) {
      if(item.metadata?.reported_after_completion && item.name && rows.some(row=>row.name===item.name && !row.metadata?.reported_after_completion))continue;
      // Argument token events are preparation, not additional tool executions.
      if(item.type==='function_call' && !item.name)continue;
      if(item.type==='function_call' && [...entries.values()].some(other=>other!==item && other.name===item.name && /^tool_call/.test(other.type || '')))continue;
      const input=item.metadata?.input || item.input;
      const key=item.source ? 'source:'+ (item.source.url || item.source.id || item.id) : null;
      const duplicate=rows.find(row=>key ? row.workKey===key : item.name && row.name===item.name && JSON.stringify(row.metadata?.input || row.input || '')===JSON.stringify(input || '') && stamp(item)>=stamp(row) && Math.abs(stamp(item)-stamp(row))<1000);
      if(duplicate)Object.assign(duplicate,item,{id:duplicate.id,at:duplicate.at,workKey:key});
      else rows.push({...item,id:item.id || 'work-'+rows.length,workKey:key});
    }
    return rows;
  }
  function workLabel(item) {
    const failed=['failed','error','blocked'].includes(item.status), done=ended(item.status);
    const type=item.type || '', name=item.name || '';
    if(failed) {
      const evidence=[name,item.detail,item.metadata?.output].map(v=>typeof v==='string'?v:JSON.stringify(v || '')).join(' ');
      return (/serpapi/i.test(evidence)?'SerpAPI search':human(name) || 'Tool')+(item.status==='blocked'?' blocked':' failed');
    }
    if(item.source)return (/reading/.test(type)?done?'Read ':'Reading ':'Found ')+sourceName(item.source);
    if(name==='delegate_to_agent') {
      const target=item.metadata?.input?.agent_id;
      return (done?'Delegated':'Delegating')+(target?' to '+human(target):' to an agent');
    }
    if(/sub.?agent/.test(type))return human(name) || item.label || 'Agent';
    if(/model_reasoning|reasoning_summary/.test(type))return 'Thinking';
    return item.label && !/^(Agent activity|Activity)$/.test(item.label) ? item.label.replace(/\.{3}$/, '') : (done?'Used ':'Using ')+human(name || 'tool');
  }
  function responseProgress(msg) {
    const status=msg.responseStatus || msg.trace?.status;
    if(!msg.streaming || ended(status) || msg.phase==='queued')return {active:false,state:'base',label:status==='cancelled'?'Stopped':status==='error'?'Response interrupted':'Complete'};
    const all=workItems(msg);
    const answering=!!msg.text || msg.phase==='answering' || status==='answering';
    const answerStart=Math.max(0,...(msg.trace?.steps || []).filter(item=>/^final_answer/.test(item.type || '')).map(stamp));
    const live=all.filter(item=>!item.metadata?.reported_after_completion && (!answering || answerStart>0 && stamp(item)>answerStart));
    const latest=live.slice().reverse().sort((a,b)=>stamp(b)-stamp(a)).at(0);
    if(latest && ['failed','error','blocked'].includes(latest.status))return {active:true,state:'base',label:workLabel(latest),failed:true};
    const active=live.filter(item=>!ended(item.status)).reverse().sort((a,b)=>stamp(b)-stamp(a)).at(0);
    if(active) {
      const type=String(active.type || '').toLowerCase(), name=String(active.name || '').toLowerCase();
      if(/retry|fallback/.test(type))return {active:true,state:'retrying',label:'Retrying'};
      if(/compact|compress/.test(type))return {active:true,state:'compacting',label:'Working'};
      if(/background/.test(type))return {active:true,state:'background',label:'Working in the background'};
      if(/reasoning/.test(type))return {active:true,state:'reasoning',label:'Thinking'};
      if(/source_reading/.test(type))return {active:true,state:'searching',label:workLabel(active)};
      const web=/(?:^|__)(?:web_search|search_web|websearch|serpapi|tavily_search|brave_search|exa_search|firecrawl_search)(?:$|__)/.test(name);
      if(web || /(?:^|[_:. ])(?:search|retriev)/.test(type+' '+name)) {
        return {active:true,state:'searching',label:workLabel(active)};
      }
      return {active:true,state:'working',label:workLabel(active)};
    }
    if(answering || answerStart)return {active:true,state:'working',label:'Writing answer'};
    return {active:true,state:'working',label:'Working'};
  }
  function responseModel(msg) {
    const snapshot=msg.responseModel || {};
    // Runtime-prepared metadata is authoritative; a later picker change is not.
    const prepared=[...(msg.trace?.steps || []),...(msg.activity || [])].filter(item=>item?.type==='runtime_prepared' && item.metadata?.model).at(-1);
    const id=prepared?.metadata.model || msg.trace?.model || snapshot.id || '';
    const vendor=id.split('/')[0].toLowerCase();
    return {
      id, vendor,
      provider:snapshot.route_provider || (vendor==='ollama'?'ollama':undefined),
    };
  }
  window.VellumUI={...window.VellumUI,responseProgress,responseModel,workItems,workLabel};
})();
