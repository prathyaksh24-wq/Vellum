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
    pushStatus:vi.fn(async()=>({endpoint_configured:true,active_channels:50,desired_channels:80,pending_channels:30,queued_uploads:2,last_received_at:'',warnings:[]})),
    creators:vi.fn(async()=>({configured:true,enabled:true,min_duration_seconds:180,pending_duration_checks:2,
      active_topics:['basketball'],baselined_channels:10,monitored_channels:50,creators:[],excluded:[],warnings:['Metadata unavailable.']})),
    historyStatus:vi.fn(async()=>({config:{url:'https://www.youtube.com/feed/history'},records:5,message:'Saved history'}))};
  const icon=()=>React.createElement('span');
  const Modal=Function('React','useState','useEffect','YouTubeAPI','GLogo','YTLogo','IcX',compiled)(React,React.useState,React.useEffect,api,icon,icon,icon);
  const container=document.createElement('div');document.body.append(container);
  const root=createRoot(container);
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  vi.useFakeTimers();
  try {
    await act(async()=>root.render(React.createElement(Modal,{onClose:vi.fn(),onConnected:vi.fn(),onAction:vi.fn()})));
    expect(container.querySelector('[role="alert"]').textContent).toContain('Google rejected');
    expect(container.textContent).toContain('videos longer than 3 minutes');
    expect(container.textContent).toContain('2 awaiting duration verification');
    expect(container.textContent).toContain('basketball');
    expect(container.textContent).toContain('Metadata unavailable.');
    expect(container.textContent).toContain('YouTube push: 50 of 80 channel subscriptions active');
    expect(container.textContent).toContain('30 awaiting verification; 2 received uploads awaiting processing');
    api.pushStatus.mockResolvedValue({endpoint_configured:true,active_channels:80,desired_channels:80,pending_channels:0,queued_uploads:0,warnings:[],
      transport:'hosted',saved_subscriptions:65,eligible_subscriptions:60,relay_retention_days:7,last_relay_sync_at:'2026-10-17T12:00:00Z'});
    await act(async()=>vi.advanceTimersByTimeAsync(10000));
    expect(container.textContent).toContain('YouTube push: 80 of 80 channel subscriptions active');
    expect(container.textContent).toContain('65 saved YouTube subscriptions; 60 eligible after exclusions');
    expect(container.textContent).toContain('Hosted receiver · 7-day catch-up while this laptop is off');
    expect([...container.querySelectorAll('button')].find(button=>button.textContent==='Reconnect with Google')).toBeTruthy();
    expect([...container.querySelectorAll('button')].find(button=>button.textContent==='Sync subscriptions').disabled).toBe(true);
  } finally {
    await act(async()=>root.unmount());container.remove();vi.useRealTimers();
  }
});
