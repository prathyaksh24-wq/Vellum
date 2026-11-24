// In-app updates for the installed Vellum, modeled on the ChatGPT desktop flow:
// a background check finds a newer published build -> state "ready" (the rail
// shows "Update available") -> the user clicks -> state "installing" with a
// progress dialog -> the new build becomes current and Vellum relaunches into it.
//
// Only an installed copy (running from <install root>\app-<id>) updates itself.
// Development runs and the raw out/ folder never do.
const fs = require('node:fs');
const path = require('node:path');
const core = require('./install-core.cjs');

const CHECK_INTERVAL_MS = 10 * 60 * 1000;

function currentBuild({resourcesPath = process.resourcesPath} = {}) {
  const build = core.readJSON(path.join(resourcesPath, core.BUILD_FILE));
  return core.validBuild(build) ? build : null;
}

function isInstalledCopy({execPath = process.execPath, root = core.installRoot()} = {}) {
  let real;
  try { real = fs.realpathSync(execPath); } catch { return false; }
  const base = path.resolve(root).toLowerCase() + path.sep;
  return real.toLowerCase().startsWith(base) && /^app-/i.test(path.basename(path.dirname(real)));
}

function createUpdater({app, broadcast = () => {}, beforeRelaunch = async () => {}, feed = core.feedRoot(), root = core.installRoot(),
  build = currentBuild(), enabled = app.isPackaged && isInstalledCopy({root}), intervalMs = CHECK_INTERVAL_MS} = {}) {
  let state = {status: enabled ? 'idle' : 'unavailable', current: build?.id || null, available: null, progress: null, error: null};
  let timer = null, watcher = null, debounce = null, installing = null;

  const publish = patch => { state = {...state, ...patch}; broadcast(snapshot()); };
  const snapshot = () => ({...state});

  function check() {
    if (!enabled || state.status === 'installing') return snapshot();
    const latest = core.readLatest(feed);
    if (core.isNewer(latest, build)) {
      if (state.available !== latest.id || state.status !== 'ready') publish({status: 'ready', available: latest.id, error: null});
    } else if (state.status === 'ready' || state.available) {
      publish({status: 'idle', available: null});
    }
    return snapshot();
  }

  async function install() {
    if (!enabled) throw new Error('Updates apply to the installed Vellum app only.');
    if (installing) return installing;
    const latest = core.readLatest(feed);
    if (!core.isNewer(latest, build)) { check(); return snapshot(); }
    installing = (async () => {
      publish({status: 'installing', progress: 0, error: null, available: latest.id});
      try {
        const executable = await core.installRelease(latest, {root, onProgress: progress => publish({progress})});
        await beforeRelaunch();
        // Relaunch through the stable junction so the new build owns pins and shortcuts.
        app.relaunch({execPath: executable, args: process.argv.slice(1)});
        app.quit();
        return snapshot();
      } catch (error) {
        publish({status: 'failed', progress: null, error: 'Unable to install the update. ' + (error.message || '')});
        setTimeout(check, 5000);
        throw error;
      } finally { installing = null; }
    })();
    return installing;
  }

  function start() {
    if (!enabled) return snapshot();
    // Finished updates leave the previous build behind for one launch; tidy now.
    setTimeout(() => { try { core.pruneInstalled(root); } catch {} }, 30000).unref?.();
    check();
    timer = setInterval(check, intervalMs); timer.unref?.();
    try {
      fs.mkdirSync(feed, {recursive: true});
      // latest.json is replaced atomically on publish; react within a second.
      watcher = fs.watch(feed, (_event, name) => {
        if (name && name !== 'latest.json') return;
        clearTimeout(debounce); debounce = setTimeout(check, 750);
      });
      watcher.on('error', () => {});
    } catch {}
    return snapshot();
  }

  function stop() { clearInterval(timer); clearTimeout(debounce); watcher?.close(); }

  return {start, stop, check, install, snapshot, enabled};
}

module.exports = {createUpdater, currentBuild, isInstalledCopy};
