// @vitest-environment node
import {afterAll, beforeAll, expect, test} from 'vitest';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';

let server;
let origin;
beforeAll(async () => {
  server = await createServer({
    configFile:fileURLToPath(new URL('../vite.config.mjs',import.meta.url)),
    server:{host:'127.0.0.1',port:0},
    logLevel:'silent',
  });
  await server.listen();
  origin = `http://127.0.0.1:${server.httpServer.address().port}`;
});
afterAll(async () => { await server?.close(); });

test.each(['/', '/index.html', '/?view=agent&agent=browser'])('opens Vellum from %s', async path => {
  const response = await fetch(origin + path,{redirect:'manual'});
  expect(response.status).toBe(302);
  const query = path.includes('?') ? path.slice(path.indexOf('?')) : '';
  expect(response.headers.get('location')).toBe('/design-uploads/Vellum%20Default%20Re-designed.html' + query);
  const entry = await fetch(origin + response.headers.get('location'));
  expect(entry.status).toBe(200);
  expect(await entry.text()).toContain('components/browser-panel.jsx');
});
