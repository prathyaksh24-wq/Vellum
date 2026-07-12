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
      const target = resolve(here, 'ui-dist/ui/terminal/vellum');
      rmSync(target, { recursive: true, force: true });
      cpSync(resolve(here, 'ui/terminal/vellum'), target, { recursive: true });
      cpSync(resolve(designUploadsRoot, 'api'), resolve(here, 'ui-dist/api'), { recursive: true });
      const apiTarget = resolve(here, 'ui-dist/api');
      for (const file of readdirSync(apiTarget)) {
        if (file.endsWith('.test.js')) rmSync(resolve(apiTarget, file), { force: true });
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
        if (['/Vellum Default Re-designed.html', '/ui/Vellum Default Re-designed.html'].includes(decodeURIComponent(path))) {
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
  root: designUploadsRoot,
  publicDir: false,
  server: {
    fs: {
      allow: [here, designUploadsRoot],
    },
  },
  test: {
    root: here,
    exclude: ['node_modules/**', 'ui-dist/**'],
  },
  build: {
    outDir: resolve(here, 'ui-dist'),
    emptyOutDir: true,
    rollupOptions: {
      input: resolve(designUploadsRoot, 'Vellum Default Re-designed.html'),
    },
  },
});
