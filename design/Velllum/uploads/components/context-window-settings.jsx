/* Settings → Configuration → Context window.
   Reads /api/settings `context_window`; every change dispatches the
   settings.context_window.set App Action (the same one chat uses). */
(function () {
  const {useEffect, useState} = React;
  const tokens = value => value >= 1000000 ? (value / 1000000).toFixed(value % 1000000 ? 2 : 0).replace(/\.?0+$/, '') + 'M'
    : Math.round(value / 1024) + 'k';
  const SOURCES = {environment: 'Set by OLLAMA_CONTEXT_LENGTH in .env', settings: 'Your choice',
    measured: 'Measured on this computer', default: 'Default until Vellum measures this model'};

  function ContextWindowSettings() {
    const [state, setState] = useState(null), [busy, setBusy] = useState(false);
    const [error, setError] = useState(''), [notice, setNotice] = useState('');
    const load = async () => { const value = await window.VellumApi.settings.get(); setState(value.context_window || null); };
    useEffect(() => {
      let alive = true;
      window.VellumApi.settings.get().then(value => { if (alive) setState(value.context_window || null); })
        .catch(() => { if (alive) setError('Context settings are unavailable.'); });
      return () => { alive = false; };
    }, []);
    const save = async patch => {
      setBusy(true); setError(''); setNotice('');
      try {
        const receipt = await window.VellumApi.appActions.dispatch({request_id: 'context_' + crypto.randomUUID(),
          action_id: 'settings.context_window.set', arguments: patch}, {source: 'ui'});
        if (receipt.status !== 'applied') throw new Error(receipt.message || 'The context window was not saved.');
        setNotice(receipt.message || 'Saved.');
        await load();
      } catch (err) { setError(err.message); } finally { setBusy(false); }
    };
    if (!state) return error ? <p role="alert" className="plugins-error">{error}</p> : null;
    const measured = state.measured;
    const automatic = 'Automatic' + (measured ? ' · ' + tokens(measured.window) + (measured.placement === 'gpu' ? ' on your GPU' : ' (' + measured.placement + ')') : '');
    const localOptions = [{value: 'auto', label: automatic},
      ...state.local_choices.map(value => ({value: String(value), label: tokens(value) + ' tokens'}))];
    const cloudOptions = [{value: 'full', label: 'Full model limit'},
      ...state.cloud_choices.map(value => ({value: String(value), label: 'Up to ' + tokens(value)}))];
    const pick = (key, value) => save({[key]: value === 'auto' || value === 'full' ? value : Number(value)});
    return <section className="cfg-current cfg-context-window" aria-label="Context window" aria-busy={busy}>
      <div className="cfg-current-identity"><div><span className="settings-small-label">Context window</span>
        <strong>{state.active_window ? tokens(state.active_window) + ' tokens for ' + state.model.replace(/^[^/]+\//, '') : 'Per model'}</strong></div></div>
      <div className="cfg-current-model"><span>Local models</span>
        <window.VellumUI.VSelect ariaLabel="Local model context window" value={String(state.preferences.local)} options={localOptions}
          disabled={busy || state.local_source === 'environment'} onValueChange={value => pick('local', value)}/></div>
      <div className="cfg-current-model"><span>Hosted models</span>
        <window.VellumUI.VSelect ariaLabel="Hosted model context cap" value={String(state.preferences.cloud)} options={cloudOptions}
          disabled={busy || state.cloud_source === 'environment' && !!state.cloud_cap} onValueChange={value => pick('cloud', value)}/></div>
      <p className="cfg-key-help">{SOURCES[state.local_source] || ''}. Larger windows keep more of the chat in view; earlier parts are summarized and stay searchable either way. Hosted models charge for every token sent, so a cap keeps long chats affordable. You can also ask Vellum in chat, for example “set the context to 64k”.</p>
      {notice && <p className="cfg-key-help" role="status">{notice}</p>}
      {error && <p role="alert" className="plugins-error">{error}</p>}
    </section>;
  }
  window.VellumUI = window.VellumUI || {};
  window.VellumUI.ContextWindowSettings = ContextWindowSettings;
})();
