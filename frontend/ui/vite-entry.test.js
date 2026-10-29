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
