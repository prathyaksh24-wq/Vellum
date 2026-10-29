const http = require('node:http');
const {readFile, stat} = require('node:fs/promises');
const path = require('node:path');

const types = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.ico': 'image/x-icon',
  '.woff2': 'font/woff2'};

async function serveUI(root, port = 5173) {
  const absolute = path.resolve(root);
  const server = http.createServer(async (req, res) => {
    if (!['GET', 'HEAD'].includes(req.method)) { res.writeHead(405).end(); return; }
    try {
      let route = decodeURIComponent((req.url || '/').split('?')[0]);
      if (route.startsWith('/design-uploads/')) route = route.slice('/design-uploads'.length);
      if (route === '/') route = '/Vellum Default Re-designed.html';
      const file = path.resolve(absolute, '.' + route);
      const relative = path.relative(absolute, file);
      if (!relative || relative.startsWith('..') || path.isAbsolute(relative) || relative.includes(':')) {
        res.writeHead(403).end(); return;
      }
      if (!(await stat(file)).isFile()) { res.writeHead(404).end(); return; }
      const data = await readFile(file);
      res.writeHead(200, {'Content-Type': types[path.extname(file)] || 'application/octet-stream',
        'X-Content-Type-Options': 'nosniff', 'Content-Length': data.length});
      res.end(req.method === 'HEAD' ? undefined : data);
    } catch (error) { res.writeHead(error.code === 'ENOENT' ? 404 : 400).end(); }
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, '127.0.0.1', resolve);
  });
  return server;
}

module.exports = {serveUI};
