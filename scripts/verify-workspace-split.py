"""Isolated browser split regression checks; fake DOM/data, blocked network.

Run from the repository root with its existing Python Playwright, Node and
frontend dependencies. Creates a disposable headless browser, never attaches to
an existing session. No installs, backend calls, credentials or private data.
"""
import argparse,asyncio,json,shutil,subprocess,sys
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--browser',default=r'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe')
parser.add_argument('--capture',action='store_true',help='Save fake-data screenshots alongside measurements')
parser.add_argument('--built',action='store_true',help='Load the compiled desktop CSS instead of source CSS')
ARGS=parser.parse_args()
OUT=ROOT/'.scratch/workspace-split';OUT.mkdir(parents=True,exist_ok=True)
CSS_ROOT=ROOT/('desktop/resources/ui' if ARGS.built else 'design/Velllum/uploads')
sys.path.insert(0,str(ROOT/'backend'))
from agent.app_actions.runtime import AppActionRuntime
from agent.app_actions.models import AppActionRequest,AppActionContext
SOURCE=ROOT/'design/Velllum/uploads'

class Styles(HTMLParser):
    def __init__(self,root):
        super().__init__();self.root=root;self.css=[];self.style=False;self.head=False
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='head':self.head=True
        if not self.head:return
        if tag=='style':self.style=True
        if tag=='link' and a.get('rel')=='stylesheet':
            href=a.get('href','').split('?')[0]
            if href.startswith(('http:','https:','//')):return
            file=self.root/href.lstrip('/')
            if file.is_file():self.css.append(file.read_text(encoding='utf-8-sig'))
    def handle_endtag(self,tag):
        if tag=='style':self.style=False
        if tag=='head':self.head=False
    def handle_data(self,data):
        if self.style:self.css.append(data)

FIXTURE=r'''import React,{useState,useEffect,useLayoutEffect,useRef} from '../../frontend/node_modules/react/index.js';
import {createRoot} from '../../frontend/node_modules/react-dom/client.js';
window.fixture={commits:[],sidebarCommits:[],mounts:[],inFlight:0,maxInFlight:0};
const nativeBridge={mount:async request=>{fixture.mounts.push(request);fixture.maxInFlight=Math.max(fixture.maxInFlight,++fixture.inFlight);await new Promise(resolve=>setTimeout(resolve,25));fixture.inFlight--;return {};}};
__SPLIT_COMPONENTS__
function FakeBrowser({expanded,suspended}){
 const native=true,state={running:true,native_target_id:'fake-tab'},home=false,overlayVisible=false,moreOpen=false,downloadsOpen=false,addressOpen=false,suggestions=[];
 const screenRef=useRef(null),[still,setNativeStill]=useState(''),[error,setViewError]=useState('');
__NATIVE_EFFECT__
 return <aside className={'browser-panel'+(expanded?' browser-expanded':'')}><header className="browser-heading"><span>Browser · Fake page</span></header><div className="browser-address-row"><input aria-label="Fake address" defaultValue="https://example.test/"/></div><div ref={screenRef} className="browser-screen"><p>Isolated browser fixture</p>{error}</div></aside>;
}
function Fixture(){
 const [sidebarWidth,setSidebarWidth]=useState(260);fixture.sidebarSaved=sidebarWidth;
 const sidebarCommit=async width=>{const response=await fetch('https://fixture.test/layout',{method:'POST',body:JSON.stringify({width})});const receipt=await response.json();if(receipt.status==='applied'){fixture.sidebarCommits.push(width);setSidebarWidth(width);}return receipt;};
 const [pinned,setPinned]=useState(true),[peeking,setPeeking]=useState(false),[ratio,setRatio]=useState(38),[active,setActive]=useState(true),[expanded,setExpanded]=useState(false),[suspended,setSuspended]=useState(false);
 fixture.setPinned=setPinned;fixture.setPeeking=setPeeking;fixture.setPreference=setRatio;fixture.setActive=setActive;fixture.setExpanded=setExpanded;fixture.setSuspended=setSuspended;fixture.saved=ratio;
 const commit=async value=>{fixture.commits.push(value);setRatio(value);return {status:'applied'};};
 return <div className="stage"><div className="win"><div className={'body'+(active?' browser-active':'')} style={{'--workspace-sidebar-width':sidebarWidth+'px'}}><div className="main-sidebar-slot" data-state={pinned||peeking?'open':'closed'} data-pinned={pinned} data-peeking={peeking}><aside className="sidebar"><h2>Vellum</h2><p>Fake navigation</p></aside>{pinned && <SidebarResizeHandle value={sidebarWidth} onChange={sidebarCommit}/>}</div>
 <BrowserSplitView active={active} value={ratio} onChange={commit} onDismiss={()=>setActive(false)}>
 <main className="main" data-variant="inset" data-main-sidebar={pinned?'open':'closed'}><header className="chat-head"><h2>Example chat</h2></header><div className="msgs"><p>Fake conversation for layout checks.</p><button>Fake chat action</button></div></main>
 {active && <FakeBrowser expanded={expanded} suspended={suspended}/>}
 </BrowserSplitView></div></div></div>;
}
createRoot(document.getElementById('root')).render(<Fixture/>);
'''

