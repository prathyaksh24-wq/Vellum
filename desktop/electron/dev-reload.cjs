const {execFile} = require('node:child_process');
const {existsSync, mkdirSync, readFileSync, readdirSync, rmSync, watch, writeFileSync} = require('node:fs');
const path = require('node:path');
const {promisify} = require('node:util');

const run = promisify(execFile);

function createDevBundle(root, node) {
  const runtime = path.join(root, '.desktop-runtime');
  // A stable directory keeps the last good build across launches, so the
  // window opens on it immediately while a fresh build runs in the background.
  const directory = path.join(runtime, 'ui-dev');
  mkdirSync(directory, {recursive: true});
  const pointer = path.join(directory, 'current.json');
  let current;
  try {
    const name = JSON.parse(readFileSync(pointer, 'utf8')).build;
    if ((name === 'a' || name === 'b') && existsSync(path.join(directory, name, 'Vellum Default Re-designed.html'))) current = path.join(directory, name);
  } catch {}
  // Earlier versions left one temporary build directory per launch.
  for (const item of readdirSync(runtime, {withFileTypes: true})) {
    if (item.isDirectory() && /^ui-watch-[A-Za-z0-9]{6}$/.test(item.name)) {
      try { rmSync(path.join(runtime, item.name), {recursive: true, force: true}); } catch {}
    }
  }

  return {
    get current() { return current; },
    async build() {
      // Keep serving the last good build until the next output is complete.
      const name = current === path.join(directory, 'a') ? 'b' : 'a';
      const next = path.join(directory, name);
      await run(node, [
        path.join(root, 'frontend/node_modules/vite/bin/vite.js'),
        'build', '--config', 'vite-desktop.config.mjs', '--outDir', next, '--emptyOutDir',
      ], {cwd: path.join(root, 'frontend'), windowsHide: true});
      const entry = 'Vellum Default Re-designed.html';
      let changed = true;
      try { changed = !current || readFileSync(path.join(current, entry), 'utf8') !== readFileSync(path.join(next, entry), 'utf8'); } catch {}
      current = next;
      writeFileSync(pointer, JSON.stringify({build: name}));
      return changed;
    },
    close() {},
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
    observe('docs', 'backend', file => ['main.md', 'SOUL.md', 'PERSONALITY.md'].includes(file), false);
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
