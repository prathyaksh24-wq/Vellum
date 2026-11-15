// @vitest-environment node
import {expect, test, vi} from 'vitest';
import config from '../vite.config.mjs';

test('the served app HTML receives the Vite runtime required by module-backed React controls', async () => {
  const routes = new Map();
  const transformIndexHtml = vi.fn(async () => '<html>runtime initialized</html>');
  config.plugins.find(plugin => plugin.name === 'serve-design-uploads').configureServer({
    middlewares:{use:(path, handler) => routes.set(path, handler)}, transformIndexHtml,
  });
  const response = {setHeader:vi.fn(), end:vi.fn()};
  const next = vi.fn();
  await routes.get('/design-uploads')({url:'/Vellum%20Default%20Re-designed.html', originalUrl:'/design-uploads/Vellum%20Default%20Re-designed.html'}, response, next);
  expect(transformIndexHtml).toHaveBeenCalledOnce();
  expect(transformIndexHtml.mock.calls[0][0]).toBe('/Vellum Default Re-designed.html');
  expect(transformIndexHtml.mock.calls[0][1]).toContain('src="/books-entry.js"');
  expect(response.end).toHaveBeenCalledWith('<html>runtime initialized</html>');
  expect(next).not.toHaveBeenCalled();
});

test('plain API scripts are served unchanged without an HTML runtime transform', async () => {
  const routes = new Map();
  const transformIndexHtml = vi.fn();
  config.plugins.find(plugin => plugin.name === 'serve-design-uploads').configureServer({
    middlewares:{use:(path, handler) => routes.set(path, handler)}, transformIndexHtml,
  });
  const response = {setHeader:vi.fn(), end:vi.fn()};
  await routes.get('/design-uploads')({url:'/api/books.js'}, response, vi.fn());
  expect(transformIndexHtml).not.toHaveBeenCalled();
  expect(response.end.mock.calls[0][0].toString()).toContain('/api/app-actions/books/import');
});

test('static UI scripts and assets are copied into the configured build output', async () => {
  const {mkdtempSync, existsSync, rmSync} = await import('node:fs');
  const {tmpdir} = await import('node:os');
  const {join} = await import('node:path');
  // Desktop development builds into a temporary folder; static files must follow it.
  const outDir = mkdtempSync(join(tmpdir(), 'vellum-ui-out-'));
  try {
    const plugin = config.plugins.find(item => item.name === 'copy-static-ui-assets');
    plugin.configResolved({root: outDir, build: {outDir}});
    plugin.closeBundle();
    for (const file of ['api/client.js', 'components/vellum-face.jsx', 'assets/brand/vellum-icon-orange.png', 'assets/pets/boba.webp']) {
      expect(existsSync(join(outDir, file)), file).toBe(true);
    }
    expect(existsSync(join(outDir, 'api/client.test.js'))).toBe(false);
  } finally {
    rmSync(outDir, {recursive: true, force: true});
  }
});
