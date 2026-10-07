import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect, test, vi} from 'vitest';

const compile = () => execFileSync(process.execPath, ['-e', `
 const {createRequire}=require('node:module');
 const esbuild=createRequire(require.resolve('vite'))('esbuild');
 process.stdout.write(esbuild.transformSync(require('node:fs').readFileSync(process.argv[1],'utf8'),
 {loader:'jsx',jsxFactory:'React.createElement',jsxFragment:'React.Fragment'}).code);
`, resolve('../design/Velllum/uploads/components/youtube-history.jsx')], {encoding:'utf8'});

async function mount(dispatch) {
  window.VellumApi = {appActions:{dispatch}};
  Function('React','window',compile())(React,window);
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  await act(async()=>root.render(React.createElement(window.VellumUI.YouTubeHistoryControls)));
  return {container, cleanup:async()=> {await act(async()=>root.unmount());container.remove();}};
}

test('refresh dispatches the typed action and displays receipt-backed fresh coverage', async()=> {
  const dispatch = vi.fn(async()=>({status:'applied', result:{history:{total:18, account_id:'a', refreshed_at:'2026-10-07T10:00:00Z'}}}));
  const ui = await mount(dispatch);
  try {
    await act(async()=>ui.container.querySelector('button').click());
    expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({action_id:'youtube.history.refresh', arguments:{}}), {source:'ui'});
    expect(ui.container.textContent).toContain('18 recent entries');
    expect(ui.container.textContent).toContain('Saved locally');
  } finally {await ui.cleanup();}
});

test('a failed refresh replaces success with the actual failure reason', async()=> {
  const dispatch = vi.fn().mockResolvedValueOnce({status:'applied', result:{history:{total:18, account_id:'a', refreshed_at:'2026-10-07T10:00:00Z'}}})
    .mockResolvedValueOnce({status:'failed', message:'Sign into YouTube in Browser.'});
  const ui = await mount(dispatch);
  try {
    await act(async()=>ui.container.querySelector('button').click());
    await act(async()=>ui.container.querySelector('button').click());
    expect(ui.container.querySelector('[role="alert"]').textContent).toContain('Sign into YouTube');
    expect(ui.container.textContent).not.toContain('18 recent entries');
  } finally {await ui.cleanup();}
});

test.each([false, true])('browser presentation is requested only for foreground sessions: %s', async foreground => {
  const html = readFileSync(resolve('../design/Velllum/uploads/Vellum Default Re-designed.html'), 'utf8');
  const body = html.match(/const refreshBrowser = async \(\) => \{([\s\S]*?)\n  \};/)[1];
  const present = vi.fn();
  const seen = {current:''};
  const refresh = Function('API','setBrowserState','browserSeenSession','dispatchSurfacePresentation',
    'return async()=>{' + body + '}')({browser:{status:async()=>({running:true, session_id:'same-session',
      presentation_requested:foreground})}}, vi.fn(), seen, present);
  await refresh();
  expect(present).toHaveBeenCalledTimes(foreground ? 1 : 0);
  if (!foreground) {
    // Explicitly opening that same background session remains available.
    const open = Function('API','setBrowserState','browserSeenSession','dispatchSurfacePresentation',
      'return async()=>{' + body + '}')({browser:{status:async()=>({running:true,session_id:'same-session',
        presentation_requested:true})}}, vi.fn(), seen, present);
    await open();
    expect(present).toHaveBeenCalledTimes(1);
  }
});
