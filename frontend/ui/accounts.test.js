import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {afterEach, beforeEach, expect, test, vi} from 'vitest';

const require = createRequire(import.meta.url);
const source = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../design/Velllum/uploads/components/accounts.jsx'), 'utf8');
const originalUint8Array = globalThis.Uint8Array;
let compiled;
try {
  globalThis.Uint8Array = new TextEncoder().encode('').constructor;
  compiled = createRequire(require.resolve('vite'))('esbuild').transformSync(source, {loader:'jsx'}).code;
} finally {globalThis.Uint8Array = originalUint8Array;}
let host, root, api, state, Accounts;
const account = {id:'google:alex', provider:'google', display_name:'Alex', email:'alex@example.com', username:''};
const another = {id:'github:sam', provider:'github', display_name:'Sam', email:'sam@example.com', username:'sam'};
const emailAccount = {id:'email:alex', provider:'email', display_name:'alex', email:'alex@example.com', username:''};
const button = text => [...host.querySelectorAll('button')].find(b => b.textContent === text);
const click = async text => {const target = button(text); expect(target).toBeTruthy(); await act(async () => target.click());};
const fill = async (id, value) => act(async () => {
  const target = host.querySelector('#' + id);
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(target, value);
  target.dispatchEvent(new Event('input', {bubbles:true}));
});
const credentials = async (confirm=true) => {
  await fill('account-email', 'alex@example.com'); await fill('account-password', 'fixture-password-only');
  if (confirm) await fill('account-confirm-password', 'fixture-password-only');
};
const render = async () => act(async () => root.render(React.createElement(Accounts.Root, null, context => React.createElement('div', null,
  React.createElement('p', null, 'Local workspace'), React.createElement('button', {onClick:context.add}, 'Add from workspace'), React.createElement(Accounts.Settings)))));

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  HTMLDialogElement.prototype.showModal = function () {this.open = true;};
  state = {accounts:[], active_account_id:null, email_auth_available:true, providers:[{id:'google',name:'Google',available:true},{id:'github',name:'GitHub',available:true}]};
  api = {
    status:vi.fn(async () => state),
    start:vi.fn(async provider => ({flow_id:'flow-12345678901234567890',provider,status:'pending',authorization_url:'https://github.com/login/device',user_code:'ABCD-EFGH',interval:5})),
    poll:vi.fn(async () => ({flow_id:'flow-12345678901234567890',provider:'github',status:'pending',interval:5})),
    cancel:vi.fn(async () => ({status:'cancelled'})),
    select:vi.fn(async id => ({...state,active_account_id:id})),
    signOut:vi.fn(async id => ({...state,accounts:state.accounts.filter(a => a.id !== id),active_account_id:null})),
    logOut:vi.fn(async () => ({...state, active_account_id:null, logged_out:true})),
    continueLocal:vi.fn(async () => ({...state, active_account_id:null, logged_out:false})),
    navigateToProvider:vi.fn(),
    focusVellum:vi.fn(),
    signUp:vi.fn(async () => ({status:'confirmation_required',flow:{flow_id:'email-12345678901234567890',provider:'email',status:'pending',interval:3,message:'Check your email to confirm your account.'}})),
    signIn:vi.fn(async () => {state = {...state,accounts:[emailAccount],active_account_id:emailAccount.id,logged_out:false}; return state;}),
  };
  window.VellumApi = {accounts:api};
  window.VellumUI = {};
  new Function('React', compiled)(React);
  Accounts = window.VellumUI.Accounts;
});
afterEach(async () => {await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); vi.restoreAllMocks();});

test('first launch offers email registration, provider sign-in and a persistent guest choice', async () => {
  await render();
  expect(button('Create account').disabled).toBe(false);
  expect(host.querySelector('#account-confirm-password')).toBeTruthy();
  expect(button('Sign up with Google')).toBeUndefined();
  expect(host.textContent).not.toContain('SSO');
  await click('Sign in instead');
  expect(host.textContent).toContain('Sign in to Vellum');
  expect(button('Continue with Google').disabled).toBe(false);
  expect(button('Continue with GitHub').disabled).toBe(false);
  await click('Continue as guest');
  expect(host.textContent).toContain('Local workspace');
  expect(localStorage.getItem('vellum-local-welcome-v1')).toBe('1');
  expect(api.start).not.toHaveBeenCalled();
});

