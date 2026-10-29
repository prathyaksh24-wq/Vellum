// Explicit live-site QA. Requires the disposable browser_live_server fixture.
// Never point this script at the user's backend or browser profile.
import {mkdirSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const {chromium} = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE_PATH).href);
const output = resolve(process.env.BROWSER_QA_OUTPUT || '.test-data/browser-public-sites');
mkdirSync(output,{recursive:true});
const backend = 'http://127.0.0.1:8020';
const browser = await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE,args:['--mute-audio']});
const page = await browser.newPage({viewport:{width:1536,height:1024}});
const results = [];
const safeUrl = value => {
  const url = new URL(value);
  for (const key of ['jsc_token','solution','jsc_orig_r']) url.searchParams.delete(key);
  return url.href;
};
const detail = async () => {
  const response = await fetch(backend+'/fixture/site-details');
  if (!response.ok) throw new Error('Public-page inspection failed: '+response.status);
  return response.json();
};
const wait = async predicate => {
  const deadline = Date.now()+10000;
  while(Date.now()<deadline) {if(await predicate()) return; await new Promise(r=>setTimeout(r,100));}
  throw new Error('Browser state did not settle.');
};
try {
  await page.goto('http://127.0.0.1:5180/design-uploads/Vellum%20Default%20Re-designed.html?conversation_id=browser-fixture&backend='+encodeURIComponent(backend));
  await page.locator('.sidebar').getByRole('button',{name:'Browser',exact:true}).click();
  const panel = page.getByRole('complementary',{name:'Vellum browser'});
  await panel.waitFor();
  const address = panel.getByRole('textbox',{name:'Browser address'});
  await wait(async()=> (await (await fetch(backend+'/api/browser/status')).json()).running);
  await panel.getByRole('button',{name:'Home',exact:true}).click();
  await panel.locator('.browser-home').waitFor();
  for (const [name,input,url,query] of [
    ['google','google','https://www.google.com/',''],
    ['wikipedia','https://en.wikipedia.org/wiki/Main_Page','https://en.wikipedia.org/wiki/Main_Page','Brave browser'],
    ['youtube','youtube','https://www.youtube.com/','Brave browser'],
    ['reddit','reddit','https://www.reddit.com/',''],
    ['spotify','spotify','https://open.spotify.com/','Brave browser'],
    ['x','x','https://x.com/',''],
  ]) {
    const result = {name,requestedInput:input,requestedUrl:url};
    try {
      const navigation = page.waitForResponse(response => response.url().endsWith('/api/app-actions/dispatch') && response.request().postDataJSON()?.request?.arguments?.operation==='navigate', {timeout:35000});
      const started = Date.now();
      await address.fill(input); await address.press('Enter');
      const response = await navigation;
      const dispatchedUrl = response.request().postDataJSON().request.arguments.url;
      if (dispatchedUrl !== url) throw new Error('Address took a search detour: '+dispatchedUrl);
      const receipt = await response.json();
      result.navigationMs = Date.now()-started;
      if(receipt.status!=='applied') result.navigationError = receipt.message;
      await page.waitForTimeout(2200);
      const observed = await detail();
      result.title=observed.title; result.finalUrl=safeUrl(observed.url); result.publicText=observed.text;
      result.visibleInputs=observed.fields.filter(field=>field.box.width>0 && field.box.height>0).map(field=>field.name);
      result.visibleLinks=observed.links.length;
      result.blocked=/blocked|access (?:to .* )?(?:was )?denied|HTTP ERROR 403|verify you are human|unusual traffic|something went wrong|too many requests|unsupported browser/i.test(observed.text);
      if(query && !result.blocked && !result.navigationError) {
        const clickBox = async box => {
          const rect = await panel.locator('.browser-screen').boundingBox();
          const frame = await (await fetch(backend+'/api/browser/frame')).json();
          const scale = Math.min(rect.width/frame.width,rect.height/frame.height);
          await page.mouse.click(rect.x+(rect.width-frame.width*scale)/2+(box.x+box.width/2)*scale,
            rect.y+(rect.height-frame.height*scale)/2+(box.y+box.height/2)*scale);
        };
        let current = observed;
        let field = current.fields.find(field=>/search|what do you want to play/i.test(field.name) && field.box.width>20 && field.box.height>10);
        if (!field) {
          const searchLink = current.links.find(link=>link.text.trim()==='Search' && link.box.width>0);
          if(searchLink) {await clickBox(searchLink.box); await page.waitForTimeout(1500); current=await detail();
            field=current.fields.find(field=>/search/i.test(field.name) && field.box.width>20 && field.box.height>10);}
        }
        if(field) {
          await clickBox(field.box);
          await page.keyboard.type(query);
          await page.keyboard.press('Enter');
          await page.waitForTimeout(3000);
          const searched=await detail();
          result.search={query,title:searched.title,url:safeUrl(searched.url),publicText:searched.text.slice(0,900)};
        } else result.search='No visible search field on the initial page';
      }
      await page.screenshot({path:resolve(output,name+'.png'),fullPage:true});
    } catch(error) {result.error=error.message;}
    results.push(result);
    console.log(JSON.stringify({...result,publicText:result.publicText?.slice(0,550),search:typeof result.search==='object'?{title:result.search.title,url:result.search.url}:result.search}));
  }
  const newTab = page.waitForResponse(response => response.url().endsWith('/api/app-actions/dispatch') && response.request().postDataJSON()?.request?.arguments?.operation==='new_tab', {timeout:35000});
  await panel.getByRole('button',{name:'New tab',exact:true}).click();
  const newTabReceipt = await (await newTab).json();
  const newHome = await detail();
  if (newTabReceipt.status !== 'applied' || new URL(newHome.url).hostname !== 'www.google.com' || new URL(newHome.url).pathname !== '/') throw new Error('New tab did not open the Google homepage.');
  if (results.some(result=>result.error)) throw new Error('Public-site checks failed.');
  await panel.getByRole('button',{name:'Close session',exact:true}).click();
  await wait(async()=> !(await (await fetch(backend+'/api/browser/status')).json()).running);
  writeFileSync(resolve(output,'public-sites.json'),JSON.stringify(results,null,2));
} finally {await browser.close();}
