(function () {
  const {useEffect, useRef, useState} = React;
  const LOCAL_CHOICE = 'vellum-local-welcome-v1';
  const ACCOUNT_CHANGE = 'vellum-account-change-v1';
  const Context = React.createContext(null);
  const empty = {accounts: [], providers: [], active_account_id: null};
  const providerName = id => ({google:'Google', github:'GitHub', email:'Email'})[id];
  function ProviderIcon({provider}) {
    return provider === 'google' ? <svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M21.6 12.23c0-.71-.06-1.39-.18-2.05H12v3.88h5.38a4.6 4.6 0 0 1-2 3.02v2.51h3.24c1.9-1.75 2.98-4.33 2.98-7.36Z"/><path fill="#34A853" d="M12 22c2.7 0 4.96-.9 6.61-2.41l-3.24-2.51c-.9.6-2.04.96-3.37.96-2.6 0-4.8-1.76-5.59-4.12H3.07v2.59A10 10 0 0 0 12 22Z"/><path fill="#FBBC05" d="M6.41 13.92A6 6 0 0 1 6.1 12c0-.67.11-1.31.31-1.92V7.49H3.07A10 10 0 0 0 2 12c0 1.61.39 3.14 1.07 4.51l3.34-2.59Z"/><path fill="#EA4335" d="M12 5.96c1.47 0 2.79.51 3.82 1.51l2.87-2.87A9.6 9.6 0 0 0 12 2a10 10 0 0 0-8.93 5.49l3.34 2.59C7.2 7.72 9.4 5.96 12 5.96Z"/></svg> : <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .8a11.2 11.2 0 0 0-3.54 21.83c.56.1.77-.24.77-.54v-2.08c-3.13.68-3.79-1.33-3.79-1.33-.51-1.3-1.25-1.65-1.25-1.65-1.02-.7.08-.69.08-.69 1.13.08 1.72 1.16 1.72 1.16 1 1.72 2.62 1.22 3.26.93.1-.72.39-1.22.71-1.5-2.5-.28-5.12-1.25-5.12-5.57 0-1.23.44-2.23 1.16-3.02-.12-.28-.5-1.43.11-2.98 0 0 .95-.3 3.08 1.15a10.7 10.7 0 0 1 5.61 0c2.14-1.45 3.08-1.15 3.08-1.15.61 1.55.23 2.7.11 2.98a4.34 4.34 0 0 1 1.16 3.02c0 4.33-2.63 5.28-5.14 5.56.4.35.76 1.03.76 2.08v3.09c0 .3.2.65.77.54A11.2 11.2 0 0 0 12 .8Z"/></svg>;
  }

  function SignIn({state, error, onRefresh, onComplete, onLocal, adding=false, initialMode='signup'}) {
    const [mode, setMode] = useState(initialMode);
    const [busy, setBusy] = useState(false);
    const [flow, setFlow] = useState(null);
    const [failure, setFailure] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const live = useRef(true);
    const pending = useRef(null);
    const api = window.VellumApi.accounts;
    useEffect(() => {
      live.current = true;
      return () => {live.current = false; if (pending.current) api.cancel(pending.current).catch(() => {});};
    }, []);
    useEffect(() => {
      if (!flow || flow.status !== 'pending') return;
      let cancelled = false;
      const timer = setTimeout(async () => {
        try {
          const result = await api.poll(flow.flow_id);
          if (cancelled || !live.current) return;
          setFlow(result);
          if (result.status === 'complete') {
            pending.current = null;
            await onComplete();
          } else if (result.status !== 'pending') {
            pending.current = null;
            setFailure(result.message || 'Sign-in did not complete. Try again.');
          }
        } catch (e) {if (!cancelled && live.current) setFailure(e.message);}
      }, Math.max(2, flow.interval) * 1000);
      return () => {cancelled = true; clearTimeout(timer);};
    }, [flow]);
    async function start(provider) {
      setFailure(''); setBusy(true);
      try {
        const method = state.providers.find(p => p.id === provider)?.method || 'redirect';
        const result = await api.start(provider, method);
        if (!live.current) {await api.cancel(result.flow_id); return;}
        pending.current = result.flow_id;
        setFlow(result);
        api.navigateToProvider(result);
      } catch (e) {if (live.current) setFailure(e.message);}
      finally {if (live.current) setBusy(false);}
    }
    async function cancel() {
      setBusy(true);
      try {
        if (pending.current) await api.cancel(pending.current);
        pending.current = null;
        setFlow(null); setFailure('');
      } catch (e) {setFailure(e.message);}
      finally {setBusy(false);}
    }
    async function submitEmail(event) {
      event.preventDefault(); setFailure('');
      if (mode === 'signup' && password !== confirmPassword) {setFailure('The passwords do not match.'); return;}
      setBusy(true);
      try {
        const result = await (mode === 'signup' ? api.signUp(email, password) : api.signIn(email, password));
        if (!live.current) {if (result.flow) await api.cancel(result.flow.flow_id); return;}
        setPassword(''); setConfirmPassword('');
        if (result.status === 'confirmation_required') {
          pending.current = result.flow.flow_id; setFlow(result.flow);
        } else {await onComplete();}
      } catch (e) {if (live.current) {setPassword(''); setConfirmPassword(''); setFailure(e.message);}}
      finally {if (live.current) setBusy(false);}
    }
    function changeMode() {
      setMode(mode === 'signup' ? 'signin' : 'signup'); setFailure(''); setPassword(''); setConfirmPassword('');
    }
    const waiting = flow?.status === 'pending';
    return <div className="account-form">
      <h2>{mode === 'signup' ? 'Create your Vellum account' : adding ? 'Add an account' : 'Sign in to Vellum'}</h2>
      <p>{mode === 'signup' ? 'Create an account with your email and password.' : adding ? 'Sign in to another account.' : 'Welcome back. Sign in to continue.'}</p>
      {!adding && !waiting && <button className="account-mode account-guest" onClick={onLocal} disabled={busy}>Continue as guest</button>}
      {!waiting && <form className="account-email-form" onSubmit={submitEmail}>
        <label htmlFor="account-email">Email</label>
        <input id="account-email" type="email" autoComplete="username" maxLength={254} value={email} onChange={event => setEmail(event.target.value)} required disabled={busy}/>
        <label htmlFor="account-password">Password</label>
        <input id="account-password" type="password" autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} minLength={mode === 'signup' ? 8 : 1} maxLength={1024} value={password} onChange={event => setPassword(event.target.value)} required disabled={busy} aria-describedby={mode === 'signup' ? 'account-password-help' : undefined}/>
        {mode === 'signup' && <React.Fragment>
          <p id="account-password-help" className="account-field-help">Use at least 8 characters.</p>
          <label htmlFor="account-confirm-password">Confirm password</label>
          <input id="account-confirm-password" type="password" autoComplete="new-password" maxLength={1024} value={confirmPassword} onChange={event => setConfirmPassword(event.target.value)} required disabled={busy}/>
        </React.Fragment>}
        <button type="submit" className="account-primary" disabled={busy || !state.email_auth_available}>{busy ? mode === 'signup' ? 'Creating account…' : 'Signing in…' : mode === 'signup' ? 'Create account' : 'Sign in'}</button>
        {!state.email_auth_available && <p className="account-field-help">{state.email_auth_reason || 'Email sign-in is not available yet. You can continue as guest.'}</p>}
      </form>}
      {mode === 'signin' && !waiting && <div className="account-separator">or sign in with</div>}
      {mode === 'signin' && ['google','github'].map(id => {
        const provider = state.providers.find(p => p.id === id);
        return <React.Fragment key={id}>
          <button className="account-provider" disabled={busy || waiting || !provider?.available} aria-describedby={!provider?.available ? `account-${id}-reason` : undefined} onClick={() => start(id)}><ProviderIcon provider={id}/>Continue with {providerName(id)}</button>
          {provider && !provider.available && <p id={`account-${id}-reason`}>{provider.reason}</p>}
        </React.Fragment>;
      })}
      {waiting && <div className="account-feedback" role="status">
        {flow.provider === 'email' ? flow.message : flow.user_code ? <React.Fragment>Enter this code on GitHub, then authorize Vellum.<strong className="account-code">{flow.user_code}</strong></React.Fragment> : 'Complete sign-in in your browser. Vellum will open when you finish.'}
        {flow.authorization_url && <a className="account-link" href={flow.authorization_url} target="_blank" rel="noopener noreferrer">{flow.browser_opened ? 'Open sign-in again' : 'Open sign-in in your browser'}</a>}
        <p>Waiting for {providerName(flow.provider)}…</p>
        <button className="account-secondary" onClick={async () => {await cancel(); if (flow.provider === 'email') setMode('signin');}} disabled={busy}>{flow.provider === 'email' ? 'Back to sign in' : 'Cancel sign-in'}</button>
      </div>}
      {(failure || error) && <div className="account-feedback" role="alert">{failure || error}<button className="account-secondary" onClick={async () => {await cancel(); await onRefresh();}}>Try again</button></div>}
      {!waiting && <React.Fragment>
        {adding && <button className="account-secondary" onClick={onLocal} disabled={busy}>Back to Vellum</button>}
        {(!adding || !state.active_account_id) && <p>{mode === 'signup' ? 'Already have an account?' : 'New to Vellum?'} <button className="account-mode" onClick={changeMode} disabled={busy}>{mode === 'signup' ? 'Sign in instead' : 'Sign up'}</button></p>}
      </React.Fragment>}
      <p className="account-note">Sign-in saves your identity on this device. Your chats and memory stay in this local workspace. Switching accounts does not move or separate that data.</p>
    </div>;
  }

  function AccountSettings() {
    const context = React.useContext(Context);
    return <section aria-label="Accounts" className="account-list">
      <h2>Accounts</h2>
      <p className="account-note">Manage saved accounts here. To add another, open the account picker in your profile menu. All accounts on this device share its local chats and memory.</p>
      {context.error && <p role="alert">{context.error}</p>}
      {!context.state.accounts.length && <p className="account-note">You’re using Vellum as a guest. No account is signed in.</p>}
      {context.state.accounts.map(account => <div className="account-list-row" key={account.id}>
        <div className="account-list-meta"><strong>{account.display_name}</strong><small>{account.email || '@' + account.username}</small><small>{providerName(account.provider)}{account.id === context.state.active_account_id ? ' · Active' : ''}</small></div>
        {account.id !== context.state.active_account_id && <button className="btn" disabled={context.busy} onClick={() => context.select(account.id)}>Switch</button>}
        <button className="btn" disabled={context.busy} onClick={() => context.signOut(account.id)} aria-label={`Remove ${account.display_name} from this device`}>Remove account</button>
      </div>)}
      <div className="account-settings-actions">
        {context.state.active_account_id && <button className="btn" disabled={context.busy} onClick={context.logOut}>Log out</button>}
      </div>
      <p className="account-note">Log out returns to sign-in. Remove account forgets that identity on this device. Your local data stays here.</p>
    </section>;
  }

  function AccountRoot({children}) {
    const [state, setState] = useState(empty);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [adding, setAdding] = useState(false);
    const [local, setLocal] = useState(() => {try {return localStorage.getItem(LOCAL_CHOICE) === '1';} catch {return false;}});
    const dialog = useRef(null);
    const returnFocus = useRef(null);
    const stateRevision = useRef(0);
    const mutating = useRef(false);
    async function refresh() {
      if (mutating.current) return;
      const revision = ++stateRevision.current;
      try {const next = await window.VellumApi.accounts.status(); if (revision === stateRevision.current) {setState(next); setError('');} return next;}
      catch (e) {if (revision === stateRevision.current) setError('Could not load accounts. ' + e.message); throw e;}
      finally {setLoading(false);}
    }
    useEffect(() => {refresh().catch(() => {});}, []);
    useEffect(() => {
      const sync = () => {refresh().catch(() => {});};
      const storage = event => {if (event.key === ACCOUNT_CHANGE || event.key === LOCAL_CHOICE) {try {setLocal(localStorage.getItem(LOCAL_CHOICE) === '1');} catch {} sync();}};
      window.addEventListener('focus', sync);
      window.addEventListener('storage', storage);
      return () => {window.removeEventListener('focus', sync); window.removeEventListener('storage', storage);};
    }, []);
    useEffect(() => {
      if (!adding) return;
      if (dialog.current && !dialog.current.open) dialog.current.showModal();
      return () => {
        const target = returnFocus.current?.isConnected ? returnFocus.current : document.querySelector('[aria-label="Open account menu"]');
        target?.focus();
      };
    }, [adding]);
    function notifyChange() {try {localStorage.setItem(ACCOUNT_CHANGE, String(Date.now()) + Math.random());} catch {}}
    async function chooseLocal() {
      // Local use remains available when the backend or credential store is offline.
      try {setState(await window.VellumApi.accounts.continueLocal());}
      catch {setState(current => ({...current, logged_out:false}));}
      try {localStorage.setItem(LOCAL_CHOICE, '1');} catch {}
      setLocal(true); notifyChange();
    }
    async function completeSignIn() {
      await refresh(); notifyChange();
      try {await window.VellumApi.accounts.focusVellum();} catch {}
    }
    async function mutate(method, id) {
      if (mutating.current) return false;
      mutating.current = true; ++stateRevision.current;
      setBusy(true); setError('');
      try {
        setState(await window.VellumApi.accounts[method](id));
        if (method === 'logOut') {
          try {localStorage.removeItem(LOCAL_CHOICE);} catch {}
          setLocal(false); setAdding(false);
        }
        notifyChange(); return true;
      }
      catch (e) {setError(e.message); return false;}
      finally {mutating.current = false; setBusy(false);}
    }
    function openAccount() {returnFocus.current = document.activeElement; setAdding(true);}
    const context = {state, error, busy, add: openAccount, select: id => mutate('select', id), signOut: id => mutate('signOut', id), logOut: () => mutate('logOut')};
    const active = state.accounts.find(a => a.id === state.active_account_id);
    const showWelcome = !active && (!local || state.logged_out);
    return <Context.Provider value={context}>
      {loading ? <main className="account-welcome"><p role="status">Opening Vellum…</p></main> : showWelcome ?
        <main className="account-welcome"><div className="account-layout"><div className="account-intro"><div className="account-wordmark">Vellum</div><h1>A place for everything<br/>you’re learning.</h1><p>Your conversations, knowledge, and ideas. Kept together, on your device.</p></div><SignIn state={state} initialMode={state.logged_out ? 'signin' : 'signup'} error={error} onRefresh={() => refresh().catch(() => {})} onComplete={completeSignIn} onLocal={chooseLocal}/></div></main> : children(context)}
      {adding && <dialog ref={dialog} className="account-dialog" aria-label="Add account" onCancel={event => {event.preventDefault(); setAdding(false);}} onClose={() => setAdding(false)}>
        <button className="account-dialog-close" onClick={() => setAdding(false)} autoFocus>Close</button>
        <SignIn adding initialMode="signin" state={state} error={error} onRefresh={() => refresh().catch(() => {})} onComplete={async () => {await completeSignIn(); setAdding(false);}} onLocal={() => setAdding(false)}/>
      </dialog>}
    </Context.Provider>;
  }
  window.VellumUI = window.VellumUI || {};
  window.VellumUI.Accounts = {Root: AccountRoot, Settings: AccountSettings, Context};
})();
