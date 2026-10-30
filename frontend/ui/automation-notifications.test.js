import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {beforeEach,afterEach,test,expect,vi} from 'vitest';
const require = createRequire(import.meta.url);
const path = resolve(dirname(fileURLToPath(import.meta.url)),'../../design/Velllum/uploads/components/automation-notifications.jsx');
const nativeUint = globalThis.Uint8Array;
let compiled, scheduledCompiled, toastCompiled;
try {
  globalThis.Uint8Array = new TextEncoder().encode('').constructor;
  compiled = createRequire(require.resolve('vite'))('esbuild').transformSync(readFileSync(path,'utf8'),{loader:'jsx'}).code;
  const html = readFileSync(resolve(dirname(path),'../Vellum Default Re-designed.html'),'utf8');
  const toastStart=html.indexOf('{toast && <div className=');
  const toastExpression=html.slice(toastStart,html.indexOf('\n',toastStart)).trim().slice(1,-1);
  toastCompiled=createRequire(require.resolve('vite'))('esbuild').transformSync(
    'function Toast({toast,browserPanelVisible=false,view="chat"}) {return '+toastExpression+';}',{loader:'jsx'}).code;
  const source = html.slice(html.indexOf('const AUTOMATION_WEEKDAYS'),html.indexOf('const AutomationForm')) +
    html.slice(html.indexOf('const ScheduledView'),html.indexOf('const PETDEX_MANIFEST'));
  scheduledCompiled = createRequire(require.resolve('vite'))('esbuild').transformSync(source,{loader:'jsx'}).code;
} finally {globalThis.Uint8Array = nativeUint;}
let host,root,Center,History,Trigger,onAction,onPing,notifications,snapshot;
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-11T02:00:00Z')); globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  host=document.createElement('div'); document.body.append(host); root=createRoot(host);
  snapshot={items:[],unread_count:0}; notifications=vi.fn(async () => snapshot);
  window.VellumApi={plugins:{capabilities:vi.fn(async () => ({features:{automation_notifications:{enabled:true}}}))},automations:{notifications}};
  new Function('React','window',compiled)(React,window);
  ({AutomationNotificationCenter:Center,AutomationRunHistory:History,NotificationTrigger:Trigger}=window.VellumAutomationNotifications);
  onAction=vi.fn(async () => ({status:'applied'})); onPing=vi.fn();
});
afterEach(async () => {await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); vi.restoreAllMocks();});
function Harness(props) {
  const [state,setState]=React.useState({unread:0,open:false});
  return React.createElement(React.Fragment,null,
    React.createElement('nav',null,React.createElement(Trigger,{unread:state.unread,expanded:state.open,
      onClick:event=>window.dispatchEvent(new CustomEvent('vellum:notifications-open',{detail:{toggle:true,trigger:event.currentTarget}}))})),
    React.createElement(Center,{onAction,onPing,onStateChange:setState,...props}));
}
const renderCenter=async (props={}) => act(async () => root.render(React.createElement(Harness,props)));
const open=async () => act(async () => host.querySelector('.notification-trigger').click());
test('shows retained unread notifications without replaying pings and dispatches read actions',async () => {
  snapshot={items:[{id:'saved',title:'New upload',message:'Creator: Saved video',url:'https://www.youtube.com/watch?v=abcdefghijk',created_at:'2026-10-11T02:00:00Z'}],unread_count:1};
  await renderCenter(); expect(onPing).not.toHaveBeenCalled();
  expect(host.querySelector('.notification-trigger').getAttribute('aria-label')).toBe('Notifications, 1 recent unread');
  await open(); expect(host.textContent).toContain('Creator: Saved video');
  expect(host.querySelector('a').getAttribute('rel')).toBe('noopener noreferrer');
  await act(async () => [...host.querySelectorAll('button')].find(b => b.textContent==='Mark read').click());
  expect(onAction).toHaveBeenCalledWith('automation.notifications.read',{ids:['saved']},{notify:false});
});
test('push change events refresh immediately and close the stream on unmount',async () => {
  let change;
  const close = vi.fn();
  window.VellumApi.plugins.capabilities.mockResolvedValue({features:{automation_notifications:{enabled:true,endpoints:{events:'/api/automations/notifications/events'}}}});
  window.VellumApi.automations.notificationEvents=vi.fn(callback=>{change=callback;return close;});
  await renderCenter();
  snapshot={items:[{id:'push',message:'Creator: Push upload',created_at:new Date().toISOString()}],recent_unread_count:1};
  await act(async()=>change());
  expect(onPing).toHaveBeenCalledTimes(1);
  expect(onPing.mock.calls[0][0].message).toBe('Creator: Push upload');
  await act(async()=>change());
  expect(onPing).toHaveBeenCalledTimes(1);
  await act(async()=>root.render(null));
  expect(close).toHaveBeenCalledTimes(1);
});

