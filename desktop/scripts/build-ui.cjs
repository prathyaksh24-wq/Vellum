const {spawnSync} = require('node:child_process');
const {cpSync, mkdirSync, rmSync} = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');
const result = spawnSync(process.execPath, [path.join(root, 'frontend/node_modules/vite/bin/vite.js'), 'build'], {
  cwd: path.join(root, 'frontend'), stdio: 'inherit',
});
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status || 1);
const destination = path.join(root, 'desktop/resources/ui');
rmSync(destination, {recursive: true, force: true});
mkdirSync(destination, {recursive: true});
cpSync(path.join(root, 'frontend/ui-dist'), destination, {recursive: true});
