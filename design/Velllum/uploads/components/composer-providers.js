// Transient composer projections of the existing catalogs; no provider execution
// or private content fetch is implied by a suggestion or reference selection.
export function referenceUrl(value) {
  try {
    const url=new URL(value);
    if(!['http:','https:'].includes(url.protocol) || url.username || url.password)return '';
    for(const key of [...url.searchParams.keys()])if(/^(?:access_token|refresh_token|id_token|code|state|token|api_key|key)$/i.test(key))url.searchParams.delete(key);
    if(/(?:token|code|secret)=/i.test(url.hash))url.hash='';
    return url.href.slice(0,2048);
  } catch {return '';}
}
// This is a read-only projection of PluginRegistry records, not a new catalog.
export function componentsForPlugin(plugin) {
  const declared=plugin.relationships?.components;
  if(Array.isArray(declared))return declared.map(component=>{
    const raw=(component.kind==='app'?plugin.apps:component.kind==='mcp'?plugin.mcp_connectors:plugin.skills || []) || [];
    return {...(raw.find(row=>String(row.id || row.name)===component.id) || {}),...component};
  });
  const rows=[];
  for(const [kind,items] of [['app',plugin.apps || []],['mcp',plugin.mcp_connectors || []],['skill',plugin.skills || []]]){
    for(const item of items)rows.push({...item,kind,id:String(item.id || item.name),name:item.display_name || item.name || item.id,owner_plugin_id:plugin.id,
      canonical_id:item.canonical_app_id || item.canonicalAppId || item.app_id || (kind==='app'?(item.id || item.name):''),enabled:plugin.enabled!==false && item.enabled!==false});
  }
  if(!rows.some(row=>row.kind==='app') && plugin.type==='connector')rows.unshift({kind:'app',id:plugin.id,name:plugin.name,owner_plugin_id:plugin.id,canonical_id:plugin.id,enabled:plugin.enabled!==false,configured:plugin.configured,connected:plugin.metadata?.connection?.connected});
  // Compatibility with the original composer's app-only catalog input.
  if(!plugin.type && !plugin.source && !rows.length)rows.push({kind:'app',id:plugin.id,name:plugin.name,owner_plugin_id:plugin.id,canonical_id:plugin.id,enabled:plugin.enabled!==false});
  return rows;
}
// Slash capability rows and @ results refer to the same catalog identities.// Selecting one supplies context; it does not navigate or execute the provider.export function commandReference(item) {  const kind=item?.kind,raw=item?.raw;  if(!['plugin','app','mcp','skill'].includes(kind) || !raw)return null;  const component=String(raw.id || raw.name || ''),owner=String(item.plugin?.id || raw.owner_plugin_id || raw.owner_plugin || (kind==='plugin'?raw.id:'') || '');  const id=kind==='app'?(raw.canonical_id || raw.canonical_app_id || raw.canonicalAppId || raw.app_id || component):component;  if(!id || !item.label)return null;  return {kind,id:String(id),label:item.label,url:'',owner_plugin_id:owner,component_id:kind==='plugin'?'':component};}export function referenceProviders({library=[],chats=[],projects=[],apps=[],skills=[],agents=[],browserTabs=[]}={}) {
  const item=(kind,id,label,description='',url='',owner='',component='')=>({id:kind+':'+(owner?owner+':':'')+id,label:String(label||id).slice(0,256),description,
    reference:{kind,id:String(id).slice(0,512),label:String(label||id).slice(0,256),url:referenceUrl(url),owner_plugin_id:String(owner).slice(0,512),component_id:String(component).slice(0,512)}});
  const packages=[],integrations=[],servers=[],ownedSkills=new Map(),activeOwners=new Set();
  for(const plugin of apps){
    if(plugin.installed===false || plugin.enabled===false)continue;
    activeOwners.add(plugin.id);
    const components=componentsForPlugin(plugin).filter(row=>row.enabled!==false);
    const canonical=plugin.relationships?.canonical_app_id || (plugin.type==='connector' && components.filter(row=>row.kind==='app').length===1?components.find(row=>row.kind==='app').canonical_id:'');
    if(plugin.relationships?.is_package!==false && plugin.source!=='mcp_configuration' && (plugin.type || plugin.source)){
      packages.push({...item('plugin',plugin.id,plugin.name,plugin.description || 'Plugin package'),duplicateOf:canonical?'app:'+canonical:''});
    }
    for(const component of components){
      const identity=component.canonical_id || component.id;
      const description=[component.description || plugin.description,component.connected===true?'Connected':component.configured===false?'Needs setup':'',plugin.name].filter(Boolean).join(' · ');
      if(component.kind==='app')integrations.push({...item('app',identity,component.name,description,'',plugin.id,component.id),canonicalKey:'app:'+identity,priority:component.connected===true?2:component.configured===true?1:0});
      if(component.kind==='mcp')servers.push({...item('mcp',component.id,component.name,description,'',plugin.id,component.id),duplicateOf:(component.canonical_id || canonical)?'app:'+(component.canonical_id || canonical):''});
      if(component.kind==='skill')ownedSkills.set(component.id,{...component,owner_plugin:plugin.id});
    }
  }
  for(const skill of skills){
    const owner=skill.owner_plugin || '';
    if(['archived','retired','proposed'].includes(skill.state) || skill.enabled===false || (owner && apps.some(p=>p.id===owner) && !activeOwners.has(owner)))continue;
    ownedSkills.set(String(skill.id || skill.name),{...ownedSkills.get(String(skill.id || skill.name)),...skill});
  }
  const appIdentities=new Map();
  for(const row of integrations){const previous=appIdentities.get(row.canonicalKey);if(!previous || row.priority>previous.priority)appIdentities.set(row.canonicalKey,row);}
  const sources=[
    ['plugins','Plugins',packages,'Installable packages and their capabilities'],
    ['apps','Apps',[...appIdentities.values()],'Registered apps and connected integrations'],
    ['mcps','MCPs',servers,'Tool and resource servers'],
    ['skills','Skills',[...ownedSkills.values()].map(row=>item('skill',row.id||row.name,row.display_name||row.name||row.identity||row.id,row.description||'Installed skill','',row.owner_plugin||row.owner_plugin_id||'',row.id||row.name)),'Reusable instructions'],
    ['chats','Conversations',chats.filter(row=>!row.archived).map(row=>item('chat',row.id,row.title||row.name||'Untitled chat','Conversation reference')),'Other conversations'],
    ['files','Files',library.filter(row=>row.attachment || row.source_id).map(row=>item(row.kind==='wiki'?'page':'file',row.id,row.name,'Attached library item')),'Attached files and searchable resources'],
    ['projects','Projects',projects.map(row=>item('project',row.id,row.name,'Project reference')),'Vellum project context'],
    ['tabs','Browser tabs',browserTabs.filter(row=>referenceUrl(row.url)).map(row=>item('browser_tab',row.id,row.title||row.url,'Open Vellum browser tab',row.url)),'Open Vellum browser pages'],
    ['agents','Agents',agents.map(row=>item('agent',row.id,row.name,row.desc||'Vellum agent')),'Specialist agent references'],
  ];
  return sources.map(([id,label,items,description])=>({id,label,description,search:async(_query,{signal})=>signal.aborted?[]:items}));
}
export function referenceAttachments(references,library=[]) {
  return references.map(reference=>{
    const file=reference.kind==='file' ? library.find(row=>String(row.id)===reference.id)?.attachment : null;
    return {...(file||{}),name:file?.name||reference.label,kind:file?.kind||'reference',fresh:false,reference};
  });
}