test('an unavailable backend preserves local access and explains the error', async () => {
  api.status.mockRejectedValue(new Error('Backend offline'));
  await render();
  expect(host.querySelector('[role="alert"]').textContent).toContain('Backend offline');
  await click('Continue as guest');
  expect(host.textContent).toContain('Local workspace');
});

test('provider readiness disables unavailable sign-in with a visible reason', async () => {
  state.providers[0] = {...state.providers[0],available:false,reason:'Google sign-in has not been configured.'};
  await render();
  await click('Sign in instead');
  expect(button('Continue with Google').disabled).toBe(true);
  expect(host.textContent).toContain('Google sign-in has not been configured.');
});

test('GitHub device code polls until verified, then opens the workspace', async () => {
  vi.useFakeTimers();
  await render();
  await click('Sign in instead'); await click('Continue with GitHub');
  expect(api.start).toHaveBeenCalledWith('github', 'redirect');
  expect(host.textContent).toContain('ABCD-EFGH');
  expect(host.textContent).not.toContain('Local workspace');
  state = {...state,accounts:[another],active_account_id:another.id};
  api.poll.mockResolvedValue({status:'complete',provider:'github'});
  await act(async () => vi.advanceTimersByTimeAsync(5000));
  expect(host.textContent).toContain('Local workspace');
  expect(host.textContent).toContain('Sam');
});

test('cancelling a pending sign-in keeps the welcome screen and stops polling', async () => {
  vi.useFakeTimers();
  await render(); await click('Sign in instead'); await click('Continue with Google'); await click('Cancel sign-in');
  expect(api.cancel).toHaveBeenCalledWith('flow-12345678901234567890');
  await act(async () => vi.advanceTimersByTimeAsync(10000));
  expect(api.poll).not.toHaveBeenCalled();
  expect(button('Continue with Google').disabled).toBe(false);
});

test('failed provider sign-in stays visible and does not invent an account', async () => {
  vi.useFakeTimers(); await render(); await click('Sign in instead'); await click('Continue with GitHub');
  api.poll.mockResolvedValue({status:'failed',provider:'github',message:'Sign-in denied'});
  await act(async () => vi.advanceTimersByTimeAsync(5000));
  expect(host.querySelector('[role="alert"]').textContent).toContain('Sign-in denied');
  expect(host.textContent).not.toContain('Local workspace');
});

test('add account, switch and sign-out use server results with multiple accounts', async () => {
  state = {...state,accounts:[account,another],active_account_id:account.id};
  await render(); await click('Switch');
  expect(api.select).toHaveBeenCalledWith(another.id);
  expect(host.textContent).toContain('GitHub · Active');
  await click('Add from workspace');
  expect(host.querySelector('dialog').open).toBe(true);
  await click('Continue with Google');
  await click('Close');
  expect(api.cancel).toHaveBeenCalledOnce();
  expect(host.querySelector('dialog')).toBeNull();
  await click('Remove account');
  expect(api.signOut).toHaveBeenCalledWith(account.id);
});

test('welcome requires provider sign-in instead of restoring a logged-out saved identity', async () => {
  state.accounts = [another];
  state.logged_out = true;
  await render();
  expect(host.textContent).toContain('Sign in to Vellum');
  expect(button('Continue as Sam (GitHub)')).toBeUndefined();
  expect(api.select).not.toHaveBeenCalled();
  await click('Continue with GitHub');
  expect(api.start).toHaveBeenCalledWith('github', 'redirect');
});

test('logout returns to sign-in even after local continuation and survives a stale local choice', async () => {
  localStorage.setItem('vellum-local-welcome-v1', '1');
  state = {...state, accounts:[account,another], active_account_id:account.id};
  await render(); await click('Log out');
  expect(api.logOut).toHaveBeenCalledOnce();
  expect(api.signOut).not.toHaveBeenCalled();
  expect(localStorage.getItem('vellum-local-welcome-v1')).toBeNull();
  expect(host.textContent).toContain('Sign in to Vellum');
  expect(host.textContent).not.toContain('Local workspace');
  await click('Sign up');
  expect(host.textContent).toContain('Create your Vellum account');
  expect(button('Create account')).toBeTruthy();
  await click('Continue as guest');
  expect(api.continueLocal).toHaveBeenCalledOnce();
  expect(host.textContent).toContain('Local workspace');
});

