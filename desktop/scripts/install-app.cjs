// Install the newest published Vellum release like a normal desktop app:
// %LOCALAPPDATA%\Programs\Vellum, plus Start menu and desktop shortcuts.
// After this, updates happen from inside the app ("Update available" in the rail).
//
//   npm run install-app            install (or reinstall) the latest release and open it
//   npm run install-app -- --no-launch
const {execFileSync, spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const core = require('../electron/install-core.cjs');

function shortcut(file, target) {
  fs.mkdirSync(path.dirname(file), {recursive: true});
  // Values arrive through the environment, never interpolated into the script.
  const script = '$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:VLNK);$s.TargetPath=$env:VTARGET;' +
    '$s.WorkingDirectory=(Split-Path $env:VTARGET);$s.IconLocation=$env:VTARGET+",0";$s.Description="Vellum";$s.Save()';
  execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script],
    {env: {...process.env, VLNK: file, VTARGET: target}, stdio: 'inherit', windowsHide: true});
}

async function install({launch = true} = {}) {
  const release = core.readLatest();
  if (!release) throw new Error('No published release found in ' + core.feedRoot() + '. Run: npm run release');
  const root = core.installRoot();
  console.log('[install] Installing ' + release.id + ' into ' + root);
  let last = -1;
  const executable = await core.installRelease(release, {root, onProgress: p => { if (p - last >= 10 || p === 100) { last = p; process.stdout.write(`  ${p}%\n`); } }});
  const appData = process.env.APPDATA, home = process.env.USERPROFILE;
  shortcut(path.join(appData, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Vellum.lnk'), executable);
  const desktopDir = path.join(home, 'Desktop'), oneDriveDesktop = path.join(home, 'OneDrive', 'Desktop');
  shortcut(path.join(fs.existsSync(desktopDir) ? desktopDir : oneDriveDesktop, 'Vellum.lnk'), executable);
  console.log('[install] Vellum is installed. Open it from the Start menu or the desktop shortcut.');
  if (launch) spawn(executable, [], {detached: true, stdio: 'ignore', cwd: path.dirname(executable)}).unref();
  return executable;
}

if (require.main === module) install({launch: !process.argv.includes('--no-launch')}).catch(error => { console.error('[install] ' + error.message); process.exit(1); });
module.exports = {install};
