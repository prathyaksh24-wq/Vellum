/* Read-only projections of canonical conversation, browser and plugin records. */
(function(){
  const list=value=>Array.isArray(value)?value:[];
  const text=value=>typeof value==='string'?value:'';
  const web=value=>{try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)?url.href:'';}catch{return '';}};
  function resourceIcon(file){
    const type=(file.mime_type||file.type||file.kind||file.language||'').toLowerCase();
    return /image/.test(type)?'ImageSquare':/spreadsheet|excel|csv/.test(type)?'Grid':/presentation|powerpoint/.test(type)?'FileDocument':/html|site|page|website/.test(type)?'Globe':/code|javascript|python/.test(type)?'Code':'FileDocument';
  }
  const messageCache=new WeakMap();
  function messageResources(message){
    let value=messageCache.get(message);if(value)return value;
    value={attachments:list(message.attachments),artifacts:list(message.artifacts),
      code:message.role==='assistant'?[...text(message.text).matchAll(/```([\w.+-]*)[^\n]*\n([\s\S]*?)```/g)]:[],
      sources:window.VellumUI.responseSources?.(message)||list(message.sources).concat(list(message.trace?.sources)),
      activity:window.VellumUI.activityItems?.(message)||list(message.activity).concat(list(message.trace?.steps)),
      plan:Array.isArray(message.plan)?message.plan:list(message.plan?.steps)};
    messageCache.set(message,value);return value;
  }
  function taskResources(chat,{chats=[],automations=[],browser={},environment=null,sideChatIds=[]}={}){
    const sections={progress:[],outputs:[],inputs:[],sources:[],chats:[],agents:[],browser:[],automations:[],environment:[]},seen=new Set(),agentRows=new Map();
    const add=(section,row)=>{const key=section+':'+row.id;if(!row.label)return;if(seen.has(key)){if(['progress','browser'].includes(section)){const index=sections[section].findIndex(item=>item.id===row.id);sections[section][index]={...sections[section][index],...row};}return;}seen.add(key);sections[section].push(row);};
    const fileRow=(file,id,messageId)=>({id:file.id||file.digest||id,label:file.name||file.title||'File',icon:resourceIcon(file),meta:file.mime_type||file.kind||'',kind:'file',file,messageId});
    const messages=list(chat?.messages);
    for(const [index,message] of messages.entries()){
      if(!message||typeof message!=='object')continue;
      const messageId=message.id||'message:'+index,cached=messageResources(message);
      for(const [i,file] of cached.attachments.entries())add('inputs',fileRow(file,messageId+':input:'+i,messageId));
      for(const [i,file] of cached.artifacts.entries()){
        const row=fileRow(file,messageId+':output:'+i,messageId),url=web(file.url||file.href);
        add('outputs',{...row,kind:/site|website|external|drive|page/.test(file.type||file.kind||'')&&url?'url':'file',url});
      }
      for(const [i,match] of cached.code.entries()){
        const language=match[1]||'text';add('outputs',fileRow({id:messageId+':code:'+i,name:language==='html'?'HTML preview':'Response '+language+' '+(i+1),kind:'code',language,text_content:match[2]},messageId+':code:'+i,messageId));
      }
      const sources=cached.sources;
      for(const [i,source] of sources.entries())add('sources',{id:source.id||source.url||messageId+':source:'+i,label:source.title||source.provider_label||source.domain||source.url||source.source_type,meta:source.source_type||source.provider||'',icon:source.source_type==='web'?'Globe':source.source_type==='book'?'BookOpen':'ConnectApps',kind:web(source.url)?'url':'message',url:web(source.url),messageId});
      const activity=cached.activity;
      for(const [i,item] of activity.entries()){
        const type=item.type||'',meta=item.metadata||{},id=item.id||messageId+':activity:'+i;
        if(/sub.?agent|delegat/.test(type)){
          const key=meta.run_id||meta.agent_id||item.name||id;
          agentRows.set(key,{id:key,label:item.name||item.label||'Agent',icon:'Agent',status:item.status||'',meta:item.status||'',kind:'message',messageId});
        }
        if(/^(plan_step|task_step|progress_step)$/.test(type))add('progress',{id,label:item.label||item.detail,status:item.status,icon:item.status==='completed'?'Check':'Clock',meta:item.status||'',kind:'message',messageId});
        if(/browser/.test(type+' '+item.name))add('browser',{id,label:item.label||item.name,icon:'Globe',meta:item.status||'',kind:'message',messageId});
        if(meta.plugin_id||meta.skill_name||meta.memory_id)add('sources',{id:'provenance:'+id,label:meta.skill_name||meta.plugin_id||'Memory reference',meta:meta.skill_name?'Skill':meta.plugin_id?'Plugin':'Memory',icon:meta.skill_name?'Sparkle':'ConnectApps',kind:'message',messageId});
      }
      const plan=cached.plan;
      for(const [i,step] of plan.entries())add('progress',{id:step.id||messageId+':plan:'+i,label:step.label||step.step||step.title,status:step.status,icon:step.status==='completed'?'Check':'Clock',meta:step.status||'',kind:'message',messageId});
    }
    for(const row of agentRows.values())add('agents',row);
    for(const side of chats.filter(side=>!side.archived&&(!!chat?.id&&side.parent_conversation_id===chat.id||sideChatIds.includes(side.id))))add('chats',{id:side.id,label:side.title||'Side chat',icon:'Chat',meta:side.messages?.some(message=>message.streaming)?'Working':'Conversation',kind:'chat',reference:side.id});
    const automationIds=new Set(messages.filter(Boolean).flatMap(message=>list(message.automation_ids).concat(message.automation_id?[message.automation_id]:[])));
    for(const record of automations)if(automationIds.has(record.id)||chat?.thread_id&&(record.thread_id===chat.thread_id||record.destination?.thread_id===chat.thread_id))add('automations',{id:record.id,label:record.name||record.title,icon:'Calendar',meta:record.state,kind:'automation',reference:record.id});
    if(environment?.workspace_root)add('environment',{id:'workspace',label:environment.workspace_root,icon:'FolderOpen',meta:'Local workspace',kind:'directory'});
    return sections;
  }
  function workspaceTools({browserAvailable,terminalAvailable,directoryAvailable,open}){
    const tools=[{id:'files',title:'Files and previews',icon:'FolderOpen',kind:'files',open:()=>open('files')},{id:'chat',title:'Side chat',icon:'Chat',kind:'chat',open:()=>open('chat')}];
    if(directoryAvailable)tools.unshift({id:'directory',title:'Workspace files',icon:'FolderOpen',kind:'directory',open:()=>open('directory','workspace')});
    if(terminalAvailable)tools.push({id:'terminal',title:'Terminal',icon:'Terminal',kind:'terminal',open:()=>open('terminal')});
    if(browserAvailable)tools.push({id:'browser',title:'Browser',icon:'Globe',kind:'browser',open:()=>open('browser')});
    return tools;
  }
  // Authored Vellum geometry based on the supplied visual reference. Public
  // sprite artwork remains the default for all other roles.
  function WorkspaceIcon({name,size=16,...props}){
    const h=window.React.createElement,parts={
      Summary:[['circle',{cx:3.9,cy:4.65,r:2.0}],['circle',{cx:3.9,cy:11.35,r:2.0}],['path',{d:'M8.7 4.65H14M8.7 11.35H14'}]],
      Minus:[['path',{d:'M3 8h10'}]],
      Tabs:[['rect',{x:2,y:2,width:12,height:12,rx:2}]],
      Files:[['path',{d:'M2 5V3a1 1 0 0 1 1-1h3l1.5 1.5H13a1 1 0 0 1 1 1V11M1.5 7h4l1.5 1.5h5v5h-11z'}]],
      SideChat:[['path',{d:'M13.2 10.5a5.6 5.6 0 1 0-2.7 2.7l3 .8zM8 5v5M5.5 7.5h5'}]],
      Full:[['path',{d:'M9.5 3H13v3.5M6.5 13H3V9.5'}]],
      Split:[['path',{d:'M13 6.5H9.5V3M3 9.5h3.5V13'}]],
    };
    if(!parts[name])return h(window.VellumUI.AppIcon,{name,size,...props});
    return h('svg',{width:size,height:size,viewBox:'0 0 16 16',fill:'none',stroke:'currentColor',strokeWidth:1.05,strokeLinecap:'round',strokeLinejoin:'round','aria-hidden':true,...props},...parts[name].map(([tag,attrs],i)=>h(tag,{...attrs,key:i})));
  }
  window.VellumUI=Object.assign(window.VellumUI||{},{taskResources,workspaceTools,resourceIcon,WorkspaceIcon});
})();
