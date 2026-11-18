(function () {
  // First-run setup (components/onboarding.jsx) against the real backend.
  var client = window.VellumApi.client;
  var get = function (path) { return client.request(path, {cache: 'no-store'}); };
  var post = function (path, body) { return client.request(path, client.jsonOptions('POST', body || {})); };

  // Connectors offered during setup, with their logos. Only ones this build
  // actually ships (present in /api/plugins) are shown.
  var CONNECTORS = [
    ['gmail', 'gmail.svg', 'google'], ['google-calendar', 'googlecalendar.svg', 'google'],
    ['google-drive', 'googledrive.png', 'google'], ['google-contacts', 'googlecontacts.png', 'google'],
    ['github', 'github.png', 'github'], ['notion', 'notion.png'], ['linear', 'linear.png'],
    ['slack', 'slack.png'], ['spotify', 'spotify.svg'], ['todoist', 'todoist.svg'], ['asana', 'asana.svg'],
    ['clickup', 'clickup.png'], ['airtable', 'airtable.svg'], ['hubspot', 'hubspot.svg'], ['figma', 'figma.svg'],
    ['dropbox', 'dropbox.svg'], ['discord', 'discord.svg'], ['obsidian', 'obsidian.svg'],
  ];
  // Subscription sign-in: only OpenAI permits other apps to use a plan, and
  // only for apps it has approved. Until Vellum is approved this explains why.
  var PLANS = {openai: {available: false, label: 'Sign in with ChatGPT',
    note: 'Uses your ChatGPT Plus or Pro plan. No API key needed.',
    reason: 'Sign in with ChatGPT is waiting on OpenAI’s approval for Vellum. Use an API key for now; you can switch to your plan later in Settings.'}};

  function dispatch(actionId, args) {
    var request = {action_id: actionId, arguments: args};
    var context = {source: 'ui'};
    return window.VellumApi.appActions.dispatch(request, context).then(function (receipt) {
      // The user's own click in setup is the confirmation for these actions.
      if (receipt && receipt.status === 'confirmation_required' && receipt.confirmation) {
        return window.VellumApi.appActions.confirm(receipt.confirmation.token, request, context);
      }
      return receipt;
    }).then(function (receipt) {
      if (!receipt || receipt.status === 'failed' || receipt.status === 'denied') {
        throw new Error((receipt && receipt.message) || 'That change could not be saved.');
      }
      return receipt;
    });
  }

  window.VellumApi.setup = {
    onboarding: function () { return get('/api/setup/onboarding'); },
    hardware: function () { return get('/api/setup/hardware'); },
    models: function (options) {
      var query = new URLSearchParams({category: options.category || 'general', q: options.q || '', uncensored: options.uncensored ? 'true' : 'false'});
      return get('/api/setup/models?' + query);
    },
    providers: function () {
      // Free first, then the providers most people already have.
      var ORDER = ['groq', 'openrouter', 'anthropic', 'openai', 'google', 'xai', 'kimi', 'meta', 'opencode'];
      var rank = function (id) { var i = ORDER.indexOf(id); return i < 0 ? ORDER.length : i; };
      return get('/api/settings').then(function (body) {
        return (body.provider_connections || []).map(function (p) { return Object.assign({}, p, {plan: PLANS[p.id] || null}); })
          .sort(function (a, b) { return rank(a.id) - rank(b.id); });
      });
    },
    connectors: function () {
      return get('/api/plugins').then(function (body) {
        var byId = {};
        (body.plugins || []).forEach(function (plugin) { byId[plugin.id] = plugin; });
        return CONNECTORS.filter(function (c) { return byId[c[0]]; }).map(function (c) {
          var plugin = byId[c[0]];
          var description = String(plugin.description || '').split(/(?<=\.)\s/)[0];
          return {id: c[0], name: plugin.name, description: description, icon: 'assets/plugins/' + c[1], account: c[2] || null};
        });
      });
    },
    engines: function () { return get('/api/memory/engines'); },
    ollama: function () { return get('/api/setup/ollama'); },
    pull: function (model) { return post('/api/setup/ollama/pull', {model: model}); },
    planSignIn: function () { return Promise.reject(new Error(PLANS.openai.reason)); },
    saveKey: function (provider, secret) { return dispatch('provider.credential.configure', {provider: provider, secret: secret}); },
    enableConnector: function (id) { return dispatch('plugin.state.set', {plugin_id: id, enabled: true}); },
    importPrompt: function () { return get('/api/memory/import/prompt'); },
    importPlan: function (text) { return post('/api/memory/import/plan', {text: text}); },
    // The reviewed list the user ticked is the confirmation for saving it.
    importApply: function (items) {
      return dispatch('memory.import.apply', {items: items}).then(function (receipt) { return receipt.result || {}; });
    },
    complete: function (state) { return post('/api/setup/complete', {state: state}); },
  };
})();
