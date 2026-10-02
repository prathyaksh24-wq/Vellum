(function () {
  const playerUrl = 'http://127.0.0.1:5173/design-uploads/Vellum%20Default%20Re-designed.html';
  let sdkLoad;
  function loadSDK() {
    if (window.Spotify && window.Spotify.Player) return Promise.resolve(window.Spotify);
    if (sdkLoad) return sdkLoad;
    sdkLoad = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      let timeout;
      const fail = () => {
        clearTimeout(timeout); script.remove(); sdkLoad = null;
        reject(new Error('Could not load Spotify playback. Check your connection and try again.'));
      };
      window.onSpotifyWebPlaybackSDKReady = () => { clearTimeout(timeout); resolve(window.Spotify); };
      script.src = 'https://sdk.scdn.co/spotify-player.js';
      script.onerror = fail;
      timeout = setTimeout(fail, 30000);
      document.head.appendChild(script);
    });
    return sdkLoad;
  }

  function create(options) {
    const api = options.api || window.VellumApi.plugins;
    const actions = options.actions || window.VellumApi.appActions;
    const ownerId = options.ownerId || crypto.randomUUID();
    const load = options.loadSDK || loadSDK;
    const onChange = options.onChange || (() => {});
    const onPlayer = options.onPlayer || (() => {});
    let player, enabled = false, disposed = false, fatal = false, generation = 0;
    let deviceId = '', ready = false, retries = 0, retryTimer, heartbeat, connecting = false;
    let updates = Promise.resolve();
    const startedAt = Date.now();
    let diagnostics = [];
    function record(event, values = {}) {
      diagnostics.push({event, at_ms:Math.max(0, Date.now() - startedAt), ...values});
      diagnostics = diagnostics.slice(-32);
    }
    let forceRefresh = false, authFailures = 0, enabling;
    let snapshot = {status: 'loading', enabled: false, ready: false, message: ''};
    function emit(status, message = '') {
      if (disposed) return;
      snapshot = {status, enabled, ready, message}; onChange(snapshot);
    }
    async function session(operation) {
      const receipt = await actions.dispatch({action_id: 'spotify.playback.session', arguments: {owner_id: ownerId, operation}}, {source: 'ui'});
      if (receipt.status !== 'applied') throw new Error(receipt.message || 'Could not enable this Vellum player.');
    }
    function publish(id) {
      const epoch = generation;
      updates = updates.catch(() => {}).then(async () => {
        if (!enabled || disposed || epoch !== generation) return;
        const observations = diagnostics.splice(0);
        const body = {owner_id:ownerId, device_id:id, ...(observations.length ? {diagnostics:observations} : {})};
        try {
          await api.spotifyPlaybackDevice(body);
        } catch (error) {
          // Restore the already-authorized session after a backend restart. An
          // active owner in another window rejects this claim rather than losing playback.
          if (error.status !== 409) { diagnostics = [...observations,...diagnostics].slice(-32); throw error; }
          await session('enable');
          if (!enabled || disposed || epoch !== generation) return;
          await api.spotifyPlaybackDevice(body);
        }
      });
      return updates;
    }
    function retry() {
      if (!enabled || disposed || fatal || retryTimer) return;
      retryTimer = setTimeout(() => {
        retryTimer = null; connect();
      }, Math.min(60000, 1000 * 2 ** Math.min(retries++, 6)));
    }
    async function connect() {
      if (!enabled || disposed || fatal || connecting) return;
      connecting = true;
      const epoch = generation;
      let deadline;
      record('connecting');
      emit('connecting');
      try {
        player.disconnect();
        const success = await Promise.race([player.connect(), new Promise(resolve => {
          deadline = setTimeout(() => {record('connect_timeout'); resolve(false);}, 30000);
        })]);
        if (epoch !== generation || disposed || !enabled) { player.disconnect(); return; }
        if (!success) { player.disconnect(); emit('reconnecting', 'Spotify is reconnecting.'); retry(); }
      } catch (_) { if (enabled && !disposed) { emit('reconnecting', 'Spotify is reconnecting.'); retry(); } }
      finally { clearTimeout(deadline); connecting = false; }
    }
    function offline(status, message, terminal = false) {
      ready = false; deviceId = ''; fatal = terminal;
      if (terminal) { clearTimeout(retryTimer); retryTimer = null; }
      emit(status, message);
      publish('').catch(() => {});
      if (!terminal) retry();
    }
    async function prepare() {
      if (new URL(options.pageUrl || window.location.href).protocol === 'file:') {
        emit('file_preview', 'Open Vellum through its local server to enable Spotify audio. Your connection is already saved.');
        return;
      }
      try {
        const SDK = await load();
        if (disposed) return;
        player = new SDK.Player({name: 'Vellum', volume: 0.5, enableMediaSession: true,
          getOAuthToken: callback => {
            const epoch = generation;
            // No cached credentials: the backend refreshes before every SDK request.
            const refresh = forceRefresh; forceRefresh = false;
            api.spotifyPlaybackToken(refresh).then(value => {
              if (!disposed && enabled && epoch === generation) callback(value.access_token);
            }).catch(error => {
              if (disposed || epoch !== generation) return;
              if (error.status === 403) offline('origin_error', 'Open Vellum through its local server to enable Spotify audio.', true);
              else offline(error.status === 401 ? 'reauth_required' : 'reconnecting',
                error.status === 401 ? 'Reconnect Spotify to allow playback inside Vellum.' : 'Spotify connection interrupted.', error.status === 401);
              callback('');
            });
          },
        });
        player.addListener('ready', async event => {
          if (!enabled || disposed || fatal) return;
          const epoch = generation; deviceId = event.device_id;
          record('ready');
          try {
            await publish(deviceId);
            if (disposed || !enabled || epoch !== generation || deviceId !== event.device_id) return;
            ready = true; retries = 0; authFailures = 0; clearTimeout(retryTimer); retryTimer = null; emit('ready');
          } catch (_) { offline('error', 'Could not register Vellum playback. Enable it again.', true); }
        });
        player.addListener('not_ready', () => { if (enabled) {record('not_ready'); offline('reconnecting', 'Spotify is reconnecting.');} });
        player.addListener('autoplay_failed', () => {record('autoplay_failed'); offline('autoplay_required', 'Click Enable audio to allow Spotify to play here.', true);});
        player.addListener('initialization_error', () => {record('initialization_error'); offline('unsupported', 'This browser cannot initialize Spotify protected audio. Open Vellum in a browser with protected-content support.', true);});
        player.addListener('authentication_error', () => {
          if (!fatal && enabled) {
            record('authentication_error');
            forceRefresh = true;
            if (++authFailures >= 3) offline('reauth_required', 'Spotify rejected playback authorization. Reconnect Spotify.', true);
            else offline('reconnecting', 'Spotify authorization is refreshing.');
          }
        });
        player.addListener('account_error', () => {record('account_error'); offline('account_error', 'Spotify Premium is required for playback inside Vellum.', true);});
        player.addListener('playback_error', () => {record('playback_error'); publish(deviceId).catch(() => {}); emit('error', 'Spotify could not play this track. Check this browser\'s protected-content support or try another track.');});
        player.addListener('player_state_changed', state => {
          if (!state || !enabled || disposed) return;
          record('state', {paused:state.paused, position_ms:Math.max(0,state.position || 0)});
            const track = state.track_window?.current_track;
          if (!track) return;
            const show = track.show || {};
            const album = track.album || {};
            const images = track.images || album.images || show.images || [];
          onPlayer({is_playing: !state.paused, progress_ms: state.position, duration_ms: state.duration,
              track: {id: track.id, uri: track.uri, name: track.name}, artists: track.artists?.map(a => a.name) || (show.name ? [show.name] : []),
            queue: state.track_window.next_tracks || [],
              artwork_url: images[0]?.url || '', album: album.name || show.name || '',
            device: {id: deviceId, name: 'Vellum'},
            shuffle: state.shuffle, repeat: ['off', 'context', 'track'][state.repeat_mode] || 'off'});
        });
        emit('available');
      } catch (_) { emit('error', 'Could not load Spotify playback. Try again.'); }
    }
    function enable() {
      if (enabling) return enabling;
      if (!player) return prepare();
      // Called directly from the click handler, before any awaited action.
      const activation = player.activateElement();
      if (activation && activation.catch) activation.catch(() => emit('autoplay_required', 'Click Enable audio to allow playback.'));
      if (snapshot.status === 'ready') return Promise.resolve();
      enabling = (async () => {
        try {
          await activation;
          await session('enable');
          if (disposed) { await session('disable'); return; }
          enabled = true; fatal = false; ready = false; generation++;
          clearInterval(heartbeat);
          heartbeat = setInterval(() => {
            if (!enabled || disposed || fatal) return;
            if (player.getVolume) Promise.resolve(player.getVolume()).then(volume => {
              if (enabled && !disposed) record('state', {volume_percent:Math.round(Math.max(0,Math.min(1,volume)) * 100)});
            }).catch(() => {});
            publish(deviceId).catch(() => offline('reconnecting', 'Vellum playback connection interrupted.'));
            if (!ready && !connecting) retry();
          }, 20000);
          await connect();
        } catch (error) { emit('busy', error.message); }
      })().finally(() => { enabling = null; });
      return enabling;
    }
    async function disable() {
      generation++; enabled = false; ready = false; deviceId = '';
      clearTimeout(retryTimer); retryTimer = null; clearInterval(heartbeat);
      if (player) player.disconnect();
      await updates.catch(() => {});
      await session('disable'); emit('available');
    }
    const wake = () => { if (enabled && !fatal && !ready) retry(); };
    window.addEventListener('online', wake);
    document.addEventListener('visibilitychange', wake);
    return {
      prepare, enable, disable, getSnapshot: () => snapshot,
      dispose: () => {
        disposed = true; generation++; enabled = false;
        clearTimeout(retryTimer); clearInterval(heartbeat);
        if (player) player.disconnect();
        window.removeEventListener('online', wake); document.removeEventListener('visibilitychange', wake);
        // Expiry also protects abrupt window/process exits where requests cannot finish.
        updates.catch(() => {}).then(() => session('disable')).catch(() => {});
      },
    };
  }
  window.VellumSpotifyPlayback = {create, playerUrl};
})();
