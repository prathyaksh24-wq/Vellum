// @vitest-environment node
import {expect,test} from 'vitest';
import {parse} from 'parse5';
import {desktopWorkspaceBuild} from '../vite-desktop.config.mjs';

function scripts(html){
  const result=[];
  const walk=node=>{if(node.tagName==='script')result.push(node);for(const child of node.childNodes||[])walk(child);};
  walk(parse(html));return result;
}
const attr=(node,key)=>node.attrs.find(item=>item.name===key)?.value;
test.each([
  '<SCRIPT SRC="https://unpkg.com/react@18/x.js"></SCRIPT\t\n bar>',
  '<script src=https://unpkg.com/react@18/x.js data-label="a > b"></script>',
  '<script src="https://unpkg.com/&#114;eact@18/x.js"></script>',
])('removes CDN scripts using browser HTML parsing: %s',input=>{
  const output=desktopWorkspaceBuild().transformIndexHtml.handler(input);
  expect(scripts(output).filter(node=>attr(node,'src'))).toEqual([]);
});
test('removal cannot join text into a newly executable script',()=>{
  const input='<<script src="https://unpkg.com/react@18/x.js"></script>script>alert(1)</script>';
  const output=desktopWorkspaceBuild().transformIndexHtml.handler(input);
  expect(scripts(output).some(node=>node.childNodes.some(child=>child.value?.includes('alert(1)')))).toBe(false);
});
test('compiles unquoted JSX in order and preserves ordinary local scripts and boot handshake',async()=>{
  const plugin=desktopWorkspaceBuild();
  const output=plugin.transformIndexHtml.handler('<html><head><script src="components/app-icons.js"></script><script type=text/babel data-note="a > b">window.first=1;</script><script type="text/jsx">window.second=2;</script><script type=module src="/composer-entry.js"></script></head><body><div id="root"></div></body></html>');
  expect(scripts(output).some(node=>attr(node,'src')==='components/app-icons.js')).toBe(true);
  expect(scripts(output).some(node=>attr(node,'src')==='/composer-entry.js')).toBe(true);
  expect(scripts(output).some(node=>['text/babel','text/jsx'].includes(attr(node,'type')))).toBe(false);
  expect(output).toContain('Opening your workspace');
  const boot=await plugin.load('\0virtual:vellum-desktop/boot');
  expect(boot).toContain("invoke('workspace_ready')");
  expect(boot.indexOf('init0();')).toBeLessThan(boot.indexOf('init1();'));
  expect(await plugin.load('\0virtual:vellum-desktop/init/0')).toContain('window.first = 1');
  expect(await plugin.load('\0virtual:vellum-desktop/init/1')).toContain('window.second = 2');
});
test.each(['https://example.com/app.jsx','//example.com/app.jsx','../private.jsx','%2e%2e/private.jsx'])('rejects remote or escaped JSX source %s',src=>{
  expect(()=>desktopWorkspaceBuild().transformIndexHtml.handler('<script type=text/babel src="'+src+'"></script>')).toThrow();
});
