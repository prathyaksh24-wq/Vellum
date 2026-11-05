"""Muted, isolated layout check. Only synthetic data; all network blocked."""
from pathlib import Path
import re,base64,subprocess,asyncio,json
from playwright.async_api import async_playwright
ROOT=Path.cwd();SOURCE=ROOT/'design/Velllum/uploads';OUT=ROOT/'.scratch/sidebar-project-preview';OUT.mkdir(parents=True,exist_ok=True)
from html.parser import HTMLParser
html=(SOURCE/'Vellum Default Re-designed.html').read_text(encoding='utf-8')
class Styles(HTMLParser):
 def __init__(self):super().__init__();self.head=False;self.style=False;self.css=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='head':self.head=True
  if not self.head:return
  if tag=='style':self.style=True
  if tag=='link' and a.get('rel')=='stylesheet':
   f=SOURCE/a.get('href','').split('?')[0]
   if f.is_file():self.css.append(f.read_text(encoding='utf-8-sig'))
 def handle_endtag(self,tag):
  if tag=='style':self.style=False
  if tag=='head':self.head=False
 def handle_data(self,text):
  if self.style:self.css.append(text)
style=Styles();style.feed(html)
icons=dict(re.findall(r'const (Ic\w+) = \(p\)=> <window.VellumUI.AppIcon name="([^"]+)"',html))
shared=html[html.index('const SourceMarks ='):html.index('const RailFly =')]
for name in set(re.findall(r'\bIc\w+',shared)):
 icons.setdefault(name,{'IcBrain':'MemoryOnRemember','IcPenLine':'Edit','IcCheck':'Check','IcImage':'ImageSquare','IcFile':'FileDocument','IcNote':'FileDocument'}.get(name,'FileDocument'))
