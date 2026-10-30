(function () {
  function createController(api, options = {}) {
    let state = {items:[], total:0, offset:0, limit:40, loading:false, detail:null, detailLoading:false, busy:'', error:''};
    let alive = true, listVersion = 0, detailVersion = 0;
    let listAbort, detailAbort;
    const listeners = new Set();
    const update = patch => {
      if (!alive) return;
      state = {...state, ...patch};
      listeners.forEach(listener => listener(state));
    };
    async function load(offset = state.offset) {
      const version = ++listVersion;
      listAbort?.abort();
      listAbort = new AbortController();
      update({loading:true, error:''});
      try {
        const result = await api.list({offset, limit:state.limit, signal:listAbort.signal});
        if (version === listVersion) update({items:result.items, total:result.total, offset:result.offset, limit:result.limit, rightsAttestationVersion:result.rights_attestation_version, loading:false});
      } catch (error) {
        if (version === listVersion && error.name !== 'AbortError') update({loading:false, error:error.message || 'Books are unavailable.'});
      }
    }
    async function open(id) {
      const version = ++detailVersion;
      detailAbort?.abort();
      detailAbort = new AbortController();
      update({detail:null, detailLoading:true, error:''});
      try {
        const result = await api.detail(id, detailAbort.signal);
        if (version === detailVersion) update({detail:result.book, detailLoading:false});
      } catch (error) {
        if (version === detailVersion && error.name !== 'AbortError') update({detailLoading:false, error:error.message || 'Book is unavailable.'});
      }
    }
    async function mutate(label, operation, {applyReceipt = true, openResult = true, closeResult = false} = {}) {
      if (state.busy || !alive) return false;
      update({busy:label, error:''});
      try {
        const response = await operation();
        if (!alive) return false;
        if (response && response.action_id) {
          if (applyReceipt && options.onReceipt) options.onReceipt(response);
          if (response.status !== 'applied') throw new Error(response.message || 'Book operation failed.');
        }
        const result = response && response.result && response.result.library ? response.result.library : response;
        if (closeResult) {++detailVersion; detailAbort?.abort(); update({detail:null,detailLoading:false});}
        await load(0);
        update({lastBookResult:result});
        if (openResult && result.book?.id) await open(result.book.id);
        if (result.error_code) update({error:result.error_code});
        return !result.error_code;
      } catch (error) {
        update({error:error.message || 'Book operation failed.'});
        return false;
      } finally { update({busy:''}); }
    }
    return {
      getState:() => state,
      subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
      load, open,
      close() { ++detailVersion; detailAbort?.abort(); update({detail:null, detailLoading:false}); },
      importEpub(file, consent) { return mutate('Importing EPUB', () => api.importEpub(file, consent), {openResult:false}); },
      importFile(file, consent) { return mutate('Importing book', () => api.importFile(file, consent), {openResult:false}); },
      importUrl(url, consent) { return mutate('Importing book', () => api.importUrl(url, consent), {openResult:false}); },
      async saveProgress(id, progress) {
        if (!options.onAction) throw new Error('Reading position storage is unavailable.');
        const receipt = await options.onAction('book.reader.progress', {import_id:id, progress}, {notify:false});
        if (receipt?.status !== 'applied') throw new Error(receipt?.message || 'Reading position could not be saved.');
        update({items:state.items.map(book => book.id===id ? {...book,reader_progress:progress} : book)});
      },
      process(id) { return mutate('Processing book', () => options.onAction ? options.onAction('book.process', {import_id:id}, {confirmedFromUi:true}) : api.process(id), {applyReceipt:!options.onAction}); },
      compile(id) { return mutate('Building Book knowledge', () => options.onAction ? options.onAction('book.compile', {import_id:id}, {confirmedFromUi:true}) : api.compile(id), {applyReceipt:!options.onAction}); },
      remove(id) { return mutate('Removing book', () => {
        if (!options.onAction) throw new Error('Book removal is unavailable.');
        return options.onAction('book.remove', {import_id:id}, {confirmedFromUi:true});
      }, {applyReceipt:false,openResult:false,closeResult:true}); },
      destroy() { alive = false; ++listVersion; ++detailVersion; listAbort?.abort(); detailAbort?.abort(); listeners.clear(); },
    };
  }
  window.VellumBooks = {...window.VellumBooks, createController};
})();
