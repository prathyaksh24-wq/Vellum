import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {describe, expect, test, vi} from 'vitest';

const source = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../design/Velllum/uploads/Vellum Default Re-designed.html'), 'utf8');
const receiptHandler = source.split('  const showAppActionReceipt = ')[1].split('  const applyAppActionReceipt = ')[0].trim().replace(/;$/, '');

function harness() {
  const pushToast = vi.fn();
  const show = new Function('pushToast', 'getTauriInvoke', `return (${receiptHandler});`)(pushToast, () => null);
  return {pushToast, show};
}

describe('quiet workspace transitions', () => {
  test.each(['ui.sidebar.set', 'ui.surface.configure', 'conversation.open', 'agent.select', 'ui.adaptive.apply'])('%s succeeds without a toast', action_id => {
    const {show, pushToast} = harness();
    show({action_id, status:'applied', message:'Sidebar hidden.', result:{}, undo:{token:'undo'}});
    expect(pushToast).not.toHaveBeenCalled();
  });

  test('a first automatic layout change during navigation is also quiet', () => {
    const {show, pushToast} = harness();
    show({action_id:'ui.adaptive.apply', status:'applied', message:'Sidebar hidden.', result:{adaptive_rule:{first_use:true}}, undo:{token:'undo'}});
    expect(pushToast).not.toHaveBeenCalled();
  });

  test.each(['failed', 'unavailable', 'confirmation_required'])('%s remains visible for layout actions', status => {
    const {show, pushToast} = harness();
    show({action_id:'ui.surface.configure', status, message:'Could not change settings.', result:{}});
    expect(pushToast).toHaveBeenCalledOnce();
  });

  test('destructive and device-setting outcomes remain visible', () => {
    const {show, pushToast} = harness();
    show({action_id:'conversation.delete', status:'applied', message:'Deleted.', result:{}});
    show({action_id:'settings.device.update', status:'applied', message:'Background changed.', result:{}});
    expect(pushToast).toHaveBeenCalledTimes(2);
  });

  test('Appearance omits layout and Adaptive UI controls', () => {
    const appearance = source.split("{tab === 'Appearance' && (")[1].split("{tab === '")[0];
    expect(appearance).not.toContain('Workspace layout controls');
    expect(appearance).not.toContain('Adaptive UI');
    expect(appearance).toContain('Live &amp; animated');
    expect(appearance).toContain('Static scenes');
  });

  test('a real conversation-save failure is visible and preserves the submitted messages', async () => {
    const code = source.split('  const saveConversation = ')[1].split('  const attachKnowledgeContext = ')[0].trim().replace(/;$/, '');
    const conversation = {id:'save-test',messages:[{role:'user',text:'hide sidebar'}]};
    const save = vi.fn(async () => {throw new Error('file locked');});
    const notify = vi.fn(), refresh = vi.fn(), warn = vi.fn();
    const handler = new Function('FEATURE_FLAGS','API','scheduleConversationLibraryRefresh','pushToast','console',`return (${code});`)({realConversations:true},{conversations:{save}},refresh,notify,{warn});
    await handler(conversation);
    expect(save).toHaveBeenCalledWith(conversation);
    expect(conversation.messages[0].text).toBe('hide sidebar');
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({message:expect.stringContaining("couldn't be saved")}));
    expect(refresh).not.toHaveBeenCalled();
  });
});