test('persisted logout overrides a local-use marker left in another tab', async () => {
  localStorage.setItem('vellum-local-welcome-v1', '1');
  state = {...state, accounts:[account], logged_out:true};
  await render();
  expect(host.textContent).toContain('Sign in to Vellum');
  expect(host.textContent).not.toContain('Local workspace');
});

test('failed logout preserves the workspace and reports the failure', async () => {
  state = {...state, accounts:[account], active_account_id:account.id};
  api.logOut.mockRejectedValue(new Error('Credential store locked'));
  await render(); await click('Log out');
  expect(host.textContent).toContain('Local workspace');
  expect(host.querySelector('[role="alert"]').textContent).toContain('Credential store locked');
});

test('a status response started before logout cannot restore the old active account', async () => {
  state = {...state, accounts:[account], active_account_id:account.id};
  await render();
  let finishStatus;
  api.status.mockImplementationOnce(() => new Promise(resolve => {finishStatus = resolve;}));
  await act(async () => window.dispatchEvent(new Event('focus')));
  await click('Log out');
  await act(async () => finishStatus(state));
  expect(host.textContent).toContain('Sign in to Vellum');
  expect(host.textContent).not.toContain('Local workspace');
});

test('signed-in settings and add-account do not expose signup or duplicate add controls', async () => {
  state = {...state, accounts:[account], active_account_id:account.id};
  await render();
  expect(button('Sign up')).toBeUndefined();
  expect(button('Add account')).toBeUndefined();
  await click('Add from workspace');
  expect(button('Sign up')).toBeUndefined();
  expect(button('Create account')).toBeUndefined();
  await click('Continue with Google');
  expect(api.navigateToProvider).toHaveBeenCalledWith(expect.objectContaining({provider:'google'}));
});

test('email signup checks confirmation before sending credentials', async () => {
  await render(); await credentials(); await fill('account-confirm-password', 'different-fixture');
  await click('Create account');
  expect(api.signUp).not.toHaveBeenCalled();
  expect(host.querySelector('[role="alert"]').textContent).toContain('passwords do not match');
});

test('email signup waits for confirmation before opening the workspace', async () => {
  vi.useFakeTimers(); await render(); await credentials(); await click('Create account');
  expect(api.signUp).toHaveBeenCalledWith('alex@example.com','fixture-password-only');
  expect(host.textContent).toContain('Check your email');
  expect(host.textContent).not.toContain('Local workspace');
  expect(host.querySelector('input[type="password"]')).toBeNull();
  state = {...state,accounts:[emailAccount],active_account_id:emailAccount.id};
  api.poll.mockResolvedValue({status:'complete',provider:'email'});
  await act(async () => vi.advanceTimersByTimeAsync(3000));
  expect(host.textContent).toContain('Email · Active');
  expect(host.textContent).toContain('Local workspace');
  expect(button('Sign up')).toBeUndefined();
});

test('email sign-in uses server verification and removes password fields on success', async () => {
  state.logged_out = true;
  await render(); await credentials(false); await click('Sign in');
  expect(api.signIn).toHaveBeenCalledWith('alex@example.com','fixture-password-only');
  expect(host.textContent).toContain('Local workspace');
  expect(host.querySelector('input[type="password"]')).toBeNull();
});

test('failed email sign-in clears passwords and keeps the error visible', async () => {
  state.logged_out = true;
  api.signIn.mockRejectedValue(new Error('Check your email and password.'));
  await render(); await credentials(false); await click('Sign in');
  expect(host.querySelector('[role="alert"]').textContent).toContain('Check your email and password');
  expect(host.querySelector('#account-password').value).toBe('');
  expect(host.textContent).not.toContain('Local workspace');
});

test('failed account switching keeps the active identity and displays the error', async () => {
  state = {...state,accounts:[account,another],active_account_id:account.id};
  api.select.mockRejectedValue(new Error('Credential store locked'));
  await render(); await click('Switch');
  expect(host.textContent).toContain('Google · Active');
  expect(host.querySelector('[role="alert"]').textContent).toContain('Credential store locked');
});
