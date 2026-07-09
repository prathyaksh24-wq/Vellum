import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { cpSync, existsSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs';
import { dirname, extname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const designUploadsRoot = resolve(here, '../design/Velllum/uploads');

function copyStaticUiAssets() {
  return {
    name: 'copy-static-ui-assets',
    closeBundle() {
      for (const [source, target] of [
        ['ui/terminal/vellum', 'ui-dist/ui/terminal/vellum'],
        ['ui/api', 'ui-dist/ui/api'],
      ]) {
        rmSync(target, { recursive: true, force: true });
        cpSync(source, target, { recursive: true });
        if (source === 'ui/api') {
          for (const file of readdirSync(target)) {
            if (file.endsWith('.test.js')) rmSync(`${target}/${file}`, { force: true });
          }
        }
      }
    },
  };
}

function serveDesignUploads() {
  const contentTypes = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
  };
  return {
    name: 'serve-design-uploads',
    configureServer(server) {
      server.middlewares.use('/design-uploads', (req, res, next) => {
        const rawPath = (req.url || '/').split('?')[0].replace(/^\/+/, '');
        const decodedPath = decodeURIComponent(rawPath || 'Vellum Default Re-designed.html');
        const target = resolve(designUploadsRoot, decodedPath);
        const allowedRoot = designUploadsRoot.endsWith(sep) ? designUploadsRoot : designUploadsRoot + sep;
        if (target !== designUploadsRoot && !target.startsWith(allowedRoot)) {
          res.statusCode = 403;
          res.end('Forbidden');
          return;
        }
        if (!existsSync(target) || !statSync(target).isFile()) {
          next();
          return;
        }
        res.setHeader('Content-Type', contentTypes[extname(target).toLowerCase()] || 'application/octet-stream');
        res.end(readFileSync(target));
      });
      server.middlewares.use((req, res, next) => {
        const path = (req.url || '').split('?')[0];
        if (decodeURIComponent(path) === '/Vellum Default Re-designed.html') {
          res.statusCode = 302;
          res.setHeader('Location', '/design-uploads/Vellum%20Default%20Re-designed.html');
          res.end();
          return;
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), serveDesignUploads(), copyStaticUiAssets()],
  root: '.',
  publicDir: false,
  server: {
    fs: {
      allow: [here, designUploadsRoot],
    },
  },
  test: {
    exclude: ['node_modules/**', 'ui-dist/**'],
  },
  build: {
    outDir: 'ui-dist',
    emptyOutDir: true,
    rollupOptions: {
      input: 'ui/Vellum Default Re-designed.html',
    },
  },
});
