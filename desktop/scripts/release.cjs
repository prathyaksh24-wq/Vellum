// Build, sign and publish a Vellum desktop release to the local update feed.
// The installed app watches the feed and shows "Update available" in the rail.
//
//   npm run release                 build UI + backend, package (EVS-signed), publish
//   npm run release -- --engines    also rebuild the memory-engine runtimes
//   npm run release -- --ui-only    rebuild only the UI (reuse the built backend), package, publish
//   npm run release -- --no-build   publish the existing out/ package as-is
//   npm run release -- --install    publish, then install it now (first install)
const {spawnSync, execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const core = require('../electron/install-core.cjs');

const desktop = path.resolve(__dirname, '..');
const repo = path.resolve(desktop, '..');
const packaged = path.join(desktop, 'out', 'vellum-desktop-win32-x64');
const args = new Set(process.argv.slice(2));

function step(label, command, commandArgs, options = {}) {
  console.log('\n[release] ' + label);
  const result = spawnSync(command, commandArgs, {cwd: desktop, stdio: 'inherit', windowsHide: true, shell: options.shell || false});
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(label + ' failed (exit ' + result.status + ').');
}

function git(...gitArgs) {
  try { return execFileSync('git', gitArgs, {cwd: repo, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore']}).trim(); } catch { return ''; }
}

function releaseId(now, commit) {
  const pad = n => String(n).padStart(2, '0');
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return commit ? stamp + '-' + commit : stamp;
}

function pruneReleases(feed, keep = 3) {
  const releases = path.join(feed, 'releases');
  if (!fs.existsSync(releases)) return;
  const latest = core.readJSON(path.join(feed, 'latest.json'))?.id;
  const ids = fs.readdirSync(releases).filter(name => name !== latest).sort().reverse();
  for (const id of ids.slice(Math.max(0, keep - 1))) {
    try { core.removeTree(path.join(releases, id), releases); } catch {}
  }
}

async function main() {
  if (process.platform !== 'win32') throw new Error('Vellum desktop releases are built on Windows x64.');
  if (!args.has('--no-build')) {
    step('Building the UI', process.execPath, [path.join(__dirname, 'build-ui.cjs')]);
    const backendBuilt = fs.existsSync(path.join(desktop, 'resources/backend-runtime/app/desktop-backend.json'));
    if (!args.has('--ui-only') || !backendBuilt) step('Building the backend runtime', process.execPath, [path.join(__dirname, 'build-backend.cjs')]);
    if (args.has('--engines') || !fs.existsSync(path.join(desktop, 'resources/engine-runtimes/hindsight/python/python.exe'))) {
      step('Building the memory engines', process.execPath, [path.join(__dirname, 'build-engines.cjs')]);
    }
    // A fresh output folder: published releases hard-link these files, so the
    // packager must never rewrite them in place.
    fs.rmSync(packaged, {recursive: true, force: true, maxRetries: 3});
    step('Packaging and signing (electron-forge)', 'npx', ['electron-forge', 'package'], {shell: true});
  }
  if (!fs.existsSync(path.join(packaged, 'Vellum.exe'))) throw new Error('No packaged app at ' + packaged + '. Run without --no-build.');

  const commit = git('rev-parse', '--short=7', 'HEAD');
  const dirty = git('status', '--porcelain', '--', 'desktop', 'backend', 'frontend', 'design').length > 0;
  const now = new Date();
  const build = {id: releaseId(now, commit), sequence: now.getTime(), commit: commit || null, dirty, branch: git('branch', '--show-current') || null, builtAt: now.toISOString()};

  const feed = core.feedRoot();
  const directory = path.join(feed, 'releases', build.id);
  console.log('\n[release] Publishing ' + build.id + ' to ' + directory);
  const staging = directory + '.publishing';
  fs.rmSync(staging, {recursive: true, force: true});
  await core.mirrorTree(packaged, staging);
  core.writeJSONAtomic(path.join(staging, 'resources', core.BUILD_FILE), build);
  fs.renameSync(staging, directory);
  // Publishing is this one atomic rename; the running app reacts within seconds.
  core.writeJSONAtomic(path.join(feed, 'latest.json'), build);
  pruneReleases(feed);
  console.log('[release] Published. Installed Vellum will show "Update available".');

  if (args.has('--install')) {
    require('./install-app.cjs').install({launch: true}).catch(error => { console.error(error.message); process.exitCode = 1; });
  }
}

if (require.main === module) main().catch(error => { console.error('[release] ' + error.message); process.exit(1); });
module.exports = {releaseId};
