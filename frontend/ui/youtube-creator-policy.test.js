import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect, test, vi} from 'vitest';

test('a rejected Google grant exposes reconnect while showing the saved long-form policy and coverage', async () => {
  const html=readFileSync(resolve('../design/Velllum/uploads/Vellum Default Re-designed.html'),'utf8');
  const source=html.slice(html.indexOf('const YouTubeConnectModal ='),html.indexOf('const SRC_DOMAINS ='))+'\nreturn YouTubeConnectModal;';
  const compiled=execFileSync(process.execPath,['-e',`
    const {createRequire}=require('node:module');
    const esbuild=createRequire(require.resolve('vite'))('esbuild');
    process.stdout.write(esbuild.transformSync(process.argv[1],{loader:'jsx'}).code);
  `,source],{encoding:'utf8'});
  const api={status:vi.fn(async()=>({connected:true,configured:true,authorization_required:true,channel_title:'Saved identity'})),
    creators:vi.fn(async()=>({configured:true,enabled:true,min_duration_seconds:180,pending_duration_checks:2,
      active_topics:['basketball'],baselined_channels:10,monitored_channels:50,creators:[],excluded:[],warnings:['Metadata unavailable.']})),
    historyStatus:vi.fn(async()=>({config:{url:'https://www.youtube.com/feed/history'},records:5,message:'Saved history'}))};
  const icon=()=>React.createElement('span');
  const Modal=Function('React','useState','useEffect','YouTubeAPI','GLogo','YTLogo','IcX',compiled)(React,React.useState,React.useEffect,api,icon,icon,icon);
  const container=document.createElement('div');document.body.append(container);
  const root=createRoot(container);
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  try {
    await act(async()=>root.render(React.createElement(Modal,{onClose:vi.fn(),onConnected:vi.fn(),onAction:vi.fn()})));
    expect(container.querySelector('[role="alert"]').textContent).toContain('Google rejected');
    expect(container.textContent).toContain('videos longer than 3 minutes');
    expect(container.textContent).toContain('2 awaiting duration verification');
    expect(container.textContent).toContain('basketball');
    expect(container.textContent).toContain('Metadata unavailable.');
    expect([...container.querySelectorAll('button')].find(button=>button.textContent==='Reconnect with Google')).toBeTruthy();
    expect([...container.querySelectorAll('button')].find(button=>button.textContent==='Sync subscriptions').disabled).toBe(true);
  } finally {
    await act(async()=>root.unmount());container.remove();
  }
});
