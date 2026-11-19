/* Analytics page: Overview · Runs · Context · Usage. Reads come from
   window.VellumApi.observability; live / pause / refresh stay App Actions
   (observability.stream.set, observability.refresh). */
(function () {
  const {useState, useEffect, useMemo, useRef, useCallback} = React;
  const A = () => window.VellumUI.Analytics;
  const api = () => window.VellumApi.observability;

  const PERIODS = [['today', 'Today'], ['7d', '7 days'], ['30d', '30 days'], ['all', 'All time']];
  const PERIOD_LABEL = {today: 'Today', '7d': 'Last 7 days', '30d': 'Last 30 days', month: 'This month', all: 'All time'};
  const TABS = [['overview', 'Overview'], ['runs', 'Runs'], ['context', 'Context'], ['usage', 'Usage']];
  const OUTCOME_TONE = {completed: 'var(--av-good)', failed: 'var(--av-bad)', cancelled: 'var(--av-k-context)'};
  const PRIVACY = {GREEN: ['General', 'var(--av-good)'], YELLOW: ['Personal, scrubbed', 'var(--av-warn)'], RED: ['Sensitive, blocked', 'var(--av-bad)']};

  const RefreshIcon = () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12 1M18 17A7 7 0 0 1 6 16"/></svg>;

  function useSnapshot(period, control) {
    const [snapshot, setSnapshot] = useState(null);
    const [error, setError] = useState('');
    const load = useCallback(async () => {
      try { setSnapshot(await api().summary(period)); setError(''); }
      catch (err) { setError(err && err.message ? err.message : 'Analytics is unreachable.'); }
    }, [period]);
    useEffect(() => { load(); }, [load]);
    useEffect(() => {
      if (control && control.snapshot && control.snapshot.period === period) { setSnapshot(control.snapshot); setError(''); }
    }, [control && control.snapshot, period]);
    return {snapshot, error, setError, load};
  }

  function useLiveEvents(paused, reconnectRevision, onRunEvent) {
    const [state, setState] = useState('connecting');
    const last = useRef(0);
    const handler = useRef(onRunEvent);
    handler.current = onRunEvent;
    useEffect(() => {
      if (paused) { setState('paused'); return undefined; }
      setState('connecting');
      const source = new EventSource(api().streamUrl(last.current));
      const onEvent = event => {
        try {
          const item = JSON.parse(event.data);
          last.current = Math.max(last.current, Number(item.id || 0));
          setState('live');
          handler.current(item);
        } catch (_) { /* a malformed frame is skipped */ }
      };
      source.onopen = () => setState('live');
      source.onerror = () => setState('reconnecting');
      source.addEventListener('observability.event', onEvent);
      return () => { source.removeEventListener('observability.event', onEvent); source.close(); };
    }, [paused, reconnectRevision]);
    return state;
  }

  // ------------------------------------------------------------ overview
  function Overview({snapshot, period, onOpenRun, onTab}) {
    const {StatTile, Delta, Breakdown, ModelUsage, ContextWindowCard, fmtTokens, fmtMs, fmtPct, relTime, shortId} = A();
    const turns = snapshot.turns || {};
    const daily = turns.daily || [];
    const ctx = snapshot.context || {};
    const latency = turns.latency || {};
    const runs = snapshot.recent_runs || [];
    const outcomes = Object.entries(turns.outcomes || {}).map(([key, value]) => ({label: A().humanize(key), value, color: OUTCOME_TONE[key] || 'var(--av-k-context)'}));
    const privacy = Object.entries(turns.privacy || {}).map(([key, value]) => ({label: (PRIVACY[key] || [key])[0], value, color: (PRIVACY[key] || [0, 'var(--av-k-context)'])[1]}));
    const providers = Object.entries(turns.providers || {}).map(([key, value], i) => ({label: A().providerLabel('', key), value, color: ['var(--av-m3)', 'var(--av-m1)', 'var(--av-m2)', 'var(--av-m4)'][i % 4]}));
    const latestModel = (turns.models || [])[0];
    return <React.Fragment>
      <div className="av-grid kpis">
        <StatTile label="Turns" count={turns.turns || 0} slot={0} delta={<Delta now={turns.turns} before={turns.previous_turns} tone="neutral"/>} series={daily.map(d => d.turns)}/>
        <StatTile label="Answered without error" slot={1} {...(turns.turns ? {count: turns.success_rate, format: n => fmtPct(n, 1)} : {value: '—'})}
          sub={`${(turns.outcomes || {}).failed || 0} failed · ${(turns.outcomes || {}).cancelled || 0} stopped`} series={daily.map(d => d.turns ? 1 - d.failed / d.turns : 0)} tone="var(--av-good)"/>
        <StatTile label="First token, median" slot={2} {...(latency.first_token_p50_ms != null ? {count: latency.first_token_p50_ms, format: fmtMs} : {value: '—'})} sub={`p95 ${fmtMs(latency.first_token_p95_ms)} · full reply ${fmtMs(latency.total_p50_ms)}`}
          series={daily.map(d => d.p50_total_ms || 0)} tone="var(--av-c-convo)"/>
        <StatTile label="Tokens" count={turns.tokens || 0} format={fmtTokens} slot={3} delta={<Delta now={turns.tokens} before={turns.previous_tokens} tone="neutral"/>} series={daily.map(d => d.input + d.output)} tone="var(--av-c-instr)"/>
      </div>
      <div className="av-grid two">
        <ModelUsage turns={turns} periodLabel={PERIOD_LABEL[period]}/>
        <div className="av-grid" style={{alignContent: 'start'}}>
          <ContextWindowCard shape={ctx.latest} model={latestModel && latestModel.model} title="Latest context window"/>
          <section className="av-card">
            <header className="av-card-head"><h3>Context pressure</h3><small>{(ctx.turns || 0).toLocaleString()} measured turns</small></header>
            <div className="av-grid halves" style={{gap: 10}}>
              <div><div className="av-stat-label">Average fill</div><div className="av-stat-value" style={{fontSize: 18}}>{ctx.turns ? fmtPct(ctx.avg_fill) : '—'}</div></div>
              <div><div className="av-stat-label">Compactions</div><div className="av-stat-value" style={{fontSize: 18}}>{ctx.compactions || 0}</div></div>
            </div>
            <button type="button" className="av-link" onClick={() => onTab('context')}>See what fills it →</button>
          </section>
        </div>
      </div>
      <div className="av-grid three">
        <Breakdown title="How turns ended" parts={outcomes} slot={0}/>
        <Breakdown title="Privacy gate" note="per turn" parts={privacy} slot={1}/>
        <Breakdown title="Where inference ran" parts={providers} slot={2}/>
      </div>
      <section className="av-card av-recent">
        <header className="av-card-head" style={{padding: '8px 10px 0'}}><h3>Recent runs</h3><small>click one for its trace</small>
          <button type="button" className="av-link" style={{marginLeft: 'auto'}} onClick={() => onTab('runs')}>All runs →</button></header>
        {runs.length ? runs.slice(0, 6).map((run, i) => <RunRow key={run.response_id} run={run} slot={i} onClick={() => onOpenRun(run.response_id)}/>)
          : <p className="av-empty">Runs appear here as you chat with Vellum.</p>}
      </section>
    </React.Fragment>;
  }

  function RunRow({run, active, onClick, slot = 0}) {
    const {relTime, shortId} = A();
    return <button type="button" className={'av-run av-enter' + (active ? ' on' : '')} style={{'--slot': Math.min(slot, 14)}} onClick={onClick}>
      <span className={'av-run-dot ' + run.status}/>
      <span className="av-run-main"><b>Run {shortId(run.response_id)}</b>
        <span>{run.tool_count} {run.tool_count === 1 ? 'tool' : 'tools'} · {run.source_count} sources · {run.event_count} events</span></span>
      <span className="av-run-when">{run.status === 'in_progress' ? 'Live' : relTime(run.started_at)}</span>
    </button>;
  }

  // ------------------------------------------------------------ runs
  function Runs({runs, selected, onSelect, trace, traceLoading, turns}) {
    const {TraceWaterfall, Segmented} = A();
    const [filter, setFilter] = useState('all');
    const list = runs.filter(run => filter === 'all' || (filter === 'failed' ? run.status === 'failed' : run.tool_count > 0));
    return <div className="av-runs">
      <section className="av-card av-run-list" aria-label="Runs">
        <div className="av-run-filter"><Segmented label="Filter runs" value={filter} onChange={setFilter} options={[['all', 'All'], ['tools', 'Used tools'], ['failed', 'Failed']]}/></div>
        {list.length ? list.map((run, i) => <RunRow key={run.response_id} run={run} slot={i} active={run.response_id === selected} onClick={() => onSelect(run.response_id)}/>)
          : <p className="av-empty">No runs match.</p>}
      </section>
      <TraceWaterfall trace={trace} loading={traceLoading}/>
    </div>;
  }

  // ------------------------------------------------------------ context
  function ContextTab({snapshot}) {
    const {ContextWindowCard, CONTEXT_PARTS, fmtTokens, fmtPct} = A();
    const ctx = snapshot.context || {};
    const avg = ctx.avg_layers || {};
    const parts = CONTEXT_PARTS.filter(part => !part.reserved);
    const maxLayer = Math.max(1, ...parts.map(part => avg[part.key] || 0));
    const totalAvg = parts.reduce((sum, part) => sum + (avg[part.key] || 0), 0);
    const model = ((snapshot.turns || {}).models || [])[0];
    return <div className="av-ctx-page">
      <ContextWindowCard shape={ctx.latest} model={model && model.model} title="Latest context window"/>
      <div className="av-grid" style={{alignContent: 'start'}}>
        <div className="av-grid halves">
          <section className="av-card av-stat"><div className="av-stat-label">Average fill</div><div className="av-stat-value">{ctx.turns ? fmtPct(ctx.avg_fill) : '—'}</div><div className="av-stat-sub">peak {ctx.turns ? fmtPct(ctx.peak_fill) : '—'}</div></section>
          <section className="av-card av-stat"><div className="av-stat-label">Turns near the limit</div><div className="av-stat-value">{ctx.near_limit || 0}</div><div className="av-stat-sub">{ctx.compactions || 0} compacted</div></section>
        </div>
        <section className="av-card">
          <header className="av-card-head"><h3>What an average turn carries</h3><small>{(ctx.turns || 0).toLocaleString()} turns · {fmtTokens(totalAvg)} tokens</small></header>
          {ctx.turns ? <div className="av-layers">{parts.map(part => <div className="av-layer-row" key={part.key} title={part.hint}>
            <span>{part.label}</span>
            <span className="av-layer-bar"><i className="av-fill" style={{width: ((avg[part.key] || 0) / maxLayer * 100) + '%', background: part.color, '--slot': parts.indexOf(part)}}/></span>
            <span className="av-layer-v">{fmtTokens(avg[part.key] || 0)}</span>
          </div>)}</div> : <p className="av-empty">Context is measured from your next reply onward.</p>}
          <p className="av-hint" style={{marginTop: 12}}>Instructions and tool definitions are paid on every turn; trimming unused tools or plugins frees the most room on a local model.</p>
        </section>
      </div>
    </div>;
  }

  // ------------------------------------------------------------ usage
  function UsageTab({snapshot, period}) {
    const {ModelUsage, fmtTokens, fmtMs, fmtMoney, modelName, providerLabel, shortDay} = A();
    const turns = snapshot.turns || {};
    const daily = turns.daily || [];
    const max = Math.max(1, ...daily.map(d => d.turns));
    const [hover, setHover] = useState(null);
    return <React.Fragment>
      <ModelUsage turns={turns} periodLabel={PERIOD_LABEL[period]}/>
      <div className="av-grid halves">
        <section className="av-card">
          <header className="av-card-head"><h3>Turns per day</h3><small>{hover !== null && daily[hover] ? `${shortDay(daily[hover].day)} · ${daily[hover].turns} turns · ${daily[hover].failed} failed` : 'failed turns in red'}</small></header>
          {daily.length ? <React.Fragment>
            <div className="av-trend" onMouseLeave={() => setHover(null)}>{daily.map((d, i) => <div className="av-trend-col av-grow-y" key={d.day} style={{'--slot': i, '--step': (Math.min(.12, .9 / daily.length)).toFixed(3) + 's'}} onMouseEnter={() => setHover(i)}>
              {d.failed > 0 && <i className="fail" style={{height: (d.failed / max * 100) + '%'}}/>}
              <i style={{height: ((d.turns - d.failed) / max * 100) + '%'}}/>
            </div>)}</div>
            <div className="av-trend-x"><span>{shortDay(daily[0].day)}</span><span>{shortDay(daily[daily.length - 1].day)}</span></div>
          </React.Fragment> : <p className="av-empty">No turns in this period.</p>}
        </section>
        <section className="av-card">
          <header className="av-card-head"><h3>By model</h3></header>
          {(turns.models || []).length ? <table className="av-table"><thead><tr><th>Model</th><th>Turns</th><th>In</th><th>Out</th><th>First token</th><th>Cost</th></tr></thead>
            <tbody>{turns.models.slice(0, 8).map((m, i) => <tr key={m.model} className="av-enter" style={{'--slot': i}}><td>{modelName(m.model)}<small>{providerLabel(m.model, m.provider)}</small></td>
              <td>{m.turns.toLocaleString()}</td><td>{fmtTokens(m.input)}</td><td>{fmtTokens(m.output)}</td><td>{fmtMs(m.p50_first_token_ms)}</td><td>{fmtMoney(m.cost_usd)}</td></tr>)}</tbody></table>
            : <p className="av-empty">No model calls in this period.</p>}
        </section>
      </div>
    </React.Fragment>;
  }

  // ------------------------------------------------------------ page
  function AnalyticsPage({control, onAction}) {
    const {Segmented} = A();
    const [tab, setTab] = useState('overview');
    const [period, setPeriod] = useState('7d');
    const [refreshing, setRefreshing] = useState(false);
    const {snapshot, error, setError, load} = useSnapshot(period, control);
    const [selected, setSelected] = useState(null);
    const [trace, setTrace] = useState(null);
    const [traceLoading, setTraceLoading] = useState(false);
    const paused = !control || control.streaming === false;

    const loadTrace = useCallback(async (id, quiet = false) => {
      if (!id) return;
      if (!quiet) setTraceLoading(true);
      try { setTrace(await api().trace(id)); } catch (_) { if (!quiet) setTrace(null); }
      finally { if (!quiet) setTraceLoading(false); }
    }, []);
    useEffect(() => { loadTrace(selected); }, [selected, loadTrace]);
    useEffect(() => {
      const runs = (snapshot && snapshot.recent_runs) || [];
      if (!selected && runs.length) setSelected(runs[0].response_id);
    }, [snapshot, selected]);

    const selectedRef = useRef(selected);
    selectedRef.current = selected;
    const live = useLiveEvents(paused, control && control.reconnectRevision, item => {
      if (item.response_id === selectedRef.current) loadTrace(item.response_id, true);
      if (item.type === 'run_started' || item.type === 'run_completed' || item.type === 'run_failed') load();
    });

    const dispatchControl = async (actionId, arguments_ = {}) => {
      if (typeof onAction !== 'function') return null;
      const receipt = await onAction(actionId, arguments_);
      if (!receipt || receipt.status !== 'applied') setError(receipt && receipt.message ? receipt.message : 'Analytics is unreachable.');
      return receipt;
    };
    const refresh = async () => {
      setRefreshing(true);
      try { await dispatchControl('observability.refresh', {period}); await load(); if (selected) await loadTrace(selected, true); }
      finally { setRefreshing(false); }
    };
    const openRun = id => { setSelected(id); setTab('runs'); };
    const liveLabel = paused ? 'Paused' : live === 'live' ? 'Live' : live === 'reconnecting' ? 'Reconnecting' : 'Connecting';

    return <section className="av-page" aria-label="Analytics">
      <div className="av-page-inner">
        <header className="av-page-head">
          <h1>Analytics</h1>
          <nav className="av-page-tabs" role="tablist" aria-label="Analytics views">{TABS.map(([id, label]) =>
            <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>{label}</button>)}</nav>
          <div className="av-page-tools">
            {tab !== 'runs' && <Segmented label="Period" value={period} onChange={setPeriod} options={PERIODS}/>}
            {paused
              ? <button type="button" className="av-live" aria-pressed="false" onClick={() => dispatchControl('observability.stream.set', {enabled:true})}>Paused · resume</button>
              : <button type="button" className={'av-live ' + (live === 'live' ? 'on' : 'wait')} aria-pressed="true" title="Pause live updates" onClick={() => dispatchControl('observability.stream.set', {enabled:paused})}>{liveLabel}</button>}
            <button type="button" className={'av-icon-btn' + (refreshing ? ' spin' : '')} aria-label="Refresh" disabled={refreshing} onClick={refresh}><RefreshIcon/></button>
          </div>
        </header>
        {error && <div className="av-error" role="alert">{error} Live data resumes when the Vellum API is reachable.</div>}
        {!snapshot ? <p className="av-empty">{error ? '' : 'Loading analytics…'}</p>
          : tab === 'overview' ? <Overview snapshot={snapshot} period={period} onOpenRun={openRun} onTab={setTab}/>
          : tab === 'runs' ? <Runs runs={snapshot.recent_runs || []} selected={selected} onSelect={setSelected} trace={trace} traceLoading={traceLoading} turns={snapshot.turns}/>
          : tab === 'context' ? <ContextTab snapshot={snapshot}/>
          : <UsageTab snapshot={snapshot} period={period}/>}
        <p className="av-hint">Read from Vellum’s local records on this device: run events, the per-turn audit log and context measurements. No prompt or answer text is stored here.</p>
      </div>
    </section>;
  }

  window.VellumUI = window.VellumUI || {};
  window.VellumUI.AnalyticsPage = AnalyticsPage;
})();
