const {spawn} = require('node:child_process');
const path = require('node:path');
const {mkdtempSync, existsSync, readFileSync} = require('node:fs');
const os = require('node:os');

const env = {...process.env, VELLUM_SMOKE_PROFILE: mkdtempSync(path.join(os.tmpdir(), 'vellum-electron-smoke-'))};
env.VELLUM_SMOKE_RESULT = path.join(env.VELLUM_SMOKE_PROFILE, 'result.json');
env.ELECTRON_ENABLE_LOGGING = '1';
delete env.ELECTRON_RUN_AS_NODE;
const child = spawn(require('electron'), [path.resolve(__dirname, '../test/smoke-app.cjs'), '--mute-audio'], {
  env, stdio: 'inherit', windowsHide: true,
});
let timedOut = false;
const timeout = setTimeout(() => { timedOut = true; child.kill(); }, 30000);
child.on('error', () => { console.error('Electron smoke could not start.'); clearTimeout(timeout); process.exitCode = 1; });
child.on('exit', (code, signal) => {
  clearTimeout(timeout);
  const result = existsSync(env.VELLUM_SMOKE_RESULT) ? JSON.parse(readFileSync(env.VELLUM_SMOKE_RESULT, 'utf8')) : {};
  if (timedOut || signal || code !== 0 || result.status !== 'passed') {
    console.error('Electron smoke failed:', {code, signal, timedOut});
    process.exitCode = 1;
  } else console.log('Electron smoke passed:', result.checks.join(', '));
});
