(function () {
  const client = window.VellumApi.client;
  const base = '/api/music/local';
  const headers = {'X-Vellum-Music':'1'};
  function mediaBase(){
    const url=new URL(client.backendBase());
    if(['localhost','127.0.0.1','[::1]'].includes(url.hostname) && ['localhost','127.0.0.1','[::1]'].includes(location.hostname))url.hostname=location.hostname;
    return url.origin;
  }
  window.VellumApi.localMusic = {
    library: () => client.request(base+'/library',{cache:'no-store'}).then(page=>({...page,collections:page.collections.map(group=>({...group,entries:group.entries.map(entry=>({...entry,artwork_url:entry.artwork_url?.startsWith(base+'/artwork/')?mediaBase()+entry.artwork_url:entry.artwork_url || ''}))}))})),
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
