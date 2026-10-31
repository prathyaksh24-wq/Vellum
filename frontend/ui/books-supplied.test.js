import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {BookRuntimeContext} from '../../design/Velllum/uploads/components/bookshelf/VellumRuntime';
import {BookReader} from '../../design/Velllum/uploads/components/bookshelf/reader/BookReader';
import {ImportBooksDialog} from '../../design/Velllum/uploads/components/bookshelf/components/ImportBooksDialog';
import {BriefingBookshelf} from '../../design/Velllum/uploads/components/bookshelf/components/BriefingBookshelf';
import {BriefingOpenOverlay} from '../../design/Velllum/uploads/components/bookshelf/components/BriefingOpenOverlay';

const engineRecords=vi.hoisted(()=>[]);
vi.mock('../../design/Velllum/uploads/components/bookshelf/shelf/BriefingShelfEngine',()=>({
  BriefingShelfEngine:class {
    constructor(canvas,books,callbacks){this.books=books;this.callbacks=callbacks;this.setTheme=vi.fn();this.matchVellumBackground=vi.fn();this.dispose=vi.fn();engineRecords.push(this);callbacks.onReady();}
    updateBooks(books){this.books=books;}
    setSpotlightIndex(){}
  },
}));

let root,host,runtime;
const book={id:'book-1',title:'Complete book',author:'Real author',source:'upload',gutenbergId:null,hasCover:false,coverUrl:null,coverAspect:null,spineColor:'',accentColor:'',inkColor:'',contentChars:1000,progress:0,dateAdded:'2026-10-28',content:'CHAPTER I\n\nThe first complete chapter.\n\nCHAPTER II\n\nThe second complete chapter.\n\nCHAPTER III\n\nThe final complete chapter.'};
beforeEach(()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  HTMLElement.prototype.scrollTo=function({top}){this.scrollTop=top;};
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  runtime={books:[],loading:false,theme:'dark',rightsVersion:'local-epub-v1',refresh:vi.fn(),setTheme:vi.fn(),saveProgress:vi.fn(async()=>{}),importFile:vi.fn(async()=>({title:'Real Book'})),importText:vi.fn(),importUrl:vi.fn(),loadBook:vi.fn()};
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.useRealTimers();});
async function render(component){await act(async()=>root.render(React.createElement(BookRuntimeContext.Provider,{value:runtime},component)));}

test('the supplied reader exposes complete chapters, contents and original typography controls',async()=>{
  await render(React.createElement(BookReader,{book}));
  expect(host.textContent).toContain('The first complete chapter.');
  await act(async()=>host.querySelector('[aria-label="Next chapter"]').click());
  expect(host.textContent).toContain('The second complete chapter.');
  await act(async()=>host.querySelector('[aria-label="Next chapter"]').click());
  expect(host.textContent).toContain('The final complete chapter.');
  expect(host.querySelector('[aria-label="Next chapter"]').disabled).toBe(true);
  await act(async()=>host.querySelector('[aria-label="Text size L"]').click());
  expect(localStorage.getItem('bookshelf.reader.fontSize')).toBe('18.5');
});

test('the supplied reader saves progress through its canonical runtime callback',async()=>{
  vi.useFakeTimers();
  await render(React.createElement(BookReader,{book}));
  await act(async()=>vi.advanceTimersByTime(32));
  const scroll=host.querySelector('div.overflow-y-auto');
  Object.defineProperty(scroll,'scrollHeight',{value:1000});
  Object.defineProperty(scroll,'clientHeight',{value:400});
  scroll.scrollTop=300;
  await act(async()=>scroll.dispatchEvent(new Event('scroll')));
  await act(async()=>vi.advanceTimersByTime(1250));
  expect(runtime.saveProgress).toHaveBeenCalledWith('book-1',expect.any(Number));
  expect(runtime.saveProgress.mock.calls[0][1]).toBeGreaterThan(0);
});

test('reopening the supplied reader restores the saved chapter and scroll position',async()=>{
  vi.useFakeTimers();
  await render(React.createElement(BookReader,{book:{...book,progress:.5}}));
  const scroll=host.querySelector('div.overflow-y-auto');
  Object.defineProperty(scroll,'scrollHeight',{value:1000});
  Object.defineProperty(scroll,'clientHeight',{value:400});
  await act(async()=>vi.advanceTimersByTime(32));
  expect(host.textContent).toContain('The second complete chapter.');
  expect(scroll.scrollTop).toBe(300);
});

test('the supplied upload imports an explicit selection without repeated permission prompts',async()=>{
  const onImported=vi.fn(),onOpenChange=vi.fn();
  await render(React.createElement(ImportBooksDialog,{open:true,onOpenChange,onImported}));
  const dialog=document.querySelector('[role="dialog"]');
  const submit=[...dialog.querySelectorAll('button')].find(button=>button.textContent==='Add to shelf');
  expect(dialog.querySelectorAll('input[type=checkbox]')).toHaveLength(0);
  const file=new File(['fixture'],'Real Book.epub',{type:'application/octet-stream'});
  const event=new Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(event,'dataTransfer',{value:{files:[file]}});
  const drop=[...dialog.querySelectorAll('button')].find(button=>button.textContent.includes('Choose a book file'));
  await act(async()=>drop.dispatchEvent(event));
  expect(dialog.textContent).toContain('Real Book.epub');
  expect(runtime.importFile).not.toHaveBeenCalled();
  expect(submit.disabled).toBe(false);
  await act(async()=>submit.click());
  expect(runtime.importFile).toHaveBeenCalledWith(file,'','',null,{rightsAttestationVersion:'local-epub-v1',scanApproved:true,localOnly:true});
  expect(onImported).toHaveBeenCalledOnce();
  expect(onOpenChange).toHaveBeenCalledWith(false);
});

