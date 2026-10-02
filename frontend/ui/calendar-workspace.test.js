import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach, beforeEach, expect, test, vi} from 'vitest';
let root,host,api,connected,onAction;
const empty={available:true,proposed:null};
const proposal={available:false,conflict_count:1,proposed:{start:'2026-10-02T15:30:00+05:30',end:'2026-10-02T16:00:00+05:30',time_zone:'Asia/Kolkata'}};
async function mount(props={}) {
  vi.resetModules(); window.React=React;window.VellumUI={};window.IS_REACT_ACT_ENVIRONMENT=true;globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  window.VellumApi={plugins:api,client:{backendBase:()=> 'http://127.0.0.1:8000'}};
  await import('../../design/Velllum/uploads/components/calendar-workspace.jsx');
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  await act(async()=>root.render(React.createElement(window.VellumUI.CalendarWorkspace,{onAction,...props})));
}
function button(text){return [...host.querySelectorAll('button')].find(b=>b.textContent===text);}
async function click(text){await act(async()=>button(text).click());}
async function fill(label,value){const el=host.querySelector(`[aria-label="${label}"]`);await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,value);el.dispatchEvent(new Event('input',{bubbles:true}));});}
async function draft(){await fill('Event title','Vellum QA');await fill('Event start','2026-10-02T15:00');await fill('Event end','2026-10-02T15:30');}
beforeEach(()=>{
  connected=true; api={
    calendarStatus:vi.fn(async()=>({configured:true,connected,enabled:true,time_zone:'Asia/Kolkata',status:connected?'ready':'not_connected'})),
    calendarCalendars:vi.fn(async()=>({items:[{id:'primary',summary:'Primary',primary:true}]})),
    calendarEvents:vi.fn(async()=>({items:[]})),calendarOAuthStart:vi.fn(async()=>({authorization_url:'https://accounts.google.com/oauth'})),
    calendarAvailability:vi.fn(async()=>empty),calendarCreateEvent:vi.fn(async()=>({event:{id:'new'}})),
    calendarUpdateEvent:vi.fn(async()=>({event:{id:'event-1'}})),calendarDeleteEvent:vi.fn(async()=>({deleted:true})),calendarDisconnect:vi.fn(async()=>{connected=false;})
  };
  onAction=vi.fn(async(id,body={},options={})=>{
    let result;
    if(id==='calendar.connection.start') result={connection:await api.calendarOAuthStart()};
    else if(id==='calendar.connection.disconnect') result=await api.calendarDisconnect();
    else if(id==='calendar.event.create') result=await api.calendarCreateEvent({...body,confirm:options.confirmedFromUi===true});
    else if(id==='calendar.event.update') {const {event_id,...patch}=body;result=await api.calendarUpdateEvent(event_id,{...patch,confirm:options.confirmedFromUi===true});}
    else if(id==='calendar.event.delete') result=await api.calendarDeleteEvent(body.event_id,body.calendar_id,options.confirmedFromUi===true);
    return {status:'applied',result};
  });
});
afterEach(async()=>{if(root)await act(async()=>root.unmount());host?.remove();root=null;vi.useRealTimers();vi.restoreAllMocks();});
test('shows live Connected status and uses existing API adapter',async()=>{await mount();expect(host.textContent).toContain('Connected');expect(host.textContent).toContain('Asia/Kolkata');expect(api.calendarEvents).toHaveBeenCalled();});
test('disabled plugin keeps connection and does not read events',async()=>{await mount({enabled:false});expect(host.textContent).toContain('Disabled');expect(api.calendarEvents).not.toHaveBeenCalled();expect(button('Create event')).toBeUndefined();});
test('OAuth button opens consent and polling updates Connected automatically',async()=>{
  vi.useFakeTimers();connected=false;const popup={location:{href:''},close:vi.fn()};vi.spyOn(window,'open').mockReturnValue(popup);
  await mount();await click('Connect Google Calendar');expect(api.calendarOAuthStart).toHaveBeenCalledOnce();expect(popup.location.href).toContain('accounts.google.com');
  connected=true;await act(async()=>vi.advanceTimersByTimeAsync(1600));expect(host.textContent).toContain('Connected');expect(button('Connect Google Calendar')).toBeUndefined();
});
test('ignores completion messages from unrelated origins',async()=>{await mount();const count=api.calendarStatus.mock.calls.length;await act(async()=>window.dispatchEvent(new MessageEvent('message',{origin:'https://example.com',data:{type:'vellum:google-calendar-oauth-complete'}})));expect(api.calendarStatus.mock.calls.length).toBe(count);});
test('checks availability and requires confirmation before create',async()=>{await mount();await draft();await click('Create event');expect(api.calendarAvailability).toHaveBeenCalledOnce();expect(api.calendarCreateEvent).not.toHaveBeenCalled();await click('Confirm');expect(api.calendarCreateEvent).toHaveBeenCalledWith(expect.objectContaining({summary:'Vellum QA',confirm:true}));});
test('collision asks about an alternative without writing',async()=>{api.calendarAvailability.mockResolvedValue(proposal);await mount();await draft();await click('Create event');expect(host.textContent).toContain('Does that time work');expect(api.calendarCreateEvent).not.toHaveBeenCalled();await click('Use suggested time');expect(api.calendarCreateEvent).not.toHaveBeenCalled();await click('Confirm');expect(api.calendarCreateEvent).toHaveBeenCalledWith(expect.objectContaining({start:proposal.proposed.start}));});
test('late conflict replaces confirmation with a new proposal',async()=>{api.calendarCreateEvent.mockRejectedValue(Object.assign(new Error('Conflict'),{status:409,detail:{availability:proposal}}));await mount();await draft();await click('Create event');await click('Confirm');expect(host.textContent).toContain('Does that time work');expect(button('Confirm')).toBeUndefined();});
test('search and upcoming controls submit bounded queries',async()=>{await mount();await fill('Find calendar events','Review');await click('Find events');expect(api.calendarEvents.mock.lastCall[0].query).toBe('Review');await click('Upcoming events');expect(api.calendarEvents.mock.lastCall[0].query).toBe('');});
test('disconnect updates status immediately',async()=>{await mount();await click('Disconnect');expect(host.textContent).toContain('Not connected');expect(api.calendarDisconnect).toHaveBeenCalledOnce();});
test('edit and delete use exact event ids and explicit confirmation',async()=>{
  api.calendarEvents.mockResolvedValue({items:[{id:'event-1',calendar_id:'primary',summary:'Review',start:'2026-10-02T15:00:00+05:30',end:'2026-10-02T15:30:00+05:30'}]});
  await mount();await click('Edit');await fill('Event title','Updated');await click('Update event');expect(api.calendarUpdateEvent).not.toHaveBeenCalled();await click('Confirm');expect(api.calendarUpdateEvent).toHaveBeenCalledWith('event-1',expect.objectContaining({summary:'Updated',confirm:true}));
  await click('Delete');expect(api.calendarDeleteEvent).not.toHaveBeenCalled();await click('Confirm');expect(api.calendarDeleteEvent).toHaveBeenCalledWith('event-1','primary',true);
});

