(function () {
  const client = window.VellumApi.client;
  const root = '/api/knowledge/core/books/library';
  const schema = 'books-library-v1';

  async function request(path, options) {
    const result = await client.request(root + path, options);
    if (!result || result.schema_version !== schema) throw new Error('Unsupported Books API response.');
    return result;
  }
  function bookPath(id) {
    if (!id || typeof id !== 'string') throw new Error('Book identity is required.');
    return '/' + encodeURIComponent(id);
  }
  window.VellumApi.books = {
    list({limit = 40, offset = 0, signal} = {}) {
      return request('?' + new URLSearchParams({limit, offset}), {signal});
    },
    detail(id, signal) { return request(bookPath(id), {signal}); },
    coverUrl(path) {
      if (!path || !path.startsWith(root + '/') || !/^\/api\/knowledge\/core\/books\/library\/[a-zA-Z0-9_-]+\/cover$/.test(path)) return '';
      return client.backendBase() + path;
    },
    importEpub(file, {scanApproved, rightsAttestationVersion, localOnly} = {}, signal) {
      if (!file || !/\.epub$/i.test(file.name)) throw new Error('Choose an EPUB file.');
      if (scanApproved !== true || !rightsAttestationVersion) throw new Error('Confirm import permissions and local scanning.');
      const body = new FormData();
      body.set('file', file);
      body.set('scan_approved', 'true');
      body.set('rights_attestation_version', rightsAttestationVersion);
      body.set('local_only', String(localOnly === true));
      return request('/import', {method:'POST', body, signal});
    },
    process(id) { return request(bookPath(id) + '/process', client.jsonOptions('POST', {confirm:true})); },
    compile(id) { return request(bookPath(id) + '/compile', client.jsonOptions('POST', {confirm:true})); },
  };
})();
