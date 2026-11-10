/* Shared by the web renderer and Electron. No browser, IPC or storage access. */
const command=(id,label,group,keys,options={})=>Object.freeze({id,label,group,keys:Object.freeze(keys),...options});
const commands=Object.freeze([
  command('app.home','Go to Home','Navigation',['Ctrl+Shift+H']),
  command('chat.new','New chat','Chats',['Ctrl+N','Ctrl+Shift+O']),
  command('commands.open','Search commands and chats','App',['Ctrl+K','Ctrl+Shift+P'],{allowOverlay:true,editingKeys:['Ctrl+K'],nativeKeys:['Ctrl+Shift+P']}),
  command('settings.open','Open Settings','App',['Ctrl+Comma']),
  command('shortcuts.open','Keyboard shortcuts','App',['Ctrl+Slash'],{allowOverlay:true}),
  command('sidebar.toggle','Toggle sidebar','Navigation',['Ctrl+B'],{requires:'sidebar',editingKeys:['Ctrl+B'],nativeKeys:[]}),
  command('history.back','Back in app history','Navigation',['Ctrl+BracketLeft'],{native:false,allowOverlay:true,editingKeys:['Ctrl+BracketLeft']}),
  command('history.forward','Forward in app history','Navigation',['Ctrl+BracketRight'],{native:false,allowOverlay:true,editingKeys:['Ctrl+BracketRight']}),
  command('chat.rename','Rename chat','Chats',['Ctrl+Alt+R'],{requires:'chat'}),
  command('chat.pin','Pin or unpin chat','Chats',['Ctrl+Alt+P'],{requires:'chat'}),
  command('chat.archive','Archive chat','Chats',['Ctrl+Shift+A'],{requires:'chat'}),
  command('chat.previous','Previous sidebar chat','Chats',['Ctrl+Alt+BracketLeft','Ctrl+Alt+ArrowLeft'],{requires:'chats'}),
  command('chat.next','Next sidebar chat','Chats',['Ctrl+Alt+BracketRight','Ctrl+Alt+ArrowRight'],{requires:'chats'}),
  command('chat.attention','Next chat needing attention','Chats',['Ctrl+Alt+A'],{requires:'attention'}),
  command('project.picker','Open project picker','Navigation',['Ctrl+Alt+Shift+O']),
  command('library.open','Open Library','Navigation',['Ctrl+Shift+L']),
  command('skills.open','Manage skills','Navigation',['Ctrl+Shift+K']),
  command('memory.open','Open Memory','Navigation',['Ctrl+Shift+E']),
  command('analytics.open','Open Analytics','Navigation',['Ctrl+Shift+G'],{native:false}),
  command('instructions.open','Custom instructions','App',['Ctrl+Shift+I']),
  command('model.open','Choose a model','Composer',['Ctrl+Shift+M','Alt+M'],{requires:'composer'}),
  command('files.add','Add photos and files','Composer',['Ctrl+U'],{requires:'composer'}),
  command('code.copy','Copy last code block','Composer',['Ctrl+Shift+Semicolon'],{requires:'chat'}),
  command('chat.delete','Delete chat','Chats',['Ctrl+Shift+Backspace'],{requires:'chat'}),
  command('dev.toggle','Toggle development mode','App',['Ctrl+Period']),
  command('browser.new','New browser tab','Browser',['Ctrl+T']),
  command('browser.close','Close active browser tab','Browser',['Ctrl+W','Ctrl+F4'],{requires:'tabs'}),
  command('window.close','Close Vellum window','App',['Ctrl+W','Ctrl+F4'],{requires:'desktop',scope:'app',native:false}),
  command('browser.reopen','Reopen closed browser tab','Browser',['Ctrl+Shift+T']),
  command('browser.next','Next browser tab','Browser',['Ctrl+Tab','Ctrl+PageDown','Ctrl+Shift+BracketRight'],{requires:'tabs'}),
  command('browser.previous','Previous browser tab','Browser',['Ctrl+Shift+Tab','Ctrl+PageUp','Ctrl+Shift+BracketLeft'],{requires:'tabs'}),
  command('browser.closeOthers','Close other browser tabs','Browser',['Ctrl+Alt+W'],{requires:'tabs'}),
  command('browser.address','Focus browser address','Browser',['Ctrl+L'],{requires:'tabs',scope:'browser'}),
  command('browser.back','Back in browser','Browser',['Alt+ArrowLeft'],{requires:'tabs',scope:'browser'}),
  command('browser.forward','Forward in browser','Browser',['Alt+ArrowRight'],{requires:'tabs',scope:'browser'}),
  command('surface.reload','Reload current surface','Browser',['Ctrl+R','F5']),
  command('surface.forceReload','Reload without cache','Browser',['Ctrl+Shift+R','Ctrl+F5']),
  command('find.open','Find in current surface','App',['Ctrl+F'],{allowOverlay:true}),
  command('find.next','Next find result','App',['F3','Ctrl+G'],{requires:'find',nativeKeys:['F3']}),
  command('find.previous','Previous find result','App',['Shift+F3','Ctrl+Shift+G'],{requires:'find',nativeKeys:['Shift+F3'],priority:20}),
  command('workspace.summary','Toggle summary','Chats',['Ctrl+Shift+S'],{requires:'chat'}),
  command('workspace.tabs','Show workspace tabs','Navigation',['Ctrl+Shift+F']),
  command('workspace.sideChat','Open side chat','Chats',['Ctrl+Alt+S']),
  command('workspace.layout','Cycle browser layout','Navigation',['Ctrl+Shift+B'],{requires:'tabs'}),
  command('zoom.in','Zoom in','App',['Ctrl+Equal','Ctrl+Shift+Equal','Ctrl+NumpadAdd'],{requires:'desktop'}),
  command('zoom.out','Zoom out','App',['Ctrl+Minus','Ctrl+NumpadSubtract'],{requires:'desktop'}),
  command('zoom.reset','Reset zoom','App',['Ctrl+Digit0','Ctrl+Numpad0'],{requires:'desktop'}),
  command('dismiss','Dismiss active popup','App',['Escape'],{hidden:true,native:false,priority:100,allowOverlay:true}),
]);
const unavailable=Object.freeze([
  {label:'Temporary chat',reason:'Temporary chat is not available. Turning memory off does not make a chat temporary.'},
  {label:'Mark unread / clear unread',reason:'Vellum does not yet have persisted chat unread controls.'},
  {label:'Coding/review tools',reason:'These surfaces are not available in Vellum yet.'},
]);
const keyAliases={',':'Comma','/':'Slash','[':'BracketLeft',']':'BracketRight','.':'Period',';':'Semicolon','=':'Equal','+':'Equal','-':'Minus',' ':'Space','esc':'Escape'};
function chord(event){
  if(event.isComposing||event.getModifierState?.('AltGraph'))return '';
  let code=event.code;
  if(!code||code==='Unidentified'){
    const key=String(event.key||'');
    code=keyAliases[key]||(/^[a-z]$/i.test(key)?'Key'+key.toUpperCase():/^\d$/.test(key)?'Digit'+key:key[0]?.toUpperCase()+key.slice(1));
  }
  if(!code||/^(Control|Meta|Shift|Alt)/.test(code))return '';
  if(/^Key[A-Z]$/.test(code))code=code.slice(3);
  return [event.ctrlKey||event.metaKey||event.control||event.meta?'Ctrl':'',event.altKey||event.alt?'Alt':'',event.shiftKey||event.shift?'Shift':'',code].filter(Boolean).join('+');
}
function definition(id){return commands.find(item=>item.id===id);}
function numberCommand(event,context={}){
  const value=chord(event),match=/^(Ctrl|Alt)\+Digit([1-9])$/.exec(value);
  if(!match)return null;
  const tabs=(context.numberPrimary||'tabs')==='tabs' ? match[1]==='Ctrl':match[1]==='Alt';
  return {id:tabs?'browser.number':'chat.number',index:Number(match[2]),label:tabs?'Switch browser tab':'Switch sidebar chat',requires:tabs?'tabs':'chats'};
}
function eligible(item,context={}){
  return !(context.overlay&&!item.allowOverlay) && (!item.requires||!!context[item.requires]) && (!item.scope||item.scope==='browser'&&!!context.browser||item.scope==='app'&&!context.browser);
}
function match(event,context={}){
  const key=chord(event);if(!key||event.defaultPrevented||event.target?.closest?.('[data-shortcut-capture]'))return null;
  const numeric=numberCommand(event,context);
  if(numeric)return eligible(numeric,context)?numeric:null;
  return [...commands].sort((a,b)=>(b.priority||0)-(a.priority||0)).find(item=>item.keys.includes(key)&&eligible(item,context)&&
    !(context.editable&&item.editingKeys?.includes(key))&&!(context.native&&(item.native===false||item.nativeKeys&&!item.nativeKeys.includes(key))))||null;
}
function displayKey(value){return value.replace('BracketLeft','[').replace('BracketRight',']').replace('Comma',',').replace('Slash','/').replace('Semicolon',';').replace('Period','.').replace('Equal','+').replace('Minus','-').replace(/Digit(\d)/,'$1').replace(/Numpad(\d)/,'Num $1').replace('NumpadAdd','Num +').replace('NumpadSubtract','Num -').replace('ArrowLeft','Left').replace('ArrowRight','Right');}
function createRuntime({context,handlers,onError=()=>{}}){
  function execute(id,override={},extra){
    const state={...context(),...override},item=definition(id)||{id,requires:id.startsWith('browser.')?'tabs':'chats'};
    const handler=handlers()[id];if(!handler||!eligible(item,state))return false;
    try{const result=handler(state,extra);if(result===false)return false;Promise.resolve(result).catch(onError);return true;}catch(error){onError(error);return false;}
  }
  return {execute,dispatch(event,override={}){const item=match(event,{...context(event),...override});if(!item)return false;if(event.repeat&&!['browser.next','browser.previous','find.next','find.previous','zoom.in','zoom.out'].includes(item.id)){event.preventDefault?.();return true;}if(!execute(item.id,override,item.index))return false;event.preventDefault?.();event.stopPropagation?.();return true;},entries(override={}){const state={...context(),...override};return commands.filter(item=>!item.hidden&&eligible(item,state)&&handlers()[item.id]);}};
}
module.exports={commands,unavailable,definition,chord,match,eligible,numberCommand,displayKey,createRuntime};
