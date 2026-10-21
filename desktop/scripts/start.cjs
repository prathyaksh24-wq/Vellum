const fs = require('node:fs');
const path = require('node:path');

function configureRuntime({root = path.resolve(__dirname, '../..'), env = process.env, platform = process.platform, exists = fs.existsSync} = {}) {
  if (!env.VELLUM_DESKTOP_PROFILE) env.VELLUM_DESKTOP_PROFILE = path.join(root,'.desktop-runtime','workspace-profile');
  // Keep the installed stock package intact. A locally provisioned, signed ECS
  // distribution survives npm ci and uses Electron's own override/CLI support.
  if (env.ELECTRON_OVERRIDE_DIST_PATH) return;
  const directory = path.join(root, '.desktop-runtime', 'protected-audio');
  const executable = platform === 'win32' ? 'electron.exe'
    : platform === 'darwin' ? 'Electron.app/Contents/MacOS/Electron' : 'electron';
  if (exists(path.join(directory, executable))) env.ELECTRON_OVERRIDE_DIST_PATH = directory;
}

if (require.main === module) {
  configureRuntime();
  require('electron/cli.js');
}

module.exports = {configureRuntime};
