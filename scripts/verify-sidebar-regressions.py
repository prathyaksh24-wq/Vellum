from pathlib import Path
import asyncio,json,subprocess
from playwright.async_api import async_playwright
ROOT=Path.cwd()
import runpy
base=runpy.run_path(str(ROOT/'scripts/verify-sidebar-projects.py'))
for name in ['html','fixture','OUT','style','SOURCE','node']:globals()[name]=base[name]
modal=html[html.index('const CreateProjectModal ='):html.index('/* Profile */',html.index('const CreateProjectModal ='))]
button=html[html.index('const BorderGradientButton ='):html.index('const BorderGradientButton =')+html[html.index('const BorderGradientButton ='):].index('\n};')+4]
fixture=fixture.replace("title:'Project conversation',projectId:'p1'","title:'Project conversation',pinned:true,projectId:'p1'")
fixture=fixture.replace('window.fixture={actions:[],calls:[]};',"const I=()=>null;const DEFAULT_BORDER_GRADIENT_COLORS=['transparent'];\n"+button+'\n'+modal+"\nwindow.fixture={actions:[],calls:[],creates:0};")
fixture=fixture.replace(' fixture.pinned=setPinned;'," const [showCreate,setShowCreate]=useState(false);fixture.modal=setShowCreate;\n fixture.pinned=setPinned;")
fixture=fixture.replace('return <div className="stage"><div className="win">', 'return <div className="stage">{showCreate&&<CreateProjectModal onClose={()=>setShowCreate(false)} onCreate={async()=>{fixture.creates++;await new Promise(resolve=>setTimeout(resolve,2000));return {status:\'applied\'};}}/>}<div className="win">')
(OUT/'regressions.jsx').write_text(fixture,encoding='utf-8')
subprocess.run([node,str(ROOT/'frontend/node_modules/esbuild/bin/esbuild'),str(OUT/'regressions.jsx'),'--bundle','--outfile='+str(OUT/'regressions.js'),'--log-level=warning'],check=True)
async def run():
 async with async_playwright() as pw:
  browser=await pw.chromium.launch(executable_path=r'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe',headless=True,args=['--mute-audio'])
  context=await browser.new_context(viewport={'width':1440,'height':960});await context.route('**/*',lambda route:route.abort());page=await context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
  css='\n'.join(style.css)+'\n.stage{padding:0}.win{width:100%;height:100%;border:0;border-radius:0}#root{height:100vh}.body{height:100%}'
  import base64
  for font in ['SNPro-VariableRegular.woff2','SNPro-VariableItalic.woff2']:
   css=css.replace('../assets/fonts/'+font,'data:font/woff2;base64,'+base64.b64encode((SOURCE/'assets/fonts'/font).read_bytes()).decode())
  sprite=(SOURCE/'assets/icons/openai/sprite.svg').read_text(encoding='utf-8').replace('<svg ','<svg style="position:absolute;width:0;height:0;overflow:hidden" ',1)
  await page.set_content('<html data-theme="dark"><head><style>'+css+'</style></head><body>'+sprite+'<div id="root"></div></body></html>');await page.add_script_tag(path=str(OUT/'regressions.js'));await page.wait_for_timeout(100)
  report={}
  await page.evaluate('fixture.modal(true)');await page.get_by_placeholder('Copenhagen Trip').fill('Research');await page.get_by_placeholder('Copenhagen Trip').evaluate("node=>{for(let i=0;i<3;i++)node.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));}");await page.wait_for_timeout(50);report['createCallsForOneSubmission']=await page.evaluate('fixture.creates');await page.evaluate('fixture.modal(false)')
  duplicate=page.locator('.shell-chat-row').filter(has_text='Project conversation').first;await duplicate.hover();await page.wait_for_timeout(300);report['sameChatInTwoSectionsHasOneCard']=await page.locator('.shell-chat-card').count()==1;await page.mouse.move(1000,850);await page.wait_for_timeout(500)
  first=page.locator('.project-open').filter(has_text='Reading room');second=page.locator('.project-open').filter(has_text='Weekend plans');await first.hover();await page.wait_for_timeout(400);await page.screenshot(path=str(OUT/'project-hover-design.png'));await second.focus();await page.wait_for_timeout(350);report['simultaneousHoverCards']=await page.locator('.shell-chat-card').count();await page.screenshot(path=str(OUT/'sidebar-hover-card.png'));await page.mouse.move(1000,850);await page.locator('body').click(position={'x':1000,'y':850});await page.wait_for_timeout(550)
  before=await page.locator('.project-disclosure').first.get_attribute('aria-expanded');await first.click();after=await page.locator('.project-disclosure').first.get_attribute('aria-expanded');report['projectNameToggles']=before!=after
  await first.hover();await page.get_by_role('button',name='New chat in Reading room',exact=True).click();await page.wait_for_timeout(50);report['draftHeaderFolderIcons']=await page.locator('.workspace-project-context').count()
  row=page.locator('.shell-chat-row').filter(has_text='A long conversation');await row.hover();await page.wait_for_timeout(350);card=page.get_by_role('complementary',name='Conversation details');report['chatCardInitiallyVisible']=await card.count()>0
  if await card.count():
   box=await card.bounding_box();r=await row.bounding_box();await page.mouse.move(r['x']+r['width']+5,r['y']+r['height']/2);await page.wait_for_timeout(650);report['cardSurvivesRowToCardGap']=await card.count()>0
   if await card.count():
    await card.get_by_role('button',name='Open chat',exact=True).click();report['chatCardActionReachable']=await page.evaluate("fixture.state().active==='c2'")
  await page.mouse.move(1000,850);await page.wait_for_timeout(500);await first.hover();options=page.get_by_role('button',name='Options for project Reading room',exact=True);newchat=page.get_by_role('button',name='New chat in Reading room',exact=True);report['projectOptionsBeforeNewChat']=(await options.bounding_box())['x']<(await newchat.bounding_box())['x'];report['recentsOptionsBeforeNewChat']=(await page.get_by_role('button',name='Recent chat organization',exact=True).bounding_box())['x']<(await page.get_by_role('button',name='New chat from Recents',exact=True).bounding_box())['x']
  report['pageErrors']=errors;print(json.dumps(report,indent=2));(OUT/'regressions-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8');await browser.close()
  assert report['createCallsForOneSubmission']==1 and report['simultaneousHoverCards']<=1 and report['projectNameToggles'] and report['draftHeaderFolderIcons']==0 and report.get('cardSurvivesRowToCardGap') and report.get('chatCardActionReachable') and report.get('sameChatInTwoSectionsHasOneCard') and report.get('projectOptionsBeforeNewChat') and report.get('recentsOptionsBeforeNewChat'),report
asyncio.run(run())
