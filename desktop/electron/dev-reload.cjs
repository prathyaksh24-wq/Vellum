const {execFile} = require('node:child_process');
const {mkdirSync, mkdtempSync, rmSync, watch} = require('node:fs');
const path = require('node:path');
const {promisify} = require('node:util');

const run = promisify(execFile);

function createDevBundle(root, node) {
  const runtime = path.join(root, '.desktop-runtime');
  mkdirSync(runtime, {recursive: true});
  const directory = mkdtempSync(path.join(runtime, 'ui-watch-'));
  let current;

  return {
    get current() { return current; },
    async build() {
      // Keep serving the last good build until the next output is complete.
      const next = path.join(directory, current === path.join(directory, 'a') ? 'b' : 'a');
      await run(node, [
        path.join(root, 'frontend/node_modules/vite/bin/vite.js'),
        'build', '--config', 'vite-desktop.config.mjs', '--outDir', next, '--emptyOutDir',
      ], {cwd: path.join(root, 'frontend'), windowsHide: true});
      current = next;
    },
    close() {
      // This is the exact directory created by mkdtempSync above.
      rmSync(directory, {recursive: true, force: true});
    },
  };
}

function watchDevelopment(root, update) {
  const watchers = [];
  const changed = new Set();
  let timer;
  let active = Promise.resolve();
  let closed = false;

  function queue(kind) {
    changed.add(kind);
    clearTimeout(timer);
    timer = setTimeout(() => {
      const batch = new Set(changed);
      changed.clear();
      active = active.then(() => {
        if (!closed) return update(batch);
      }).catch(error => console.error('[Vellum dev]', error.stderr || error.message));
    }, 350);
  }

  function observe(directory, kind, matches = () => true, recursive = true) {
    const watcher = watch(path.join(root, directory), {recursive}, (_, file) => {
      if (!closed && (!file || matches(file.split(path.sep).join('/')))) queue(kind);
    });
    watchers.push(watcher);
    watcher.on('error', error => console.error('[Vellum dev] Watch failed:', error.message));
  }

  const backendSource = file => !/(^|\/)(?:__pycache__|node_modules|\.git|tests)(?:\/|$)/.test(file) &&
    !/(^|\/)(?:auth|oauth-flow)\.json$/.test(file) && /\.(?:py|json|ya?ml|ps1|md|txt)$/.test(file);

  try {
    observe('design/Velllum/uploads', 'ui');
    observe('frontend/ui', 'ui');
    observe('frontend', 'ui', file => /^vite(?:-desktop)?\.config\.mjs$/.test(file), false);
    for (const directory of ['backend/agent', 'plugins', 'scripts']) observe(directory, 'backend', backendSource);
    observe('backend', 'backend', file => file === 'pyproject.toml', false);
    observe('docs', 'backend', file => file === 'SOUL.md', false);
    observe('desktop/electron', 'desktop');
    observe('desktop/assets', 'desktop');
  } catch (error) {
    for (const watcher of watchers) watcher.close();
    throw error;
  }

  return async () => {
    closed = true;
    clearTimeout(timer);
    for (const watcher of watchers) watcher.close();
    await active;
  };
}

module.exports = {createDevBundle, watchDevelopment};
