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
    async reader(id, signal) {
      const result = await client.request(root + bookPath(id) + '/reader', {signal});
      if (result?.schema_version !== 'books-reader-v1') throw new Error('Unsupported book reader response.');
      return result;
    },
    async readerSection(id, sectionId, signal) {
      const result = await client.request(root + bookPath(id) + '/reader/' + encodeURIComponent(sectionId), {signal});
      if (result?.schema_version !== 'books-reader-v1') throw new Error('Unsupported book reader response.');
      return result;
    },
    async readerText(id, signal) {
      const result = await client.request(root + bookPath(id) + '/reader/full', {signal});
      if (result?.schema_version !== 'books-reader-v1') throw new Error('Unsupported book reader response.');
      return result;
    },
    importFile(file, {title='', author='', cover=null, scanApproved, rightsAttestationVersion, localOnly=true} = {}) {
      if (!file || !/\.(epub|txt|md)$/i.test(file.name.trim())) throw new Error('Choose an EPUB, TXT or Markdown file.');
      const body = new FormData();
      body.set('file',file); body.set('title',title); body.set('author',author);
      if (cover) body.set('cover',cover);
      body.set('scan_approved','true'); body.set('rights_attestation_version',rightsAttestationVersion || 'local-epub-v1'); body.set('local_only',String(localOnly===true));
      return client.request('/api/app-actions/books/import',{method:'POST',body});
    },
    importUrl(url, {scanApproved,rightsAttestationVersion} = {}) {
      return client.request('/api/app-actions/books/import-url',client.jsonOptions('POST',{url,rights_attestation_version:rightsAttestationVersion || 'local-epub-v1',scan_approved:true}));
    },
    coverUrl(path) {
      if (!path || !path.startsWith(root + '/') || !/^\/api\/knowledge\/core\/books\/library\/[a-zA-Z0-9_-]+\/cover$/.test(path)) return '';
      return client.backendBase() + path;
    },
    importEpub(file, {scanApproved, rightsAttestationVersion, localOnly} = {}, signal) {
      if (!file || !/\.epub$/i.test(file.name.trim())) throw new Error('Choose an EPUB file.');
      const body = new FormData();
      body.set('file', file);
      body.set('scan_approved', 'true');
      body.set('rights_attestation_version', rightsAttestationVersion || 'local-epub-v1');
      body.set('local_only', String(localOnly === true));
      return client.request('/api/app-actions/books/import', {method:'POST', body, signal});
    },
    process(id) { return request(bookPath(id) + '/process', client.jsonOptions('POST', {confirm:true})); },
    compile(id) { return request(bookPath(id) + '/compile', client.jsonOptions('POST', {confirm:true})); },
  };
})();
