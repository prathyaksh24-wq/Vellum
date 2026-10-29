import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect, test, vi} from 'vitest';

test.each([
  ['google', 'https://www.google.com/'],
  [' YouTube ', 'https://www.youtube.com/'],
  ['reddit', 'https://www.reddit.com/'],
  ['wikipedia', 'https://www.wikipedia.org/'],
  ['spotify', 'https://open.spotify.com/'],
  ['x', 'https://x.com/'],
  ['twitter', 'https://x.com/'],
  [' youtube.com/feed/history ', 'https://youtube.com/feed/history'],
  ['http://localhost:5173/path', 'http://localhost:5173/path'],
  ['localhost:5173/path', 'http://localhost:5173/path'],
  ['127.0.0.1:8000', 'http://127.0.0.1:8000'],
  ['[::1]:8000', 'http://[::1]:8000'],
  ['about:blank', 'about:blank'],
  ['liked videos & subscriptions', 'https://www.google.com/search?q=liked%20videos%20%26%20subscriptions'],
  ['file:///private', 'file:///private'],
  ['javascript:alert(1)', 'javascript:alert(1)'],
])('normalizes address %s while retaining unsupported schemes for server rejection', async (input, expected) => {
  vi.resetModules();
  window.VellumApi = {client:{request:vi.fn()}};
  await import('../../design/Velllum/uploads/api/browser.js');
  expect(window.VellumApi.browser.addressUrl(input)).toBe(expected);
});

test('submitting a recognized website name opens that site without a search intermediary', async () => {
  vi.resetModules();
  window.VellumApi = {client:{request:vi.fn().mockResolvedValue({})},
    appActions:{dispatch:vi.fn().mockResolvedValue({status:'applied'})}};
  await import('../../design/Velllum/uploads/api/browser.js');
  // Compile the checked-in classic JSX in Node, outside jsdom's typed-array realm.
  const code = execFileSync(process.execPath, ['-e', `
    const {createRequire}=require('node:module');
    const esbuild=createRequire(require.resolve('vite'))('esbuild');
    process.stdout.write(esbuild.transformSync(require('node:fs').readFileSync(process.argv[1],'utf8'),
      {loader:'jsx',jsxFactory:'React.createElement',jsxFragment:'React.Fragment'}).code);
  `, resolve('..', 'design/Velllum/uploads/components/browser-panel.jsx')],
    {encoding:'utf8',cwd:process.cwd()});
  Function('React', 'window', code)(React, window);
  window.VellumApi.browser.frame = vi.fn().mockResolvedValue({tab_id:'tab', width:1280, height:800, data_url:'data:image/png;base64,aQ=='});
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  try {
    await act(async () => root.render(React.createElement(window.VellumUI.BrowserPanel, {
      state:{running:true, available:true, control:'user', session_id:'fixture', active_tab_id:'tab', downloads:[],
        tabs:[{id:'tab', active:true, title:'New tab', url:'about:blank'}]},
      onRefresh:vi.fn(), onHide:vi.fn(),
    })));
    const input = container.querySelector('[aria-label="Browser address"]');
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'google');
      input.dispatchEvent(new Event('input', {bubbles:true}));
    });
    await act(async () => container.querySelector('form').dispatchEvent(new Event('submit', {bubbles:true, cancelable:true})));
    expect(window.VellumApi.appActions.dispatch).toHaveBeenCalledWith(
      expect.objectContaining({arguments:{operation:'navigate',url:'https://www.google.com/'}}),
      expect.objectContaining({source:'ui'}),
    );
  } finally {
    await act(async () => root.unmount());
    container.remove();
    delete globalThis.IS_REACT_ACT_ENVIRONMENT;
  }
});
