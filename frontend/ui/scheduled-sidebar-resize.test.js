import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect, test, vi} from 'vitest';

const entry = '../design/Velllum/uploads/Vellum Default Re-designed.html';
const source = readFileSync(entry, 'utf8');
const panel = '../design/Velllum/uploads/components/browser-panel.jsx';

test('Scheduled drag stays in its slot and snaps only on release', async () => {
  const compiled = execFileSync(process.execPath, ['-e', `
    const {createRequire} = require('node:module');
    const esbuild = createRequire(require.resolve('vite'))('esbuild');
    const code = require('node:fs').readFileSync(process.argv[1], 'utf8');
    process.stdout.write(esbuild.transformSync(code, {loader:'jsx'}).code);
  `, panel], {encoding:'utf8'});
  const ui = {};
  Function('React', 'window', compiled)(React, {
    VellumUI:ui,
    addEventListener:window.addEventListener.bind(window),
    removeEventListener:window.removeEventListener.bind(window),
  });
  const shell = document.createElement('div');
  shell.className = 'body';
  shell.style.setProperty('--workspace-sidebar-width', '320px');
  document.body.append(shell);
  const root = createRoot(shell);
  const onCollapse = vi.fn();
  const onChange = vi.fn();
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;

  try {
    await act(async () => root.render(React.createElement('div', {className:'main-sidebar-slot'},
      React.createElement(ui.SidebarResizeHandle, {value:260, onCollapse, onChange}))));
    const divider = shell.querySelector('[role="separator"]');
    const pointer = (type, x) => divider.dispatchEvent(new MouseEvent(type, {bubbles:true, clientX:x, button:0}));
    await act(async () => {
      pointer('pointerdown', 300);
      pointer('pointermove', 90);
      await new Promise(requestAnimationFrame);
    });
    expect(shell.style.getPropertyValue('--workspace-sidebar-width')).toBe('320px');
    expect(divider.getAttribute('aria-valuenow')).toBe('200');
    expect(onCollapse).not.toHaveBeenCalled();
    await act(async () => pointer('pointerup', 90));
    expect(onCollapse).toHaveBeenCalledOnce();
    expect(onChange).not.toHaveBeenCalled();
    expect(shell.style.getPropertyValue('--workspace-sidebar-width')).toBe('320px');
  } finally {
    await act(async () => root.unmount());
    shell.remove();
    delete globalThis.IS_REACT_ACT_ENVIRONMENT;
  }
});

test('Scheduled owns the docked state and width without changing other sidebar previews', () => {
  const layout = source.slice(source.indexOf('  const featureOwnsSidebar='), source.indexOf('  const toggleContextualSidebar='));
  const derive = new Function('view', 'scheduledChatId', 'activeChatId', 'sidebarPeeking', 'railPreview',
    'sidebarPinned', 'scheduledSidebarOpen', 'scheduledSidebarWidth', 'sidebarWidth', 'workspaceLayout',
    'useState', 'useEffect', 'automations', 'pluginSidebarVisible', layout + ';return {shellSidebarPinned, shellSidebarVisible, mainSidebarContext, activeSidebarWidth, contextualSidebarVisible};');
  const state = (view, peek, open, scheduledChatId = null) => derive(view, scheduledChatId, 'run', !!peek, peek,
    true, open, 205, 320, {surfaces:{}}, value => [value, () => {}], () => {}, [], true);

  expect(state('scheduled', null, false)).toMatchObject({shellSidebarPinned:false, shellSidebarVisible:false});
  expect(state('chat', 'scheduled', false, 'run')).toMatchObject({shellSidebarPinned:false, shellSidebarVisible:true, activeSidebarWidth:205});
  expect(state('scheduled', 'library', false)).toMatchObject({mainSidebarContext:'library', shellSidebarVisible:true, activeSidebarWidth:320});
  expect(state('chat', null, false)).toMatchObject({shellSidebarPinned:true, activeSidebarWidth:320});
  for (const view of ['apps', 'music', 'library']) {
    expect(state(view, null, false)).toMatchObject({contextualSidebarVisible:true, activeSidebarWidth:320});
  }
});
