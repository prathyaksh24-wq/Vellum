import {beforeEach, describe, expect, test, vi} from 'vitest';

async function adapter(receipt={status:'applied'}) {
  vi.resetModules();
  window.VellumApi = {client:{request:vi.fn().mockResolvedValue({})}, appActions:{dispatch:vi.fn().mockResolvedValue(receipt)}};
  await import('../../../design/Velllum/uploads/api/browser.js');
  return window.VellumApi.browser;
}
describe('Browser adapter contract', () => {
  beforeEach(() => vi.restoreAllMocks());
  test('reads live status/frame without caches and routes mutations through App Actions', async () => {
    const api = await adapter();
    await api.status(); await api.frame();
    expect(window.VellumApi.client.request.mock.calls).toEqual([['/api/browser/status',{cache:'no-store'}],['/api/browser/frame',{cache:'no-store'}]]);
    await api.control({operation:'take_over'}, {source:'nlp', invocation_conversation_id:'chat-1'});
    expect(window.VellumApi.appActions.dispatch).toHaveBeenCalledWith({action_id:'browser.session.control',action_version:'1',arguments:{operation:'take_over'}},{source:'ui',invocation_conversation_id:'chat-1'});
  });
  test('surfaces failed receipts instead of pretending an action happened', async () => {
    const api = await adapter({status:'failed',message:'The page changed.'});
    await expect(api.control({operation:'click'})).rejects.toThrow('The page changed.');
  });
  test('maps contain-scaled preview coordinates and rejects letterbox clicks', async () => {
    const api = await adapter();
    const rect = {left:100,top:50,width:640,height:600};
    const frame = {width:1280,height:800};
    expect(api.point(rect,frame,420,350)).toEqual({x:640,y:400});
    expect(api.point(rect,frame,420,60)).toBeNull();
    expect(api.point(rect,frame,741,350)).toBeNull();
  });
});