test('choosing another file replaces the title and clears metadata belonging to the previous file',async()=>{
  await render(React.createElement(ImportBooksDialog,{open:true,onOpenChange:vi.fn(),onImported:vi.fn()}));
  const dialog=document.querySelector('[role="dialog"]');
  const input=dialog.querySelector('input[type=file]');
  const choose=async(name)=>{Object.defineProperty(input,'files',{value:[new File(['fixture'],name)],configurable:true});await act(async()=>input.dispatchEvent(new Event('change',{bubbles:true})));};
  await choose('First Book.epub');
  expect(dialog.querySelector('#import-title').value).toBe('First Book');
  await choose('Second Book.epub');
  expect(dialog.querySelector('#import-title').value).toBe('Second Book');
  const drop=[...dialog.querySelectorAll('button')].find(button=>button.textContent.includes('Second Book.epub'));
  const event=new Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(event,'dataTransfer',{value:{files:[new File(['third'],'Third Book.epub')]}});
  await act(async()=>drop.dispatchEvent(event));
  expect(dialog.querySelector('#import-title').value).toBe('Third Book');
});

test('the supplied width correction keeps real cover proportions and changes theme without rebuilding the shelf',async()=>{
  engineRecords.length=0;
  const books=[{...book,coverUrl:'http://127.0.0.1:8000/api/knowledge/core/books/library/book-1/cover',coverAspect:2/3}];
  const onActiveIndexChange=vi.fn();
  await render(React.createElement(BriefingBookshelf,{books,activeIndex:0,onActiveIndexChange,spotlightIndex:0,darkMode:true}));
  expect(engineRecords).toHaveLength(1);
  const engine=engineRecords[0],volume=engine.books[0];
  expect((volume.coverPlaneWidth-.065)/(volume.height-.065)).toBeCloseTo(2/3,8);
  expect(volume.coverImage).toBe(books[0].coverUrl);
  expect(engine.setTheme).toHaveBeenLastCalledWith('dark');
  expect(engine.matchVellumBackground).toHaveBeenCalled();
  await render(React.createElement(BriefingBookshelf,{books,activeIndex:0,onActiveIndexChange,spotlightIndex:0,darkMode:false}));
  expect(engineRecords).toHaveLength(1);
  expect(engine.setTheme).toHaveBeenLastCalledWith('light');
});

test('rebuilding an open shelf after a removal clears focused mode so the canvas remains clickable',async()=>{
  engineRecords.length=0;
  const onModeChange=vi.fn(),onActiveIndexChange=vi.fn();
  const books=[book,{...book,id:'book-2',title:'Another book'}];
  await render(React.createElement(BriefingBookshelf,{books,activeIndex:0,onModeChange,onActiveIndexChange,darkMode:true}));
  const engine=engineRecords[0];
  await act(async()=>engine.callbacks.onMode('open',0));
  expect(host.querySelector('canvas').classList.contains('pointer-events-none')).toBe(true);
  await render(React.createElement(BriefingBookshelf,{books:books.slice(1),activeIndex:0,onModeChange,onActiveIndexChange,darkMode:true}));
  expect(host.querySelector('canvas').classList.contains('pointer-events-none')).toBe(false);
});

test('reader removal is cancelled by Keep, Escape, or five seconds without activity',async()=>{
  vi.useFakeTimers();runtime.loadBook=vi.fn(async()=>book);
  const onBack=vi.fn(),onRemove=vi.fn(async()=>{});
  await render(React.createElement(BriefingOpenOverlay,{mode:'open',transition:null,book,onBack,onRemove}));
  const trigger=()=>host.querySelector('.bk-reader-remove-trigger');
  const prompt=()=>host.querySelector('[role=alertdialog]');
  await act(async()=>trigger().click());expect(prompt().textContent).toContain('Remove this book?');
  expect(document.activeElement.textContent).toBe('Keep');
  await act(async()=>host.querySelector('.bk-reader-keep').click());expect(prompt()).toBeNull();
  await act(async()=>trigger().click());
  await act(async()=>window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true})));
  expect(prompt()).toBeNull();expect(onBack).not.toHaveBeenCalled();
  await act(async()=>trigger().click());
  await act(async()=>vi.advanceTimersByTime(4000));
  await act(async()=>window.dispatchEvent(new Event('pointermove')));
  await act(async()=>vi.advanceTimersByTime(4000));expect(prompt()).not.toBeNull();
  await act(async()=>vi.advanceTimersByTime(1000));expect(prompt()).toBeNull();
  expect(onRemove).not.toHaveBeenCalled();
});

test('reader removal requires the red confirmation and dispatches the selected book once',async()=>{
  runtime.loadBook=vi.fn(async()=>book);let finish;
  const onRemove=vi.fn(()=>new Promise(resolve=>{finish=resolve;})),onBack=vi.fn();
  await render(React.createElement(BriefingOpenOverlay,{mode:'open',transition:null,book,onBack,onRemove}));
  await act(async()=>host.querySelector('.bk-reader-remove-trigger').click());
  expect(onRemove).not.toHaveBeenCalled();
  await act(async()=>host.querySelector('.bk-reader-remove-confirm').click());
  expect(onRemove).toHaveBeenCalledWith(book.id);
  expect(host.querySelector('.bk-reader-remove-confirm').disabled).toBe(true);
  await act(async()=>host.querySelector('.bk-reader-remove-confirm').click());
  expect(onRemove).toHaveBeenCalledTimes(1);
  await act(async()=>finish());
});
