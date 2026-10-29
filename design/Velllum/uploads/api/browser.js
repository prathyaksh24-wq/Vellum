(function () {
  var client = window.VellumApi.client;
  window.VellumApi.browser = {
    engines: [
      {id:'google', name:'Google', wallpaper:'google.png', icon:'google.ico'},
      {id:'brave', name:'Brave', wallpaper:'brave.png', icon:'brave.svg', mask:true},
      {id:'duckduckgo', name:'DuckDuckGo', wallpaper:'duckduckgo.png', icon:'duckduckgo-logo.png'},
      {id:'startpage', name:'Startpage', wallpaper:'startpage.png', icon:'startpage.svg', mask:true},
      {id:'searxng', name:'SearXNG', wallpaper:'searxng.png', icon:'searxng.svg', mask:true},
    ],
    defaultPreferences: {search_engine:'google', searxng_url:'', suggestions_enabled:true, shortcuts:[
      {id:'github', name:'GitHub', url:'https://github.com/'},
      {id:'wikipedia', name:'Wikipedia', url:'https://www.wikipedia.org/'},
      {id:'youtube', name:'YouTube', url:'https://www.youtube.com/'},
    ]},
    searchUrl: function (query, preferences) {
      var selected = preferences || this.defaultPreferences;
      var endpoints = {google:'https://www.google.com/search?q=', brave:'https://search.brave.com/search?q=',
        duckduckgo:'https://duckduckgo.com/?q=', startpage:'https://www.startpage.com/sp/search?query='};
      var endpoint = endpoints[selected.search_engine] || endpoints.google;
      if (selected.search_engine === 'searxng') {
        var instance = String(selected.searxng_url || '').trim();
        if (!instance) throw new Error('Set a SearXNG instance URL before searching.');
        var parsed = new URL(instance);
        if (!['https:', 'http:'].includes(parsed.protocol) || parsed.username || parsed.password || parsed.search || parsed.hash) {
          throw new Error('Enter an http or https SearXNG instance URL without credentials, a query or fragment.');
        }
        endpoint = instance.replace(/\/+$/, '') + '/search?q=';
      }
      return endpoint + encodeURIComponent(String(query || '').trim());
    },
    addressUrl: function (input, preferences) {
      var value = String(input || '').trim();
      if (!value || /^https?:\/\//i.test(value) || value === 'about:blank') return value;
      // Exact site names open their destination instead of searching for it.
      var sites = {google:'https://www.google.com/', youtube:'https://www.youtube.com/',
        reddit:'https://www.reddit.com/', wikipedia:'https://www.wikipedia.org/',
        spotify:'https://open.spotify.com/', x:'https://x.com/', twitter:'https://x.com/'};
      if (Object.prototype.hasOwnProperty.call(sites, value.toLowerCase())) return sites[value.toLowerCase()];
      var host = value.split(/[/?#]/)[0];
      var local = /^(localhost|127(?:\.\d{1,3}){3}|\[::1\])(?::\d+)?$/i.test(host);
      var website = /^(?:[a-z0-9-]+\.)+[a-z0-9-]+(?::\d+)?$/i.test(host) || /^\[[a-f0-9:]+\](?::\d+)?$/i.test(host);
      if (!/\s/.test(value) && (local || website)) return (local ? 'http://' : 'https://') + value;
      // Unsupported schemes remain subject to the canonical server validator.
      if (/^[a-z][a-z0-9+.-]*:/i.test(value)) return value;
      return this.searchUrl(value, preferences);
    },
    status: function () { return client.request('/api/browser/status', {cache:'no-store'}); },
    suggestions: function (query) { return client.request('/api/browser/suggestions?q=' + encodeURIComponent(String(query || '').slice(0,256)), {cache:'no-store'}); },
    addressSuggestions: function (query, tabs, shortcuts, history, preferences, queries) {
      var value = String(query || '').trim();
      var needle = value.toLowerCase();
      var seen = new Set();
      var items = [];
      (tabs || []).map(function (tab) { return {title:tab.title, url:tab.url, tab_id:tab.id, kind:'tab'}; })
        .concat((history || []).map(function (item) { return {title:item.title, url:item.url, kind:'history'}; }),
          (shortcuts || []).map(function (item) { return {title:item.name, url:item.url, kind:'shortcut'}; }),
          value ? [{title:'Spotify',url:'https://open.spotify.com/',kind:'website'},
            {title:'GitHub',url:'https://github.com/',kind:'website'},
            {title:'YouTube',url:'https://www.youtube.com/',kind:'website'},
            {title:'Wikipedia',url:'https://www.wikipedia.org/',kind:'website'},
            {title:'Reddit',url:'https://www.reddit.com/',kind:'website'},
            {title:'Google',url:'https://www.google.com/',kind:'website'}] : [])
        .forEach(function (item) {
          try { var parsed = new URL(item.url); if (!/^https?:$/.test(parsed.protocol) || parsed.username || parsed.password) return; } catch (_) { return; }
          if (seen.has(item.url) || needle && !(item.url + ' ' + item.title).toLowerCase().includes(needle)) return;
          seen.add(item.url); items.push(item);
        });
      items = items.slice(0,4);
      if (value) {
        try { items.push({title:value, url:this.searchUrl(value,preferences), kind:'search'}); } catch (_) {}
      }
      (queries || []).forEach(function (text) {
        if (typeof text !== 'string' || !text.trim() || text.length > 256 || text.toLowerCase() === needle) return;
        try {
          var url = this.searchUrl(text,preferences);
          if (!items.some(function (item) { return item.url === url; })) items.push({title:text,url:url,kind:'query'});
        } catch (_) {}
      },this);
      return items.slice(0,8);
    },
    frame: function () { return client.request('/api/browser/frame', {cache:'no-store'}); },
    viewport: function (rect) {
      // Preserve the panel's aspect ratio within the transport's bounded viewport.
      var scale = Math.min(1, 1920 / rect.width, 1080 / rect.height);
      return {width:Math.max(240, Math.round(rect.width * scale)), height:Math.max(160, Math.round(rect.height * scale))};
    },
    stream: function (onFrame, onError) {
      var url = new URL(client.backendBase() + '/api/browser/stream');
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      var socket = new WebSocket(url.href);
      socket.onmessage = function (event) {
        try {
          var frame = JSON.parse(event.data);
          if (frame.error) onError(new Error(frame.error));
          else onFrame(frame);
        } catch (_) { onError(new Error('The browser sent an invalid frame.')); }
      };
      socket.onerror = function () { onError(new Error('The live browser view disconnected.')); };
      socket.onclose = function () { onError(new Error('The live browser view disconnected.')); };
      return function () { socket.onclose = null; socket.onerror = null; socket.close(); };
    },
    control: function (arguments_, context) {
      return window.VellumApi.appActions.dispatch(
        {action_id:'browser.session.control', action_version:'1', arguments:arguments_},
        Object.assign({source:'ui'}, context || {}, {source:'ui'}),
      ).then(function (receipt) {
        if (receipt.status !== 'applied') throw new Error(receipt.message || 'Browser action failed.');
        return receipt;
      });
    },
    settings: function () { return client.request('/api/browser/settings'); },
    linkDestination: function (url, preferences) {
      var target = new URL(url);
      if (!['http:', 'https:'].includes(target.protocol)) throw new Error('Open an http or https website.');
      var local = ['localhost','127.0.0.1','[::1]'].includes(target.hostname.toLowerCase());
      return (preferences || {})[local ? 'local_link_destination' : 'web_link_destination'] || 'default';
    },
    point: function (rect, frame, clientX, clientY) {
      var scale = Math.min(rect.width / frame.width, rect.height / frame.height);
      var x = (clientX - rect.left - (rect.width - frame.width * scale) / 2) / scale;
      var y = (clientY - rect.top - (rect.height - frame.height * scale) / 2) / scale;
      if (x < 0 || y < 0 || x >= frame.width || y >= frame.height) return null;
      return {x:x, y:y};
    },
  };
})();
