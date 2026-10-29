const {test} = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {configureRuntime} = require('../scripts/start.cjs');

test('normal desktop startup selects the provisioned protected-audio runtime', () => {
  const root = path.resolve('fixture'), env = {};
  const directory = path.join(root, '.desktop-runtime', 'protected-audio');
  configureRuntime({root, env, platform:'win32', exists:file => file === path.join(directory,'electron.exe')});
  assert.equal(env.ELECTRON_OVERRIDE_DIST_PATH, directory);
  assert.equal(env.VELLUM_DESKTOP_PROFILE,path.join(root,'.desktop-runtime','workspace-profile'));
});

test('an incomplete audio runtime does not replace stock startup or an explicit override', () => {
  const env = {};
  configureRuntime({env, exists:() => false});
  assert.equal(env.ELECTRON_OVERRIDE_DIST_PATH, undefined);
  env.ELECTRON_OVERRIDE_DIST_PATH = path.resolve('explicit-runtime');
  configureRuntime({env, exists:() => {throw Error('must preserve explicit configuration');}});
  assert.equal(env.ELECTRON_OVERRIDE_DIST_PATH, path.resolve('explicit-runtime'));
});
