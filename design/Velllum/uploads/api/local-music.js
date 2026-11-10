(function () {
  const client = window.VellumApi.client;
  const base = '/api/music/local';
  const headers = {'X-Vellum-Music':'1'};
  function mediaBase(){
    const url=new URL(client.backendBase());
    if(['localhost','127.0.0.1','[::1]'].includes(url.hostname) && ['localhost','127.0.0.1','[::1]'].includes(location.hostname))url.hostname=location.hostname;
    return url.origin;
  }
  function withArtwork(entry, origin) {
    return {
      ...entry,
      artwork_url:entry.artwork_url?.startsWith(base+'/artwork/') ? origin+entry.artwork_url : entry.artwork_url || '',
    };
  }
  let libraryRead;
  window.VellumApi.localMusic = {
    library: ({fresh=false}={}) => {
      if (fresh && libraryRead) return libraryRead.catch(() => {}).then(() => window.VellumApi.localMusic.library());
      libraryRead ??= client.request(base+'/library',{cache:'no-store'}).then(page => {
        const origin = mediaBase();
        const groups = items => items.map(group => ({...group, entries:group.entries.map(entry => withArtwork(entry, origin))}));
        return {...page, collections:groups(page.collections), pending_imports:groups(page.pending_imports || [])};
      }).finally(() => { libraryRead = undefined; });
      return libraryRead;
    },
    entry: (id, signal) => client.request(base+'/entry/'+encodeURIComponent(id),{cache:'no-store',signal})
      .then(entry => withArtwork(entry, mediaBase())),
    player: () => client.request(base+'/player',{cache:'no-store'}),
    report: body => client.request(base+'/player/report',{...client.jsonOptions('POST',body),headers:{...headers,'Content-Type':'application/json'}}),
    action: (name,args) => window.VellumApi.appActions.dispatch({action_id:'local_music.'+name,arguments:args},{source:'ui'}),
    search: query => client.request(base+'/search?'+new URLSearchParams({query}),{cache:'no-store'}),
    accountPlaylists: () => client.request(base+'/account-playlists',{cache:'no-store'}),
    upload: (file,entryId='') => {
      const form = new FormData(); form.append('file',file);form.append('entry_id',entryId);
      return client.request(base+'/files',{method:'POST',headers,body:form});
    },
    artworkUrl: id => mediaBase()+base+'/artwork/'+encodeURIComponent(id),
    audioUrl: id => mediaBase()+base+'/audio/'+encodeURIComponent(id),
    exportUrl: id => mediaBase()+base+'/export/'+encodeURIComponent(id),
  };
})();
