// Explicit, muted QA against the disposable browser_live_server fixture only.
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const {chromium} = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE_PATH).href);
const output = resolve('../.impeccable/review');
await mkdir(output,{recursive:true});
const backend = 'http://127.0.0.1:8020';
const browser = await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE,args:['--mute-audio']});
const page = await browser.newPage({viewport:{width:1586,height:992}});
const errors=[],results={};
const capture = async name => {
  // Playwright scrolls overflow-hidden ancestors to reach menu items. Restore
  // the document origin so captures represent the user-visible app viewport.
  await page.evaluate(()=> {
    window.scrollTo(0,0);
    for(let element=document.querySelector('.browser-home') || document.querySelector('.browser-panel');element;element=element.parentElement) {
      element.scrollTop=0;element.scrollLeft=0;
    }
  });
  await page.screenshot({path:resolve(output,name+'.png'),animations:'disabled'});
};
page.on('pageerror',error=>errors.push(error.message));
const status = async()=> (await fetch(backend+'/api/browser/status')).json();
const wait = async predicate => {
  const deadline=Date.now()+15000;
  while(Date.now()<deadline){if(await predicate())return;await new Promise(r=>setTimeout(r,80));}
  throw new Error('Browser QA condition did not settle.');
};
try {
  await page.goto('http://127.0.0.1:5180/design-uploads/Vellum%20Default%20Re-designed.html?conversation_id=browser-fixture&backend='+encodeURIComponent(backend));
  const expandSidebar=page.getByRole('button',{name:/Expand sidebar/});
  if(await expandSidebar.count()) await expandSidebar.click();
  await page.locator('.sidebar').getByRole('button',{name:'Browser',exact:true}).click();
  const panel=page.getByRole('complementary',{name:'Vellum browser'});
  await panel.waitFor();
  await wait(async()=> (await status()).running);
  // The isolated Brave profile restores tabs, including sites from earlier runs.
  await panel.getByRole('button',{name:'Home',exact:true}).click();
  await wait(async()=> (await status()).tabs.find(t=>t.active)?.url==='about:blank');
  await panel.locator('.browser-home').waitFor();
  assert.equal((await status()).tabs.find(t=>t.active).url,'about:blank');
  // The disposable preference record may survive a previous QA attempt.
  await page.evaluate(async()=>{
    await window.VellumApi.browser.control({operation:'preferences',search_engine:'google',searxng_url:'',shortcuts:window.VellumApi.browser.defaultPreferences.shortcuts});
  });
  await wait(async()=>panel.locator('.browser-home[data-engine="google"]').isVisible());
  const googleTitle=await panel.locator('.browser-home-title').boundingBox();
  // Regression: the unset SearXNG form lifts the title near the top edge.
  await panel.getByRole('button',{name:'Choose search engine'}).click();
  await panel.getByRole('menuitemradio',{name:'SearXNG',exact:true}).click();
  await panel.locator('.browser-home[data-engine="searxng"]').waitFor();
  assert.equal(await panel.locator('.browser-home-edit').count(),0,'Engine selection unexpectedly opens setup');
  await capture('searxng-unconfigured');
  const searxngTitle=await panel.locator('.browser-home-title').boundingBox();
  assert(Math.abs(searxngTitle.y-googleTitle.y)<2,'SearXNG title is not aligned with other engines: '+JSON.stringify({googleTitle,searxngTitle}));
  results.engineTitleAligned=true;
  await panel.getByRole('button',{name:'Choose search engine'}).click();
  await panel.getByRole('menuitem',{name:'SearXNG instance',exact:true}).click();
  await panel.getByLabel('SearXNG instance').waitFor();
  await panel.getByRole('button',{name:'Choose search engine'}).click();
  await capture('searxng-setup-menu');
  const setupMenu=await panel.locator('.browser-engine-menu').boundingBox();
  const setupHome=await panel.locator('.browser-home').boundingBox();
  assert(setupMenu.y>=setupHome.y && setupMenu.y+setupMenu.height<=setupHome.y+setupHome.height,'First-use engine menu is clipped by the homepage');
  results.setupMenuViewports=[];
  for(const viewport of [{width:1920,height:1200},{width:1200,height:800},{width:390,height:844}]) {
    await page.setViewportSize(viewport);
    await wait(async()=> {
      const menu=await panel.locator('.browser-engine-menu').boundingBox();
      const home=await panel.locator('.browser-home').boundingBox();
      return menu.x>=home.x && menu.y>=home.y && menu.x+menu.width<=home.x+home.width && menu.y+menu.height<=home.y+home.height;
    });
    await capture('searxng-setup-menu-'+viewport.width);
    assert(await panel.locator('.browser-engine-menu').evaluate(menu=> [...menu.querySelectorAll('button')].every(button=> {
      const rect=button.getBoundingClientRect();
      return button.contains(document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2));
    })),'Homepage controls intercept engine menu clicks');
    results.setupMenuViewports.push(viewport);
  }
  await page.setViewportSize({width:1586,height:992});
  results.setupMenuContained=true;
  await panel.getByRole('menuitemradio',{name:'Google',exact:true}).click();
  await wait(async()=>panel.locator('.browser-home[data-engine="google"]').isVisible());
  const address=panel.getByRole('textbox',{name:'Browser address'});
  for(const [id,name] of [['google','Google'],['brave','Brave'],['duckduckgo','DuckDuckGo'],['startpage','Startpage'],['searxng','SearXNG']]) {
    if(id!=='google'){
      await panel.getByRole('button',{name:'Choose search engine'}).click();
      await panel.getByRole('menuitemradio',{name,exact:true}).click();
    }
    await wait(async()=> (await status()).preferences.search_engine===id);
    const home=panel.locator('.browser-home[data-engine="'+id+'"]');
    await home.waitFor();
    if(id==='searxng') {
      await home.getByRole('button',{name:'Choose search engine'}).click();
      await home.getByRole('menuitem',{name:'SearXNG instance',exact:true}).click();
      await home.getByLabel('SearXNG instance').fill('http://127.0.0.1:8020');
      await home.getByRole('button',{name:'Use instance'}).click();
      await wait(async()=> !!(await status()).preferences.searxng_url);
      await home.getByRole('button',{name:'Choose search engine'}).click();
    }
    await home.evaluate(async el=>{
      const src=getComputedStyle(el).backgroundImage.slice(5,-2);
      const img=new Image(); img.src=src; await img.decode();
      await Promise.all([...el.querySelectorAll('img')].map(image=>image.decode()));
      for(const element of el.querySelectorAll('.browser-brand-icon')) {
        const mask=getComputedStyle(element).maskImage;
        if(mask.startsWith('url(')) {
          const resource=await fetch(mask.slice(5,-2));
          if(!resource.ok) throw new Error('Brand icon failed to load');
        }
      }
    });
    await capture(id);
    const metrics=await home.evaluate(el=>({width:el.clientWidth,height:el.clientHeight,overflow:el.scrollWidth>el.clientWidth,engine:el.dataset.engine}));
    assert(!metrics.overflow,'Homepage has horizontal overflow');
    results[id]=metrics;
    if(id==='searxng') await page.keyboard.press('Escape');
  }
  const search=panel.getByRole('textbox',{name:'Search with SearXNG'});
  await search.fill('browser tools');
  const searchAction=page.waitForRequest(r=>r.url().endsWith('/api/app-actions/dispatch')&&r.postDataJSON()?.request?.arguments?.operation==='navigate');
  await search.press('Enter');
  assert.equal((await searchAction).postDataJSON().request.arguments.url,backend+'/search?q=browser%20tools');
  await wait(async()=> (await status()).tabs.find(t=>t.active).url===backend+'/search?q=browser%20tools');
  await wait(async()=> !(await panel.locator('.browser-home').count()));
  await panel.getByRole('button',{name:'Home',exact:true}).click();
  await wait(async()=> (await status()).tabs.find(t=>t.active).url==='about:blank');
  await panel.locator('.browser-home').waitFor();
  await panel.getByRole('button',{name:'Add shortcut',exact:true}).click();
  await panel.getByLabel('Shortcut name').fill('Test page');
  await panel.getByLabel('Website',{exact:true}).fill(backend+'/fixture/page');
  await panel.getByRole('button',{name:'Save shortcut'}).click();
  await wait(async()=> (await status()).preferences.shortcuts.some(s=>s.name==='Test page'));
  await panel.getByRole('button',{name:'Test page',exact:true}).click();
  await panel.getByAltText('Live view of the dedicated browser tab').waitFor();
  await wait(async()=> (await status()).tabs.find(t=>t.active).url===backend+'/fixture/page');
  await wait(async()=> {
    const rect=await panel.locator('.browser-screen').boundingBox(),state=await status();
    return Math.abs(rect.width/rect.height-state.viewport_width/state.viewport_height)<.008;
  });
  const details=await (await fetch(backend+'/fixture/details')).json();
  const frame=await (await fetch(backend+'/api/browser/frame')).json();
  const box=await panel.locator('.browser-screen').boundingBox();
  const scale=Math.min(box.width/frame.width,box.height/frame.height);
  await page.mouse.click(box.x+(box.width-frame.width*scale)/2+(details.box.x+details.box.width/2)*scale,
    box.y+(box.height-frame.height*scale)/2+(details.box.y+details.box.height/2)*scale);
  await page.keyboard.type('smooth input');
  await wait(async()=> (await (await fetch(backend+'/fixture/details')).json()).value==='smooth input');
  results.liveInput=true;
  const count=(await status()).tabs.length,started=Date.now();
  for(let i=0;i<3;i++)await panel.getByRole('button',{name:'New tab',exact:true}).click();
  assert(await address.evaluate(el=>el===document.activeElement));
  await wait(async()=> (await status()).tabs.length===count+3);
  results.threeTabsMs=Date.now()-started;
  assert(results.threeTabsMs<4000,'Blank tabs waited for network loads');
  await panel.getByRole('button',{name:'Expand browser',exact:true}).click();
  assert.equal(await page.locator('.body>.main').isVisible(),false);
  const expanded=await panel.boundingBox();
  assert(expanded.x<260 && expanded.width>1250,'Expanded panel leaves a chat strip');
  await capture('expanded');
  await panel.getByRole('button',{name:'Restore split view',exact:true}).click();
  assert(await page.locator('.body>.main').isVisible());
  await panel.getByRole('textbox',{name:'Browser address'}).press('Alt+w');
  await wait(async()=> (await status()).tabs.length===count+2);
  await page.keyboard.press('Escape');assert(await panel.isVisible());
  results.shortcuts=true;results.expansion=true;results.escape=true;
  await panel.getByRole('button',{name:'Home',exact:true}).click();
  await wait(async()=> (await status()).tabs.find(t=>t.active).url==='about:blank');
  await panel.locator('.browser-home').waitFor();
  await page.setViewportSize({width:390,height:844});
  await capture('mobile');
  const mobile=await panel.locator('.browser-home').evaluate(el=>({width:el.clientWidth,scroll:el.scrollWidth}));
  assert(mobile.scroll<=mobile.width,'Mobile homepage clips horizontally');
  const mobilePanel=await panel.boundingBox();
  assert(mobilePanel.x>=0 && mobilePanel.x+mobilePanel.width<=390,'Mobile panel is outside the viewport');
  results.mobile={...mobile,panel:mobilePanel};
  await page.setViewportSize({width:1920,height:1200});
  await capture('user-1920');
  assert.deepEqual(errors,[],'Frontend emitted runtime errors');
  results.pageErrors=errors;results.passed=true;
  await writeFile(resolve(output,'browser-home-results.json'),JSON.stringify(results,null,2));
  console.log(JSON.stringify(results));
} finally {
  await fetch(backend+'/api/app-actions/dispatch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request:{action_id:'browser.session.control',action_version:'1',arguments:{operation:'close'}},context:{source:'ui'}})}).catch(()=>{});
  await browser.close();
}
