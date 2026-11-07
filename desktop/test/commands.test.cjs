const {test}=require('node:test');
const assert=require('node:assert/strict');
const registry=require('../electron/commands.cjs');
const {validateChromeRequest}=require('../electron/chrome.cjs');
function key(code,options={}){return {code,key:code,ctrlKey:true,...options};}
const base={chat:true,chats:true,tabs:true,browser:true,sidebar:true,composer:true,desktop:true,attention:true};
test('side chat is available through the shared command registry',()=>{assert.equal(registry.match(key('KeyS',{altKey:true}),base).id,'workspace.sideChat');});

test('old Vellum aliases and familiar chat/sidebar bindings use the same commands',()=>{
  for(const event of [key('KeyN'),key('KeyO',{shiftKey:true})])assert.equal(registry.match(event,base).id,'chat.new');
  assert.equal(registry.match(key('KeyB'),base).id,'sidebar.toggle');
  assert.equal(registry.match(key('KeyS',{shiftKey:true}),base).id,'workspace.summary');
  assert.equal(registry.match(key('KeyH',{shiftKey:true}),base).id,'app.home');
  assert.equal(registry.match(key('KeyM',{shiftKey:true}),base).id,'model.open');
});
test('editing, composition, AltGraph and nested popup owners retain their keys',()=>{
  assert.equal(registry.match(key('KeyB'),{...base,editable:true}),null);
  assert.equal(registry.match(key('KeyK'),{...base,editable:true}),null);
  assert.equal(registry.match(key('KeyB',{isComposing:true}),base),null);
  assert.equal(registry.match(key('KeyB',{getModifierState:()=>true}),base),null);
  assert.equal(registry.match(key('KeyN'),{...base,overlay:true}),null);
  assert.equal(registry.match(key('KeyS',{shiftKey:true}),{...base,editable:true}).id,'workspace.summary');
});
test('find wins over Analytics only while Find is active',()=>{
  const event=key('KeyG',{shiftKey:true});
  assert.equal(registry.match(event,base).id,'analytics.open');
  assert.equal(registry.match(event,{...base,find:true}).id,'find.previous');
  assert.equal(registry.match(event,{...base,native:true}),null);
});
test('workspace tab close cannot accidentally become a window close while tabs are visible',()=>{
  assert.equal(registry.match(key('KeyW'),{...base,browser:false}).id,'browser.close');
  assert.equal(registry.match(key('F4'),base).id,'browser.close');
  assert.equal(registry.match(key('KeyW'),{...base,tabs:false,browser:false}).id,'window.close');
});
test('tab cycling aliases resolve without adding global listeners',()=>{
  for(const event of [key('Tab'),key('PageDown'),key('BracketRight',{shiftKey:true})])assert.equal(registry.match(event,base).id,'browser.next');
  for(const event of [key('Tab',{shiftKey:true}),key('PageUp'),key('BracketLeft',{shiftKey:true})])assert.equal(registry.match(event,base).id,'browser.previous');
});
test('browser Alt navigation and app history are distinct contexts',()=>{
  assert.equal(registry.match(key('ArrowLeft',{ctrlKey:false,altKey:true}),base).id,'browser.back');
  assert.equal(registry.match(key('ArrowLeft',{ctrlKey:false,altKey:true}),{...base,browser:false}),null);
  assert.equal(registry.match(key('BracketLeft'),base).id,'history.back');
  assert.equal(registry.match(key('BracketLeft'),{...base,native:true}),null);
});
test('number preference swaps tabs/chats and preserves 9 as last-item intent',()=>{
  assert.equal(registry.match(key('Digit1'),base).id,'browser.number');
  assert.equal(registry.match(key('Digit2',{ctrlKey:false,altKey:true}),base).id,'chat.number');
  assert.equal(registry.match(key('Digit1'),{...base,numberPrimary:'chats'}).id,'chat.number');
  const last=registry.match(key('Digit9',{ctrlKey:false,altKey:true}),{...base,numberPrimary:'chats'});
  assert.equal(last.id,'browser.number');assert.equal(last.index,9);
});
test('a handled DOM event cannot dispatch again at the window listener',()=>{
  let calls=0;
  const runtime=registry.createRuntime({context:()=>base,handlers:()=>({'chat.new':()=>calls++})});
  const event=key('KeyN',{preventDefault(){this.defaultPrevented=true;},stopPropagation(){}});
  assert.equal(runtime.dispatch(event),true);assert.equal(runtime.dispatch(event),false);assert.equal(calls,1);
});
test('repeat cannot create many chats, but tab cycling can repeat',()=>{
  const calls=[];const runtime=registry.createRuntime({context:()=>base,handlers:()=>({'chat.new':()=>calls.push('chat'),'browser.next':()=>calls.push('tab')})});
  runtime.dispatch(key('KeyN',{repeat:true}));runtime.dispatch(key('Tab',{repeat:true}));assert.deepEqual(calls,['tab']);
});
test('command menu, shortcut reference and native labels share unique definitions',()=>{
  assert.equal(new Set(registry.commands.map(item=>item.id)).size,registry.commands.length);
  assert.equal(registry.definition('commands.open').keys.includes('Ctrl+Shift+P'),true);
  assert.equal(registry.displayKey('Ctrl+BracketLeft'),'Ctrl+[');
  assert.equal(registry.match(key('KeyN',{shiftKey:true}),base),null);
  assert.ok(registry.unavailable.some(item=>item.label==='Temporary chat'));
});
test('native page editing is not overridden by app Ctrl+B or Ctrl+K',()=>{
  assert.equal(registry.match(key('KeyB'),{...base,native:true}),null);
  assert.equal(registry.match(key('KeyK'),{...base,native:true}),null);
  assert.equal(registry.match(key('KeyP',{shiftKey:true}),{...base,native:true}).id,'commands.open');
  assert.equal(registry.match(key('KeyR',{shiftKey:true}),{...base,native:true}).id,'surface.forceReload');
});
test('chrome accepts only bounded zoom modes and registered command identities',()=>{
  assert.equal(validateChromeRequest({kind:'zoom',mode:'reset'},{}).mode,'reset');
  assert.equal(validateChromeRequest({kind:'commands',enabled:['chat.new']},{}).enabled[0],'chat.new');
  for(const input of [{kind:'zoom',mode:'eval'},{kind:'zoom',mode:'in',url:'https://example.test'},{kind:'commands',enabled:['arbitrary.execute']}])assert.throws(()=>validateChromeRequest(input,{}));
});
