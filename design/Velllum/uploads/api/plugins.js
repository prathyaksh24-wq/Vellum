(function () {
  var client = window.VellumApi.client;
  var playbackCommand;
  var artworkCache=new Map(),artworkQueue=new Map(),artworkTimer,artworkRequests=0;
  function flushArtwork() {
    clearTimeout(artworkTimer);
    if(artworkRequests>=2 || !artworkQueue.size)return;
    var ids=Array.from(artworkQueue.keys()).slice(0,4),batch=new Map();
    ids.forEach(id=>{batch.set(id,artworkQueue.get(id));artworkQueue.delete(id);});
    artworkRequests++;
    var abort=new AbortController(),deadline=setTimeout(()=>abort.abort(),12000);
    client.request('/api/plugins/spotify/artwork?'+new URLSearchParams({ids:ids.join(',')}),{cache:'no-store',signal:abort.signal})
      .then(page=>{
        var items=new Map((page.items || []).map(item=>[item.id,item]));
        batch.forEach((resolve,id)=>{
          var item=items.get(id) || {id,artwork_url:''},cached=artworkCache.get(id);
          if(item.pending && (resolve.attempts || 0)<30){
            resolve.attempts=(resolve.attempts || 0)+1;
            setTimeout(()=>{artworkQueue.set(id,resolve);flushArtwork();},250);return;
          }
          if(cached)cached.expires=Date.now()+(item.artwork_url?3600000:30000);
          resolve(item);
        });
      },()=>batch.forEach((resolve,id)=>resolve({id,artwork_url:''})))
      .finally(()=>{clearTimeout(deadline);artworkRequests--;flushArtwork();});
    if(artworkQueue.size && artworkRequests<2)flushArtwork();
  }
  function spotifyTrackArtwork(id) {
    if(!/^[A-Za-z0-9]{22}$/.test(id))return Promise.resolve({id,artwork_url:''});
    var prior=artworkCache.get(id);
    if(prior && prior.expires>Date.now())return prior.promise;
    var promise=new Promise(resolve=>artworkQueue.set(id,resolve));
    artworkCache.set(id,{promise,expires:Date.now()+60000});
    while(artworkCache.size>512)artworkCache.delete(artworkCache.keys().next().value);
    clearTimeout(artworkTimer);artworkTimer=setTimeout(flushArtwork,25);
    return promise;
  }
  function spotifyAction(body) {
    var key = JSON.stringify(body);
    if (playbackCommand) {
      if (playbackCommand.key === key) return playbackCommand.promise;
      return Promise.reject(new Error('Wait for the current Spotify control to finish.'));
    }
    var request = {request_id:'spotify_' + crypto.randomUUID(), action_id:'spotify.playback.control', arguments:body};
    var promise = window.VellumApi.appActions.dispatch(request, {source:'ui'}).then(receipt => {
      if (receipt.status !== 'applied') throw new Error(receipt.message || 'Spotify control failed.');
      return receipt.result;
    }).finally(() => { playbackCommand = null; });
    playbackCommand = {key, promise};
    return promise;
  }
  window.VellumApi.plugins = {
    connectorTools: (pluginId, connector) => client.request('/api/plugins/mcp/connectors/'+encodeURIComponent(pluginId)+'/'+encodeURIComponent(connector)+'/tools', {cache:'no-store'}),
    navigateToGoogle: flow => {
      var target = new URL(flow.authorization_url);
      if (target.origin + target.pathname !== 'https://accounts.google.com/o/oauth2/v2/auth') throw new Error('The Google sign-in address is invalid. Try again.');
      if (flow.browser_opened) return;
      if (window.VellumDesktop && window.VellumDesktop.invoke) throw new Error('The default browser could not be opened. Use Continue to Google to retry.');
      // Same-tab navigation survives asynchronous setup without popup blockers.
      // The loopback callback returns to this Vellum page after sign-in.
      window.location.assign(target.href);
    },
    googleStatus: () => client.request('/api/plugins/google/status', {headers:{'X-Vellum-Google':'1'},cache:'no-store'}),
    googleCatalog: params => client.request('/api/plugins/google/catalog?'+new URLSearchParams(params), {headers:{'X-Vellum-Google':'1'},cache:'no-store'}),
    googleOAuthStatus: flowId => client.request('/api/plugins/google/oauth/status?flow_id='+encodeURIComponent(flowId), {headers:{'X-Vellum-Google':'1'},cache:'no-store'}),
    googleRead: body => client.request('/api/plugins/google/read', {...client.jsonOptions('POST',body),headers:{'Content-Type':'application/json','X-Vellum-Google':'1'},cache:'no-store'}),
    linearStatus: () => client.request('/api/plugins/linear/status', {headers:{'X-Vellum-Linear':'1'}, cache:'no-store'}),
    githubStatus: () => client.request('/api/plugins/github/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    keyedMcpStatus: provider => client.request('/api/plugins/keyed/'+encodeURIComponent(provider)+'/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    keyedMcpTools: (provider,refresh=false) => client.request('/api/plugins/keyed/'+encodeURIComponent(provider)+'/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    keyedMcpStage: (provider,token) => client.request('/api/plugins/keyed/'+encodeURIComponent(provider)+'/credentials/stage', {...client.jsonOptions('POST',{token}), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    keyedMcpDiscard: (provider,credential_id) => client.request('/api/plugins/keyed/'+encodeURIComponent(provider)+'/credentials/discard', {...client.jsonOptions('POST',{credential_id}), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    linearOAuthWindowUrl: flowId => client.backendBase()+'/api/plugins/linear/oauth/open?flow_id='+encodeURIComponent(flowId),
    serpapiStatus: () => client.request('/api/plugins/serpapi/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    serpapiMcpTools: (refresh=false) => client.request('/api/plugins/serpapi/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    serpapiMcpRead: body => client.request('/api/plugins/serpapi/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    serpapiStage: token => client.request('/api/plugins/serpapi/credentials/stage', {...client.jsonOptions('POST',{token}), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    serpapiDiscard: credential_id => client.request('/api/plugins/serpapi/credentials/discard', {...client.jsonOptions('POST',{credential_id}), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    asanaStatus: () => client.request('/api/plugins/asana/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    hubspotStatus: () => client.request('/api/plugins/hubspot/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    asanaMcpTools: (refresh=false) => client.request('/api/plugins/asana/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    hubspotMcpTools: (refresh=false) => client.request('/api/plugins/hubspot/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    asanaMcpRead: body => client.request('/api/plugins/asana/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    hubspotMcpRead: body => client.request('/api/plugins/hubspot/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    asanaOAuthStatus: flowId => client.request('/api/plugins/asana/oauth/status?flow_id='+encodeURIComponent(flowId), {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    hubspotOAuthStatus: flowId => client.request('/api/plugins/hubspot/oauth/status?flow_id='+encodeURIComponent(flowId), {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    asanaOAuthWindowUrl: flowId => client.backendBase()+'/api/plugins/asana/oauth/open?flow_id='+encodeURIComponent(flowId),
    hubspotOAuthWindowUrl: flowId => client.backendBase()+'/api/plugins/hubspot/oauth/open?flow_id='+encodeURIComponent(flowId),
    asanaStage: body => client.request('/api/plugins/asana/credentials/stage', {...client.jsonOptions('POST',body),headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'},cache:'no-store'}),
    hubspotStage: body => client.request('/api/plugins/hubspot/credentials/stage', {...client.jsonOptions('POST',body),headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'},cache:'no-store'}),
    asanaDiscard: credential_id => client.request('/api/plugins/asana/credentials/discard', {...client.jsonOptions('POST',{credential_id}),headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'},cache:'no-store'}),
    hubspotDiscard: credential_id => client.request('/api/plugins/hubspot/credentials/discard', {...client.jsonOptions('POST',{credential_id}),headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'},cache:'no-store'}),
    clickupStatus: () => client.request('/api/plugins/clickup/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    clickupMcpTools: (refresh=false) => client.request('/api/plugins/clickup/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    clickupMcpRead: body => client.request('/api/plugins/clickup/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    clickupOAuthStatus: flowId => client.request('/api/plugins/clickup/oauth/status?flow_id='+encodeURIComponent(flowId), {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    clickupOAuthWindowUrl: flowId => client.backendBase()+'/api/plugins/clickup/oauth/open?flow_id='+encodeURIComponent(flowId),
    swiggyStatus: () => client.request('/api/plugins/swiggy/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    zomatoStatus: () => client.request('/api/plugins/zomato/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    districtStatus: () => client.request('/api/plugins/district/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    vercelStatus: () => client.request('/api/plugins/vercel/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    swiggyMcpTools: (refresh=false) => client.request('/api/plugins/swiggy/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    zomatoMcpTools: (refresh=false) => client.request('/api/plugins/zomato/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    districtMcpTools: (refresh=false) => client.request('/api/plugins/district/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    vercelMcpTools: (refresh=false) => client.request('/api/plugins/vercel/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    swiggyMcpRead: body => client.request('/api/plugins/swiggy/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    zomatoMcpRead: body => client.request('/api/plugins/zomato/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    districtMcpRead: body => client.request('/api/plugins/district/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    vercelMcpRead: body => client.request('/api/plugins/vercel/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    swiggyOAuthStatus: flowId => client.request('/api/plugins/swiggy/oauth/status?flow_id='+encodeURIComponent(flowId), {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    zomatoOAuthStatus: flowId => client.request('/api/plugins/zomato/oauth/status?flow_id='+encodeURIComponent(flowId), {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    districtOAuthStatus: flowId => client.request('/api/plugins/district/oauth/status?flow_id='+encodeURIComponent(flowId), {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    vercelOAuthStatus: flowId => client.request('/api/plugins/vercel/oauth/status?flow_id='+encodeURIComponent(flowId), {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    swiggyOAuthWindowUrl: flowId => client.backendBase()+'/api/plugins/swiggy/oauth/open?flow_id='+encodeURIComponent(flowId),
    zomatoOAuthWindowUrl: flowId => client.backendBase()+'/api/plugins/zomato/oauth/open?flow_id='+encodeURIComponent(flowId),
    districtOAuthWindowUrl: flowId => client.backendBase()+'/api/plugins/district/oauth/open?flow_id='+encodeURIComponent(flowId),
    vercelOAuthWindowUrl: flowId => client.backendBase()+'/api/plugins/vercel/oauth/open?flow_id='+encodeURIComponent(flowId),
    supabaseStatus: () => client.request('/api/plugins/supabase/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    supabaseMcpTools: (refresh=false) => client.request('/api/plugins/supabase/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    supabaseMcpRead: body => client.request('/api/plugins/supabase/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    supabaseOAuthStatus: flowId => client.request('/api/plugins/supabase/oauth/status?flow_id='+encodeURIComponent(flowId), {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    supabaseOAuthWindowUrl: flowId => client.backendBase()+'/api/plugins/supabase/oauth/open?flow_id='+encodeURIComponent(flowId),
    exaStatus: () => client.request('/api/plugins/exa/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    exaMcpTools: (refresh=false) => client.request('/api/plugins/exa/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    exaMcpRead: body => client.request('/api/plugins/exa/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    exaOAuthStatus: flowId => client.request('/api/plugins/exa/oauth/status?flow_id='+encodeURIComponent(flowId), {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    exaOAuthWindowUrl: flowId => client.backendBase()+'/api/plugins/exa/oauth/open?flow_id='+encodeURIComponent(flowId),
    tavilyStatus: () => client.request('/api/plugins/tavily/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    tavilyMcpTools: (refresh=false) => client.request('/api/plugins/tavily/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    tavilyMcpRead: body => client.request('/api/plugins/tavily/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    tavilyOAuthStatus: flowId => client.request('/api/plugins/tavily/oauth/status?flow_id='+encodeURIComponent(flowId), {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    tavilyOAuthWindowUrl: flowId => client.backendBase()+'/api/plugins/tavily/oauth/open?flow_id='+encodeURIComponent(flowId),
    firecrawlStatus: () => client.request('/api/plugins/firecrawl/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    firecrawlOAuthStatus: flowId => client.request('/api/plugins/firecrawl/oauth/status?flow_id='+encodeURIComponent(flowId), {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    firecrawlOAuthWindowUrl: flowId => client.backendBase()+'/api/plugins/firecrawl/oauth/open?flow_id='+encodeURIComponent(flowId),
    firecrawlMcpTools: (refresh=false) => client.request('/api/plugins/firecrawl/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    firecrawlMcpRead: body => client.request('/api/plugins/firecrawl/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    apifyStatus: () => client.request('/api/plugins/apify/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    apifyOAuthStatus: flowId => client.request('/api/plugins/apify/oauth/status?flow_id='+encodeURIComponent(flowId), {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    apifyOAuthWindowUrl: flowId => client.backendBase()+'/api/plugins/apify/oauth/open?flow_id='+encodeURIComponent(flowId),
    apifyMcpTools: (refresh=false) => client.request('/api/plugins/apify/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    apifyMcpRead: body => client.request('/api/plugins/apify/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    notionStatus: () => client.request('/api/plugins/notion/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    notionOAuthStatus: flowId => client.request('/api/plugins/notion/oauth/status?flow_id='+encodeURIComponent(flowId), {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    notionOAuthWindowUrl: flowId => client.backendBase()+'/api/plugins/notion/oauth/open?flow_id='+encodeURIComponent(flowId),
    notionMcpTools: (refresh=false) => client.request('/api/plugins/notion/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    notionMcpRead: body => client.request('/api/plugins/notion/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    airtableStatus: () => client.request('/api/plugins/airtable/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    airtableOAuthStatus: flowId => client.request('/api/plugins/airtable/oauth/status?flow_id='+encodeURIComponent(flowId), {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    airtableOAuthWindowUrl: flowId => client.backendBase()+'/api/plugins/airtable/oauth/open?flow_id='+encodeURIComponent(flowId),
    airtableMcpTools: (refresh=false) => client.request('/api/plugins/airtable/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    airtableMcpRead: body => client.request('/api/plugins/airtable/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    slackStatus: () => client.request('/api/plugins/slack/status', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    slackSetup: () => client.request('/api/plugins/slack/setup', {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    slackOAuthStatus: flowId => client.request('/api/plugins/slack/oauth/status?flow_id='+encodeURIComponent(flowId), {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    slackOAuthWindowUrl: flowId => client.backendBase()+'/api/plugins/slack/oauth/open?flow_id='+encodeURIComponent(flowId),
    slackMcpTools: (refresh=false) => client.request('/api/plugins/slack/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    slackMcpRead: body => client.request('/api/plugins/slack/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    githubOAuthStatus: flowId => client.request('/api/plugins/github/oauth/status?flow_id='+encodeURIComponent(flowId), {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    githubOAuthWindowUrl: flowId => client.backendBase()+'/api/plugins/github/oauth/open?flow_id='+encodeURIComponent(flowId),
    githubMcpTools: (refresh=false) => client.request('/api/plugins/github/mcp/tools?refresh='+refresh, {headers:{'X-Vellum-Accounts':'1'}, cache:'no-store'}),
    githubMcpRead: body => client.request('/api/plugins/github/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Accounts':'1'}, cache:'no-store'}),
    linearOAuthStatus: flow_id => client.request('/api/plugins/linear/oauth/status?flow_id='+encodeURIComponent(flow_id), {headers:{'X-Vellum-Linear':'1'}, cache:'no-store'}),
    linearMcpTools: () => client.request('/api/plugins/linear/mcp/tools', {headers:{'X-Vellum-Linear':'1'}, cache:'no-store'}),
    linearMcpRead: body => client.request('/api/plugins/linear/mcp/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-Linear':'1'}, cache:'no-store'}),
    productHuntStatus: () => client.request('/api/plugins/producthunt/status', {headers:{'X-Vellum-ProductHunt':'1'}, cache:'no-store'}),
    productHuntStage: token => client.request('/api/plugins/producthunt/credentials/stage', {...client.jsonOptions('POST',{token}), headers:{'Content-Type':'application/json','X-Vellum-ProductHunt':'1'}, cache:'no-store'}),
    productHuntDiscard: credential_id => client.request('/api/plugins/producthunt/credentials/discard', {...client.jsonOptions('POST',{credential_id}), headers:{'Content-Type':'application/json','X-Vellum-ProductHunt':'1'}, cache:'no-store'}),
    productHuntRead: body => client.request('/api/plugins/producthunt/read', {...client.jsonOptions('POST',body), headers:{'Content-Type':'application/json','X-Vellum-ProductHunt':'1'}, cache:'no-store'}),
    spotifyStatus: () => client.request('/api/plugins/spotify/status'),
    spotifyStart: clientId => client.request('/api/plugins/spotify/oauth/start', client.jsonOptions('POST', {client_id: clientId || ''})),
    spotifyLogout: () => client.request('/api/plugins/spotify/logout', client.jsonOptions('POST')),
    spotifyPlayer: details => client.request('/api/plugins/spotify/player' + (details ? '?details=true' : '')),
    spotifyAction,
    spotifyPlaylistEdit: args => window.VellumApi.appActions.dispatch({action_id:'spotify.playlist.edit', arguments:args}, {source:'ui'}),
    spotifyPlaylistConfirm: (receipt, args) => window.VellumApi.appActions.confirm(receipt.confirmation.token, {action_id:'spotify.playlist.edit', arguments:args}, {source:'ui'}),
    spotifyPlaylistCancel: receipt => window.VellumApi.appActions.cancel(receipt.confirmation.token, {source:'ui'}),
    spotifyBrowse: (params, signal) => client.request('/api/plugins/spotify/browse?' + new URLSearchParams(params || {}), {signal}),
    spotifyTrackArtwork,
    spotifySearch: (params, signal) => client.request('/api/plugins/spotify/search?' + new URLSearchParams(params || {}), {signal}),
    spotifyPlaybackToken: forceRefresh => client.request('/api/plugins/spotify/playback/token', {
      ...client.jsonOptions('POST', {force_refresh: !!forceRefresh}), headers: {'Content-Type': 'application/json', 'X-Vellum-Spotify-Playback': '1'}, cache: 'no-store', signal: AbortSignal.timeout(25000),
    }),
    spotifyPlaybackDevice: body => client.request('/api/plugins/spotify/playback/device', {
      ...client.jsonOptions('POST', body), headers: {'Content-Type': 'application/json', 'X-Vellum-Spotify-Playback': '1'}, signal: AbortSignal.timeout(10000),
    }),
    list: function () { return client.request("/api/plugins", {signal:AbortSignal.timeout(30000)}); },
    setEnabled: function (id, enabled) { return client.request("/api/plugins/" + encodeURIComponent(id) + "/state", client.jsonOptions("POST", {enabled:!!enabled})); },
    skills: function () { return client.request("/api/skills"); },
    skillsOverview: function (signal) { return client.request("/api/skills/v2/overview", { signal: signal }); },
    skillsCatalog: function (params, signal) {
      var query = new URLSearchParams(params || {}).toString();
      return client.request("/api/skills/v2/catalog" + (query ? "?" + query : ""), { signal: signal });
    },
    skillDetail: function (name, signal) { return client.request("/api/skills/" + encodeURIComponent(name), { signal: signal }); },
    skillAction: function (body, signal) { return client.request("/api/skills/action", client.jsonOptions("POST", body, signal)); },
    pendingApprove: function (id) { return client.request("/api/skills/v2/pending/" + encodeURIComponent(id) + "/approve", client.jsonOptions("POST")); },
    pendingReject: function (id) { return client.request("/api/skills/v2/pending/" + encodeURIComponent(id) + "/reject", client.jsonOptions("POST")); },
    duplicateDecision: function (id, decision, reason) { return client.request("/api/skills/v2/duplicates/" + encodeURIComponent(id) + "/decision", client.jsonOptions("POST", {decision:decision, reason:reason || ""})); },
    hubSearch: function (body, signal) { return client.request("/api/skills/v2/hub/search", client.jsonOptions("POST", body, signal)); },
    hubInspect: function (identifier, signal) { return client.request("/api/skills/v2/hub/inspect", client.jsonOptions("POST", {identifier:identifier}, signal)); },
    hubMutation: function (action, body) { return client.request("/api/skills/v2/hub/" + action, client.jsonOptions("POST", body)); },
    learn: function (source, threadId, category) { return client.request("/api/skills/learn", client.jsonOptions("POST", {source:source, thread_id:threadId || "skills-hub", category:category || "community"})); },
    capabilities: function () { return client.request("/api/capabilities"); },
    youtubeStatus: function () { return client.request("/api/plugins/youtube/status"); },
    youtubeCreatorTracking: function (limit) { return client.request("/api/plugins/youtube/creators?limit=" + encodeURIComponent(limit || 20), {cache:"no-store"}); },
    youtubeHistoryStatus: function () { return client.request("/api/plugins/youtube/history/status", {cache:'no-store'}); },
    youtubeIntelligenceStatus: function () { return client.request("/api/plugins/youtube/intelligence/status"); },
    youtubeOAuthStart: function () { return client.request("/api/plugins/youtube/oauth/start", client.jsonOptions("POST")); },
    youtubeSync: function (idempotencyKey) { return client.request("/api/plugins/youtube/sync", client.jsonOptions("POST", {idempotency_key:idempotencyKey || ""})); },
    youtubeDisconnect: function () { return client.request("/api/plugins/youtube/connection", {method:"DELETE"}); },
    calendarStatus: function (probe) { return client.request("/api/plugins/google-calendar/status?probe=" + String(probe === true)); },
    calendarOAuthStart: function () { return client.request("/api/plugins/google-calendar/oauth/start", client.jsonOptions("POST")); },
    calendarDisconnect: function () { return client.request("/api/plugins/google-calendar/connection", {method:"DELETE"}); },
    calendarCalendars: function () { return client.request("/api/plugins/google-calendar/calendars"); },
    calendarEvents: function (params) { var query = new URLSearchParams(params || {}).toString(); return client.request("/api/plugins/google-calendar/events" + (query ? "?" + query : "")); },
    calendarEvent: function (eventId, calendarId) { return client.request("/api/plugins/google-calendar/events/" + encodeURIComponent(eventId) + "?calendar_id=" + encodeURIComponent(calendarId || "primary")); },
    calendarFreeBusy: function (body) { return client.request("/api/plugins/google-calendar/free-busy", client.jsonOptions("POST", body)); },
    calendarAvailability: function (body) { return client.request("/api/plugins/google-calendar/availability", client.jsonOptions("POST", body)); },
    calendarCreateEvent: function (body) { return client.request("/api/plugins/google-calendar/events", client.jsonOptions("POST", body)); },
    calendarUpdateEvent: function (eventId, body) { return client.request("/api/plugins/google-calendar/events/" + encodeURIComponent(eventId), client.jsonOptions("PATCH", body)); },
    calendarDeleteEvent: function (eventId, calendarId, confirm) { return client.request("/api/plugins/google-calendar/events/" + encodeURIComponent(eventId) + "/delete", client.jsonOptions("POST", {calendar_id:calendarId || "primary", confirm:confirm === true})); },
    discordStatus: function () { return client.request("/api/plugins/discord/status"); },
    discordInstall: function () { return client.request("/api/plugins/discord/install"); },
    discordGuilds: function () { return client.request("/api/plugins/discord/guilds"); },
    discordChannels: function (guildId) { return client.request("/api/plugins/discord/guilds/" + encodeURIComponent(guildId) + "/channels"); },
    discordMessages: function (channelId, limit) { return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/messages?limit=" + encodeURIComponent(limit || 20)); },
    discordArchiveStatus: function () { return client.request("/api/plugins/discord/archive/status"); },
    discordArchiveHistory: function (params) { var query = new URLSearchParams(params || {}).toString(); return client.request("/api/plugins/discord/archive/history" + (query ? "?" + query : "")); },
    discordImportArchive: function (file) { return client.request("/api/plugins/discord/archive/import", {method:"POST", headers:{"Content-Type":"application/zip","X-Vellum-Confirm":"true"}, body:file}); },
    discordSend: function (channelId, content, confirm) { return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/messages", client.jsonOptions("POST", {content:content, confirm:confirm === true})); },
    discordReply: function (channelId, messageId, content, confirm) { return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/messages/" + encodeURIComponent(messageId) + "/reply", client.jsonOptions("POST", {content:content, confirm:confirm === true})); },
    discordEditOwn: function (channelId, messageId, content, confirm) { return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/messages/" + encodeURIComponent(messageId), client.jsonOptions("PATCH", {content:content, confirm:confirm === true})); },
    discordDeleteOwn: function (channelId, messageId, confirm) { return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/messages/" + encodeURIComponent(messageId) + "/delete", client.jsonOptions("POST", {confirm:confirm === true})); },
    discordReact: function (channelId, messageId, emoji, confirm) { return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/messages/" + encodeURIComponent(messageId) + "/reactions", client.jsonOptions("POST", {emoji:emoji, confirm:confirm === true})); },
    discordCreateThread: function (channelId, messageId, name, confirm) { return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/messages/" + encodeURIComponent(messageId) + "/threads", client.jsonOptions("POST", {name:name, confirm:confirm === true})); },
    discordSendThread: function (channelId, threadId, content, confirm) { return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/threads/" + encodeURIComponent(threadId) + "/messages", client.jsonOptions("POST", {content:content, confirm:confirm === true})); },
    discordSendAttachment: function (channelId, file, content, confirm) { var body = new FormData(); body.set("file", file); body.set("content", content || ""); body.set("confirm", String(confirm === true)); return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/attachments", {method:"POST", body:body}); },
  };
})();
