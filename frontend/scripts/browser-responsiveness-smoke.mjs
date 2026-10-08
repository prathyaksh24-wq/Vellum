// Disposable fixture only: browser input, slow tabs and local video fullscreen.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {mkdir,writeFile} from 'node:fs/promises';
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE_PATH).href);
const backend='http://127.0.0.1:8020';
const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE,args:['--mute-audio']});
const page=await browser.newPage({viewport:{width:1536,height:1024}});
const state=async()=> (await fetch(backend+'/api/browser/status')).json();
const wait=async fn=> {const end=Date.now()+20000;while(Date.now()<end){if(await fn())return;await new Promise(r=>setTimeout(r,40));}throw new Error('Condition timed out');};
try {
  await page.route('**/api/app-actions/dispatch',route=> {
    const body=route.request().postDataJSON();
    if(body.request?.action_id==='browser.session.control' && body.request.arguments.operation==='new_tab') {
      body.request.arguments.url=backend+'/fixture/slow';
      return route.continue({postData:JSON.stringify(body)});
    }
    return route.continue();
  });
  await page.goto('http://127.0.0.1:5180/design-uploads/Vellum%20Default%20Re-designed.html?conversation_id=browser-fixture&backend='+encodeURIComponent(backend));
  const opened=page.waitForResponse(r=>r.url().endsWith('/api/app-actions/dispatch')&&r.request().postDataJSON()?.request?.arguments?.operation==='open');
  await page.locator('.sidebar').getByRole('button',{name:'Browser',exact:true}).click();
  await opened;
  const panel=page.getByRole('complementary',{name:'Vellum browser'});
  await panel.waitFor();
  await panel.getByRole('button',{name:'Home',exact:true}).click();
  await panel.locator('.browser-home').waitFor();
  await page.waitForTimeout(500);
  const address=panel.getByRole('textbox',{name:'Browser address'});
  const before=(await state()).tabs.length;
  const started=Date.now();
  for(let i=0;i<3;i++)await panel.getByRole('button',{name:'New tab',exact:true}).click();
  const addressFocused=await address.evaluate(el=>el===document.activeElement);
  await wait(async()=> (await state()).tabs.length===before+3);
  const threeTabsMs=Date.now()-started;
  console.log(JSON.stringify({threeTabsMs,addressFocused,delayedHomeMs:4000}));
  assert(threeTabsMs<6000,'Three tab creations waited for serialized slow homepage loads');
  assert(addressFocused,'New tab did not immediately focus the address');
  await address.fill(backend+'/fixture/video');await address.press('Enter');
  await wait(async()=> (await state()).tabs.some(tab=>tab.active && tab.url===backend+'/fixture/video'));
  await page.waitForTimeout(600);
  const media=async()=> (await fetch(backend+'/fixture/media-details')).json();
  await wait(async()=> (await media()).media?.time>0);
  await wait(async()=> {
    const rect=await panel.locator('.browser-screen').boundingBox();
    const frame=await (await fetch(backend+'/api/browser/frame')).json();
    return Math.abs(rect.width/rect.height-frame.width/frame.height)<.005;
  });
  await page.waitForTimeout(400);
  const frame=await (await fetch(backend+'/api/browser/frame')).json();
  const details=await media(),rect=await panel.locator('.browser-screen').boundingBox();
  await mkdir('../.test-data/browser-input-qa',{recursive:true});
  await writeFile('../.test-data/browser-input-qa/normal-caption.jpg',Buffer.from(frame.data_url.split(',')[1],'base64'));
  const scale=Math.min(rect.width/frame.width,rect.height/frame.height),box=details.box;
  await page.mouse.click(rect.x+(rect.width-frame.width*scale)/2+(box.x+box.width/2)*scale,
    rect.y+(rect.height-frame.height*scale)/2+(box.y+box.height/2)*scale);
  await page.waitForTimeout(500);
  console.log(JSON.stringify({clickedFullscreen:await media(),panelError:await panel.locator('.browser-error').allTextContents()}));
  await wait(async()=> (await media()).fullscreen);
  await page.waitForTimeout(500);
  const fullscreenFrame=await (await fetch(backend+'/api/browser/frame')).json();
  await mkdir('../.test-data/browser-input-qa',{recursive:true});
  await writeFile('../.test-data/browser-input-qa/fullscreen-caption.jpg',Buffer.from(fullscreenFrame.data_url.split(',')[1],'base64'));
  console.log(JSON.stringify({fullscreenMedia:await media()}));
  await page.keyboard.press('Escape');
  await wait(async()=> !(await media()).fullscreen);
  assert(await panel.isVisible(),'Escape hid the entire browser panel');
  const videoStart=(await media()).media.time;
  await page.waitForTimeout(2000);
  assert((await media()).media.time>videoStart,'Video stopped after exiting fullscreen');
  await page.keyboard.press('Alt+l');
  assert(await address.evaluate(el=>el===document.activeElement),'Alt+L did not focus address');
  const count=(await state()).tabs.length;
  await page.keyboard.press('Alt+w');
  await wait(async()=> (await state()).tabs.length===count-1);
  assert(!page.isClosed(),'Panel shortcut closed the host tab');
  await page.getByRole('button',{name:'Sources',exact:true}).click();
  await page.locator('.activity-panel').waitFor();
  assert(!(await panel.isVisible()),'Sources reopened the Browser instead of showing activity');
  assert(await page.locator('.activity-panel .act-source').count()>0,'Sources drawer is empty');
  assert((await state()).running,'Opening Sources closed the dedicated session');
  console.log(JSON.stringify({passed:true,threeTabsMs,addressFocused,fullscreenEscape:true,localVideoContinues:true,altShortcuts:true,sourcesDrawer:true}));
} finally {
  await fetch(backend+'/api/app-actions/dispatch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request:{action_id:'browser.session.control',action_version:'1',arguments:{operation:'close'}},context:{source:'ui'}})});
  await browser.close();
}
