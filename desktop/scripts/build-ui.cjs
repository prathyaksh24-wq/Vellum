const {spawnSync} = require('node:child_process');
const {cpSync, mkdirSync, rmSync, readFileSync} = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');
const result = spawnSync(process.execPath, [path.join(root, 'frontend/node_modules/vite/bin/vite.js'), 'build', '--config', path.join(root,'frontend/vite-desktop.config.mjs')], {
  cwd: path.join(root, 'frontend'), stdio: 'inherit',
});
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status || 1);
const entry=readFileSync(path.join(root,'frontend/ui-dist/Vellum Default Re-designed.html'),'utf8');
if(/<script\b[^>]*(?:type=["']text\/(?:babel|jsx)["']|src=["']https?:\/\/)/i.test(entry)) {
  throw new Error('Desktop startup still depends on a remote script or runtime JSX compiler.');
}
const destination = path.join(root, 'desktop/resources/ui');
rmSync(destination, {recursive: true, force: true});
mkdirSync(destination, {recursive: true});
cpSync(path.join(root, 'frontend/ui-dist'), destination, {recursive: true});
