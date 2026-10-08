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
    defaultPreferences: {search_engine:'google', searxng_url:'', shortcuts:[
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
    point: function (rect, frame, clientX, clientY) {
      var scale = Math.min(rect.width / frame.width, rect.height / frame.height);
      var x = (clientX - rect.left - (rect.width - frame.width * scale) / 2) / scale;
      var y = (clientY - rect.top - (rect.height - frame.height * scale) / 2) / scale;
      if (x < 0 || y < 0 || x >= frame.width || y >= frame.height) return null;
      return {x:x, y:y};
    },
  };
})();