def compile_fixture():
    # Exercise the served controller and native mount effect, not copied logic.
    source=SOURCE.joinpath('components/browser-panel.jsx').read_text(encoding='utf-8')
    components=source[source.index('  // Saved preference'):source.index('  const assets =')]
    start=source.index('    const nativeMountQueue=useRef(Promise.resolve());')
    end=source.index('    useEffect(()=>()=>{if(native)',start)
    native=source[start:end]
    entry=OUT/'fixture.jsx';entry.write_text(FIXTURE.replace('__SPLIT_COMPONENTS__',components).replace('__NATIVE_EFFECT__',native),encoding='utf-8')
    fallback=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    node=shutil.which('node') or (str(fallback) if fallback.is_file() else None)
    if not node:raise SystemExit('Node.js is required; no installation was attempted.')
    subprocess.run([node,str(ROOT/'frontend/node_modules/esbuild/bin/esbuild'),str(entry),'--bundle','--outfile='+str(OUT/'fixture.js'),'--log-level=warning'],cwd=ROOT,check=True)

compile_fixture()
from playwright.async_api import async_playwright
MEASURE="""()=>{const root=document.querySelector('.workspace-split'),main=root.querySelector(':scope>.main'),panel=root.querySelector('.browser-panel'),separator=root.querySelector('.browser-splitter');const rect=el=>{if(!el)return null;const r=el.getBoundingClientRect(),s=getComputedStyle(el);return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom,position:s.position,display:s.display,transition:s.transitionDuration};};return {viewport:innerWidth,mode:root.dataset.splitMode,region:rect(root),main:rect(main),panel:rect(panel),separator:rect(separator),saved:fixture.saved,inert:main.inert,overflow:document.documentElement.scrollWidth>innerWidth,commits:[...fixture.commits],slot:rect(document.querySelector('.main-sidebar-slot'))};}"""
async def poll(page,expression,arg=None):
 for _ in range(100):
  result=await page.evaluate(expression,arg)
  if result:return result
  await page.wait_for_timeout(30)
 raise AssertionError('Timed out: '+expression+'; '+str(await page.evaluate(MEASURE)))
