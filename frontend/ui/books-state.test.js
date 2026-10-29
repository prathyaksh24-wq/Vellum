import {expect, test, vi} from 'vitest';

test('confirmed shelf removal dispatches its App Action, closes details and refreshes the shelf', async()=>{
  await import('../../design/Velllum/uploads/components/books-state.js');
  const onAction=vi.fn(async()=>({action_id:'book.remove',status:'applied',result:{library:{removed_import_id:'book',removed:true}}}));
  const api={detail:vi.fn(async()=>({book:{id:'book',title:'A book'}})),list:vi.fn(async()=>({items:[],total:0,offset:0,limit:40}))};
  const controller=window.VellumBooks.createController(api,{onAction});
  await controller.open('book');
  expect(await controller.remove('book')).toBe(true);
  expect(onAction).toHaveBeenCalledWith('book.remove',{import_id:'book'},{confirmedFromUi:true});
  expect(controller.getState().detail).toBeNull();
  expect(controller.getState().total).toBe(0);
  expect(api.detail).toHaveBeenCalledTimes(1);
  controller.destroy();
});

test('failed removal keeps the selected book visible and reports the error', async()=>{
  await import('../../design/Velllum/uploads/components/books-state.js');
  const api={detail:vi.fn(async()=>({book:{id:'book'}})),list:vi.fn()};
  const onAction=vi.fn(async()=>({action_id:'book.remove',status:'failed',message:'Removal failed'}));
  const controller=window.VellumBooks.createController(api,{onAction});await controller.open('book');
  expect(await controller.remove('book')).toBe(false);
  expect(controller.getState().detail.id).toBe('book');
  expect(controller.getState().error).toBe('Removal failed');
  expect(api.list).not.toHaveBeenCalled();controller.destroy();
});

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

test('process and compile use App Actions and apply their canonical library projection', async () => {
  await import('../../design/Velllum/uploads/components/books-state.js');
  const onAction = vi.fn(async (actionId, args, options) => ({
    action_id:actionId,
    status:'applied',
    result:{library:{book:{id:args.import_id,state:'parsed'},status:'ready'}},
  }));
  const api = {
    list:vi.fn(async () => ({items:[{id:'book',state:'parsed'}],total:1,offset:0,limit:40})),
    detail:vi.fn(async () => ({book:{id:'book',state:'parsed'}})),
  };
  const controller = window.VellumBooks.createController(api, {onAction});
  expect(await controller.process('book')).toBe(true);
  expect(onAction).toHaveBeenCalledWith('book.process', {import_id:'book'}, {confirmedFromUi:true});
  expect(controller.getState().detail.state).toBe('parsed');
  controller.destroy();
});
