import {readFileSync} from 'node:fs';
import {expect,test,vi} from 'vitest';
const html=readFileSync('../design/Velllum/uploads/Vellum Default Re-designed.html','utf8');
function workspace(){
  const state={properties:{items:[],active_item:'',content:'workspace'},chats:[]};
  const dispatch=vi.fn(async()=>({status:'applied',result:{navigation:{view:'chat',conversation_id:null}}}));
  const openBrowser=vi.fn(async()=>({running:true}));
  const code=html.slice(html.indexOf('  const openWorkspace='),html.indexOf('  const workspaceTabs='));
  const owner=Function('runWorkspace','getWorkspacePresentation','setWorkspace','dispatchConversationAction','activeChatProject','uid','selModel','draftReasoningMode','setChats','openBrowser','commandWorkspaceBrowser','API','browserState','workspaceMode','workspaceTerminalAvailable','refreshBrowser','hideBrowserPanel',code+';return {openWorkspace,closeWorkspaceItem};')(
    work=>work(),()=>state,async(p,visible=true)=>{state.properties={...state.properties,...p};state.visible=visible;return {status:'applied'};},dispatch,null,()=> 'draft-side','test-model','',update=>{state.chats=update(state.chats);},openBrowser,vi.fn(async()=>true),{browser:{addressUrl:()=> 'https://www.google.com/search?q=hello'}},{tabs:[],preferences:{}},'split',true,vi.fn(async()=>({tabs:[]})),vi.fn());
  return {state,dispatch,openBrowser,...owner};
}
test('side chat accepts the canonical draft-only new-conversation receipt',async()=>{
  const owner=workspace();await owner.openWorkspace('chat');
  expect(owner.state.properties.items).toHaveLength(1);
  expect(owner.state.chats[0]).toMatchObject({id:'draft-side',messages:[],model:'test-model'});
  expect(owner.state.properties.items[0].reference_id).toBe('draft-side');
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
