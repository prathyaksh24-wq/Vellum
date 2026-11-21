import {test, expect} from 'vitest';
import '../../design/Velllum/uploads/components/response-progress.js';

const compacting = {id: 'compaction-1', type: 'context_compacting', name: 'conversation_context',
  label: 'Compacting context', status: 'in_progress'};

test('automatic compaction shows as one live row that completes in place', () => {
  const {workItems, workLabel} = window.VellumUI;
  const live = workItems({activity: [compacting]});
  expect(live).toHaveLength(1);
  expect(workLabel(live[0])).toBe('Compacting context');

  const done = workItems({activity: [compacting, {...compacting, type: 'context_compacted', status: 'completed',
    label: 'Compacted context · 12 earlier messages summarized'}]});
  expect(done).toHaveLength(1);
  expect(workLabel(done[0])).toBe('Compacted context · 12 earlier messages summarized');
});

test('routine context preparation stays out of the progress list', () => {
  const rows = window.VellumUI.workItems({activity: [
    {id: 'context-1', type: 'context_preparing', status: 'in_progress', label: 'Preparing conversation context'},
    {id: 'context-1', type: 'context_ready', status: 'completed', label: 'Conversation context ready'}]});
  expect(rows).toHaveLength(0);
});
