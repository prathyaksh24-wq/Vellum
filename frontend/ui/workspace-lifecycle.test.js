import {readFileSync} from 'node:fs';
import {expect,test,vi} from 'vitest';
const html=readFileSync('../design/Velllum/uploads/Vellum Default Re-designed.html','utf8');
function workspace(){
  const state={properties:{items:[],active_item:'',content:'workspace'},chats:[]};
  const sideChat={id:'side-chat',temporary_side_chat:true,messages:[],revision:0};
  const dispatch=vi.fn(async action=>action==='conversation.new'
    ? {status:'applied',result:{conversation:sideChat}}
    : {status:'confirmation_required',confirmation:{token:'discard-side-chat'}});
  const confirm=vi.fn(async()=>({status:'applied',result:{deleted:true}}));
  const openBrowser=vi.fn(async()=>({running:true}));
  const code=html.slice(html.indexOf('  const openWorkspace='),html.indexOf('  const workspaceResources='));
  const bindings={
    state,
    pendingSideChatCreates:{current:new Map()},
    closingWorkspaceIds:{current:new Set()},workspaceCloseSelection:{current:null},setClosingWorkspaceTabs:()=>{},
    workspaceViews:{get activeId(){return state.properties.active_item;}},
    workspaceTerminalAvailable:true,
    workspaceActionRuntimeRef:{current:{previewSurface:vi.fn(()=>()=>{}),context:()=>({workspace_layout:{surfaces:{'right-panel':state}}})}},
    runWorkspace:work=>work(),
    getWorkspacePresentation:()=>state,
    setWorkspace:async(p,visible=true)=>{state.properties={...state.properties,...p};state.visible=visible;},
    dispatchConversationAction:dispatch,
    conversationActionRuntimeRef:{current:{confirm}},
    activeChatId:'main-chat',
    setChats:update=>{state.chats=update(state.chats);},
    isSideChat:chat=>!!chat?.temporary_side_chat,
    closingSideChats:{current:new Set()},
    voiceRuntimeRef:{current:null},
    turnCtl:{current:{}},
    turnQueueRef:{current:{}},
    sideChatSaves:{current:new Map()},
    threadRef:{current:{}},
    openBrowser,
    API:{browser:{addressUrl:()=> 'https://www.google.com/search?q=hello'},conversations:{get:async()=>({conversation:sideChat})}},
    browserState:{tabs:[],preferences:{}},
  };
  const owner=Function(...Object.keys(bindings),'const getChats=()=>state.chats;const getWorkspaceTabs=()=>state.properties.items;'+code.replace(/\bchats\.find\(/g,'getChats().find(').replace(/workspaceTabs\.filter\(/g,'getWorkspaceTabs().filter(')+';return {openWorkspace,closeWorkspaceItem};')(...Object.values(bindings));
  return {state,dispatch,confirm,openBrowser,...owner};
}
test('side chat opens from a temporary record and confirms deletion of that record on close',async()=>{
  const owner=workspace();await owner.openWorkspace('chat');
  expect(owner.state.properties.items).toHaveLength(1);
  expect(owner.state.properties.items[0].reference_id).toBe('side-chat');
  await owner.closeWorkspaceItem(owner.state.properties.items[0]);
  expect(owner.dispatch).toHaveBeenLastCalledWith('conversation.delete',{conversation_id:'side-chat',target_revision:0},{conversationId:'side-chat',applyNavigation:false,notify:false});
  expect(owner.confirm).toHaveBeenCalledOnce();
  expect(owner.state.properties.items).toEqual([]);
});
test('closing a legacy tab pointing to an ordinary chat preserves that chat',async()=>{
  const owner=workspace();
  const item={id:'legacy',kind:'chat',reference_id:'main-chat'};
  owner.state.chats=[{id:'main-chat',messages:[]}];
  owner.state.properties.items=[item];
  await owner.closeWorkspaceItem(item);
  expect(owner.dispatch).not.toHaveBeenCalled();
  expect(owner.state.properties.items).toEqual([]);
});
test('closing one launcher retains and selects the remaining workspace tab',async()=>{
  const owner=workspace();await owner.openWorkspace('launcher');await owner.openWorkspace('launcher');
  const [first,second]=owner.state.properties.items;await owner.closeWorkspaceItem(second);
  expect(owner.state.properties.items.map(x=>x.id)).toEqual([first.id]);
  expect(owner.state.properties.active_item).toBe(first.id);expect(owner.state.visible).toBe(true);
});

test('launcher search passes its results URL into browser creation',async()=>{
  const owner=workspace();await owner.openWorkspace('browser','split','hello');
  expect(owner.openBrowser).toHaveBeenCalledExactlyOnceWith({mode:'split',newTab:true,initialUrl:'https://www.google.com/search?q=hello',throwOnError:true});
});


test('separate terminal views keep independent identities when reopened',async()=>{
  const owner=workspace();
  await owner.openWorkspace('terminal');await owner.openWorkspace('terminal');
  const [first,second]=owner.state.properties.items;
  expect(first.kind).toBe('terminal');expect(second.kind).toBe('terminal');
  expect(first.id).not.toBe(second.id);
  expect(first.reference_id).not.toBe(second.reference_id);
  await owner.closeWorkspaceItem(second);
  expect(owner.state.properties.items.map(item=>item.id)).toEqual([first.id]);
});
