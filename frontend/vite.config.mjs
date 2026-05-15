import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { cpSync, rmSync } from 'node:fs';

function copyTerminalVellum() {
  return {
    name: 'copy-terminal-vellum',
    closeBundle() {
      const target = 'ui-dist/ui/terminal/vellum';
      rmSync(target, { recursive: true, force: true });
      cpSync('ui/terminal/vellum', target, { recursive: true });
    },
  };
}

export default defineConfig({
  plugins: [react(), copyTerminalVellum()],
  root: '.',
  publicDir: false,
  build: {
    outDir: 'ui-dist',
    emptyOutDir: true,
    rollupOptions: {
      input: 'ui/vellum-chat.html',
    },
  },
});
