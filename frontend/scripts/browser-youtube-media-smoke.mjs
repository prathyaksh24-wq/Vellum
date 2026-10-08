// Public video only, using the disposable QA API/profile. No account sign-in.
import {mkdir,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE_PATH).href);
const backend='http://127.0.0.1:8020';
const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE});
const page=await browser.newPage({viewport:{width:1536,height:1024}});
const media=async()=> (await fetch(backend+'/fixture/media-details')).json();
let captionsVisible=false,playbackFailed=false,maxVideoTime=0,fullscreenSeen=false;
try {
  await page.goto('http://127.0.0.1:5180/design-uploads/Vellum%20Default%20Re-designed.html?conversation_id=browser-fixture&backend='+encodeURIComponent(backend));
  await page.locator('.sidebar').getByRole('button',{name:'Browser',exact:true}).click();
  const panel=page.getByRole('complementary',{name:'Vellum browser'});
  await panel.waitFor();
  const response=page.waitForResponse(r=>r.url().endsWith('/api/app-actions/dispatch')&&r.request().postDataJSON()?.request?.arguments?.operation==='navigate');
  await panel.getByRole('textbox',{name:'Browser address'}).fill('https://www.youtube.com/watch?v=iG9CE55wbtY');
  await panel.getByRole('textbox',{name:'Browser address'}).press('Enter');
  await response;
  await page.waitForTimeout(4000);
  let details=await media();
  const clickBox=async box=> {
    const rect=await panel.locator('.browser-screen').boundingBox();
    const frame=await (await fetch(backend+'/api/browser/frame')).json();
    const scale=Math.min(rect.width/frame.width,rect.height/frame.height);
    await page.mouse.click(rect.x+(rect.width-frame.width*scale)/2+(box.x+box.width/2)*scale,
      rect.y+(rect.height-frame.height*scale)/2+(box.y+box.height/2)*scale);
    await page.waitForTimeout(1000);
  };
  if(details.media?.paused){const play=details.controls.find(c=>c.selector==='.ytp-play-button');if(play?.box)await clickBox(play.box);}
  details=await media();
  const cc=details.controls.find(c=>c.selector==='.ytp-subtitles-button');
  if(cc?.box?.width && cc.pressed!=='true')await clickBox(cc.box);
  for(let i=0;i<4;i++) {
    await page.waitForTimeout(i?30000:2000);
    const next=await media();
    captionsVisible ||= !!next.captionText;
    playbackFailed ||= !!next.playerError || !next.media;
    maxVideoTime=Math.max(maxVideoTime,next.media?.time||0);
    console.log(JSON.stringify({elapsed:i*30,details:next}));
    if(next.playerError || !next.media)break;
    if(next.captionText) {
      const frame=await (await fetch(backend+'/api/browser/frame')).json();
      await mkdir('../.test-data/browser-input-qa',{recursive:true});
      await writeFile('../.test-data/browser-input-qa/youtube-captions.jpg',Buffer.from(frame.data_url.split(',')[1],'base64'));
    }
    fullscreenSeen ||= next.fullscreen;
    if(i===1){
      const fullscreen=next.controls.find(c=>c.selector==='.ytp-fullscreen-button');
      if(fullscreen?.box?.width)await clickBox(fullscreen.box);
    }
  }
  await panel.locator('.browser-screen').press('Escape');
  await page.waitForTimeout(1000);
  const exited=!(await media()).fullscreen && await panel.isVisible();
  const passed=captionsVisible && !playbackFailed && maxVideoTime>=70 && fullscreenSeen && exited;
  console.log(JSON.stringify({passed,captionsVisible,playbackFailed,maxVideoTime,fullscreenSeen,escapeKeptPanel:exited}));
  if(!passed)process.exitCode=1;
} finally {
  await fetch(backend+'/api/app-actions/dispatch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request:{action_id:'browser.session.control',action_version:'1',arguments:{operation:'close'}},context:{source:'ui'}})});
  await browser.close();
}
