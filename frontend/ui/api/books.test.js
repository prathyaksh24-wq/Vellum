import { beforeEach, expect, test, vi } from 'vitest';

async function load(request) {
  vi.resetModules();
  window.VellumApi = { client: {
    request, backendBase: () => 'http://127.0.0.1:8000',
    jsonOptions: (method, body, signal) => ({method, body: JSON.stringify(body), signal}),
  }};
  await import('../../../design/Velllum/uploads/api/books.js');
  return window.VellumApi.books;
}
beforeEach(() => vi.restoreAllMocks());

test('lists installed Books through the canonical API without browser tenant overrides', async () => {
  const request = vi.fn(async () => ({schema_version:'books-library-v1', items:[], total:0, limit:40, offset:0}));
  const api = await load(request);
  const result = await api.list({offset:0, limit:40, user_id:'untrusted'});
  expect(request.mock.calls[0][0]).toBe('/api/knowledge/core/books/library?limit=40&offset=0');
  expect(result.items).toEqual([]);
});

test('encodes identities and permits cover assets only from the Books endpoint', async () => {
  const request = vi.fn(async () => ({schema_version:'books-library-v1',book:{id:'book'}}));
  const api = await load(request);
  await api.detail('a/b');
  expect(request.mock.calls[0][0]).toBe('/api/knowledge/core/books/library/a%2Fb');
  expect(api.coverUrl('/api/knowledge/core/books/library/book_1/cover')).toBe('http://127.0.0.1:8000/api/knowledge/core/books/library/book_1/cover');
  for (const path of ['https://remote.example/cover', '/api/knowledge/core/books/library/../private/cover', '//evil.example/cover', '/etc/passwd']) expect(api.coverUrl(path)).toBe('');
});

test('import uses multipart with explicit consent and no user identity', async () => {
  const request = vi.fn(async () => ({schema_version:'books-library-v1'}));
  const api = await load(request);
  const file = new File(['epub'], 'example.epub');
  expect(() => api.importEpub(file, {scanApproved:false})).toThrow(/Confirm/);
  await api.importEpub(file, {scanApproved:true, rightsAttestationVersion:'test-v1', localOnly:true, user_id:'untrusted'});
  const [path, opts] = request.mock.calls[0];
  expect(path).toBe('/api/knowledge/core/books/library/import');
  expect(opts.body.get('scan_approved')).toBe('true');
  expect(opts.body.get('local_only')).toBe('true');
  expect(opts.body.has('user_id')).toBe(false);
  expect(opts.headers).toBeUndefined();
});

test('rejects incompatible contracts and sends only explicit processing authority', async () => {
  const request = vi.fn().mockResolvedValueOnce({schema_version:'future-v2'}).mockResolvedValue({schema_version:'books-library-v1'});
  const api = await load(request);
  await expect(api.list()).rejects.toThrow(/Unsupported/);
  await api.process('installed');
  expect(request.mock.calls[1][0]).toBe('/api/knowledge/core/books/library/installed/process');
  expect(JSON.parse(request.mock.calls[1][1].body)).toEqual({confirm:true});
});
