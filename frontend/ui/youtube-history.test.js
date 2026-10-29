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
  const refresh = Function('API','setBrowserState','browserSeenSession','dispatchSurfacePresentation','browserSuppressed',
    'return async()=>{' + body + '}')({browser:{status:async()=>({running:true, session_id:'same-session',
      presentation_requested:foreground})}}, vi.fn(), seen, present, {current:false});
  await refresh();
  expect(present).toHaveBeenCalledTimes(foreground ? 1 : 0);
  if (!foreground) {
    // Explicitly opening that same background session remains available.
    const open = Function('API','setBrowserState','browserSeenSession','dispatchSurfacePresentation','browserSuppressed',
      'return async()=>{' + body + '}')({browser:{status:async()=>({running:true,session_id:'same-session',
        presentation_requested:true})}}, vi.fn(), seen, present, {current:false});
    await open();
    expect(present).toHaveBeenCalledTimes(1);
  }
});

test('a startup receipt cannot reopen a dismissed browser, and a later session can present', async()=> {
  const html = readFileSync(resolve('../design/Velllum/uploads/Vellum Default Re-designed.html'), 'utf8');
  const body = html.match(/const refreshBrowser = async \(\) => \{([\s\S]*?)\n  \};/)[1];
  const seen = {current:''}, suppressed = {current:true}, present = vi.fn();
  let session = 'startup';
  const refresh = Function('API','setBrowserState','browserSeenSession','dispatchSurfacePresentation','browserSuppressed',
    'return async()=>{' + body + '}')({browser:{status:async()=>({running:true,session_id:session,presentation_requested:true})}},
      vi.fn(),seen,present,suppressed);
  await refresh();
  suppressed.current = false;
  await refresh();
  expect(present).not.toHaveBeenCalled();
  session = 'later-session';
  await refresh();
  expect(present).toHaveBeenCalledOnce();
});

test('the first status ignores an existing browser but a new foreground chat session presents', async()=> {
  const html = readFileSync(resolve('../design/Velllum/uploads/Vellum Default Re-designed.html'), 'utf8');
  const body = html.match(/const refreshBrowser = async \(\) => \{([\s\S]*?)\n  \};/)[1];
  const seen = {current:null}, present = vi.fn();
  let session = 'previous-window';
  const refresh = Function('API','setBrowserState','browserSeenSession','dispatchSurfacePresentation','browserSuppressed',
    'return async()=>{' + body + '}')({browser:{status:async()=>({running:true,session_id:session,presentation_requested:true})}},
      vi.fn(),seen,present,{current:false});
  await refresh(); await refresh();
  expect(present).not.toHaveBeenCalled();
  session = 'new-chat-request';
  await refresh();
  expect(present).toHaveBeenCalledOnce();
});

test('a fresh chat open request can reveal an existing session after a reload', async()=> {
  const html = readFileSync(resolve('../design/Velllum/uploads/Vellum Default Re-designed.html'), 'utf8');
  const body = html.match(/const refreshBrowser = async \(\) => \{([\s\S]*?)\n  \};/)[1];
  const seen = {current:null}, present = vi.fn();
  let revision = 1;
  const refresh = Function('API','setBrowserState','browserSeenSession','dispatchSurfacePresentation','browserSuppressed',
    'return async()=>{' + body + '}')({browser:{status:async()=>({running:true,session_id:'existing',presentation_requested:true,presentation_revision:revision})}},
      vi.fn(),seen,present,{current:false});
  await refresh(); await refresh();
  expect(present).not.toHaveBeenCalled();
  revision += 1;
  await refresh(); await refresh();
  expect(present).toHaveBeenCalledOnce();
});

test.each([false,true])('sidebar opens explicitly and a dismissal cancels a pending opening: %s', async cancelled=> {
  const html = readFileSync(resolve('../design/Velllum/uploads/Vellum Default Re-designed.html'), 'utf8');
  const body = html.match(/const openBrowser = async \(\) => \{([\s\S]*?)\n  \};/)[1];
  let resolveStatus;
  const refresh = vi.fn().mockImplementationOnce(()=>new Promise(resolve=>{resolveStatus=resolve;})).mockResolvedValue({running:true});
  const control = vi.fn(async()=>({status:'applied'})), present = vi.fn(), epoch = {current:0};
  const open = Function('API','browserSuppressed','browserRequestEpoch','dispatchSurfacePresentation','refreshBrowser','activeChatId','pushToast','setBrowserFeature',
    'return async()=>{' + body + '}')({browser:{control}}, {current:false},epoch,present,refresh,'chat',vi.fn(),vi.fn());
  const pending = open();
  expect(present).toHaveBeenCalledWith('right-panel',{visible:true,properties:{content:'browser'}},{notify:false,persistence:'session'});
  if (cancelled) epoch.current += 1;
  resolveStatus({running:false,available:true});
  await pending;
  if (cancelled) expect(control).not.toHaveBeenCalled();
  else expect(control).toHaveBeenCalledWith({operation:'open'},{invocation_conversation_id:'chat'});
});
