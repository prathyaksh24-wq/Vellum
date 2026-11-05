import {Schema,Slice} from 'prosemirror-model';
import {EditorState,Plugin,PluginKey,TextSelection} from 'prosemirror-state';
import {EditorView} from 'prosemirror-view';
import {keymap} from 'prosemirror-keymap';
import {baseKeymap} from 'prosemirror-commands';
import {history,undo,redo} from 'prosemirror-history';
import {referenceUrl,commandReference} from './composer-providers.js';

const suggestionKey=new PluginKey('vellum-composer-suggestion');
const kinds=new Set(['file','page','chat','project','browser_tab','plugin','app','mcp','skill','agent']);
const schema=new Schema({nodes:{
  doc:{content:'paragraph'},paragraph:{content:'inline*',toDOM:()=>['p',0]},text:{group:'inline'},
  hard_break:{inline:true,group:'inline',selectable:false,toDOM:()=>['br']},
  reference:{inline:true,group:'inline',atom:true,attrs:{kind:{},id:{},label:{},url:{default:''},owner_plugin_id:{default:''},component_id:{default:''}},
    leafText:node=>'@'+node.attrs.label,toDOM:node=>['span',{class:'composer-reference','data-reference-kind':node.attrs.kind,title:node.attrs.label,contenteditable:'false'},node.attrs.label]},
}});
export function editorText(doc){return doc.firstChild.textBetween(0,doc.firstChild.content.size,'\n',node=>node.type.name==='reference'?'@'+node.attrs.label:'\n');}
function referenceAttrs(value){
  if(!value || !kinds.has(value.kind) || !String(value.id||'').trim() || !String(value.label||'').trim())return null;
  return {kind:value.kind,id:String(value.id).slice(0,512),label:String(value.label).slice(0,256),url:referenceUrl(value.url),owner_plugin_id:String(value.owner_plugin_id||'').slice(0,512),component_id:String(value.component_id||'').slice(0,512)};
}
function textDocument(text){
  const parts=String(text||'').split('\n'),nodes=[];
  parts.forEach((part,index)=>{if(index)nodes.push(schema.nodes.hard_break.create());if(part)nodes.push(schema.text(part));});
  return schema.node('doc',null,[schema.node('paragraph',null,nodes)]);
}
function segments(doc){
  const result=[];let plain=0;
  doc.firstChild.forEach((node,offset)=>{const text=node.isText?node.text:node.type.name==='reference'?'@'+node.attrs.label:'\n';result.push({node,start:plain,end:plain+text.length,pos:offset+1});plain+=text.length;});
  return result;
}
function documentPosition(doc,offset,bias=1){
  for(const item of segments(doc)){
    if(offset<=item.end){if(item.node.isText)return item.pos+Math.max(0,offset-item.start);return item.pos+(offset<=item.start?0:offset>=item.end?1:bias<0?0:1);}
  }
  return doc.content.size-1;
}
export function activeToken(state){
  const {selection}=state;
  if(!selection.empty || !selection.$from.parent.inlineContent)return null;
  const before=selection.$from.parent.textBetween(0,selection.$from.parentOffset,'\n','\uFFFC');
  if((before.match(/```/g)||[]).length%2 || (before.split('\n').at(-1).match(/`/g)||[]).length%2)return null;
  const match=/(?:^|[\s([{])([/@])([^\s/@\uFFFC]{0,128})$/u.exec(before);
  if(!match)return null;
  const from=selection.from-match[2].length-1;
  const after=selection.$from.parent.textBetween(selection.$from.parentOffset,selection.$from.parent.content.size,'\n','\uFFFC');
  const suffix=/^[^\s/@\uFFFC]*/u.exec(after)[0];
  const token={trigger:match[1],query:match[2],from,to:selection.from+suffix.length,caret:selection.from};
  token.key=[token.trigger,token.query,token.from,token.to,token.caret].join(':');
  return token;
}
function suggestionPlugin(){return new Plugin({key:suggestionKey,state:{
  init:(_,state)=>({token:activeToken(state),dismissed:null}),
  apply:(transaction,previous,_,state)=>{
    const token=activeToken(state),dismissed=transaction.getMeta(suggestionKey)?.dismiss ? token?.key : previous.dismissed;
    return {token:token?.key===dismissed?null:token,dismissed:token?.key===dismissed?dismissed:null};
  },
}});}
const normalized=value=>String(value||'').normalize('NFKC').toLocaleLowerCase().trim();
export function rankCandidates(items,query,limit=60){
  const q=normalized(query);
  return items.map((item,index)=>{
    const title=normalized(item.label),id=normalized(item.id||item.k||item.run),aliases=(Array.isArray(item.aliases)?item.aliases:[]).map(normalized);
    const score=!q?0:title===q||id===q||aliases.includes(q)?100:title.startsWith(q)?80:id.startsWith(q)||aliases.some(alias=>alias.startsWith(q))?60:[title,id,...aliases,normalized(item.description)].some(value=>value.includes(q))?40:-1;
    return {item,score,index};
  }).filter(row=>row.score>=0).sort((a,b)=>b.score-a.score||a.index-b.index).slice(0,limit).map(row=>row.item);
}
const commandGroups={command:['commands','Commands'],skill:['skills','Skills'],plugin:['plugins','Plugins'],app:['apps','Apps'],mcp:['mcps','MCPs'],agent:['agents','Agents'],project:['projects','Projects']};
function categorized(items,{scoped=false,preview=false}={}){
  const groups=new Map();for(const item of items){const key=item.sectionId || item.section || 'Results';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item);}
  const output=[];
  for(const rows of groups.values()){
    const limit=preview && !scoped && groups.size>1?6:60;
    output.push(...rows.slice(0,limit));
    if(rows.length>limit && !scoped)output.push({id:'scope:'+rows[0].sectionId,type:'scope',scope:rows[0].sectionId,label:'More '+rows[0].section.toLocaleLowerCase(),description:'Browse all matching items',section:rows[0].section,sectionId:rows[0].sectionId});
  }
  return output.slice(0,100);
}
export function commandCandidates(token,commands){
  const rows=commands.map(item=>{const [sectionId,section]=commandGroups[item.kind] || commandGroups.command,reference=commandReference(item);return {...item,reference,type:reference?'reference':'command',id:item.k||item.id||item.run,sectionId,section};});
  const colon=token.query.indexOf(':'),scope=colon>=0?token.query.slice(0,colon):'';
  const scoped=Object.values(commandGroups).some(([id])=>id===scope);
  const query=scoped?token.query.slice(colon+1):token.query;
  return categorized(rankCandidates(scoped?rows.filter(row=>row.sectionId===scope):rows,query,1000),{scoped,preview:!query});
}
export async function suggestionCandidates(token,commands,providers,signal){
  if(token.trigger==='/')return commandCandidates(token,commands);
  if(!token.query)return providers.map(provider=>({id:'scope:'+provider.id,type:'scope',scope:provider.id,label:provider.label,description:provider.description || 'Search '+provider.label.toLocaleLowerCase(),section:'Browse context',sectionId:'categories'}));
  const colon=token.query.indexOf(':'),scope=colon>=0?providers.find(provider=>provider.id===token.query.slice(0,colon)):null;
  const query=scope?token.query.slice(colon+1):token.query;
  const selected=scope?[scope]:providers,unavailable=[];
  const results=await Promise.all(selected.map(async provider=>{
    try {
      const rows=await provider.search(query,{signal});
      return (rows||[]).slice(0,500).map(row=>({...row,type:'reference',section:provider.label,sectionId:provider.id}));
    } catch(error){if(signal.aborted)throw error;unavailable.push(provider.label);return [];}
  }));
  if(signal.aborted)return [];
  const all=results.flat(),identities=new Set(all.filter(row=>row.canonicalKey).map(row=>row.canonicalKey));
  const visible=scope?all:all.filter(row=>!row.duplicateOf || !identities.has(row.duplicateOf));
  const items=categorized(rankCandidates(visible,query,1000),{scoped:Boolean(scope),preview:!query});
  items.notice=unavailable.length ? unavailable.join(', ')+': unavailable. Try again later.' : '';
  return items;
}
export function popupGeometry(anchor,bounds,preferred='up',surface=null){
  const edge=12,gap=8,width=Math.min(surface?.width || 360,Math.max(0,bounds.right-bounds.left-edge*2));
  const top=Math.min(anchor.top,surface?.top ?? anchor.top),bottom=Math.max(anchor.bottom,surface?.bottom ?? anchor.bottom);
  const above=Math.max(0,top-bounds.top-edge-gap),below=Math.max(0,bounds.bottom-bottom-edge-gap);
  const side=preferred==='down' ? (below>=160||below>=above?'down':'up') : (above>=160||above>=below?'up':'down');
  const height=Math.min(360,side==='up'?above:below);
  return {left:Math.max(bounds.left+edge,Math.min(surface?.left ?? anchor.left,bounds.right-edge-width)),top:side==='up'?top-gap:bottom+gap,width,maxHeight:height,transform:side==='up'?'translateY(-100%)':'none',side};
}
const components=new WeakMap();
export function composerComponent(React,ReactDOM){
  if(components.has(React))return components.get(React);
  const {useEffect,useLayoutEffect,useState,useRef,useImperativeHandle}=React,h=React.createElement;
  function ComposerEditor({value='',onChange,commands=[],providers=[],onCommand,onSubmit,onPasteFiles,onFocus,onBlur,referenceIcon,editorRef,preferred='up'}){
    const host=useRef(null),viewRef=useRef(null),latest=useRef(null),mounted=useRef(false),frame=useRef(0),request=useRef(0),popup=useRef(null),composing=useRef(false);
    const navigation=useRef('query'),lastPointer=useRef(null);
    const [reveal,setReveal]=useState(0);
    const [token,setToken]=useState(null),[menu,setMenu]=useState({key:'',items:[],index:0,loading:false,error:''}),[geometry,setGeometry]=useState(null);
    const id=React.useId();
    latest.current={value,onChange,commands,providers,onCommand,onSubmit,onPasteFiles,onFocus,onBlur,referenceIcon,token,menu,preferred};
    function dismiss(){const view=viewRef.current;if(view)view.dispatch(view.state.tr.setMeta(suggestionKey,{dismiss:true}));}
    function measure(){
      frame.current=0;const view=viewRef.current,current=latest.current.token;
      if(!view || !current || composing.current || !view.hasFocus()){setGeometry(null);return;}
      try {
        const anchor=view.coordsAtPos(view.state.selection.from),rect=view.dom.getBoundingClientRect(),viewport=window.visualViewport;
        const bounds={left:viewport?.offsetLeft||0,top:Math.max(viewport?.offsetTop||0,parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--desktop-chrome-height'))||0),right:(viewport?.offsetLeft||0)+(viewport?.width||innerWidth),bottom:(viewport?.offsetTop||0)+(viewport?.height||innerHeight)};
        const dialog=view.dom.closest('[role="dialog"],dialog');
        if(dialog){const r=dialog.getBoundingClientRect();bounds.left=Math.max(bounds.left,r.left);bounds.top=Math.max(bounds.top,r.top);bounds.right=Math.min(bounds.right,r.right);bounds.bottom=Math.min(bounds.bottom,r.bottom);}
        if(anchor.bottom<Math.max(rect.top,bounds.top) || anchor.top>Math.min(rect.bottom,bounds.bottom) || anchor.left<bounds.left || anchor.left>bounds.right){setGeometry(null);return;}
        setGeometry(popupGeometry(anchor,bounds,latest.current.preferred,view.dom.closest('.cpill')?.getBoundingClientRect() || rect));
      } catch {setGeometry(null);}
    }
    function schedule(){if(mounted.current && !frame.current)frame.current=requestAnimationFrame(measure);}
    function sync(){
      const view=viewRef.current;if(!view)return;
      const next=composing.current||view.composing?null:suggestionKey.getState(view.state).token;
      if(next?.key!==latest.current.token?.key)navigation.current='query';
      setToken(previous=>previous?.key===next?.key?previous:next);schedule();
    }
    function replaceToken(text,reference){
      const view=viewRef.current;if(!view)return false;
      const current=suggestionKey.getState(view.state)?.token;if(!current)return false;
      let end=current.to,tr=view.state.tr;
      if(reference){
        const attrs=referenceAttrs(reference);if(!attrs)return false;
        if(view.state.doc.textBetween(end,Math.min(end+1,view.state.doc.content.size-1))===' ')end++;
        tr=tr.replaceWith(current.from,end,[schema.nodes.reference.create(attrs),schema.text(' ')]);
        tr=tr.setSelection(TextSelection.create(tr.doc,current.from+2));
      } else tr=tr.insertText(text,current.from,end);
      view.dispatch(tr.setMeta(suggestionKey,{dismiss:true}).scrollIntoView());view.focus();return true;
    }
    function select(item){
      if(!item)return;
      if(item.type==='command'){latest.current.onCommand?.(item);return;}
      if(item.type==='scope'){
        const view=viewRef.current,current=suggestionKey.getState(view.state).token;
        if(current){view.dispatch(view.state.tr.insertText(current.trigger+item.scope+':',current.from,current.to));view.focus();}
      } else replaceToken('',item.reference);
    }
    function updateExternal(text){
      const view=viewRef.current;if(!view || composing.current || view.composing)return;
      const before=editorText(view.state.doc),after=String(text||'');if(before===after)return;
      let start=0,suffix=0;
      while(start<Math.min(before.length,after.length)&&before[start]===after[start])start++;
      while(suffix<Math.min(before.length-start,after.length-start)&&before[before.length-1-suffix]===after[after.length-1-suffix])suffix++;
      let end=before.length-suffix;
      for(const part of segments(view.state.doc))if(part.node.type.name==='reference'){
        if(start>part.start && start<part.end)start=part.start;
        if(end>part.start && end<part.end){end=part.end;suffix=before.length-end;}
      }
      const from=documentPosition(view.state.doc,start,-1),to=documentPosition(view.state.doc,end,1),replacement=after.slice(start,after.length-suffix);
      const slice=textDocument(replacement).firstChild.content;
      view.dispatch(view.state.tr.replaceWith(from,to,slice).setMeta('addToHistory',false).setMeta('external-draft',true));
    }
    useImperativeHandle(editorRef,()=>({
      focus:()=>viewRef.current?.focus(),dom:()=>viewRef.current?.dom,
      replaceActiveToken:text=>replaceToken(text),insertReference:reference=>replaceToken('',reference),dismissSuggestions:dismiss,
      getReferences:()=>{const rows=new Map();viewRef.current?.state.doc.descendants(node=>{if(node.type.name==='reference')rows.set(node.attrs.kind+':'+node.attrs.id,{...node.attrs});});return [...rows.values()];},
      setSelection:(from,to=from)=>{const view=viewRef.current;if(view){view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc,documentPosition(view.state.doc,from),documentPosition(view.state.doc,to))));view.focus();}},
      getText:()=>viewRef.current?editorText(viewRef.current.state.doc):'',
    }),[]);
    useLayoutEffect(()=>{
      mounted.current=true;
      const referenceView=node=>{
        const dom=document.createElement('span');dom.className='composer-reference';dom.contentEditable='false';
        function render(value){
          dom.dataset.referenceKind=value.attrs.kind;dom.title=value.attrs.label;dom.replaceChildren();
          const source=latest.current.referenceIcon?.(value.attrs) || '';
          dom.dataset.referenceBrand='';
          // Only bundled marks from the existing connector icon owner are used.
          if(/^assets\/plugins\/[a-zA-Z0-9._-]+$/.test(source)){
            dom.dataset.referenceBrand=source.split('/').at(-1).replace(/\.[^.]+$/,'');
            const image=document.createElement('img');image.src=source;image.alt='';image.width=16;image.height=16;
            image.draggable=false;image.referrerPolicy='no-referrer';image.addEventListener('error',()=>{image.hidden=true;},{once:true});dom.append(image);
          }
          if(value.attrs.kind==='skill'){
            const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
            svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('width','16');svg.setAttribute('height','16');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.6');svg.setAttribute('stroke-linejoin','round');svg.setAttribute('aria-hidden','true');svg.dataset.referenceIcon='skill';
            const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d','M12 3 3.5 7.5v9L12 21l8.5-4.5v-9L12 3ZM3.5 7.5 12 12l8.5-4.5M12 12v9M7.75 5.25l8.5 4.5');svg.append(path);dom.append(svg);
          }
          const label=document.createElement('span');label.textContent=value.attrs.label;dom.append(label);
        }
        render(node);
        return {dom,ignoreMutation:()=>true,update:next=>{
          if(next.type!==node.type)return false;
          if(JSON.stringify(next.attrs)!==JSON.stringify(node.attrs)){node=next;render(next);}
          return true;
        }};
      };
      const view=new EditorView(host.current,{
        nodeViews:{reference:referenceView},
        state:EditorState.create({schema,doc:textDocument(latest.current.value),plugins:[suggestionPlugin(),history(),keymap({'Mod-z':undo,'Mod-Shift-z':redo,'Mod-y':redo}),keymap(baseKeymap)]}),
        attributes:{role:'combobox','aria-label':'Message','aria-autocomplete':'list','aria-haspopup':'listbox','aria-expanded':'false','data-ui-reference':'composer'},
        dispatchTransaction(transaction){const state=view.state.apply(transaction);view.updateState(state);if(transaction.docChanged && !transaction.getMeta('external-draft'))latest.current.onChange(editorText(state.doc));sync();},
        handleKeyDown(_view,event){
          if(view.composing || composing.current || event.isComposing || event.keyCode===229)return false;
          const current=latest.current,active=suggestionKey.getState(view.state).token;
          const ready=active && current.menu.key===active.key && !current.menu.loading;
          const items=ready?current.menu.items:active?.trigger==='/'?commandCandidates(active,current.commands):[];
          const index=ready?current.menu.index:0;
          if(active && event.key==='Escape'){            event.preventDefault();event.stopPropagation();            const scope=active.query.split(':')[0],scoped=active.query.includes(':') && (active.trigger==='@'?current.providers.some(provider=>provider.id===scope):Object.values(commandGroups).some(([id])=>id===scope));            if(scoped){let tr=view.state.tr.insertText(active.trigger,active.from,active.to);tr=tr.setSelection(TextSelection.create(tr.doc,active.from+1));view.dispatch(tr.scrollIntoView());}            else dismiss();            return true;          }
          if(active && items.length){
            if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();navigation.current='keyboard';setReveal(value=>value+1);setMenu(menu=>({...menu,key:active.key,items,index:Math.max(0,Math.min(items.length-1,(menu.key===active.key?menu.index:0)+(event.key==='ArrowDown'?1:-1))),loading:false,error:''}));return true;}
            if(!event.shiftKey && (event.key==='Tab'||event.key==='Enter')){event.preventDefault();select(items[index]);return true;}
          }
          // An unfinished reference query must not accidentally send a message.
          if(active && !ready && !event.shiftKey && (event.key==='Tab'||event.key==='Enter')){event.preventDefault();return true;}
          if(event.key==='Enter'){event.preventDefault();if(event.shiftKey){view.dispatch(view.state.tr.replaceSelectionWith(schema.nodes.hard_break.create()).scrollIntoView());}else current.onSubmit?.();return true;}
          return false;
        },
        handlePaste(_view,event){
          const files=event.clipboardData?.files;if(files?.length){event.preventDefault();latest.current.onPasteFiles?.(files);return true;}
          const text=event.clipboardData?.getData('text/plain');if(typeof text==='string'){event.preventDefault();view.dispatch(view.state.tr.replaceSelection(new Slice(textDocument(text).firstChild.content,0,0)).scrollIntoView());return true;}
          return false;
        },
        handleDOMEvents:{
          focus:()=>{latest.current.onFocus?.();schedule();return false;},
          blur:()=>{latest.current.onBlur?.();dismiss();return false;},
          compositionstart:()=>{composing.current=true;setToken(null);return false;},
          compositionend:()=>{composing.current=false;setTimeout(()=>{if(mounted.current){sync();schedule();}},0);return false;},
        },
      });
      viewRef.current=view;
      const observer=new ResizeObserver(schedule);observer.observe(view.dom);
      // Parent size can move a centered input without changing the input's width.
      for(let ancestor=host.current.parentElement;ancestor && ancestor!==document.body;ancestor=ancestor.parentElement)observer.observe(ancestor);
      const onScroll=event=>{if(!popup.current?.contains(event.target))schedule();};
      document.addEventListener('scroll',onScroll,true);window.addEventListener('resize',schedule);window.visualViewport?.addEventListener('resize',schedule);window.visualViewport?.addEventListener('scroll',schedule);
      return()=>{mounted.current=false;request.current++;cancelAnimationFrame(frame.current);observer.disconnect();document.removeEventListener('scroll',onScroll,true);window.removeEventListener('resize',schedule);window.visualViewport?.removeEventListener('resize',schedule);window.visualViewport?.removeEventListener('scroll',schedule);view.destroy();viewRef.current=null;};
    },[]);
    useLayoutEffect(()=>{updateExternal(value);},[value]);
    useEffect(()=>{
      const current=++request.current,controller=new AbortController();
      if(!token){setMenu({key:'',items:[],index:0,loading:false,error:''});setGeometry(null);return()=>controller.abort();}
      // A background catalog refresh must not reset keyboard selection or scroll.
      setMenu(previous=>previous.key===token.key && previous.items.length ? previous : {key:token.key,items:[],index:0,loading:true,error:''});
      suggestionCandidates(token,commands,providers,controller.signal).then(items=>{
        if(mounted.current && current===request.current && !controller.signal.aborted){
          setMenu(previous=>{
            const same=previous.key===token.key,selected=same?previous.items[previous.index]?.id:null;
            const retained=selected?items.findIndex(item=>item.id===selected):-1;
            return {key:token.key,items,index:retained>=0?retained:same?Math.max(0,Math.min(previous.index,items.length-1)):0,loading:false,error:'',notice:items.notice || ''};
          });schedule();
        }
      }).catch(error=>{if(mounted.current && !controller.signal.aborted && current===request.current)setMenu({key:token.key,items:[],index:0,loading:false,error:'Suggestions are unavailable. Try typing again.'});});
      return()=>controller.abort();
    },[token?.key,commands,providers]);
    useLayoutEffect(()=>{
      const view=viewRef.current,open=Boolean(token&&geometry&&menu.key===token.key);
      if(view){view.dom.setAttribute('aria-expanded',String(open));if(open){view.dom.setAttribute('aria-controls',id);if(menu.items[menu.index])view.dom.setAttribute('aria-activedescendant',id+'-'+menu.index);else view.dom.removeAttribute('aria-activedescendant');}else {view.dom.removeAttribute('aria-controls');view.dom.removeAttribute('aria-activedescendant');}}
      window.dispatchEvent(new Event('vellum:composer-popup'));
    },[geometry,menu.index,menu.items,token?.key]);
    useLayoutEffect(()=>{
      // Only keyboard/query navigation reveals a row. Wheel/trackpad scrolling
      // must not be pulled back to the previously selected item on a layout tick.
      const box=popup.current,row=box?.querySelector('[aria-selected="true"]');
      if(!box || !row || !['keyboard','query'].includes(navigation.current))return;
      const selected=row.getBoundingClientRect(),bounds=box.getBoundingClientRect();
      if(selected.top<bounds.top+5)box.scrollTop-=bounds.top+5-selected.top;
      else if(selected.bottom>bounds.bottom-5)box.scrollTop+=selected.bottom-bounds.bottom+5;
    },[Boolean(token&&geometry&&menu.key===token.key),menu.key,menu.index,menu.items[menu.index]?.id,reveal]);
    useEffect(()=>()=>{window.dispatchEvent(new Event('vellum:composer-popup'));},[]);
    useEffect(()=>{
      if(!token)return;
      const outside=event=>{if(!host.current?.contains(event.target)&&!popup.current?.contains(event.target))dismiss();};
      document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside);
    },[token?.key]);
    const open=token && geometry && menu.key===token.key;
    const icons={plugins:'M9 3v4m6-4v4M6 7h12v4a6 6 0 0 1-6 6v4m0-4a6 6 0 0 1-6-6',apps:'M4 4h6v6H4zm10 0h6v6h-6zM4 14h6v6H4zm10 0h6v6h-6z',mcps:'M4 4h6v6H4zm10 10h6v6h-6zM10 7h7v7M7 10v7h7',skills:'M12 3 3.5 7.5v9L12 21l8.5-4.5v-9L12 3ZM3.5 7.5 12 12l8.5-4.5M12 12v9',chats:'M4 4h16v12H9l-5 4V4Z',files:'M5 3h9l5 5v13H5V3Zm9 0v5h5',projects:'M3 6h7l2 2h9v12H3V6Z',tabs:'M3 4h18v16H3V4Zm0 5h18',agents:'M4 8h16v12H4V8Zm8-5v5M8 12v3m8-3v3',commands:'m9 4-5 8 5 8m6-16 5 8-5 8'};
    const iconFor=item=>{
      const source=item.reference?latest.current.referenceIcon?.(item.reference):'';
      if(source && /^assets\/plugins\/[a-zA-Z0-9._-]+$/.test(source))return h('img',{src:source,alt:'',width:18,height:18,referrerPolicy:'no-referrer'});
      if(item.ic)return h(item.ic,{size:18});
      return h('svg',{width:18,height:18,viewBox:'0 0 24 24',fill:'none',stroke:'currentColor',strokeWidth:1.6,strokeLinejoin:'round',strokeLinecap:'round','aria-hidden':true},h('path',{d:icons[item.type==='scope'?item.scope:item.sectionId] || icons.files}));
    };
    const rows=[];let previousSection='';
    if(menu.loading || menu.error || !menu.items.length)rows.push(h('div',{key:'status',className:'composer-suggestion-status',role:'status'},menu.loading?'Searching…':menu.error || 'No matching '+(token?.trigger==='/'?'commands.':'references.')));
    for(const [index,item] of menu.items.entries()){
      if(item.section && item.section!==previousSection){previousSection=item.section;rows.push(h('div',{key:'heading:'+item.section,id:id+'-section-'+item.sectionId,role:'presentation',className:'composer-suggestion-heading'},item.section));}
      rows.push(h('div',{
        key:item.id,id:id+'-'+index,role:'option','aria-selected':index===menu.index,'aria-describedby':item.section?id+'-section-'+item.sectionId:undefined,'data-shared-row':'',className:'composer-suggestion',
        onPointerMove:event=>{
          const point={x:event.clientX,y:event.clientY};if(lastPointer.current?.x===point.x && lastPointer.current?.y===point.y)return;
          lastPointer.current=point;navigation.current='pointer';if(index!==menu.index)setMenu(current=>({...current,index}));
        },onPointerDown:event=>event.preventDefault(),onClick:()=>select(item),
      },h('span',{className:'composer-suggestion-icon','aria-hidden':true},iconFor(item)),h('span',{className:'composer-suggestion-copy'},h('strong',null,item.label),h('small',null,item.description||'')),h('span',{className:'composer-suggestion-kind'},item.type==='scope'?'Browse':item.owner||'')));
    }
    if(menu.notice)rows.push(h('div',{key:'notice',className:'composer-suggestion-status',role:'status'},menu.notice));
    const SharedRows=window.VellumUI?.SharedRowBackground;
    const content=SharedRows?h(SharedRows,{className:'composer-suggestion-rows',refreshKey:menu.key+':'+menu.index,hoverEnabled:navigation.current!=='keyboard',revealActive:false},rows):rows;
    const overlay=open && ReactDOM.createPortal(h('div',{
      ref:popup,id,role:'listbox','aria-label':token.trigger==='/'?'Commands, skills and agents':'References','data-composer-popup':'',className:'composer-suggestions',
      onWheel:()=>{navigation.current='scroll';},onTouchMove:()=>{navigation.current='scroll';},
      'data-placement':geometry.side,style:{left:geometry.left,top:geometry.top,width:geometry.width,maxHeight:geometry.maxHeight,transform:geometry.transform},
    },content),document.body);
    return h(React.Fragment,null,h('div',{ref:host,className:'composer-editor-host'}),overlay);
  }
  components.set(React,ComposerEditor);return ComposerEditor;
}