async def run():
 results=[];errors=[]
 async with async_playwright() as p:
  browser=await p.chromium.launch(executable_path=ARGS.browser,headless=True,args=['--mute-audio','--disable-extensions','--no-first-run'])
  context=await browser.new_context(viewport={'width':900,'height':820},reduced_motion='reduce')
  await context.route('**/*',lambda route:route.abort())
  backend=AppActionRuntime()
  async def layout_action(route):
   data=route.request.post_data_json
   receipt=backend.dispatch(AppActionRequest(action_id='ui.surface.configure',arguments={'reference':'sidebar','properties':{'width':data['width']}}),AppActionContext(source='ui',invocation_conversation_id='fixture'))
   await route.fulfill(status=200,json=receipt.model_dump(mode='json'))
  await context.route('https://fixture.test/layout',layout_action)
  page=await context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
  parser=Styles(CSS_ROOT);parser.feed(CSS_ROOT.joinpath('Vellum Default Re-designed.html').read_text(encoding='utf-8'))
  css='\n'.join(parser.css)+'\n:root{--bg:#171413;--txt:#e7ded8;--txt2:#fff;--line:#5a4c45;--glass:rgba(23,20,19,.8);--glass-side:rgba(23,20,19,.9);--glass-win:transparent;--stage:#171413;--menu-solid:#201b19}.chat-head h2{font-size:18px}'
  await page.set_content('<html class="desktop-chrome-on"><head><style>'+css+'</style></head><body><header class="desktop-titlebar"><span>Vellum · isolated layout check</span></header><div id="root"></div></body></html>')
  await page.add_script_tag(path=str(OUT/'fixture.js'))
  await poll(page,'()=>window.fixture?.setPinned && document.querySelector(".workspace-split")?.clientWidth>0')
  async def capture(name,expected=None,picture=False):
   if expected:await poll(page,"""expected=>{const node=document.querySelector('.workspace-split'),main=node.querySelector('.main'),panel=node.querySelector('.browser-panel'),grip=node.querySelector('.browser-splitter');if(!main||!panel)return false;const width=node.getBoundingClientRect().width,m=main.getBoundingClientRect(),p=panel.getBoundingClientRect();return node.dataset.splitMode===expected && (getComputedStyle(main).display==='none' ? Math.abs(p.width-width)<.2 : expected==='split' ? Math.abs(m.width+p.width+grip.getBoundingClientRect().width-width)<.2 : Math.abs(p.width-Math.min(width,Math.max(400,width-48)))<.2)}""",expected)
   row=await page.evaluate(MEASURE);row['case']=name;results.append(row)
   if expected:assert row['mode']==expected,row
   assert not row['overflow'],row
   if row['mode']=='split' and row['main']['display']!='none':
    assert row['main']['width']>=319.9 and row['panel']['width']>=399.9,row
    assert abs(row['main']['width']+row['separator']['width']+row['panel']['width']-row['region']['width'])<.2,row
    assert row['panel']['position']=='relative',row
   assert row['panel']['right']<=row['region']['right']+.2,row
   if row['mode']=='drawer':assert row['inert'],row
   if picture and ARGS.capture:await page.screenshot(path=str(OUT/(name+'.png')))
   return row
  await capture('same-window-sidebar-open','drawer',True)
  await page.evaluate('fixture.setPinned(false)');await capture('same-window-sidebar-closed','split',True)
  assert await page.evaluate('fixture.saved')==38
  await page.evaluate('fixture.setPeeking(true)');row=await capture('unpinned-sidebar-peek','split');assert row['slot']['width']==0
  await page.evaluate('fixture.setPeeking(false);fixture.setPinned(true)')
  await page.set_viewport_size({'width':981,'height':820});await capture('minimum-split-width','split')
  await page.set_viewport_size({'width':980,'height':820});await capture('one-pixel-below-minimum','drawer')
  await page.set_viewport_size({'width':1600,'height':820});await capture('wide','split',True)
  sidebar=page.get_by_role('separator',name='Resize sidebar',exact=True)
  assert (await page.evaluate(MEASURE))['slot']['width']==260
  box=await sidebar.bounding_box();await page.mouse.move(box['x']+5,box['y']+100);await page.mouse.down();await page.mouse.move(350,box['y']+100,steps=16)
  assert await page.evaluate('fixture.sidebarCommits.length')==0
  await page.mouse.up();await poll(page,'()=>fixture.sidebarSaved===350')
  assert await page.evaluate('fixture.sidebarCommits.length')==1
  await capture('sidebar-dragged-with-browser','split')
  await page.evaluate('fixture.setActive(false)');await poll(page,'()=>document.querySelector(".workspace-split").dataset.splitMode==="closed"')
  assert await page.evaluate('document.querySelector(".main-sidebar-slot").getBoundingClientRect().width')==350
  await page.evaluate('fixture.setActive(true)');await capture('same-sidebar-width-after-browser-open','split')
  assert await page.evaluate('document.querySelector(".main-sidebar-slot").getBoundingClientRect().width')==350
  await sidebar.focus();await page.keyboard.press('Home');await poll(page,'()=>fixture.sidebarSaved===260')
  for width,status in [(200,'applied'),(400,'applied'),(199,'failed'),(401,'failed')]:
   result=await page.evaluate("async width=>(await fetch('https://fixture.test/layout',{method:'POST',body:JSON.stringify({width})})).json()",width)
   assert result['status']==status,result
  assert not await page.evaluate('fixture.commits.length')

  await page.evaluate('fixture.setPreference(20)');await capture('saved-minimum','split')
  assert await page.evaluate('fixture.saved')==20
  await page.evaluate('fixture.setPreference(75)');await capture('saved-maximum-clamped','split')
  assert await page.evaluate('fixture.saved')==75
  await page.set_viewport_size({'width':2400,'height':820});row=await capture('saved-maximum-restored','split');assert abs(row['main']['width']/(row['region']['width']-1)*100-75)<.1
  await page.set_viewport_size({'width':1200,'height':820});await page.evaluate('fixture.setExpanded(true)');row=await capture('expanded','split');assert row['main']['display']=='none' and abs(row['panel']['width']-row['region']['width'])<.2
  await page.evaluate('fixture.setPinned(false)');await capture('expanded-sidebar-toggle','split')
  await page.evaluate('fixture.setExpanded(false);fixture.setPreference(38)');await capture('restored-split','split')
  sep=page.get_by_role('separator',name='Resize chat and browser')
  await sep.click();assert await page.evaluate('fixture.commits.length')==0
  await sep.focus();await page.keyboard.press('ArrowRight');await poll(page,'()=>fixture.commits.length===1')
  await page.keyboard.press('Home');await poll(page,'()=>fixture.saved===38')
  assert await sep.get_attribute('aria-valuenow') is not None
  await page.wait_for_timeout(150)
  before=await page.evaluate('({commits:fixture.commits.length,mounts:fixture.mounts.length})')
  box=await sep.bounding_box();x=box['x']+.5;y=box['y']+100
  await page.mouse.move(x,y);await page.mouse.down()
  await page.mouse.move(x+160,y,steps=20)
  assert await page.evaluate('document.querySelector(".workspace-split").classList.contains("browser-resizing")')
  assert (await page.evaluate(MEASURE))['main']['transition']=='0s'
  assert await page.evaluate('fixture.commits.length')==before['commits']
  await page.mouse.up();await poll(page,'n=>fixture.commits.length===n+1',before['commits'])
  await page.wait_for_timeout(200)
  native=await page.evaluate('start=>({calls:fixture.mounts.slice(start),max:fixture.maxInFlight})',before['mounts'])
  assert native['calls'] and all(call.get('visible') is True for call in native['calls']),native
  assert native['max']==1,native
  await capture('drag-persisted-once','split')
  before=await page.evaluate('({commits:fixture.commits.length,saved:fixture.saved})')
  box=await sep.bounding_box();await page.mouse.move(box['x']+.5,y);await page.mouse.down();await page.mouse.move(box['x']-100,y)
  await sep.dispatch_event('pointercancel',{'pointerId':1});await page.mouse.up();await page.wait_for_timeout(100)
  assert await page.evaluate('fixture.commits.length')==before['commits']
  assert not await page.evaluate('document.querySelector(".workspace-split").classList.contains("browser-resizing")')
  await page.evaluate('''()=>{const r=document.querySelector('.browser-screen').getBoundingClientRect(),popup=document.createElement('div');popup.dataset.composerPopup='';popup.style.cssText=`position:fixed;left:${r.left+10}px;top:${r.top+10}px;width:250px;height:100px`;document.body.append(popup);window.dispatchEvent(new Event('vellum:composer-popup'));}''')
  await poll(page,'()=>fixture.mounts.at(-1)?.visible===false')
  await page.evaluate('''()=>{document.querySelector('[data-composer-popup]').remove();window.dispatchEvent(new Event('vellum:composer-popup'));}''')
  await poll(page,'()=>fixture.mounts.at(-1)?.visible===true')
  await page.evaluate('fixture.setSuspended(true)');await poll(page,'()=>fixture.mounts.at(-1)?.visible===false')
  await page.evaluate('fixture.setSuspended(false)');await poll(page,'()=>fixture.mounts.at(-1)?.visible===true')
  await page.set_viewport_size({'width':500,'height':820});await capture('small-host','drawer')
  await page.evaluate('fixture.setPinned(false);fixture.setPeeking(true)');await poll(page,'()=>fixture.mounts.at(-1)?.visible===false')
  await page.evaluate('fixture.setPeeking(false)');await poll(page,'()=>fixture.mounts.at(-1)?.visible===true')
  await page.get_by_role('button',name='Return to chat').click(position={'x':10,'y':100});await poll(page,'()=>document.querySelector(".workspace-split").dataset.splitMode==="closed"')
  assert not await page.evaluate('document.querySelector(".main").inert')
  await page.evaluate('fixture.setActive(true)');await capture('reopened-drawer','drawer')
  await page.evaluate('document.documentElement.classList.remove("desktop-chrome-on");fixture.setPinned(false)')
  await page.set_viewport_size({'width':900,'height':820});await capture('web-container-split','split')
  assert not errors,errors
  await browser.close()
 OUT.joinpath('after.json').write_text(json.dumps({'cases':results,'native_drag':native,'pageErrors':errors},indent=2))
 print(json.dumps({'layoutCases':len(results),'nativeMaxConcurrent':native['max'],'nativeDragStayedMounted':True,'errors':errors},indent=2))
asyncio.run(run())
