(function () {
  const {useEffect, useState} = React;
  function WebSearchSettings() {
    const [status, setStatus] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
    const refresh = async () => { const value = await window.VellumApi.settings.get(); setStatus(value.web_search); };
    useEffect(() => { let alive = true; window.VellumApi.settings.get().then(value => { if (alive) setStatus(value.web_search); }).catch(() => { if (alive) setError('Search preferences are unavailable.'); }); return () => { alive = false; }; }, []);
    const choose = async provider => {
      setBusy(true); setError('');
      try {
        const receipt = await window.VellumApi.appActions.dispatch({request_id:'search_'+crypto.randomUUID(), action_id:'settings.web_search.set', arguments:{provider}}, {source:'ui'});
        if (receipt.status !== 'applied') throw new Error(receipt.message || 'The search preference was not saved.');
        await refresh();
      } catch (err) { setError(err.message); } finally { setBusy(false); }
    };
    const options = [{value:'auto',label:'Automatic',sub:'SerpAPI first, with available fallbacks'},
      ...(status?.providers || []).map(provider => ({value:provider.id,label:provider.name,sub:provider.available?'Available':'Needs connection'}))];
    if(status?.selected !== 'auto' && status?.selected && !options.some(option => option.value === status.selected)) options.push({value:status.selected,label:status.selected,sub:'Unavailable'});
    const activeName = status?.providers.find(provider => provider.id === status.active)?.name || status?.active || 'Unavailable';
    return <section className="product-hunt-workspace" aria-label="Web search provider" aria-busy={busy}>
      <h2>Web search</h2>
      <div className="web-search-provider-field"><span>Preferred provider</span><window.VellumUI.VSelect ariaLabel="Preferred web search provider" value={status?.selected || 'auto'} options={options} disabled={!status || busy} onValueChange={choose}/></div>
      <p className="product-hunt-privacy">{status?.automatic_fallback?'Automatic uses SerpAPI first when available, then another connected provider if it fails.':'An explicit choice uses only that provider. Connect or enable it if it is unavailable.'} Current provider: {activeName}.</p>
      {error && <p role="alert" className="plugins-error">{error}</p>}
    </section>;
  }
  window.VellumUI = window.VellumUI || {}; window.VellumUI.WebSearchSettings = WebSearchSettings;
})();
