import {expect, test, vi} from 'vitest';

test('loads canonical Books state without inventing entries on a network error', async () => {
  await import('../../design/Velllum/uploads/components/books-state.js');
  const api = {list:vi.fn().mockResolvedValueOnce({items:[{id:'installed',title:'An installed book'}],total:1,offset:0,limit:40}).mockRejectedValueOnce(new Error('Offline'))};
  const controller = window.VellumBooks.createController(api);
  await controller.load();
  expect(controller.getState().items.map(book => book.id)).toEqual(['installed']);
  await controller.load();
  expect(controller.getState().error).toBe('Offline');
  expect(controller.getState().items.map(book => book.id)).toEqual(['installed']);
  controller.destroy();
});

test('late detail responses do not replace a newer selection or reopen a closed detail', async () => {
  await import('../../design/Velllum/uploads/components/books-state.js');
  let resolveA, resolveB;
  const api = {detail:vi.fn().mockImplementationOnce(() => new Promise(resolve => {resolveA=resolve;})).mockImplementationOnce(() => new Promise(resolve => {resolveB=resolve;}))};
  const controller = window.VellumBooks.createController(api);
  const a = controller.open('a'), b = controller.open('b');
  resolveB({book:{id:'b'}}); await b;
  resolveA({book:{id:'a'}}); await a;
  expect(controller.getState().detail.id).toBe('b');
  controller.close();
  expect(controller.getState().detail).toBeNull();
  controller.destroy();
});

test('processing is single flight and refreshes backend state after completion', async () => {
  await import('../../design/Velllum/uploads/components/books-state.js');
  let finish;
  const api = {
    process:vi.fn(() => new Promise(resolve => {finish=resolve;})),
    list:vi.fn(async () => ({items:[{id:'book',state:'parsed'}],total:1,offset:0,limit:40})),
    detail:vi.fn(async () => ({book:{id:'book',state:'parsed'}})),
  };
  const controller = window.VellumBooks.createController(api);
  const first = controller.process('book');
  expect(controller.getState().busy).toBe('Processing book');
  expect(await controller.process('book')).toBe(false);
  expect(api.process).toHaveBeenCalledTimes(1);
  finish({book:{id:'book'},status:'parsed'}); await first;
  expect(controller.getState().detail.state).toBe('parsed');
  expect(controller.getState().busy).toBe('');
  controller.destroy();
});