test('a push arriving during an in-flight snapshot queues a fresh read',async () => {
  let change, finish;
  window.VellumApi.plugins.capabilities.mockResolvedValue({features:{automation_notifications:{enabled:true,endpoints:{events:'events'}}}});
  window.VellumApi.automations.notificationEvents=callback=>{change=callback;return ()=>{};};
  await renderCenter();
  notifications.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  await act(async()=>{change();});
  snapshot={items:[{id:'push',message:'Creator: Arrived during read',created_at:new Date().toISOString()}],recent_unread_count:1};
  const before=notifications.mock.calls.length;
  await act(async()=>{change();finish({items:[],recent_unread_count:0});});
  expect(notifications.mock.calls.length).toBe(before+1);
  expect(onPing).toHaveBeenCalledTimes(1);
});

test('a newly persisted upload pings once across repeated polling and retains its video link',async () => {
  await renderCenter();
  snapshot={items:[{id:'fresh',title:'New upload',message:'Creator: New video\nhttps://www.youtube.com/watch?v=abcdefghijk',url:'https://www.youtube.com/watch?v=abcdefghijk',created_at:'2026-10-11T02:00:00Z'}],unread_count:1};
  await act(async () => vi.advanceTimersByTimeAsync(15000));
  expect(onPing).toHaveBeenCalledTimes(1);
  expect(onPing.mock.calls[0][0].message).toBe('Creator: New video');
  await act(async () => vi.advanceTimersByTimeAsync(15000));
  expect(onPing).toHaveBeenCalledTimes(1);
  await open(); expect(host.querySelector('a').href).toContain('abcdefghijk');
});
test('failed read actions remain visible and unsafe links are never rendered',async () => {
  snapshot={items:[{id:'saved',title:'New upload',message:'<script>unsafe</script>',url:'javascript:alert(1)',created_at:'2026-10-11T02:00:00Z'}],unread_count:1};
  onAction.mockResolvedValue({status:'failed'}); await renderCenter(); await open();
  expect(host.querySelector('a')).toBeNull(); expect(host.querySelector('script')).toBeNull();
  await act(async () => [...host.querySelectorAll('button')].find(b => b.textContent==='Mark read').click());
  expect(host.querySelector('[role=alert]').textContent).toContain('Could not mark');
});

test('two-day-old unread items stay in dated History without a recent badge or a delayed ping',async () => {
  await renderCenter();
  snapshot={items:[{id:'old',title:'Upload',message:'Creator: Retained old upload',created_at:'2026-10-09T02:00:00Z'}],unread_count:1,recent_unread_count:0};
  await act(async()=>vi.advanceTimersByTimeAsync(15000));
  expect(onPing).not.toHaveBeenCalled();
  expect(host.querySelector('.notification-count')).toBeNull();
  await open();expect(host.textContent).toContain('You’re caught up.');
  expect(host.textContent).not.toContain('Retained old upload');
  await act(async()=>{[...host.querySelectorAll('button')].find(b=>b.textContent==='History').click();});
  await act(async()=>vi.advanceTimersByTimeAsync(0));
  expect(notifications).toHaveBeenLastCalledWith({view:'history',limit:50,offset:0,query:''});
  expect(host.textContent).toContain('Retained old upload');
  expect(host.querySelector('.notification-day h3').textContent).toContain('2026');
  expect(host.querySelector('time').getAttribute('datetime')).toBe('2026-10-09T02:00:00Z');
});