hover=html[html.index('  const [sidebarPeeking,'):html.index('  const mainSidebarTrigger=')]
fixture='''import React,{useState,useEffect,useLayoutEffect,useRef,useMemo} from '../../frontend/node_modules/react/index.js';
import * as ReactDOM from '../../frontend/node_modules/react-dom/index.js';import {createRoot} from '../../frontend/node_modules/react-dom/client.js';window.React=React;window.ReactDOM=ReactDOM;
window.VellumUI={AppIcon:({name,size=17})=><svg width={size} height={size} viewBox="0 0 24 24"><use href={'#'+name}/></svg>};
const visibleChats=chats=>chats.filter(chat=>!chat.archived&&!chat.projectId);
const FolderIcon=({open})=><window.VellumUI.AppIcon name={open?'FolderOpen':'Folder'} size={15}/>;
'''+''.join(f'const {k}=props=><window.VellumUI.AppIcon name="{v}" {{...props}}/>;\n' for k,v in icons.items())+shared+'\n'+(SOURCE/'components/morphic-ui.js').read_text(encoding='utf-8')+'\n'+(SOURCE/'components/navigation-shell.jsx').read_text(encoding='utf-8')+'\n'+(SOURCE/'components/workspace-controller.jsx').read_text(encoding='utf-8')+'''
window.fixture={actions:[],calls:[]};
const projects=[{id:'p1',name:'Reading room',revision:0},{id:'p2',name:'Weekend plans',revision:0}];
const seed=[{id:'c1',title:'Project conversation',projectId:'p1',messages:[]},{id:'c2',title:'A long conversation about a future trip to the mountains',messages:[]},{id:'c3',title:'Planning the week',messages:[]}];
function Fixture(){
 const [view,setView]=useState('chat'),[sidebarPinned,setPinned]=useState(true),[chats,setChats]=useState(seed),[secOpen,setSections]=useState({projects:true,recents:true}),[expanded,setExpanded]=useState({p1:true}),[menu,setMenu]=useState(null),[active,setActive]=useState(null),[draftProject,setDraftProject]=useState(null);
 const settingsOpen=false,desktopWorkspace=false;
'''+hover+'''
 fixture.pinned=setPinned;fixture.view=setView;fixture.state=()=>({view,sidebarPinned,sidebarPeeking,railPreview,chats,draftProject,active});
 const UI=window.VellumUI,feature=['apps','music'].includes(view),open=(!feature&&sidebarPinned)||sidebarPeeking;
 const mainSidebarContext=sidebarPeeking&&['chat','library'].includes(railPreview)?railPreview:view==='library'?'library':'chat';
 const controller={available:false,error:'',tabs:[]},project=projects.find(item=>item.id===(chats.find(chat=>chat.id===active)?.projectId||draftProject));
 return <div className="stage"><div className="win"><div className="body app-shell" style={{'--workspace-sidebar-width':'260px'}}>
 <UI.NavigationRail view={view} profile={{displayName:'Demo user'}} onHome={()=>{setView('chat');setActive(null);setDraftProject(null);}} onNav={setView} onProfile={()=>{}} onSettings={()=>{}} onSearch={()=>{}} onNotifications={()=>{}} sidebarVisible={sidebarPinned} onToggleSidebar={()=>{dismissSidebarPreview();setPinned(!sidebarPinned);}} onPreviewSidebar={previewSidebar} onLeaveSidebar={hideSidebarPeek} onDismissPreview={dismissSidebarPreview}/>
 <div className="main-sidebar-slot" data-state={open?'open':'closed'} data-peeking={sidebarPeeking&&(!sidebarPinned||feature)} data-pinned={sidebarPinned&&!feature} onPointerEnter={revealSidebar} onPointerLeave={hideSidebarPeek} inert={!open}>
 {mainSidebarContext==='library'?<UI.LibrarySidebar projects={projects} items={[]} section="all" onSection={()=>setView('library')}/>:<Sidebar chats={chats} projects={projects} activeChatId={active} view={view} secOpen={secOpen} expandedProj={expanded} onToggleSec={id=>setSections(value=>({...value,[id]:!value[id]}))} onToggleProj={id=>setExpanded(value=>({...value,[id]:!value[id]}))} onNewChat={()=>{setActive(null);setDraftProject(null);}} onSearch={()=>{}} onOpenChat={id=>{setActive(id);setDraftProject(null);}} onChatMenu={()=>{}} onChatAction={()=>{}} onRename={()=>{}} onNewProject={()=>fixture.calls.push('new-project')} onProjectMenu={()=>fixture.calls.push('project-menu')} onProjectRename={()=>{}} onOpenProject={id=>fixture.calls.push('open:'+id)} onProjectNewChat={id=>{setActive(null);setDraftProject(id);}} onProjectAction={(id,action)=>fixture.calls.push(id+':'+action)} onMoveToProject={(id,projectId)=>setChats(rows=>rows.map(chat=>chat.id===id?{...chat,projectId}:chat))}/>}</div>
 {railPreview&&railPreview!==view&&['apps','music'].includes(railPreview)&&<UI.RailContextPreview kind={railPreview} apps={[{id:'linear',name:'Linear',installed:true}]} Logo={()=> <span>L</span>} onEnter={revealSidebar} onLeave={hideSidebarPeek} onChoose={(kind,id)=>{fixture.calls.push(kind+':'+id);dismissSidebarPreview();setView(kind);}}/>}
 <div className="workspace-content" data-toolbar="true"><UI.WorkspaceToolbar controller={controller} title={active?chats.find(chat=>chat.id===active).title:''} conversation={active?{id:active}:null} sidebarVisible={sidebarPinned} project={project} onNewChat={()=>setActive(null)} onOpenProject={id=>fixture.calls.push('open:'+id)}/><main className="main" data-variant="inset"><div className="font-sample"><h1>Where would you like to start?</h1><p className="agent-response-content">A place for your conversations, ideas and projects.</p><label>Message Vellum<input placeholder="Ask anything"/></label><button type="button">Continue</button><code>const example = true;</code></div></main></div>
 </div></div></div>;
}createRoot(document.getElementById('root')).render(<Fixture/>);
'''
(OUT/'fixture.jsx').write_text(fixture,encoding='utf-8')
node=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
subprocess.run([node,str(ROOT/'frontend/node_modules/esbuild/bin/esbuild'),str(OUT/'fixture.jsx'),'--bundle','--outfile='+str(OUT/'fixture.js'),'--log-level=warning'],check=True)
async def run():
 async with async_playwright() as pw:
  browser=await pw.chromium.launch(executable_path=r'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe',headless=True,args=['--mute-audio'])
  context=await browser.new_context(viewport={'width':1440,'height':960});await context.route('**/*',lambda route:route.abort())
  page=await context.new_page();page.set_default_timeout(4000);errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
  css='\n'.join(style.css)+'\n.stage{padding:0}.win{width:100%;height:100%;border:0;border-radius:0}#root{height:100vh}.body{height:100%}.font-sample{margin:auto;max-width:700px;padding:30px}.font-sample>*{display:block;margin-bottom:18px}.font-sample h1{font:600 30px/1.2 var(--font-ui)}.font-sample input{padding:12px}.font-sample button{padding:8px 14px}'
  for font in ['SNPro-VariableRegular.woff2','SNPro-VariableItalic.woff2']:
   css=css.replace('../assets/fonts/'+font,'data:font/woff2;base64,'+base64.b64encode((SOURCE/'assets/fonts'/font).read_bytes()).decode())
  sprite=(SOURCE/'assets/icons/openai/sprite.svg').read_text(encoding='utf-8').replace('<svg ','<svg style="position:absolute;width:0;height:0;overflow:hidden" ',1)
  await page.set_content('<html data-theme="dark"><head><style>'+css+'</style></head><body>'+sprite+'<div id="root"></div></body></html>');await page.add_script_tag(path=str(OUT/'fixture.js'));await page.evaluate('document.fonts.ready');await page.wait_for_timeout(150)
  report={}
  async def check(name,value):
   report[name]=value
   assert value,(name,errors)
  await check('projectChatsVisible',await page.get_by_text('Project conversation',exact=True).count()==1)
  await page.locator('.project-open').filter(has_text='Reading room').hover();await page.get_by_role('button',name='New chat in Reading room',exact=True).click();await check('ordinaryDraftRetainsProject',await page.evaluate("fixture.state().draftProject==='p1'&&fixture.state().active===null"))
  await check('draftHasNoHeaderShortcuts',await page.locator('.workspace-project-context,.workspace-header-start [data-command="chat.new"]').count()==0)
  await page.locator('#sidebar-section-projects-button').click();await check('collapsedProjectInert',await page.locator('#sidebar-section-projects').get_attribute('inert') is not None)
  await page.get_by_role('button',name='New project',exact=True).click();await check('newProjectAvailableWhileCollapsed',await page.evaluate("fixture.calls.includes('new-project')"))
  await page.get_by_role('button',name='Project organization',exact=True).click();await page.get_by_role('menuitemradio',name='Name',exact=True).click();await page.locator('#sidebar-section-projects-button').click()
  await page.locator('#sidebar-section-recents-button').click();await check('recentsIndependent',await page.locator('#sidebar-section-projects').get_attribute('aria-hidden')=='false');await page.locator('#sidebar-section-recents-button').click()
  await page.wait_for_timeout(250)
  await page.locator('.shell-chat-row').filter(has_text='Project conversation').locator('.chat-title').click();await page.locator('.shell-chat-row').filter(has_text='Planning the week').drag_to(page.locator('.shell-project-row').filter(has_text='Reading room'));await check('dropMovesChatToProject',await page.evaluate("fixture.state().chats.find(chat=>chat.id==='c3').projectId==='p1'"))
  await page.locator('.project-open').filter(has_text='Reading room').hover();await page.wait_for_timeout(350);await check('richProjectHover',await page.get_by_role('complementary',name='Project details: Reading room').count()==1);await page.mouse.move(900,800);await page.wait_for_timeout(250)
  await page.screenshot(path=str(OUT/'sidebar-desktop.png'))
  await check('startedChatPinnedHasNoHeaderShortcuts',await page.locator('.workspace-header-start [data-command="chat.new"],.workspace-project-context').count()==0)
  await page.evaluate('fixture.pinned(false)');await page.wait_for_timeout(250);await check('startedChatHiddenShowsHeaderContext',await page.locator('.workspace-project-context').get_attribute('data-tip')=='Reading room' and await page.locator('.workspace-header-start [data-command="chat.new"]').count()==1);before=await page.locator('.workspace-content').bounding_box();await page.mouse.move(57,800);await page.wait_for_timeout(200);await check('leftEdgeDoesNotReveal',await page.evaluate('!fixture.state().sidebarPeeking'))
  await page.get_by_role('button',name='Home',exact=True).hover();await page.wait_for_timeout(150);after=await page.locator('.workspace-content').bounding_box();await check('homeHoverDoesNotPinOrResize',await page.evaluate('fixture.state().sidebarPeeking&&!fixture.state().sidebarPinned') and abs(before['x']-after['x'])<1)
  await page.get_by_role('button',name='More destinations',exact=True).click();await page.get_by_role('menuitem',name='Projects',exact=True).click();await check('hiddenSidebarMoreWorks',await page.evaluate("fixture.state().view==='projects'"))
  await page.get_by_role('button',name='Plugins',exact=True).hover();await check('pluginsRailPreview',await page.get_by_role('complementary',name='Plugins preview').count()==1);await page.screenshot(path=str(OUT/'plugins-preview.png'));await page.mouse.move(900,800);await page.wait_for_timeout(250)
  await page.get_by_role('button',name='Music',exact=True).hover();await check('musicRailPreview',await page.get_by_role('complementary',name='Music preview').count()==1);await page.mouse.move(900,800);await page.wait_for_timeout(250)
  await page.evaluate("fixture.view('chat')");await page.get_by_role('button',name='Home',exact=True).click();await page.locator('.workspace-project-context').wait_for(state='hidden');await check('unassignedDraftHasNoFolder',await page.locator('.workspace-project-context').count()==0)
  fonts=await page.evaluate("({loaded:document.fonts.check('400 16px \\\"SN Pro\\\"'),ui:getComputedStyle(document.querySelector('input')).fontFamily,prose:getComputedStyle(document.querySelector('.agent-response-content')).fontFamily,code:getComputedStyle(document.querySelector('code')).fontFamily})")
  report['fonts']=fonts;await check('localFontLoaded',fonts['loaded'] and 'SN Pro' in fonts['ui'] and 'SN Pro' in fonts['prose'] and 'Cascadia' in fonts['code'])
  await page.evaluate("fixture.view('library')");await page.get_by_role('button',name='Library',exact=True).hover();await page.wait_for_timeout(50);await check('libraryRailShowsLibrarySidebar',await page.get_by_role('complementary',name='Library navigation').count()==1)
  await page.get_by_role('button',name='Home',exact=True).hover();await page.wait_for_timeout(50);await check('homeRailInLibraryShowsConversations',await page.get_by_role('complementary',name='Conversations',exact=True).count()==1 and await page.get_by_role('complementary',name='Library navigation').count()==0)
  await page.get_by_role('button',name='Library',exact=True).hover();await page.wait_for_timeout(50);await check('libraryRailRestoresLibrarySidebar',await page.get_by_role('complementary',name='Library navigation').count()==1)
  await page.mouse.move(1000,700);await page.wait_for_timeout(200);await page.evaluate("fixture.view('chat')");
  await page.set_viewport_size({'width':640,'height':800});await page.wait_for_timeout(250);await page.screenshot(path=str(OUT/'sidebar-narrow.png'));await check('narrowNoPageOverflow',await page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
  await page.emulate_media(reduced_motion='reduce');await page.evaluate('fixture.pinned(true)');await page.wait_for_timeout(150);await check('reducedMotion',await page.locator('.project-disclosure svg').first.evaluate("node=>getComputedStyle(node).transitionDuration==='0s'"))
  report['pageErrors']=errors;await check('noPageErrors',not errors);(OUT/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2));await browser.close()
if __name__=='__main__':asyncio.run(run())
