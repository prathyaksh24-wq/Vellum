(function () {
  function YouTubeHistoryControls({onReceipt}) {
    const [busy, setBusy] = React.useState(false);
    const [message, setMessage] = React.useState('Watch history uses the YouTube account signed into Browser.');
    const [error, setError] = React.useState(false);
    const account = React.useRef('');
    const pending = React.useRef(false);
    async function refresh() {
      if (pending.current) return;
      pending.current = true;
      setBusy(true);
      setError(false);
      setMessage('Reading recent watch history from Browser…');
      try {
        const receipt = await window.VellumApi.appActions.dispatch(
          {request_id:'youtube_history_' + crypto.randomUUID(), action_id:'youtube.history.refresh', arguments:{}},
          {source:'ui'});
        onReceipt?.(receipt);
        if (receipt.status !== 'applied') throw new Error(receipt.message || 'History refresh failed.');
        const history = receipt.result.history;
        const changedAccount = account.current && account.current !== history.account_id;
        account.current = history.account_id;
        const time = new Date(history.refreshed_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
        setMessage((changedAccount ? 'Browser account changed. ' : '') +
          'Refreshed ' + history.total + ' recent entries at ' + time + '. Saved locally; recent page only.');
      } catch (failure) {
        setError(true);
        setMessage(failure.message || 'History refresh failed. Check Browser and try again.');
      } finally {
        pending.current = false;
        setBusy(false);
      }
    }
    return <div className="youtube-history-controls" style={{display:'flex', alignItems:'center', gap:12, flexWrap:'wrap', padding:'10px 0'}}>
      <button className="btn" onClick={refresh} disabled={busy} aria-label="Refresh history">{busy ? 'Refreshing…' : 'Refresh history'}</button>
      <span role={error ? 'alert' : 'status'} aria-live="polite" style={{fontSize:12, color:error ? 'var(--txt)' : 'var(--dim)', flex:'1 1 240px'}}>{message}</span>
    </div>;
  }
  window.VellumUI = window.VellumUI || {};
  window.VellumUI.YouTubeHistoryControls = YouTubeHistoryControls;
})();