test('browser use keeps the bell in navigation and delivers fresh pings without replaying saved items',async () => {
  await renderCenter({browserVisible:true});
  expect(host.querySelector('nav .notification-trigger')).toBeTruthy();
  expect(host.querySelector('.automation-notifications .notification-trigger')).toBeNull();
  snapshot={items:[{id:'fresh',title:'Upload',message:'Creator: Fresh upload',created_at:'2026-10-11T02:00:15Z'}],unread_count:1};
  await act(async()=>vi.advanceTimersByTimeAsync(15000));
  expect(onPing).toHaveBeenCalledTimes(1);
  await act(async()=>window.dispatchEvent(new Event('vellum:notifications-open')));
  expect(host.querySelector('.notification-panel')).toBeTruthy();
  expect(host.textContent).toContain('Fresh upload');
  await renderCenter({browserVisible:false});
  expect(host.querySelector('.notification-panel')).toBeNull();
  await act(async()=>vi.advanceTimersByTimeAsync(15000));
  expect(onPing).toHaveBeenCalledTimes(1);
});

test('bulk dismissal scopes the read action to recent items, retaining old history',async () => {
  snapshot={items:[{id:'fresh',title:'Upload',message:'Creator: Fresh upload',created_at:'2026-10-11T02:00:00Z'}],unread_count:1};
  await renderCenter();await open();
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Mark recent read').click());
  expect(onAction).toHaveBeenCalledWith('automation.notifications.read',{recent:true},{notify:false});
});

test('an open History view updates on polling even when no unread items exist',async()=>{
  let saved=[];
  notifications.mockImplementation(async({view})=>({items:view==='history'?saved:[],
    recent_unread_count:0,total_count:saved.length,matched_count:saved.length,has_more:false}));
  await renderCenter();await open();
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='History').click());
  await act(async()=>vi.advanceTimersByTimeAsync(0));
  saved=[{id:'background',message:'Creator: Arrived while History was open',
    created_at:'2026-10-11T02:00:15Z',read_at:'2026-10-11T02:00:15Z'}];
  await act(async()=>vi.advanceTimersByTimeAsync(15000));
  expect(host.textContent).toContain('Arrived while History was open');
  expect(onPing).not.toHaveBeenCalled();
});

test('returning to a visible tab refreshes saved notifications immediately',async()=>{
  const visibility=vi.spyOn(document,'visibilityState','get').mockReturnValue('hidden');
  await renderCenter();
  await act(async()=>vi.advanceTimersByTimeAsync(15000));
  const calls=notifications.mock.calls.length;
  snapshot={items:[{id:'returned',message:'Creator: Returned to tab',created_at:'2026-10-11T02:00:15Z'}],recent_unread_count:1};
  visibility.mockReturnValue('visible');
  await act(async()=>document.dispatchEvent(new Event('visibilitychange')));
  expect(notifications.mock.calls.length).toBe(calls+1);
  expect(host.querySelector('.notification-count').textContent).toBe('1');
});

