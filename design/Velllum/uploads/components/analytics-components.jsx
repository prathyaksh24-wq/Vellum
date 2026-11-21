/* Analytics building blocks shared by the Analytics page, the chat context meter
   and the Memory growth tab. Every number shown comes from Vellum's own local
   records (observability.db, the turn audit log, the memory store); nothing is
   sampled or invented. Components are presentational: they receive data and
   never write. */
(function () {
  const {useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect} = React;

  // ---------------------------------------------------------------- format
  const fmtTokens = value => {
    const n = Number(value || 0);
    if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1).replace(/\.0$/, '') + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 0 : 1).replace(/\.0$/, '') + 'K';
    return String(Math.round(n));
  };
  const fmtMs = value => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    const ms = Number(value);
    if (ms < 1000) return Math.round(ms) + 'ms';
    if (ms < 60000) return (ms / 1000).toFixed(ms < 10000 ? 1 : 0) + 's';
    const minutes = Math.floor(ms / 60000);
    return minutes + 'm ' + String(Math.round((ms % 60000) / 1000)).padStart(2, '0') + 's';
  };
  const fmtMoney = value => {
    const n = Number(value || 0);
    if (!n) return '$0';
    return '$' + (n < 0.01 ? n.toFixed(4) : n < 10 ? n.toFixed(2) : n.toFixed(0));
  };
  const fmtPct = (value, digits = 0) => (Number(value || 0) * 100).toFixed(digits) + '%';
  const parseTime = value => {
    if (!value) return null;
    const text = String(value);
    const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(text) || !/T/.test(text) ? text : text + 'Z');
    return Number.isNaN(date.getTime()) ? null : date;
  };
  const relTime = (value, now = Date.now()) => {
    const date = parseTime(value);
    if (!date) return '';
    const seconds = Math.round((now - date.getTime()) / 1000);
    if (seconds < 45) return 'just now';
    if (seconds < 3600) return Math.round(seconds / 60) + 'm ago';
    if (seconds < 86400) return Math.round(seconds / 3600) + 'h ago';
    if (seconds < 86400 * 30) return Math.round(seconds / 86400) + 'd ago';
    return date.toLocaleDateString(undefined, {month: 'short', day: 'numeric'});
  };
  const shortDay = value => {
    const date = parseTime(value);
    return date ? date.toLocaleDateString(undefined, {month: 'short', day: 'numeric'}) : '';
  };
  const shortId = value => String(value || '').replace(/^resp[_-]?/, '').slice(0, 8) || '—';
  const humanize = name => {
    const text = String(name || '').replace(/[_-]+/g, ' ').trim();
    return text ? text[0].toUpperCase() + text.slice(1) : 'Unnamed';
  };
  const modelName = id => {
    const text = String(id || '');
    const tail = text.includes('/') ? text.slice(text.indexOf('/') + 1) : text;
    return tail || 'Unknown model';
  };
  const providerLabel = (id, provider) => {
    const p = String(provider || String(id || '').split('/')[0] || '');
    if (p === 'ollama') return 'Local';
    if (p === 'openrouter') return 'OpenRouter';
    return p ? p[0].toUpperCase() + p.slice(1) : '';
  };

  // ---------------------------------------------------------------- shared bits
  const Glyph = ({d, size = 14}) => <svg className="av-glyph" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d}/></svg>;
  const G = {
    chevron: 'M9 6l6 6-6 6',
    close: 'M6 6l12 12M18 6 6 18',
    spark: 'M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18',
    plus: 'M12 5v14M5 12h14',
    check: 'M5 12.5l4.5 4.5L19 7.5',
    archive: 'M4 7h16v3H4zM6 10v9h12v-9M10 14h4',
    restore: 'M4 12a8 8 0 1 0 2.5-5.8M4 4v4h4',
    pencil: 'M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4',
    pin: 'M9 4h6l-1 6 3 3H7l3-3zM12 13v7',
    eyeOff: 'M3 3l18 18M10.6 6.2A9.8 9.8 0 0 1 12 6c5 0 9 6 9 6a15 15 0 0 1-2.7 3.3M6.2 7.8C4.2 9.4 3 12 3 12s4 6 9 6a8.6 8.6 0 0 0 3.4-.7',
    trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
    filter: 'M4 5h16l-6 8v6l-4-2v-4z',
    eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
    ledger: 'M6 3h10l3 3v15H6zM9 9h7M9 13h7M9 17h4',
    trace: 'M4 6h9M7 12h11M10 18h7',
  };

  // ---------------------------------------------------------------- motion
  // Ported from the Motion Prompt library (MIT, (c) 2026 Shohei Ohtaki, https://showheyohtaki.github.io/motion-prompt/):
  //   #007 Count-up        value = from + (to - from)(1 - (1 - p)^4), then a landing bounce 1 + 0.07 e^(-7t) cos(15t).
  //                        The demo counts for 2.45 s; dashboard figures count for 1.2 s (0.45 s when a value changes later).
  //   #060 Segmented ctrl  the highlight slides over 0.25 s easeInOutCubic; bars re-height with the same easing.
  //   #230 Combo chart     bars grow 0.36 s ease-out from 0.4 s, 0.12 s apart; the line draws left to right at even speed.
  //   #231 Pictogram chart cells pop in (0.3 s ease-out-back) in gray, then each category tints in turn, 0.22 s apart.
  //   #232 100% stacked    bars fill left to right over 0.7 s cubic ease-in-out, 0.16 s apart; % fades in 0.75 s after.
  //   #002 Stagger         lists drop in one by one, 0.15 s + 0.12 s apart, 0.5 s backOut(2.6).
  // CSS holds the keyframes (analytics.css, "motion" section). prefers-reduced-motion and environments without
  // matchMedia show final values at once.
  const reducedMotion = () => typeof window.matchMedia !== 'function' || window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function useCountUp(target, {duration = 1200, delay = 0} = {}) {
    const goal = Number(target) || 0;
    const [value, setValue] = useState(() => reducedMotion() ? goal : 0);
    const [landed, setLanded] = useState(0);
    const current = useRef(reducedMotion() ? goal : 0);
    const runs = useRef(0);
    useEffect(() => {
      if (reducedMotion()) { current.current = goal; setValue(goal); return undefined; }
      const from = current.current, span = runs.current++ ? Math.min(duration, 450) : duration;
      if (from === goal) { setValue(goal); return undefined; }
      const start = performance.now() + (runs.current === 1 ? delay : 0);
      let frame;
      const tick = now => {
        const p = Math.min(1, Math.max(0, (now - start) / span));
        current.current = from + (goal - from) * (1 - Math.pow(1 - p, 4));
        setValue(current.current);
        if (p < 1) frame = requestAnimationFrame(tick); else setLanded(n => n + 1);
      };
      frame = requestAnimationFrame(tick);
      return () => cancelAnimationFrame(frame);
    }, [goal]);
    return [value, landed];
  }

  // A number that counts up to its value; format turns the raw number into text.
  function CountUp({value, format = n => Math.round(n).toLocaleString(), delay = 0, className = ''}) {
    const [shown, landed] = useCountUp(value, {delay});
    return <span className={'av-count-up' + (className ? ' ' + className : '')} key={landed} data-landed={landed > 0 ? 'true' : undefined}>{format(shown)}</span>;
  }

  function Segmented({value, options, onChange, label}) {
    const ref = useRef(null);
    const [pill, setPill] = useState(null);
    useLayoutEffect(() => {
      const active = ref.current && ref.current.querySelector('[aria-selected="true"]');
      if (active) setPill(previous => ({x: active.offsetLeft, w: active.offsetWidth, ready: !!previous}));
    }, [value, options.length]);
    return <div className="av-seg" role="tablist" aria-label={label} ref={ref}>
      {pill && <i className={'av-seg-pill' + (pill.ready ? ' ready' : '')} style={{width: pill.w, transform: `translateX(${pill.x - 2}px)`}} aria-hidden="true"/>}
      {options.map(([id, text]) => <button key={id} type="button" role="tab" aria-selected={value === id} className={value === id ? 'on' : ''} onClick={() => onChange(id)}>{text}</button>)}
    </div>;
  }

  // tone: 'up' when a rise is good, 'down' when a fall is good, 'neutral' when neither.
  function Delta({now, before, tone = 'up', suffix = 'vs last period'}) {
    if (!before) return null;
    const change = (Number(now || 0) - Number(before)) / Number(before);
    if (!Number.isFinite(change)) return null;
    const up = change >= 0;
    const mood = Math.abs(change) < 0.005 ? 'flat' : tone === 'neutral' ? 'neutral' : (tone === 'down' ? !up : up) ? 'good' : 'bad';
    return <span className={'av-delta ' + mood} title={suffix}>
      {(up ? '+' : '−') + Math.abs(change * 100).toFixed(Math.abs(change) < 0.1 ? 1 : 0) + '%'} <span>{suffix}</span>
    </span>;
  }

  // Tiny area sparkline; values only, no axes.
  function Sparkline({values, height = 28, tone = 'var(--av-ink)'}) {
    const points = (values || []).map(Number);
    if (points.length < 2) return <div className="av-spark-empty" style={{height}}/>;
    const max = Math.max(1, ...points), width = 120;
    const xy = points.map((v, i) => [i / (points.length - 1) * width, height - 2 - v / max * (height - 4)]);
    const line = xy.map(p => p.map(n => n.toFixed(1)).join(',')).join(' ');
    return <svg className="av-spark av-draw" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true" style={{height}}>
      <polygon className="av-spark-area" points={`0,${height} ${line} ${width},${height}`} fill={tone} opacity=".09"/>
      <polyline points={line} fill="none" stroke={tone} strokeWidth="1.4" vectorEffect="non-scaling-stroke"/>
    </svg>;
  }

  // count + format: the value counts up (#007); value alone is shown as given.
  function StatTile({label, value, count, format, sub, delta, series, tone, slot = 0}) {
    return <section className="av-card av-stat av-enter" style={{'--slot': slot}}>
      <div className="av-stat-label">{label}</div>
      <div className="av-stat-value">{count !== undefined && count !== null ? <CountUp value={count} format={format} delay={150 + slot * 120}/> : value}</div>
      <div className="av-stat-sub">{delta}{sub && <span>{sub}</span>}</div>
      {series && <Sparkline values={series} tone={tone}/>}
    </section>;
  }

  // One 100% bar split into parts with a legend underneath (Compact Breakdown).
  function Breakdown({title, parts, format = n => n.toLocaleString(), note, slot = 0}) {
    const total = parts.reduce((sum, part) => sum + Number(part.value || 0), 0);
    const [hover, setHover] = useState(null);
    return <section className="av-card av-breakdown" style={{'--slot': slot}}>
      <header className="av-card-head"><h3>{title}</h3>{note && <small>{note}</small>}</header>
      {total ? <React.Fragment>
        <div className="av-bd-bar av-fill" role="img" aria-label={parts.map(p => `${p.label} ${p.value}`).join(', ')}>
          {parts.filter(p => p.value > 0).map(p => <i key={p.label} style={{flexGrow: p.value, background: p.color}} className={hover && hover !== p.label ? 'dim' : ''} onMouseEnter={() => setHover(p.label)} onMouseLeave={() => setHover(null)}/>)}
        </div>
        <ul className="av-bd-legend">{parts.map(p => <li key={p.label} className={hover && hover !== p.label ? 'dim' : ''} onMouseEnter={() => setHover(p.label)} onMouseLeave={() => setHover(null)}>
          <span className="av-dot" style={{background: p.color}}/><span className="av-bd-name">{p.label}</span>
          <span className="av-bd-val">{format(p.value)}</span><span className="av-bd-pct">{fmtPct(p.value / total)}</span>
        </li>)}</ul>
      </React.Fragment> : <p className="av-empty">Nothing recorded in this period.</p>}
    </section>;
  }

  // ---------------------------------------------------------------- context window
  const CONTEXT_PARTS = [
    {key: 'instructions', label: 'Instructions', hint: 'Vellum’s rules, personality and runtime contract', color: 'var(--av-c-instr)'},
    {key: 'tool_schemas', label: 'Tools', hint: 'Definitions of the tools this turn can call', color: 'var(--av-c-tools)'},
    {key: 'personal_memory', label: 'Memory', hint: 'What Vellum recalled about you', color: 'var(--av-c-memory)'},
    {key: 'retrieved_history', label: 'Past chats', hint: 'Earlier conversations pulled in for this turn', color: 'var(--av-c-retrieved)'},
    {key: 'compacted_history', label: 'Earlier summary', hint: 'Compacted digest of older turns in this chat', color: 'var(--av-c-summary)'},
    {key: 'recent_conversation', label: 'Conversation', hint: 'Recent messages in this chat', color: 'var(--av-c-convo)'},
    {key: 'output_reserved', label: 'Reserved for reply', hint: 'Room kept free for the answer', color: 'var(--av-c-reserved)', reserved: true},
    {key: 'safety_margin', label: 'Safety margin', hint: 'Headroom for estimate error', color: 'var(--av-c-margin)', reserved: true},
  ];
  const COLS = 32, ROWS = 6;

  function contextSegments(shape) {
    const layers = (shape && shape.layers) || {};
    return CONTEXT_PARTS.map(part => ({...part, value: part.key === 'output_reserved' ? Number(shape.output_reserved || 0)
      : part.key === 'safety_margin' ? Number(shape.safety_margin || 0) : Math.max(0, Number(layers[part.key] || 0))}));
  }

  // Largest-remainder cell allocation so every non-empty part gets at least one cell.
  function allocateCells(segments, window, cells) {
    const taken = segments.reduce((sum, s) => sum + s.value, 0);
    const parts = [...segments, {key: 'free', value: Math.max(0, window - taken)}];
    const total = Math.max(window, taken) || 1;
    const raw = parts.map(p => p.value / total * cells);
    const counts = raw.map((r, i) => parts[i].value > 0 ? Math.max(1, Math.floor(r)) : 0);
    let used = counts.reduce((a, b) => a + b, 0);
    // Hand out what is left by largest remainder, then trim the biggest part if minimums overshot.
    const order = raw.map((r, i) => [r - Math.floor(r), i]).filter(([frac]) => frac > 0).sort((a, b) => b[0] - a[0]);
    for (const [, i] of order) { if (used >= cells) break; counts[i] += 1; used += 1; }
    while (used > cells) { const i = counts.indexOf(Math.max(...counts)); counts[i] -= 1; used -= 1; }
    const out = [];
    parts.forEach((p, i) => { for (let n = 0; n < counts[i]; n += 1) out.push(p.key); });
    while (out.length < cells) out.push('free');
    return out;
  }

  function ContextWindowCard({shape, model, history, compact = false, title = 'Context window'}) {
    const [hover, setHover] = useState(null);
    if (!shape || !shape.context_window) {
      return <section className={'av-card av-ctx' + (compact ? ' is-compact' : '')}>
        <header className="av-ctx-head"><h3>{title}</h3></header>
        <p className="av-empty">Vellum records the context after the next reply in this chat.</p>
      </section>;
    }
    const window = Number(shape.context_window);
    const used = Number(shape.input_used || 0);
    const segments = contextSegments(shape);
    const free = Math.max(0, window - used - Number(shape.output_reserved || 0) - Number(shape.safety_margin || 0));
    const cells = allocateCells(segments, window, COLS * ROWS);
    const tintOrder = segments.filter(s => s.value > 0).map(s => s.key);
    const fill = used / window;
    const tone = fill >= 0.85 ? 'hot' : fill >= 0.65 ? 'warm' : 'calm';
    const focus = hover && hover !== 'free' ? segments.find(s => s.key === hover) : null;
    const left = Math.max(0, Number(shape.input_limit || 0) - used);
    const rows = [...segments.filter(s => s.value > 0 || !s.reserved), {key: 'free', label: 'Free space', hint: 'Unused room in the window', value: free, color: 'transparent', free: true}];
    return <section className={'av-card av-ctx' + (compact ? ' is-compact' : '')}>
      <header className="av-ctx-head">
        <h3>{title}</h3>
        {model && <span className="av-chip" title={model}>{modelName(model)}</span>}
      </header>
      <div className="av-ctx-headline">
        <strong><CountUp value={focus ? focus.value : hover === 'free' ? free : used} format={fmtTokens} delay={150}/></strong>
        <span>{focus ? focus.label : hover === 'free' ? 'Free space' : `of ${fmtTokens(window)} tokens`}</span>
        <em className={'av-pill ' + tone}><CountUp value={focus ? focus.value / window : hover === 'free' ? free / window : fill} format={n => fmtPct(n)} delay={150}/></em>
      </div>
      <div className="av-cells" style={{gridTemplateColumns: `repeat(${COLS}, 1fr)`}} role="img"
        aria-label={`${fmtTokens(used)} of ${fmtTokens(window)} tokens used`} onMouseLeave={() => setHover(null)}>
        {cells.map((key, i) => {
          const seg = segments.find(s => s.key === key);
          // #231: every cell pops in gray in order, then each category tints in turn.
          const motion = {'--d': (i * 0.0035).toFixed(4) + 's', '--c': (Math.max(0, tintOrder.indexOf(key)) * 0.22).toFixed(2) + 's'};
          return <i key={i} className={'av-cell' + (key === 'free' ? ' free' : '') + (seg && seg.reserved ? ' reserved' : '') + (hover && hover !== key ? ' dim' : '') + (hover === key ? ' lit' : '')}
            style={seg ? {...motion, '--cell': seg.color} : motion} onMouseEnter={() => setHover(key)}/>;
        })}
      </div>
      <ul className="av-ctx-rows" onMouseLeave={() => setHover(null)}>
        {rows.map((row, i) => <li key={row.key} className={'av-enter ' + (hover === row.key ? 'on ' : '') + (row.reserved || row.free ? 'quiet' : '')} style={{'--slot': i}} onMouseEnter={() => setHover(row.key)} title={row.hint}>
          <span className={'av-sq' + (row.free ? ' free' : '') + (row.reserved ? ' reserved' : '')} style={{'--cell': row.color}}/>
          <span className="av-ctx-name">{row.label}</span>
          <span className="av-ctx-val">{fmtTokens(row.value)}</span>
          <span className="av-ctx-pct">{fmtPct(row.value / window, 1)}</span>
        </li>)}
      </ul>
      {history && history.length > 1 && <ContextHistory history={history} window={window}/>}
      <footer className="av-ctx-foot">
        <span className={left < window * 0.1 ? 'warn' : ''}>{fmtTokens(left)} left before compaction</span>
        {shape.compacted ? <span>Compacted · {shape.removed_messages} earlier {shape.removed_messages === 1 ? 'message' : 'messages'} summarised</span>
          : <span>{relTime(shape.ts)}</span>}
      </footer>
    </section>;
  }

  // Fill per turn in this chat; a notch marks turns where Vellum compacted.
  function ContextHistory({history, window}) {
    const max = Math.max(window, ...history.map(p => p.input_limit || 0));
    return <div className="av-ctx-hist" aria-label="Context fill per turn">
      <div className="av-ctx-hist-bars">{history.map((point, i) => <i key={point.response_id} className={'av-grow-y' + (point.compacted ? ' compacted' : '')}
        style={{height: Math.max(6, point.input_used / max * 100) + '%', '--slot': i, '--step': '.03s'}} title={`${fmtTokens(point.input_used)} · ${relTime(point.ts)}${point.compacted ? ' · compacted' : ''}`}/>)}</div>
      <div className="av-ctx-hist-k"><span>Last {history.length} turns</span><span>{history.some(p => p.compacted) ? 'notch = compacted' : ''}</span></div>
    </div>;
  }

  // Composer pill: a ring with this chat's fill, opening the Context Window card.
  // placement 'below' sits in the chat's top-right and opens downward; hideButton
  // shows only the card (used by /context before a chat exists).
  function ContextMeter({threadId, refreshKey, openSignal, model, placement = 'above', hideButton = false}) {
    const [data, setData] = useState(null);
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    const api = window.VellumApi && window.VellumApi.observability;
    const load = useCallback(() => {
      if (!threadId || !api) { setData(null); return; }
      api.threadContext(threadId).then(setData).catch(() => setData(null));
    }, [threadId]);
    useEffect(() => { load(); }, [load, refreshKey]);
    useEffect(() => { if (openSignal) { setOpen(true); load(); } }, [openSignal]);
    useEffect(() => {
      if (!open) return;
      const down = event => { if (ref.current && !ref.current.contains(event.target)) setOpen(false); };
      const key = event => { if (event.key === 'Escape') setOpen(false); };
      document.addEventListener('mousedown', down); document.addEventListener('keydown', key);
      return () => { document.removeEventListener('mousedown', down); document.removeEventListener('keydown', key); };
    }, [open]);
    const latest = data && data.latest;
    const fill = latest ? Math.min(1, latest.input_used / latest.context_window) : 0;
    const tone = fill >= 0.85 ? 'hot' : fill >= 0.65 ? 'warm' : 'calm';
    const r = 6.5, c = 2 * Math.PI * r;
    return <div className={'av-meter is-' + placement} ref={ref}>
      {!hideButton && <button type="button" className={'av-meter-btn ' + tone + (latest ? '' : ' idle')} aria-haspopup="dialog" aria-expanded={open}
        title={latest ? `Context: ${fmtTokens(latest.input_used)} of ${fmtTokens(latest.context_window)} tokens (/context)` : 'Context window (/context)'}
        onClick={() => { setOpen(!open); if (!open) load(); }}>
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r={r} className="track"/>
          <circle cx="8" cy="8" r={r} className="arc" strokeDasharray={`${fill * c} ${c}`} transform="rotate(-90 8 8)"/></svg>
        {placement === 'below' && <span className="av-meter-k">Context</span>}
        <span className="av-meter-v">{latest ? fmtPct(fill) : '—'}</span>
      </button>}
      {open && <div className="av-meter-pop" role="dialog" aria-label="Context window for this chat">
        <ContextWindowCard shape={latest} model={model} history={data && data.history} compact title="Context window"/>
        {data && data.compactions > 0 && <p className="av-meter-note">Compacted {data.compactions} {data.compactions === 1 ? 'time' : 'times'} in the last {data.history.length} turns. Type /compact to do it now.</p>}
      </div>}
    </div>;
  }

  // ---------------------------------------------------------------- trace waterfall
  const KIND = {
    context: {label: 'Context', color: 'var(--av-k-context)'},
    runtime: {label: 'Runtime', color: 'var(--av-k-context)'},
    thinking: {label: 'Planning', color: 'var(--av-k-thinking)'},
    agent: {label: 'Sub-agent', color: 'var(--av-k-agent)'},
    tool: {label: 'Tool call', color: 'var(--av-k-tool)'},
    source: {label: 'Sources', color: 'var(--av-k-source)'},
    memory: {label: 'Memory', color: 'var(--av-k-memory)'},
    answer: {label: 'Answer', color: 'var(--av-k-answer)'},
    compaction: {label: 'Compaction', color: 'var(--av-k-summary)'},
    error: {label: 'Error', color: 'var(--av-k-error)'},
  };
  const spanName = span => span.kind === 'tool' || span.kind === 'agent' ? humanize(span.name)
    : span.kind === 'source' || span.kind === 'error' || span.kind === 'memory' ? (span.label || KIND[span.kind].label)
    : KIND[span.kind] ? KIND[span.kind].label : humanize(span.kind);

  function niceTicks(total) {
    const steps = [50, 100, 250, 500, 1000, 2000, 5000, 10000, 15000, 30000, 60000, 120000, 300000];
    const step = steps.find(s => total / s <= 5) || Math.ceil(total / 5);
    const ticks = [];
    for (let t = 0; t <= total + 1; t += step) ticks.push(t);
    return ticks;
  }

  // Motion, ported from the Motion Prompt library (MIT, (c) 2026 Shohei Ohtaki):
  //   #002 Stagger https://showheyohtaki.github.io/motion-prompt/#002 - rows enter 0.15 s + 0.12 s apart, 0.5 s backOut(2.6);
  //     here they drop down into place instead of rising, and the stagger index is capped so long runs don't wait.
  //   #233 Gantt chart https://showheyohtaki.github.io/motion-prompt/#233 - each bar grows from its left end over 0.5 s ease-out,
  //     starting 0.25 s after its row (0.4 s for the first row, as in the element); bars share the row's 0.12 s spacing.
  //   #069 Skeleton screen https://showheyohtaki.github.io/motion-prompt/#069 - while a trace loads: placeholder blocks with a
  //     160 px shine sweeping every 0.9 s (linear); content returns over 0.3 s.
  // Timings live in analytics.css (.av-trace-row, .av-bar, .av-skel). prefers-reduced-motion turns them off.
  const STAGGER_CAP = 14;

  function TraceSkeleton() {
    return <section className="av-card av-trace is-loading" aria-busy="true" aria-label="Loading trace">
      <header className="av-trace-head"><span className="av-skel" style={{width: 52, height: 12}}/><span className="av-skel" style={{width: 140, height: 10}}/></header>
      <div className="av-trace-stats">{[0, 1, 2, 3, 4, 5].map(i => <div key={i}><span className="av-skel" style={{width: 46, height: 8}}/><span className="av-skel" style={{width: 30, height: 14, marginTop: 6}}/></div>)}</div>
      <div className="av-trace-body">{[0, 1, 2, 3, 4, 5].map(i => <div className="av-trace-row" key={i}>
        <div className="av-trace-name" style={{paddingLeft: 8 + (i % 3 === 2 ? 16 : 0)}}><span className="av-skel" style={{width: 90 + (i * 23) % 50, height: 10}}/></div>
        <div className="av-trace-lane"><span className="av-skel av-skel-bar" style={{left: (i * 13) % 60 + '%', width: 12 + (i * 17) % 28 + '%'}}/></div>
      </div>)}</div>
    </section>;
  }

  function TraceWaterfall({trace, loading}) {
    const [collapsed, setCollapsed] = useState({});
    const [selected, setSelected] = useState(null);
    const [now, setNow] = useState(() => Date.now());
    const bodyRef = useRef(null);
    const seen = useRef({run: null, ids: new Set()});
    const runId = trace && trace.run && trace.run.response_id;
    const live = !!(trace && trace.run && trace.run.status === 'in_progress');
    useEffect(() => { setSelected(null); setCollapsed({}); }, [runId]);
    // While a run is live, re-render on a short clock so open spans keep growing.
    useEffect(() => {
      if (!live) return undefined;
      const timer = setInterval(() => setNow(Date.now()), 200);
      return () => clearInterval(timer);
    }, [live, runId]);
    // Each row keeps the stagger slot it got when it first appeared, so re-renders never
    // shift a running animation; steps that stream in later get slots from 0 in their own batch.
    if (seen.current.run !== runId) seen.current = {run: runId, slots: new Map()};
    let freshCount = 0;
    const slotFor = id => {
      if (!seen.current.slots.has(id)) seen.current.slots.set(id, Math.min(freshCount++, STAGGER_CAP));
      return seen.current.slots.get(id);
    };
    if (loading) return <TraceSkeleton/>;
    if (!trace) return <section className="av-card av-trace"><p className="av-empty">Pick a run to see its trace.</p></section>;
    const liveEnd = live && trace.origin_at_ms ? Math.max(0, now - trace.origin_at_ms) : 0;
    const spans = (trace.spans || []).map(span => live && span.status === 'in_progress' ? {...span, end_ms: Math.max(span.end_ms, liveEnd)} : span);
    const total = Math.max(1, trace.duration_ms || 0, liveEnd, ...spans.map(s => s.end_ms || 0));
    const children = {};
    spans.forEach(s => { (children[s.parent || 'root'] = children[s.parent || 'root'] || []).push(s); });
    const rows = [];
    const walk = (parent, depth) => (children[parent] || []).forEach(span => {
      rows.push({span, depth, hasKids: !!children[span.id]});
      if (!collapsed[span.id]) walk(span.id, depth + 1);
    });
    walk('root', 0);
    const ticks = niceTicks(total);
    const run = trace.run || {};
    const status = run.status === 'in_progress' ? 'live' : run.status === 'failed' ? 'failed' : 'done';
    const sel = selected && spans.find(s => s.id === selected);
    const selIndex = sel ? rows.findIndex(r => r.span.id === sel.id) : -1;
    return <section className="av-card av-trace">
      <header className="av-trace-head">
        <span className="av-trace-mark"><Glyph d={G.spark} size={13}/></span>
        <strong>Trace</strong><span className="av-muted">Run {shortId(run.response_id)} · {relTime(run.started_at)}</span>
        <span className={'av-status ' + status}>{status === 'live' ? 'Live' : status === 'failed' ? 'Failed' : 'Done'}</span>
      </header>
      <dl className="av-trace-stats">
        <div><dt>Duration</dt><dd>{fmtMs(live ? total : trace.duration_ms)}</dd></div>
        <div><dt>Events</dt><dd>{(trace.stats.events || 0).toLocaleString()}</dd></div>
        <div><dt>Sub-agents</dt><dd>{trace.stats.agents}</dd></div>
        <div><dt>Tool calls</dt><dd>{trace.stats.tool_calls}</dd></div>
        <div><dt>Sources</dt><dd>{trace.stats.sources}</dd></div>
        <div><dt>Errors</dt><dd className={trace.stats.errors ? 'bad' : ''}>{trace.stats.errors}</dd></div>
      </dl>
      <div className="av-trace-grid">
        <div className="av-trace-axis-l">Span</div>
        <div className="av-trace-axis">{ticks.map(t => <span key={t} style={{left: (t / total * 100) + '%'}}>{fmtMs(t)}</span>)}
          {live && <b className="av-now-tag" style={{left: (liveEnd / total * 100) + '%'}}>now</b>}</div>
      </div>
      <div className="av-trace-body" ref={bodyRef}>
        {rows.length ? rows.map(({span, depth, hasKids}) => {
          const start = span.start_ms / total * 100;
          const width = Math.max(0, (span.end_ms - span.start_ms) / total * 100);
          const point = span.end_ms - span.start_ms < 1 && ['source', 'memory', 'error'].includes(span.kind);
          const meta = span.kind === 'tool' ? 'Tool' : span.kind === 'agent' ? 'Agent' : '';
          const slot = slotFor(span.id);
          return <div key={span.id} className={'av-trace-row' + (selected === span.id ? ' on' : '') + (span.status === 'failed' ? ' failed' : '')}
            style={{'--slot': slot}} onClick={() => setSelected(selected === span.id ? null : span.id)}>
            <div className="av-trace-name" style={{paddingLeft: 8 + depth * 16}}>
              {hasKids ? <button type="button" className={'av-twist' + (collapsed[span.id] ? '' : ' open')} aria-label={collapsed[span.id] ? 'Expand' : 'Collapse'}
                onClick={event => { event.stopPropagation(); setCollapsed(c => ({...c, [span.id]: !c[span.id]})); }}><Glyph d={G.chevron} size={11}/></button> : <span className="av-twist-pad"/>}
              <span className="av-kind" style={{background: (KIND[span.kind] || KIND.context).color}}/>
              <span className="av-trace-label">{spanName(span)}</span>
              {meta && <span className="av-muted">{meta}</span>}
              {span.count > 1 && span.kind !== 'source' && <span className="av-count">×{span.count}</span>}
              {span.status === 'failed' && <span className="av-flag">failed</span>}
            </div>
            <div className="av-trace-lane">
              {ticks.map(t => <i key={t} className="av-gridline" style={{left: (t / total * 100) + '%'}}/>)}
              {live && <i className="av-now" style={{left: (liveEnd / total * 100) + '%'}} aria-hidden="true"/>}
              {point ? <span className="av-point" style={{left: start + '%', background: (KIND[span.kind] || KIND.context).color}}/>
                : <span className={'av-bar ' + span.status} style={{left: start + '%', width: `max(3px, ${width}%)`, '--bar': (KIND[span.kind] || KIND.context).color}}/>}
              {!point && <span className="av-bar-t" style={{left: `calc(${Math.min(start + width, 88)}% + 6px)`}}>{fmtMs(span.end_ms - span.start_ms)}</span>}
            </div>
          </div>;
        }) : <p className="av-empty">This run recorded no steps.</p>}
        {sel && <div className="av-trace-pop" style={{top: 8 + (selIndex + 1) * 32}}>
          <div className="av-trace-pop-h"><span className="av-kind" style={{background: (KIND[sel.kind] || KIND.context).color}}/><strong>{spanName(sel)}</strong>
            <span className={'av-status ' + (sel.status === 'failed' ? 'failed' : sel.status === 'in_progress' ? 'live' : 'done')}>{sel.status.replace('_', ' ')}</span>
            <button type="button" className="av-x" aria-label="Close" onClick={() => setSelected(null)}><Glyph d={G.close} size={12}/></button></div>
          <div className="av-trace-pop-k"><div><dt>Duration</dt><dd>{fmtMs(sel.end_ms - sel.start_ms)}</dd></div><div><dt>Started</dt><dd>+{fmtMs(sel.start_ms)}</dd></div><div><dt>Kind</dt><dd>{(KIND[sel.kind] || {}).label}</dd></div></div>
          {sel.label && sel.label !== spanName(sel) && <p className="av-muted">{sel.label}</p>}
        </div>}
      </div>
      {trace.context && <div className="av-trace-ctx">
        <span>Context this turn</span>
        <div className="av-mini-ctx">{contextSegments(trace.context).filter(s => s.value > 0).map(s => <i key={s.key} title={`${s.label} ${fmtTokens(s.value)}`} style={{width: (s.value / trace.context.context_window * 100) + '%', background: s.color}}/>)}</div>
        <span>{fmtTokens(trace.context.input_used)} / {fmtTokens(trace.context.context_window)}</span>
      </div>}
      {!trace.precise && <p className="av-foot-note">This run was recorded before millisecond timing; steps inside the same second line up together.</p>}
    </section>;
  }

  // ---------------------------------------------------------------- model usage
  const MODEL_TONES = ['var(--av-m1)', 'var(--av-m2)', 'var(--av-m3)', 'var(--av-m4)', 'var(--av-m5)'];

  function ModelUsage({turns, periodLabel = 'This period'}) {
    const [metric, setMetric] = useState('tokens');
    const models = (turns && turns.models) || [];
    const top = models.slice(0, 4);
    const rest = models.slice(4);
    const bars = rest.length ? [...top, rest.reduce((acc, m) => ({...acc, turns: acc.turns + m.turns, input: acc.input + m.input, output: acc.output + m.output, cost_usd: acc.cost_usd + m.cost_usd}),
      {model: 'Other models', provider: '', turns: 0, input: 0, output: 0, cost_usd: 0, other: rest.length})] : top;
    const valueOf = m => metric === 'tokens' ? m.input + m.output : metric === 'cost' ? m.cost_usd : m.turns;
    const fmt = metric === 'tokens' ? fmtTokens : metric === 'cost' ? fmtMoney : n => Number(n).toLocaleString();
    const total = metric === 'tokens' ? turns && turns.tokens : metric === 'cost' ? turns && turns.cost_usd : turns && turns.turns;
    const before = metric === 'tokens' ? turns && turns.previous_tokens : metric === 'cost' ? turns && turns.previous_cost_usd : turns && turns.previous_turns;
    // Headroom above the tallest bar keeps its value label clear of the top line.
    const max = (Math.max(...bars.map(valueOf), 0) || 1) * 1.15;
    const scale = [max, max / 2, 0];
    const tools = (turns && turns.tools) || [];
    const withTools = Math.max(1, (turns && turns.turns_with_tools) || 0);
    return <section className="av-card av-usage">
      <header className="av-usage-head">
        <span className="av-muted">{periodLabel}</span><strong><CountUp value={total || 0} format={fmt}/></strong>
        <Delta now={total} before={before} suffix="vs previous" tone={metric === 'cost' ? 'down' : 'neutral'}/>
        <Segmented label="Usage metric" value={metric} onChange={setMetric} options={[['tokens', 'Tokens'], ['cost', 'Cost'], ['turns', 'Turns']]}/>
      </header>
      {bars.length ? <div className="av-usage-chart">
        <div className="av-usage-y">{scale.map((v, i) => <span key={i}>{fmt(v)}</span>)}</div>
        <div className="av-usage-plot">
          {scale.map((_, i) => <i key={i} className="av-hline" style={{top: (i / 2 * 100) + '%'}}/>)}
          {bars.map((m, i) => {
            const v = valueOf(m);
            const h = v / max * 100;
            const inShare = metric === 'tokens' && v ? m.input / v : 1;
            return <div className="av-usage-col" key={m.model} title={`${m.model}: ${fmt(v)}${metric === 'tokens' ? ` (${fmtTokens(m.input)} in · ${fmtTokens(m.output)} out)` : ''}`}>
              <span className="av-usage-v av-late" style={{bottom: `calc(${h}% + 4px)`, '--slot': i}}>{fmt(v)}</span>
              <div className="av-usage-stack av-grow-y" style={{height: h + '%', '--tone': MODEL_TONES[i % MODEL_TONES.length], '--slot': i}}>
                {metric === 'tokens' && <i className="out" style={{height: ((1 - inShare) * 100) + '%'}}/>}
                <i className="in" style={{height: (inShare * 100) + '%'}}/>
              </div>
            </div>;
          })}
        </div>
        <div/>
        <div className="av-usage-x">{bars.map(m => <span key={m.model}><b>{m.other ? `Other (${m.other})` : modelName(m.model)}</b><small>{providerLabel(m.model, m.provider)}</small></span>)}</div>
      </div> : <p className="av-empty">No model calls in this period.</p>}
      {metric === 'tokens' && bars.length > 0 && <p className="av-usage-key"><span className="av-sq solid"/>Input <span className="av-sq light"/>Output</p>}
      {tools.length > 0 && <div className="av-usage-tasks">
        <div className="av-usage-tasks-h">What turns reached for <small>share of the {withTools.toLocaleString()} turns that used a tool</small></div>
        <ul>{tools.slice(0, 8).map((tool, i) => <li key={tool.name}><span className="av-task-name">{humanize(tool.name)}</span>
          <span className="av-task-bar"><i className="av-fill" style={{width: Math.min(100, tool.turns / withTools * 100) + '%', background: MODEL_TONES[i % MODEL_TONES.length], '--slot': i}}/></span>
          <span className="av-task-pct av-late" style={{'--slot': i}}>{fmtPct(tool.turns / withTools)}</span></li>)}</ul>
      </div>}
    </section>;
  }

  // ---------------------------------------------------------------- ledger
  // All changes in one scrolling list; the verb carries the meaning, so rows have no icons.
  function ChangeLedger({rows, title = 'Ledger', subtitle}) {
    const list = rows || [];
    return <section className="av-ledger">
      <header className="av-ledger-head"><Glyph d={G.ledger} size={14}/><strong>{title}</strong>{subtitle && <span className="av-muted">{subtitle}</span>}
        <span className="av-ledger-n"><b>{list.length}</b> {list.length === 1 ? 'change' : 'changes'}</span></header>
      {list.length ? <ol className="av-card av-ledger-list" tabIndex={0} aria-label={title}>{list.map((row, i) => <li key={row.id} className={'av-enter is-' + row.event} style={{'--slot': Math.min(i, 14)}}>
        <div className="av-ledger-main">
          <div className="av-ledger-line"><b>{row.verb}{row.count > 1 ? ` ${row.count}` : ''}</b>
            <span>{row.event === 'filtered' ? (row.count > 1 ? 'non-memories' : 'a non-memory') : row.title || (row.event.includes('deleted') ? 'a memory' : '')}</span></div>
          {(row.before || row.reason || row.origin) && <div className="av-ledger-change">
            {row.before && <React.Fragment><s>{row.before}</s><span aria-hidden="true">→</span><span>{row.after || 'Removed'}</span></React.Fragment>}
            {!row.before && !row.reason && row.origin && <span className="av-muted">{ORIGIN_LABEL[row.origin] || humanize(row.origin)}</span>}
            {row.reason && <span className="av-muted">{row.reason}</span>}
          </div>}
        </div>
        <span className="av-ledger-when">{relTime(row.at)}{row.topic ? ` · ${row.topic}` : row.origin ? ` · ${humanize(row.origin)}` : ''}</span>
      </li>)}</ol> : <p className="av-empty">No changes yet.</p>}
    </section>;
  }

  // ---------------------------------------------------------------- growth chart
  const ORIGIN_TONE = {stated: 'var(--av-o-stated)', inferred: 'var(--av-o-inferred)', imported: 'var(--av-o-imported)', digest: 'var(--av-o-digest)'};
  const ORIGIN_LABEL = {stated: 'You told it', inferred: 'Picked up', imported: 'Imported', digest: 'Digest'};

  function GrowthChart({series}) {
    const [hover, setHover] = useState(null);
    const points = series || [];
    if (points.length < 2) return <p className="av-empty">The chart fills in after a second day of memories.</p>;
    const W = 640, H = 180, top = 12, base = 132, barH = 34;
    const maxKnown = Math.max(1, ...points.map(p => p.known));
    const maxAdded = Math.max(1, ...points.map(p => p.added));
    const step = W / points.length;
    const x = i => i * step + step / 2;
    const y = v => base - v / maxKnown * (base - top);
    const line = points.map((p, i) => `${x(i).toFixed(1)},${y(p.known).toFixed(1)}`).join(' ');
    const origins = ['stated', 'inferred', 'imported', 'digest'];
    const h = hover !== null ? points[hover] : null;
    return <div className="av-growth" onMouseLeave={() => setHover(null)}>
      <svg className="av-draw" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`Known memories went from ${points[0].known} to ${points[points.length - 1].known}`}>
        {[0, .5, 1].map(f => <line key={f} x1="0" x2={W} y1={y(maxKnown * f)} y2={y(maxKnown * f)} className="av-g-grid"/>)}
        <polygon points={`${x(0)},${base} ${line} ${x(points.length - 1)},${base}`} className="av-g-area"/>
        <polyline points={line} className="av-g-line" vectorEffect="non-scaling-stroke"/>
        {points.map((p, i) => {
          let acc = 0;
          return <g key={p.day}>
            {origins.map(origin => {
              const n = (p.by_origin || {})[origin] || 0;
              if (!n) return null;
              const hh = Math.max(2, n / maxAdded * barH);
              const rect = <rect key={origin} x={x(i) - step * .3} width={step * .6} y={H - 4 - acc - hh} height={hh} rx="1.5" style={{fill: ORIGIN_TONE[origin]}}/>;
              acc += hh;
              return rect;
            })}
            <rect x={i * step} width={step} y="0" height={H} fill="transparent" onMouseEnter={() => setHover(i)}/>
          </g>;
        })}
        {h && <g pointerEvents="none"><line x1={x(hover)} x2={x(hover)} y1={top} y2={H - 4} className="av-g-cursor"/><circle cx={x(hover)} cy={y(h.known)} r="3.5" className="av-g-dot"/></g>}
      </svg>
      <div className="av-growth-x"><span>{shortDay(points[0].day)}</span><span>{shortDay(points[points.length - 1].day)}</span></div>
      {h && <div className="av-growth-tip" style={{left: `clamp(0px, calc(${(hover + .5) / points.length * 100}% - 90px), calc(100% - 180px))`}}>
        <b>{shortDay(h.day)}</b><span>{h.known} known</span>
        {h.added ? origins.filter(o => (h.by_origin || {})[o]).map(o => <span key={o}><i style={{background: ORIGIN_TONE[o]}}/>+{h.by_origin[o]} {ORIGIN_LABEL[o].toLowerCase()}</span>) : <span className="av-muted">nothing new</span>}
        {h.archived > 0 && <span className="av-muted">{h.archived} archived</span>}
      </div>}
      <div className="av-growth-key">{origins.filter(o => points.some(p => (p.by_origin || {})[o])).map(o => <span key={o}><i style={{background: ORIGIN_TONE[o]}}/>{ORIGIN_LABEL[o]}</span>)}<span><i className="line"/>Known</span></div>
    </div>;
  }

  window.VellumUI = window.VellumUI || {};
  window.VellumUI.Analytics = {
    fmtTokens, fmtMs, fmtMoney, fmtPct, relTime, shortDay, shortId, humanize, modelName, providerLabel, parseTime,
    Glyph, G, Segmented, Delta, Sparkline, StatTile, Breakdown, CountUp, useCountUp,
    ContextWindowCard, ContextMeter, contextSegments, allocateCells, CONTEXT_PARTS,
    TraceWaterfall, ModelUsage, ChangeLedger, GrowthChart, ORIGIN_TONE, ORIGIN_LABEL,
  };
  window.VellumUI.ContextMeter = ContextMeter;
})();
