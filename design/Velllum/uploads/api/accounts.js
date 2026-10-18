(function () {
  var client = window.VellumApi.client;
  function request(path, body) {
    var options = body === undefined ? {method: 'GET', headers: {}} : client.jsonOptions('POST', body);
    options.headers['X-Vellum-Accounts'] = '1';
    options.cache = 'no-store';
    return client.request('/api/accounts/' + path, options);
  }
  function desktopInvoke() {
    return window.VellumDesktop && window.VellumDesktop.invoke;
  }
  function returnUrl() {
    var location = window.location;
    var query = new URLSearchParams(location.search).get('desktop') === '1' ? '?desktop=1' : '';
    return location.origin + location.pathname + query;
  }
  window.VellumApi.accounts = {
    status: function () { return request('status'); },
    start: function (provider, method) {
      return request('start', {provider: provider, return_url: returnUrl(), open_browser: !!desktopInvoke() || method === 'device'});
    },
    poll: function (flowId) { return request('poll', {flow_id: flowId}); },
    cancel: function (flowId) { return request('cancel', {flow_id: flowId}); },
    select: function (accountId) { return request('select', {account_id: accountId}); },
    signOut: function (accountId) { return request('sign-out', {account_id: accountId}); },
    logOut: function () { return request('logout', {}); },
    continueLocal: function () { return request('continue-local', {}); },
    signUp: function (email, password) { return request('email/sign-up', {email: email, password: password, return_url: returnUrl()}); },
    signIn: function (email, password) { return request('email/sign-in', {email: email, password: password}); },
    navigateToProvider: function (flow) {
      if (desktopInvoke() || flow.method === 'device') return;
      // The browser returns through the loopback callback into this same tab.
      var target = new URL(flow.authorization_url);
      var allowed = flow.provider === 'google' ? 'https://accounts.google.com/o/oauth2/v2/auth' : 'https://github.com/login/oauth/authorize';
      if (target.origin + target.pathname !== allowed) throw new Error('The sign-in address is invalid. Try again.');
      window.location.assign(target.href);
    },
    focusVellum: function () {
      var invoke = desktopInvoke();
      if (invoke) return invoke('open_vellum_window');
    },
  };
})();
