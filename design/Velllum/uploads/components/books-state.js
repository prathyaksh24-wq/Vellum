(function () {
  function createController(api) {
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
    async function mutate(label, operation) {
      if (state.busy || !alive) return false;
      update({busy:label, error:''});
      try {
        const result = await operation();
        if (!alive) return false;
        await load(0);
        if (result.book?.id) await open(result.book.id);
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
      importEpub(file, consent) { return mutate('Importing EPUB', () => api.importEpub(file, consent)); },
      process(id) { return mutate('Processing book', () => api.process(id)); },
      compile(id) { return mutate('Building Book knowledge', () => api.compile(id)); },
      destroy() { alive = false; ++listVersion; ++detailVersion; listAbort?.abort(); detailAbort?.abort(); listeners.clear(); },
    };
  }
  window.VellumBooks = {...window.VellumBooks, createController};
})();