test('sidebar access reports an unavailable backend instead of claiming an empty inbox',async()=>{
  window.VellumApi.plugins.capabilities.mockResolvedValue({features:{automation_notifications:{enabled:false}}});
  await renderCenter({browserVisible:true});
  await act(async()=>window.dispatchEvent(new Event('vellum:notifications-open')));
  expect(host.querySelector('[role=alert]').textContent).toContain('not available');
  expect(host.textContent).not.toContain('You’re caught up.');
  expect(notifications).not.toHaveBeenCalled();
});
test('history displays ordered timestamps, durations, results, and failures',async () => {
  const runs=[{id:'old',status:'complete',started_at:'2026-10-10T02:00:00Z',finished_at:'2026-10-10T02:00:02.500Z',output:'1 delivered upload'},
    {id:'new',status:'failed',started_at:'2026-10-11T02:00:00Z',finished_at:'2026-10-11T02:00:03Z',error:'Provider unavailable'}];
  await act(async () => root.render(React.createElement(History,{runs})));
  expect(host.querySelector('.au-run-entry').textContent).toContain('Provider unavailable');
  expect(host.textContent).toContain('2.5 seconds'); expect(host.textContent).toContain('1 delivered upload');
  expect(host.querySelector('time').getAttribute('datetime')).toBe('2026-10-11T02:00:00Z');
  expect(host.textContent).toContain(Intl.DateTimeFormat().resolvedOptions().timeZone);
  expect(host.textContent).toContain('latest 100 runs retained');
});

test('Scheduled exposes Run now directly and History replaces the detail body with retained runs',async () => {
  const job={id:'creator-job',name:'Creator uploads',state:'active',instructions:'Check uploads',
    schedule:{kind:'interval',value:15,unit:'minutes'},destination:{kind:'notification'},
    run_history:[{id:'run-1',status:'complete',started_at:'2026-10-11T02:00:00Z',finished_at:'2026-10-11T02:00:02Z',output:'1 delivered upload'}]};
  const icons='const IcGCal=()=>null,IcSparkle=()=>null,IcSearch=()=>null,IcDots=()=>null,I=()=>null;';
  const Scheduled=new Function('React','API','AutomationRunHistory','const {useState,useEffect}=React;const MODELS=[];'+icons+scheduledCompiled+';return ScheduledView;')(React,{automations:{list:async()=>({automations:[job]})}},History);
  onAction.mockImplementation(async action => ({status:action==='automation.run'?'confirmation_required':'applied',result:{runs:job.run_history}}));
  await act(async () => root.render(React.createElement(Scheduled,{automations:[job],onAction})));
  const detail=host.querySelector('[aria-label="Scheduled task details"]');
  await act(async () => [...detail.querySelectorAll('button')].find(button=>button.textContent==='Run now').click());
  expect(onAction).toHaveBeenCalledWith('automation.run',{automation_id:job.id});
  await act(async () => [...detail.querySelectorAll('button')].find(button=>button.textContent==='History').click());
  expect(onAction).toHaveBeenCalledWith('automation.history',{automation_id:job.id},{notify:false});
  expect(detail.querySelector('.au-prompt-card')).toBeNull();
  expect(detail.querySelector('time').getAttribute('datetime')).toBe('2026-10-11T02:00:00Z');
  expect(detail.textContent).toContain('1 delivered upload');
  await act(async () => [...detail.querySelectorAll('button')].find(button=>button.textContent==='Back to details').click());
  expect(detail.textContent).toContain('Notification ping');
});


