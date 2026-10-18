const {test} = require('node:test');
const assert = require('node:assert/strict');
const {mkdtemp, writeFile, rm} = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const {serveUI} = require('../electron/ui-server.cjs');

test('packaged UI serves the canonical entry without exposing adjacent files', async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'vellum-static-'));
  await writeFile(path.join(root, 'Vellum Default Re-designed.html'), '<title>Vellum</title>');
  const server = await serveUI(root, 0);
  t.after(async () => {
    await new Promise(resolve => server.close(resolve));
    await rm(root, {recursive: true, force: true});
  });
  const base = 'http://127.0.0.1:' + server.address().port;
  const response = await fetch(base + '/design-uploads/Vellum%20Default%20Re-designed.html?desktop=1');
  assert.equal(response.status, 200);
  assert.equal(await response.text(), '<title>Vellum</title>');
  assert.match(response.headers.get('content-type'), /text\/html/);
  assert.equal((await fetch(base + '/%2e%2e%2foutside.txt')).status, 403);
  assert.equal((await fetch(base + '/missing')).status, 404);
  assert.equal((await fetch(base + '/', {method: 'POST'})).status, 405);
});
