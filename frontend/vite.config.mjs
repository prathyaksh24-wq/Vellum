import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
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
      cpSync(resolve(designUploadsRoot, 'components'), resolve(here, 'ui-dist/components'), { recursive: true });
      cpSync(resolve(designUploadsRoot, 'provider-icons'), resolve(here, 'ui-dist/provider-icons'), { recursive: true });
      cpSync(resolve(designUploadsRoot, 'assets/browser-home'), resolve(here, 'ui-dist/assets/browser-home'), { recursive: true });
      cpSync(resolve(designUploadsRoot, 'assets/backgrounds'), resolve(here, 'ui-dist/assets/backgrounds'), { recursive: true });
      cpSync(resolve(designUploadsRoot, 'assets/music'), resolve(here, 'ui-dist/assets/music'), { recursive: true });
      cpSync(resolve(designUploadsRoot, 'assets/plugins'), resolve(here, 'ui-dist/assets/plugins'), { recursive: true });
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
    '.ico': 'image/x-icon',
  };
  return {
    name: 'serve-design-uploads',
    configureServer(server) {
      server.middlewares.use('/design-uploads', async (req, res, next) => {
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
        if (extname(target).toLowerCase() === '.html') {
          try {
            // This route is the real app entry. Module-backed React components
            // need Vite's client and React runtime preamble here as well.
            res.end(await server.transformIndexHtml('/' + decodedPath, readFileSync(target, 'utf8'), req.originalUrl));
          } catch (error) {next(error);}
        } else res.end(readFileSync(target));
      });
      server.middlewares.use((req, res, next) => {
        const url = req.url || '';
        const path = url.split('?')[0];
        if (['/', '/index.html', '/Vellum Default Re-designed.html', '/ui/Vellum Default Re-designed.html'].includes(decodeURIComponent(path))) {
          const query = url.includes('?') ? url.slice(url.indexOf('?')) : '';
          res.statusCode = 302;
          res.setHeader('Location', '/design-uploads/Vellum%20Default%20Re-designed.html' + query);
          res.end();
          return;
        }
        next();
      });
    },
  };
}

export default defineConfig({
  cacheDir: resolve(here, '.vite'),
  resolve: {alias: {
    'three/examples': resolve(here, 'node_modules/three/examples'),
    three: resolve(here, 'node_modules/three/build/three.module.js'),
    clsx: resolve(here, 'node_modules/clsx'),
    'tailwind-merge': resolve(here, 'node_modules/tailwind-merge'),
    '@radix-ui/react-dialog': resolve(here, 'node_modules/@radix-ui/react-dialog'),
    '@radix-ui/react-tabs': resolve(here, 'node_modules/@radix-ui/react-tabs'),
    '@radix-ui/react-label': resolve(here, 'node_modules/@radix-ui/react-label'),
    '@radix-ui/react-slot': resolve(here, 'node_modules/@radix-ui/react-slot'),
    'class-variance-authority': resolve(here, 'node_modules/class-variance-authority'),
    sonner: resolve(here, 'node_modules/sonner'),
    'tw-animate-css': resolve(here, 'node_modules/tw-animate-css'),
    react: resolve(here, 'node_modules/react'),
    'react-dom': resolve(here, 'node_modules/react-dom'),
    motion: resolve(here, 'node_modules/motion'),
    'lucide-react': resolve(here, 'node_modules/lucide-react'),
    tailwindcss: resolve(here, 'node_modules/tailwindcss'),
    '@/components/motion/tooltip': resolve(designUploadsRoot, 'components/attachment-upload-support.jsx'),
    '@/lib/ease': resolve(designUploadsRoot, 'components/attachment-upload-support.jsx'),
    '@/lib/presence-gate': resolve(designUploadsRoot, 'components/attachment-upload-support.jsx'),
    '@/lib/utils': resolve(designUploadsRoot, 'components/attachment-upload-support.jsx'),
  }},
  plugins: [react(), tailwindcss(), serveDesignUploads(), copyStaticUiAssets()],
  root: designUploadsRoot,
  publicDir: false,
  server: {
    fs: {
      allow: [here, designUploadsRoot],
    },
  },
  test: {
    root: here,
    include: ['ui/**/*.test.js'],
    exclude: ['node_modules/**', 'ui-dist/**', '.pytest_cache/**'],
  },
  build: {
    outDir: resolve(here, 'ui-dist'),
    emptyOutDir: true,
    rollupOptions: {
      input: resolve(designUploadsRoot, 'Vellum Default Re-designed.html'),
    },
  },
});
