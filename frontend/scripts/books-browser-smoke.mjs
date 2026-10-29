// Run against backend/tests/books_library_live_server.py, never a real profile.
import assert from 'node:assert/strict';
import {mkdirSync, writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const modulePath = process.env.PLAYWRIGHT_MODULE_PATH;
const {chromium} = await import(modulePath ? pathToFileURL(modulePath).href : 'playwright');
const out = resolve(process.env.BOOKS_QA_OUTPUT || 'books-qa-output');
mkdirSync(out, {recursive:true});
const browser = await chromium.launch({headless:true, executablePath:process.env.BROWSER_EXECUTABLE,
  args:['--enable-unsafe-swiftshader']});
const page = await browser.newPage();
const errors = [], requests = [];
page.on('pageerror', error => errors.push(error.message));
page.on('request', request => { if(request.url().includes('/books/library') || request.url().includes('/chat')) requests.push({url:request.url(), method:request.method()}); });
const url = process.env.BOOKS_QA_URL || 'http://127.0.0.1:5175/design-uploads/Vellum%20Default%20Re-designed.html?view=agent&agent=books&backend=http%3A%2F%2F127.0.0.1%3A8017';

async function canvasCheck() {
  const canvas = page.locator('.bk-canvas canvas').first();
  await canvas.waitFor({timeout:30000});
  const colors = await canvas.evaluate(async node => {
    await new Promise(requestAnimationFrame);
    const copy = document.createElement('canvas'); copy.width=80; copy.height=60;
    const ctx = copy.getContext('2d'); ctx.drawImage(node,0,0,80,60);
    const data = ctx.getImageData(0,0,80,60).data, colors = new Set();
    for(let i=0;i<data.length;i+=4) colors.add(`${data[i]},${data[i+1]},${data[i+2]}`);
    return colors.size;
  });
  assert(colors > 20, `Canvas appears blank: ${colors} colors`);
  return canvas;
}

try {
  await page.setViewportSize({width:1440,height:1000});
  await page.goto(url);
  await page.getByRole('heading',{name:'Books Agent',exact:true}).waitFor({timeout:60000});
  await page.getByRole('button',{name:'Open Library Fixture',exact:true}).waitFor({timeout:30000});
  await page.waitForFunction(() => [...document.querySelectorAll('.bk-cover img')].every(image => image.complete && image.naturalWidth > 0));
  await canvasCheck();
  await page.screenshot({path:resolve(out,'shelf-desktop.png')});
  await page.getByRole('button',{name:'Open Library Fixture',exact:true}).click();
  await page.getByRole('heading',{name:'Library Fixture',exact:true}).waitFor();
  const canvas = await canvasCheck(), rect = await canvas.boundingBox();
  const before = await page.screenshot({clip:rect});
  await page.mouse.move(rect.x+rect.width*.4,rect.y+rect.height*.5);
  await page.mouse.down(); await page.mouse.move(rect.x+rect.width*.7,rect.y+rect.height*.6,{steps:12}); await page.mouse.up();
  await page.waitForTimeout(700);
  assert(!before.equals(await page.screenshot({clip:rect})),'Book did not rotate');
  await page.screenshot({path:resolve(out,'book-desktop.png')});
  const build = page.getByRole('button',{name:'Build Book skill',exact:true});
  if(await build.count()) {
    await build.click(); await page.getByRole('button',{name:'Confirm',exact:true}).click();
    await page.locator('.bk-detail dd').filter({hasText:'Compiled'}).waitFor({timeout:30000});
  }
  const postsBefore = requests.filter(item=>item.method==='POST').length;
  await page.getByRole('button',{name:'Add to Chat',exact:true}).click();
  const draft = page.locator('.bk-chat textarea').first(); await draft.waitFor();
  assert((await draft.inputValue()).includes('Library Fixture'));
  assert.equal(requests.filter(item=>item.method==='POST').length,postsBefore);
  await page.getByRole('button',{name:'Library',exact:true}).click();
  await page.getByRole('button',{name:'All books',exact:true}).click();
  if(process.env.BOOKS_QA_EPUB) {
    await page.getByRole('button',{name:'Import EPUB',exact:true}).click();
    await page.locator('dialog input[type=file]').setInputFiles(process.env.BOOKS_QA_EPUB);
    await page.getByLabel('I have permission to import and process this book.').check();
    await page.getByLabel('Allow Vellum to run the local malware scan.').check();
    await page.locator('dialog').getByRole('button',{name:'Import EPUB',exact:true}).click();
    await page.locator('dialog').waitFor({state:'detached',timeout:30000});
    await page.getByRole('button',{name:'All books',exact:true}).click();
  }
  await page.reload();
  await page.getByRole('button',{name:'Open Library Fixture',exact:true}).waitFor({timeout:30000});
  await page.setViewportSize({width:390,height:844});
  await canvasCheck(); await page.screenshot({path:resolve(out,'shelf-mobile.png')});
  assert(await page.locator('.bk-root').evaluate(node=>node.scrollWidth<=node.clientWidth+1),'Books layout overflows horizontally');
  await page.getByRole('button',{name:'Open Library Fixture',exact:true}).click();
  await page.getByRole('heading',{name:'Library Fixture',exact:true}).waitFor();
  await canvasCheck(); await page.screenshot({path:resolve(out,'book-mobile.png')});
  assert.equal(errors.length,0,errors.join('\n'));
  writeFileSync(resolve(out,'result.json'),JSON.stringify({passed:true,requests,errors},null,2));
  console.log(JSON.stringify({passed:true,screenshots:out,requests:requests.length}));
} catch(error) {
  await page.screenshot({path:resolve(out,'failure.png')});
  console.error(JSON.stringify({errors,body:(await page.locator('body').innerText()).slice(0,3000)}));
  throw error;
} finally { await browser.close(); }
