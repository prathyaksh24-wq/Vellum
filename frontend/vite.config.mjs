import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { cpSync, readdirSync, rmSync } from 'node:fs';

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

export default defineConfig({
  plugins: [react(), copyStaticUiAssets()],
  root: '.',
  publicDir: false,
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
