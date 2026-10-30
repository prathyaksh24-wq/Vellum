import {afterEach, beforeAll, beforeEach, expect, test, vi} from 'vitest';
import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

let root, host;
const Icon = () => null;
beforeAll(async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  window.matchMedia = vi.fn(() => ({matches:true, addListener(){}, removeListener(){}, addEventListener(){}, removeEventListener(){}}));
  URL.createObjectURL = vi.fn(() => 'blob:book-upload-test');
  URL.revokeObjectURL = vi.fn();
  HTMLDialogElement.prototype.showModal = function () {this.setAttribute('open', '');};
  HTMLDialogElement.prototype.close = function () {this.removeAttribute('open');};
  await import('../../design/Velllum/uploads/components/book-upload-entry.jsx');
  const source = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../design/Velllum/uploads/components/books-view.jsx'), 'utf8');
  const require = createRequire(import.meta.url);
  const uint = globalThis.Uint8Array;
  let code;
  try {
    globalThis.Uint8Array = new TextEncoder().encode('').constructor;
    code = createRequire(require.resolve('vite'))('esbuild').transformSync(source, {loader:'jsx'}).code;
  } finally {globalThis.Uint8Array = uint;}
  new Function('React', code)(React);
});
beforeEach(() => {
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => {await act(async () => root.unmount()); host.remove(); vi.useRealTimers();});

async function show(onImport = vi.fn(async () => true)) {
  const onClose = vi.fn();
  await act(async () => root.render(React.createElement(window.VellumUI.BooksImportDialog, {
    version:'local-epub-v1', onImport, onClose, icons:{Close:Icon, Upload:Icon},
  })));
  return {onImport, onClose};
}
async function drop(file) {
  const event = new Event('drop', {bubbles:true, cancelable:true});
  Object.defineProperty(event, 'dataTransfer', {value:{files:[file]}});
  await act(async () => host.querySelector('button[data-dragging]').dispatchEvent(event));
}

test('EPUB drop remains a draft until explicit submission, with local scanning already authorized', async () => {
  let finish;
  const onImport = vi.fn(() => new Promise(resolve => {finish = resolve;}));
  const {onClose} = await show(onImport);
  const file = new File(['EPUB fixture'], 'book.EPUB', {type:'application/octet-stream'});
  await drop(file);
  expect(host.textContent).toContain('book.EPUB');
  expect(onImport).not.toHaveBeenCalled();
  const submit = host.querySelector('form footer button:last-child');
  expect(submit.disabled).toBe(false);
  expect(host.textContent).not.toContain('Allow Vellum to run');
  await act(async () => submit.click());
  expect(onImport).toHaveBeenCalledExactlyOnceWith(file, {rightsAttestationVersion:'local-epub-v1', scanApproved:true, localOnly:true});
  expect(onClose).not.toHaveBeenCalled();
  await act(async () => finish(true));
  expect(onClose).toHaveBeenCalledOnce();
});

test('rejects non-EPUB drops and oversized EPUBs before an import action', async () => {
  const {onImport} = await show();
  await drop(new File(['pdf'], 'book.pdf', {type:'application/pdf'}));
  expect(host.querySelector('[role=alert]').textContent).toContain('Choose an EPUB');
  expect(host.querySelector('li')).toBeNull();
  const oversized = new File(['epub'], 'large.epub');
  Object.defineProperty(oversized, 'size', {value:64 * 1024 * 1024 + 1});
  await drop(oversized);
  expect(host.querySelector('[role=alert]').textContent).toContain('64 MB');
  expect(onImport).not.toHaveBeenCalled();
});

test('browse uses the same EPUB input and a selected file can be removed', async () => {
  vi.useFakeTimers();
  await show();
  const input = host.querySelector('input[type=file]');
  expect(input.accept).toContain('.epub');
  const browse = vi.spyOn(input, 'click');
  await act(async () => host.querySelector('button[data-dragging]').click());
  expect(browse).toHaveBeenCalledOnce();
  Object.defineProperty(input, 'files', {configurable:true, value:[new File(['epub'], 'selected.epub')]});
  await act(async () => input.dispatchEvent(new Event('change', {bubbles:true})));
  await act(async () => vi.advanceTimersByTime(2200));
  expect(host.textContent).toContain('selected.epub');
  await act(async () => host.querySelector('[aria-label="Remove selected.epub"]').click());
  await act(async () => vi.advanceTimersByTime(500));
  expect(host.querySelector('li')).toBeNull();
  expect(URL.revokeObjectURL).toHaveBeenCalled();
});
