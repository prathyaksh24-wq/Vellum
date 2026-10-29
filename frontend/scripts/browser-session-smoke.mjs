// Uses backend/tests/browser_live_server.py; never point at the user's backend.
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const {chromium} = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE_PATH).href);
const output = resolve(process.env.BROWSER_QA_OUTPUT || '.impeccable/review');
mkdirSync(output,{recursive:true});
const backend = 'http://127.0.0.1:8020';
const browser = await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE});
const context = await browser.newContext({viewport:{width:1536,height:1024},ignoreHTTPSErrors:true});
const page = await context.newPage(), errors = [], actions = [], frameTimes = [];
page.on('websocket', socket => {
  if (socket.url().includes('/api/browser/stream')) socket.on('framereceived', () => frameTimes.push(Date.now()));
});
let releaseInitialStatus;
const initialStatusGate = new Promise(resolve => { releaseInitialStatus = resolve; });
let initialStatusHeld = false;
await page.route('**/api/browser/status', async route => {
  if (!initialStatusHeld) {
    initialStatusHeld = true;
    await initialStatusGate;
  }
  await route.continue();
});
page.on('pageerror',error=>errors.push(error.message));
page.on('request',request=> {
  if (request.url().endsWith('/api/app-actions/dispatch')) {
    const body=request.postDataJSON();
    if(body.request?.action_id==='browser.session.control') actions.push(body.request.arguments);
  }
});
const status = async () => (await fetch(backend+'/api/browser/status')).json();
const wait = async predicate => {
  const until = Date.now()+20000;
  while (Date.now()<until) { if (await predicate()) return; await new Promise(resolve=>setTimeout(resolve,100)); }
  throw new Error('Fixture condition timed out.');
};
try {
  await page.goto('http://127.0.0.1:5180/design-uploads/Vellum%20Default%20Re-designed.html?conversation_id=browser-fixture&backend='+encodeURIComponent(backend));
  const sidebar=page.locator('.sidebar');
  await sidebar.getByRole('button',{name:'Browser',exact:true}).waitFor({timeout:30000});
  // One click must launch even while the initial readiness response is pending.
  await sidebar.getByRole('button',{name:'Browser',exact:true}).click();
  await wait(async () => (await status()).running);
  releaseInitialStatus();
  assert.equal(await sidebar.getByRole('button',{name:'Scheduled',exact:true}).count(),0);
  await sidebar.getByRole('button',{name:'More',exact:true}).click();
  await sidebar.getByRole('button',{name:'Scheduled',exact:true}).waitFor();
  for (const label of ['Observability','Memory','Plugins','Archive']) assert(await sidebar.getByRole('button',{name:label,exact:true}).isVisible());
  await sidebar.getByRole('button',{name:'More',exact:true}).click();
  await sidebar.getByRole('button',{name:'Browser',exact:true}).click();
  const panel=page.getByRole('complementary',{name:'Vellum browser'});
  await panel.waitFor();
  await panel.getByRole('button',{name:'Browser menu',exact:true}).click();
  await panel.getByRole('button',{name:'Close session',exact:true}).click();
  await wait(async()=> !(await status()).running);
  const rejectLaunch = route => {
    const body = route.request().postDataJSON();
    if (body.request?.action_id === 'browser.session.control' && body.request.arguments.operation === 'open') {
      return route.fulfill({json:{status:'failed',message:'Browser launch rejected for regression.'}});
    }
    return route.continue();
  };
  await page.route('**/api/app-actions/dispatch', rejectLaunch);
  await sidebar.getByRole('button',{name:'Browser',exact:true}).click();
  await page.getByText('Browser launch rejected for regression.',{exact:true}).waitFor();
  assert.deepEqual(errors,[]);
  await page.unroute('**/api/app-actions/dispatch', rejectLaunch);
  await sidebar.getByRole('button',{name:'Browser',exact:true}).click();
  await wait(async()=> (await status()).running);
  const address=panel.getByRole('textbox',{name:'Browser address'});
  await address.fill(backend+'/fixture/page'); await address.press('Enter');
  await panel.getByAltText('Live view of the dedicated browser tab').waitFor();
  await wait(async()=> (await status()).control==='user');
  await page.waitForTimeout(1500); // Display the post-navigation frame before mapping input.
  const details=await (await fetch(backend+'/fixture/details')).json();
  const screen=panel.getByRole('region',{name:/Browser page/});
  const rect=await screen.boundingBox(), frame=await (await fetch(backend+'/api/browser/frame')).json();
  const scale=Math.min(rect.width/frame.width,rect.height/frame.height);
  const x=rect.x+(rect.width-frame.width*scale)/2+(details.box.x+30)*scale;
  const y=rect.y+(rect.height-frame.height*scale)/2+(details.box.y+20)*scale;
  await page.mouse.click(x,y);
  const typingStarted = Date.now();
  const typingActionsBefore = actions.filter(action=>action.operation==='type').length;
  await page.keyboard.type('Hello Brave');
  try {
    await wait(async()=> (await (await fetch(backend+'/fixture/details')).json()).value==='Hello Brave');
  } catch (error) {
    console.log(JSON.stringify({details:await (await fetch(backend+'/fixture/details')).json(),focused:await page.evaluate(()=>document.activeElement.outerHTML.slice(0,300)),alerts:await panel.getByRole('alert').allTextContents(),rect,frameId:frame.frame_id}));
    throw error;
  }
  const typingLatencyMs = Date.now() - typingStarted;
  const typingRequests = actions.filter(action=>action.operation==='type').length - typingActionsBefore;
  assert(typingRequests < 'Hello Brave'.length, 'Rapid typing still sends a separate request for every character');
  await panel.getByRole('button',{name:'Resume agent',exact:true}).click();
  await wait(async()=> (await status()).control==='agent');
  await page.mouse.click(x,y);
  await wait(async()=> (await status()).control==='user');
  assert.equal((await (await fetch(backend+'/fixture/details')).json()).value,'Hello Brave');
  await panel.getByRole('button',{name:'Resume agent',exact:true}).click();
  await wait(async()=> (await status()).control==='agent');
  await panel.getByRole('button',{name:'Pause',exact:true}).click();
  await wait(async()=> (await status()).control==='paused');
  await panel.getByRole('button',{name:'Resume agent',exact:true}).click();
  const before=(await status()).tabs.length;
  await panel.getByRole('button',{name:'New tab',exact:true}).click();
  await wait(async()=> (await status()).tabs.length===before+1);
  await wait(async()=> (await status()).tabs.some(tab=>tab.active && tab.url==='https://www.google.com/'));
  await panel.locator('.browser-tab.active').getByRole('button',{name:/^Close /}).click();
  await wait(async()=> (await status()).tabs.length===before);
  const downloadsBefore=(await status()).downloads.map(file=>file.id);
  await address.fill(backend+'/fixture/download'); await address.press('Enter');
  await wait(async()=> (await status()).downloads.some(file=>!downloadsBefore.includes(file.id)&&file.name==='browser-test.txt'&&file.state==='saved'));
  await panel.getByRole('button',{name:'Downloads',exact:true}).click();
  await panel.getByText('browser-test.txt',{exact:true}).first().waitFor();
  await panel.getByRole('button',{name:'Close downloads',exact:true}).click();
  await address.fill(backend+'/fixture/page'); await address.press('Enter');
  await wait(async()=> (await status()).tabs.some(tab=>tab.active && tab.url===backend+'/fixture/page'));
  await page.waitForTimeout(1600);
  await panel.getByRole('button',{name:'Resume agent',exact:true}).click();
  for (const [name,width,height] of [['user-1536',1536,1024],['desktop',1440,1000],['mobile',390,844]]) {
    await page.setViewportSize({width,height}); await page.waitForTimeout(900);
    await page.evaluate(()=> {window.scrollTo(0,0);document.querySelector('.win').scrollTo(0,0);});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),`${name} overflows`);
    const bounds=await panel.boundingBox();
    assert(bounds.x>=0 && bounds.y>=0 && bounds.x+bounds.width<=width+1,`${name} panel is clipped`);
    await panel.getByAltText('Live view of the dedicated browser tab').waitFor();
    const screenBounds = await panel.locator('.browser-screen').boundingBox();
    await wait(async()=> {
      const currentFrame = await (await fetch(backend+'/api/browser/frame')).json();
      return Math.abs(currentFrame.width/currentFrame.height - screenBounds.width/screenBounds.height) < .005;
    });
    await page.screenshot({path:resolve(output,name+'.png'),fullPage:true});
  }
  await address.fill(backend+'/fixture/animation'); await address.press('Enter');
  await wait(async()=> (await status()).tabs.some(tab=>tab.active && tab.url===backend+'/fixture/animation'));
  await page.waitForTimeout(800);
  const framesBefore = frameTimes.length, animationStarted = Date.now();
  await page.waitForTimeout(2000);
  const liveFramesPerSecond = (frameTimes.length - framesBefore) / ((Date.now()-animationStarted)/1000);
  assert(liveFramesPerSecond >= 5, `Live animation updates too slowly: ${liveFramesPerSecond} fps`);
  await panel.getByRole('button',{name:'Browser menu',exact:true}).click();
  await panel.getByRole('button',{name:'Close session',exact:true}).click();
  await wait(async()=> !(await status()).running);
  await panel.getByRole('button',{name:'Open browser',exact:true}).click();
  await wait(async()=> (await status()).running);
  await panel.getByRole('button',{name:'Browser menu',exact:true}).click();
  await panel.getByRole('button',{name:'Close session',exact:true}).click();
  await wait(async()=> !(await status()).running);
  assert.deepEqual(errors,[]);
  assert(frameTimes.length>0, 'Live frame stream never connected');
  const report={passed:true,typingLatencyMs,typingRequests,liveFrames:frameTimes.length,liveFramesPerSecond,checks:['sidebar launch before initial readiness response','visible rejected-launch message','real separate Brave launch','More disclosure','scaled manual click and batched keyboard input','click automatically takes ownership','live frame stream','adaptive viewport without letterboxing','pause/resume','tabs','download saving','close/reopen','desktop/mobile overflow','no page errors'],screenshots:['user-1536.png','desktop.png','mobile.png']};
  writeFileSync(resolve(output,'browser-smoke.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
} catch (error) {
  console.log(JSON.stringify({actions,state:await status(),alerts:await page.getByRole('alert').allTextContents()}));
  throw error;
} finally { releaseInitialStatus(); await browser.close(); }
