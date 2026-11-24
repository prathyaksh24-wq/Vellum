// Installed-app layout shared by the release/install scripts and the in-app
// updater. Plain Node only: no Electron APIs, so the scripts can use it too.
//
//   ~\.vellum\updates\latest.json                        newest published release
//   ~\.vellum\updates\releases\<id>\                      immutable packaged builds
//   %LOCALAPPDATA%\Programs\Vellum\app-<id>\              installed builds
//   %LOCALAPPDATA%\Programs\Vellum\current  (junction)    -> the active app-<id>
//
// Shortcuts always target current\Vellum.exe, so pins survive updates. Files are
// hard-linked from the release when possible: a multi-GB build installs in
// seconds, and releases are never modified after publishing, so sharing is safe.
const fs = require('node:fs');
const path = require('node:path');

const BUILD_FILE = 'vellum-build.json';

function localAppData(env = process.env) {
  return env.LOCALAPPDATA || path.join(env.USERPROFILE || require('node:os').homedir(), 'AppData', 'Local');
}
// The feed sits beside the desktop profile in the home folder, not in
// %LOCALAPPDATA%\Vellum: tools running inside an MSIX-packaged app (Claude,
// Codex) get new AppData folders silently redirected to their private store,
// so a release published from there would be invisible to the installed app.
function feedRoot(env = process.env) {
  return env.VELLUM_UPDATE_FEED || path.join(env.USERPROFILE || require('node:os').homedir(), '.vellum', 'updates');
}
function installRoot(env = process.env) {
  return env.VELLUM_INSTALL_ROOT || path.join(localAppData(env), 'Programs', 'Vellum');
}

function validBuild(build) {
  return !!build && typeof build.id === 'string' && /^[A-Za-z0-9._-]{1,80}$/.test(build.id) &&
    Number.isSafeInteger(build.sequence) && build.sequence > 0;
}
function readJSON(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return null; }
}
function writeJSONAtomic(file, value) {
  fs.mkdirSync(path.dirname(file), {recursive: true});
  const staging = file + '.' + process.pid + '.tmp';
  fs.writeFileSync(staging, JSON.stringify(value, null, 2) + '\n');
  fs.renameSync(staging, file);
}

// The newest published release, or null when none is complete and readable.
function readLatest(feed = feedRoot()) {
  const latest = readJSON(path.join(feed, 'latest.json'));
  if (!validBuild(latest)) return null;
  const directory = path.join(feed, 'releases', latest.id);
  if (!fs.existsSync(path.join(directory, 'Vellum.exe'))) return null;
  return {...latest, directory};
}

function isNewer(candidate, current) {
  return validBuild(candidate) && (!validBuild(current) || candidate.sequence > current.sequence);
}

function listFiles(root) {
  const files = [];
  const walk = (relative) => {
    for (const entry of fs.readdirSync(path.join(root, relative), {withFileTypes: true})) {
      const child = path.join(relative, entry.name);
      if (entry.isDirectory()) walk(child);
      else if (entry.isFile()) files.push(child);
    }
  };
  walk('');
  return files;
}

// Mirror a directory with hard links (copy across volumes). Progress is 0-100.
async function mirrorTree(source, destination, onProgress = () => {}) {
  const files = listFiles(source);
  const made = new Set();
  let linkable = true;
  for (let index = 0; index < files.length; index++) {
    const relative = files[index];
    const target = path.join(destination, relative), directory = path.dirname(target);
    if (!made.has(directory)) { fs.mkdirSync(directory, {recursive: true}); made.add(directory); }
    if (linkable) {
      try { fs.linkSync(path.join(source, relative), target); }
      catch (error) {
        if (!['EXDEV', 'EPERM', 'ENOTSUP', 'EACCES'].includes(error.code)) throw error;
        linkable = false;
      }
    }
    if (!linkable) await fs.promises.copyFile(path.join(source, relative), target);
    if (index % 200 === 0 || index === files.length - 1) {
      onProgress(Math.round(100 * (index + 1) / files.length));
      await new Promise(resolve => setImmediate(resolve));
    }
  }
  return files.length;
}

function removeTree(directory, parent) {
  const resolved = path.resolve(directory), base = path.resolve(parent);
  if (!resolved.startsWith(base + path.sep)) throw new Error('Refusing to remove a path outside ' + base);
  fs.rmSync(resolved, {recursive: true, force: true, maxRetries: 3});
}

// Point root\current at app-<id>. Removing a junction never touches its target.
function activate(root, id) {
  const target = path.join(root, 'app-' + id), current = path.join(root, 'current');
  if (!fs.existsSync(path.join(target, 'Vellum.exe'))) throw new Error('The installed build is incomplete.');
  const next = current + '.next';
  try { fs.rmSync(next, {recursive: false, force: true}); } catch {}
  try { fs.unlinkSync(next); } catch {}
  fs.symlinkSync(target, next, 'junction');
  try { fs.unlinkSync(current); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  fs.renameSync(next, current);
  return path.join(current, 'Vellum.exe');
}

// Install a published release as app-<id> and make it current.
async function installRelease(release, {root = installRoot(), onProgress = () => {}} = {}) {
  if (!validBuild(release) || !release.directory) throw new Error('No valid release to install.');
  const final = path.join(root, 'app-' + release.id);
  if (!fs.existsSync(path.join(final, 'Vellum.exe'))) {
    const staging = final + '.installing';
    fs.mkdirSync(root, {recursive: true});
    if (fs.existsSync(staging)) removeTree(staging, root);
    await mirrorTree(release.directory, staging, onProgress);
    // The release metadata travels with the build; the app reads it to know its version.
    writeJSONAtomic(path.join(staging, 'resources', BUILD_FILE), {id: release.id, sequence: release.sequence, commit: release.commit || null, builtAt: release.builtAt || null});
    if (fs.existsSync(final)) removeTree(final, root);
    fs.renameSync(staging, final);
  }
  onProgress(100);
  return activate(root, release.id);
}

// Keep the active build and the one before it; the rest may be removed.
function pruneInstalled(root = installRoot(), keep = 2) {
  if (!fs.existsSync(root)) return [];
  let active = null;
  try { active = path.basename(fs.realpathSync(path.join(root, 'current'))); } catch {}
  const builds = fs.readdirSync(root, {withFileTypes: true})
    .filter(entry => entry.isDirectory() && /^app-/.test(entry.name))
    .map(entry => ({name: entry.name, build: readJSON(path.join(root, entry.name, 'resources', BUILD_FILE))}))
    .sort((a, b) => (b.build?.sequence || 0) - (a.build?.sequence || 0));
  const removed = [];
  let kept = 0;
  for (const {name} of builds) {
    if (name === active || (!name.endsWith('.installing') && kept < keep)) { kept++; continue; }
    try { removeTree(path.join(root, name), root); removed.push(name); } catch {}
  }
  return removed;
}

module.exports = {BUILD_FILE, feedRoot, installRoot, readLatest, isNewer, validBuild, readJSON, writeJSONAtomic, mirrorTree, removeTree, activate, installRelease, pruneInstalled};
