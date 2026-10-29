import {beforeEach, expect, test, vi} from 'vitest';

let request;
beforeEach(async () => {
  vi.resetModules();
  request = vi.fn(async () => ({}));
  window.VellumApi = {client:{request,jsonOptions:(method,body) => ({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})}};
  await import('../../../design/Velllum/uploads/api/accounts.js');
});
test('account requests carry the local UI header and never cache identities', async () => {
  const api = window.VellumApi.accounts;
  await api.status(); await api.start('google'); await api.poll('flow'); await api.cancel('flow'); await api.select('google:id'); await api.signOut('github:id'); await api.logOut(); await api.continueLocal();
  expect(request.mock.calls.map(([path]) => path)).toEqual(['status','start','poll','cancel','select','sign-out','logout','continue-local'].map(path => '/api/accounts/' + path));
  for (const [, options] of request.mock.calls) {
    expect(options.headers['X-Vellum-Accounts']).toBe('1');
    expect(options.cache).toBe('no-store');
  }
  expect(JSON.parse(request.mock.calls[1][1].body)).toEqual({provider:'google',return_url:window.location.origin + window.location.pathname,open_browser:false});
  expect(JSON.parse(request.mock.calls[2][1].body)).toEqual({flow_id:'flow'});
  expect(JSON.parse(request.mock.calls[5][1].body)).toEqual({account_id:'github:id'});
});

test('device fallback opens the browser while native redirect keeps the system browser boundary', async () => {
  const api = window.VellumApi.accounts;
  await api.start('github', 'device');
  expect(JSON.parse(request.mock.calls[0][1].body).open_browser).toBe(true);
  const invoke = vi.fn(async () => {});
  window.VellumDesktop = {invoke};
  try {
    await api.start('google', 'redirect');
    expect(JSON.parse(request.mock.calls[1][1].body).open_browser).toBe(true);
    api.navigateToProvider({method:'redirect',provider:'google',authorization_url:'https://accounts.google.com/o/oauth2/v2/auth'});
    await api.focusVellum();
    expect(invoke).toHaveBeenCalledWith('open_vellum_window');
  } finally {delete window.VellumDesktop;}
});

test('provider navigation rejects arbitrary third-party URLs', () => {
  expect(() => window.VellumApi.accounts.navigateToProvider({provider:'google',method:'redirect',authorization_url:'https://evil.example/'})).toThrow('sign-in address is invalid');
});

test('email registration and sign-in use the guarded account transport', async () => {
  const api = window.VellumApi.accounts;
  await api.signUp('alex@example.com','fixture-password-only');
  await api.signIn('alex@example.com','fixture-password-only');
  expect(request.mock.calls.map(([path]) => path)).toEqual(['/api/accounts/email/sign-up','/api/accounts/email/sign-in']);
  expect(JSON.parse(request.mock.calls[0][1].body)).toEqual({email:'alex@example.com',password:'fixture-password-only',return_url:window.location.origin + window.location.pathname});
  for (const [,options] of request.mock.calls) {
    expect(options.headers['X-Vellum-Accounts']).toBe('1');
    expect(options.cache).toBe('no-store');
  }
});