test('all calendar mutations dispatch canonical confirmed App Actions',async()=>{await mount();await draft();await click('Create event');expect(onAction).not.toHaveBeenCalled();await click('Confirm');expect(onAction).toHaveBeenCalledWith('calendar.event.create',expect.objectContaining({summary:'Vellum QA'}),{confirmedFromUi:true});});
test('late conflict action receipt asks again without claiming a write',async()=>{onAction.mockResolvedValue({status:'applied',result:{changed:false,availability:proposal}});await mount();await draft();await click('Create event');await click('Confirm');expect(host.textContent).toContain('Does that time work');expect(button('Confirm')).toBeUndefined();});
test('failed action keeps the draft and shows the truthful failure',async()=>{onAction.mockResolvedValue({status:'failed',message:'Google Calendar is unreachable'});await mount();await draft();await click('Create event');await click('Confirm');expect(host.textContent).toContain('Google Calendar is unreachable');expect(button('Confirm')).toBeDefined();});

test('shows synced calendars by default and keeps mutation targets on the source calendar',async()=>{
  api.calendarEvents.mockResolvedValue({items:[{id:'f1-1',calendar_id:'f1',calendar_label:'Formula 1',access_role:'reader',summary:'F1 Practice',start:'2026-10-02T13:30:00+05:30',end:'2026-10-02T14:30:00+05:30'}]});
  await mount();expect(api.calendarEvents.mock.lastCall[0].calendar_id).toBe('all');expect(host.textContent).toContain('Formula 1');expect(button('Edit').disabled).toBe(true);expect(button('Delete').disabled).toBe(true);
});
test('delete from aggregate view uses source calendar not all',async()=>{
  api.calendarEvents.mockResolvedValue({items:[{id:'secondary-event',calendar_id:'secondary',calendar_label:'Work',access_role:'owner',summary:'Review',start:'2026-10-02T13:30:00+05:30',end:'2026-10-02T14:30:00+05:30'}]});
  await mount();await click('Delete');await click('Confirm');expect(onAction).toHaveBeenCalledWith('calendar.event.delete',{calendar_id:'secondary',event_id:'secondary-event'},{confirmedFromUi:true});
});