test('navigation trigger toggles the inbox and Escape returns keyboard focus',async()=>{
  await renderCenter();
  const trigger=host.querySelector('nav button');
  expect(trigger.getAttribute('aria-expanded')).toBe('false');
  await open();
  expect(trigger.getAttribute('aria-expanded')).toBe('true');
  expect(document.activeElement.getAttribute('aria-label')).toBe('Close notifications');
  await act(async()=>{
    trigger.dispatchEvent(new MouseEvent('pointerdown',{bubbles:true}));
    trigger.click();
  });
  expect(host.querySelector('.notification-panel')).toBeNull();
  await open();
  await act(async()=>window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'})));
  expect(document.activeElement).toBe(trigger);
});

test('compact navigation badge includes the full unread count in its accessible name',async()=>{
  await act(async()=>root.render(React.createElement(Trigger,{compact:true,unread:123,expanded:false})));
  const trigger=host.querySelector('button');
  expect(trigger.classList.contains('rail-btn')).toBe(true);
  expect(trigger.getAttribute('aria-label')).toBe('Notifications, 123 recent unread');
  expect(trigger.querySelector('.notification-count').textContent).toBe('99+');
});


test.each([[false,'chat'],[true,'chat'],[true,'music']])('live pings render separately from ordinary action messages (browser %s, page %s)',async(browserPanelVisible,view)=>{
  const Toast=new Function('React','IcBell',toastCompiled+';return Toast;')(React,()=>null);
  await act(async()=>root.render(React.createElement(Toast,{toast:{message:'New upload',notificationPing:true},browserPanelVisible,view})));
  const ping=host.querySelector('[role=status]');
  expect(ping.classList.contains('notification-ping')).toBe(true);
  expect(ping.classList.contains('browser-notification-ping')).toBe(browserPanelVisible && view!=='music');
  expect(ping.textContent).toContain('New upload');
  await act(async()=>root.render(React.createElement(Toast,{toast:{message:'Settings saved'},browserPanelVisible,view})));
  expect(host.querySelector('[role=status]').className).toBe('toast');
});


const pointer=(element,type,pointerType='mouse')=>{
  const event=new MouseEvent(type,{bubbles:true});
  Object.defineProperty(event,'pointerType',{value:pointerType});
  element.dispatchEvent(event);
};

test('hover previews without stealing focus and stays open while moving into the inbox',async()=>{
  await renderCenter();
  const bell=host.querySelector('.notification-trigger');
  bell.focus();
  await act(async()=>{pointer(bell,'pointerover');await vi.advanceTimersByTimeAsync(120);});
  let panel=host.querySelector('.notification-panel');
  expect(panel).toBeTruthy();
  expect(document.activeElement).toBe(bell);
  await act(async()=>{
    pointer(bell,'pointerout');
    await vi.advanceTimersByTimeAsync(100);
    pointer(panel,'pointerover');
    await vi.advanceTimersByTimeAsync(250);
  });
  expect(host.querySelector('.notification-panel')).toBe(panel);
  await act(async()=>{pointer(panel,'pointerout');await vi.advanceTimersByTimeAsync(200);});
  expect(host.querySelector('.notification-panel')).toBeNull();
});

test('clicking a hover preview pins it until the bell is clicked again',async()=>{
  await renderCenter();
  const bell=host.querySelector('.notification-trigger');
  await act(async()=>{pointer(bell,'pointerover');await vi.advanceTimersByTimeAsync(120);});
  await open();
  await act(async()=>{pointer(bell,'pointerout');await vi.advanceTimersByTimeAsync(500);});
  expect(host.querySelector('.notification-panel')).toBeTruthy();
  await open();
  expect(host.querySelector('.notification-panel')).toBeNull();
});

test('a quick pass over the bell or a touch pointer does not open the inbox',async()=>{
  await renderCenter();
  const bell=host.querySelector('.notification-trigger');
  await act(async()=>{pointer(bell,'pointerover');pointer(bell,'pointerout');await vi.advanceTimersByTimeAsync(300);});
  expect(host.querySelector('.notification-panel')).toBeNull();
  await act(async()=>{pointer(bell,'pointerover','touch');await vi.advanceTimersByTimeAsync(300);});
  expect(host.querySelector('.notification-panel')).toBeNull();
});

test('interacting with a preview pins it without moving focus away from the chosen control',async()=>{
  await renderCenter();
  await open();await open();
  const bell=host.querySelector('.notification-trigger');
  await act(async()=>{pointer(bell,'pointerover');await vi.advanceTimersByTimeAsync(120);});
  const history=[...host.querySelectorAll('.notification-panel button')].find(button=>button.textContent==='History');
  await act(async()=>{pointer(history,'pointerdown');history.focus();history.click();});
  await act(async()=>{pointer(host.querySelector('.notification-panel'),'pointerout');await vi.advanceTimersByTimeAsync(250);});
  expect(host.querySelector('.notification-panel')).toBeTruthy();
  expect(document.activeElement).toBe(history);
  expect(history.getAttribute('aria-pressed')).toBe('true');
  await act(async()=>document.body.dispatchEvent(new MouseEvent('pointerdown',{bubbles:true})));
  expect(host.querySelector('.notification-panel')).toBeNull();
});
