(function () {
  const {useEffect, useState} = React;

  const STEPS = [
    {id: 'computer', label: 'This computer'},
    {id: 'model', label: 'Model'},
    {id: 'connectors', label: 'Connectors'},
    {id: 'privacy', label: 'Privacy'},
    {id: 'memory', label: 'Memory'},
  ];
  // Logo files with no colors of their own draw in black; show them in the text
  // color instead (img.mono in onboarding.css).
  const MONO = /\/(alibaba-color|claude|copilot(-color)?|deepseek-color|github-copilot-color|grok(-color)?|groq-color|huggingface-color|kimi-color|mistral-color|moonshot-color|nvidia-color|ollama(-color)?|openai|opencode|openrouter-color|qwen-portal-color|vllm-color|zai)\.svg$/;
  const Logo = ({src, alt = ''}) => <img src={src} alt={alt} className={MONO.test(src) ? 'mono' : undefined} loading="lazy"/>;

  // Who made a Hugging Face model, from its repo name.
  const MAKERS = [
    [/qwen/i, 'Alibaba Qwen', 'provider-icons/qwen-portal-color.svg'],
    [/gemma/i, 'Google', 'provider-icons/google-deepmind.svg'],
    [/llama/i, 'Meta', 'provider-icons/meta-color.svg'],
    [/mistral|ministral|devstral/i, 'Mistral', 'provider-icons/mistral-color.svg'],
    [/deepseek/i, 'DeepSeek', 'provider-icons/deepseek-color.svg'],
    [/phi-?\d/i, 'Microsoft', 'provider-icons/copilot-color.svg'],
    [/granite/i, 'IBM', 'provider-icons/huggingface-color.svg'],
    [/kimi|moonshot/i, 'Moonshot', 'provider-icons/kimi-color.svg'],
    [/minimax/i, 'MiniMax', 'provider-icons/minimax-color.svg'],
  ];
  function maker(repo) {
    const name = repo.split('/').pop();
    const hit = MAKERS.find(([re]) => re.test(name));
    return hit ? {name: hit[1], logo: hit[2]} : {name: repo.split('/')[0], logo: 'provider-icons/huggingface-color.svg'};
  }
  function modelName(repo) {
    const words = repo.split('/').pop().replace(/[-_]?GGUF$/i, '').split(/[-_\s]+/).filter(w => !/^it$/i.test(w));
    return words.map(w => /^\d+(\.\d+)?[bm]$/i.test(w) ? w.toUpperCase()
      : /^[a-z]/.test(w) ? w[0].toUpperCase() + w.slice(1) : w).join(' ');
  }
  const FIT = {gpu: 'Runs on your graphics card', cpu: 'Runs on your processor, slower', too_big: 'Too large for this computer'};

  function ProviderMark({provider}) {
    if (provider === 'google') return <svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M21.6 12.23c0-.71-.06-1.39-.18-2.05H12v3.88h5.38a4.6 4.6 0 0 1-2 3.02v2.51h3.24c1.9-1.75 2.98-4.33 2.98-7.36Z"/><path fill="#34A853" d="M12 22c2.7 0 4.96-.9 6.61-2.41l-3.24-2.51c-.9.6-2.04.96-3.37.96-2.6 0-4.8-1.76-5.59-4.12H3.07v2.59A10 10 0 0 0 12 22Z"/><path fill="#FBBC05" d="M6.41 13.92A6 6 0 0 1 6.1 12c0-.67.11-1.31.31-1.92V7.49H3.07A10 10 0 0 0 2 12c0 1.61.39 3.14 1.07 4.51l3.34-2.59Z"/><path fill="#EA4335" d="M12 5.96c1.47 0 2.79.51 3.82 1.51l2.87-2.87A9.6 9.6 0 0 0 12 2a10 10 0 0 0-8.93 5.49l3.34 2.59C7.2 7.72 9.4 5.96 12 5.96Z"/></svg>;
    if (provider === 'github') return <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .8a11.2 11.2 0 0 0-3.54 21.83c.56.1.77-.24.77-.54v-2.08c-3.13.68-3.79-1.33-3.79-1.33-.51-1.3-1.25-1.65-1.25-1.65-1.02-.7.08-.69.08-.69 1.13.08 1.72 1.16 1.72 1.16 1 1.72 2.62 1.22 3.26.93.1-.72.39-1.22.71-1.5-2.5-.28-5.12-1.25-5.12-5.57 0-1.23.44-2.23 1.16-3.02-.12-.28-.5-1.43.11-2.98 0 0 .95-.3 3.08 1.15a10.7 10.7 0 0 1 5.61 0c2.14-1.45 3.08-1.15 3.08-1.15.61 1.55.23 2.7.11 2.98a4.34 4.34 0 0 1 1.16 3.02c0 4.33-2.63 5.28-5.14 5.56.4.35.76 1.03.76 2.08v3.09c0 .3.2.65.77.54A11.2 11.2 0 0 0 12 .8Z"/></svg>;
    return null;
  }

  function Who({account}) {
    if (!account) return <div className="ob-who"><div className="ob-who-mark">V</div><div className="ob-who-text"><strong>On this device</strong><small>No account</small></div></div>;
    const initial = (account.display_name || account.email || '?').trim()[0].toUpperCase();
    const via = {google: 'Google', github: 'GitHub', email: 'Email'}[account.provider] || '';
    return <div className="ob-who">
      <div className="ob-who-mark">
        {account.photo ? <img className="ob-photo" src={account.photo} alt=""/> : initial}
        {account.provider !== 'email' && <span className="ob-who-badge"><ProviderMark provider={account.provider}/></span>}
      </div>
      <div className="ob-who-text"><strong>{account.display_name || account.username}</strong><small>{via} · {account.email || '@' + account.username}</small></div>
    </div>;
  }

  function Computer({api, scan, setScan}) {
    useEffect(() => {
      if (scan) return;
      let live = true;
      api.hardware().then(result => live && setScan(result)).catch(() => live && setScan({error: true}));
      return () => {live = false;};
    }, []);
    if (!scan) return <div className="ob-scanning" role="status"><i/>Looking at this computer…</div>;
    if (scan.error) return <p className="ob-hint">Couldn't read this computer's hardware. You can still choose any model on the next step.</p>;
    const hw = scan.hardware, rec = scan.recommendation;
    return <>
      <div className="ob-specs">
        <div className="ob-spec"><small>Memory</small><strong>{Math.round(hw.ram_gb)} GB</strong><span>RAM</span></div>
        <div className="ob-spec"><small>Graphics</small><strong>{hw.vram_gb ? `${Math.round(hw.vram_gb)} GB` : 'None usable'}</strong><span title={hw.gpu_name}>{hw.gpu_name || 'Integrated graphics'}</span></div>
        <div className="ob-spec"><small>Free space</small><strong>{Math.round(hw.free_disk_gb)} GB</strong><span>on this drive</span></div>
        <div className="ob-spec"><small>Processor</small><strong>{hw.cpu_cores} threads</strong><span title={hw.cpu_name}>{hw.cpu_name || 'CPU'}</span></div>
      </div>
      <div className="ob-verdict">
        <Logo src={rec.mode === 'local' ? 'provider-icons/ollama-color.svg' : 'provider-icons/openrouter-color.svg'}/>
        <div>
          <h3>{rec.mode === 'local' ? `${rec.label} will run well here` : 'A cloud model will serve you better'}</h3>
          <ul>{rec.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
        </div>
      </div>
    </>;
  }

  // The model the hardware scan recommended, matched by name ("Gemma 4 12B" ~ "gemma-4-12b-it").
  const squash = text => String(text || '').toLowerCase().replace(/[^a-z0-9.]/g, '');
  function recommendedIndex(models, scan) {
    const label = squash(scan?.recommendation?.mode === 'local' ? scan.recommendation.label : '');
    const hit = label ? models.findIndex(m => m.fit !== 'too_big' && squash(modelName(m.repo)).includes(label)) : -1;
    return hit >= 0 ? hit : models.findIndex(m => m.fit !== 'too_big');
  }

  function LocalModels({api, choice, setChoice, scan}) {
    const [category, setCategory] = useState('general');
    const [query, setQuery] = useState('');
    const [uncensored, setUncensored] = useState(false);
    const [state, setState] = useState({loading: true, models: []});
    useEffect(() => {
      let live = true;
      setState(current => ({...current, loading: true}));
      const timer = setTimeout(() => {
        api.models({category, q: query, uncensored})
          .then(result => live && setState({loading: false, models: result.models}))
          .catch(error => live && setState({loading: false, models: [], error: error.message}));
      }, query ? 350 : 0);
      return () => {live = false; clearTimeout(timer);};
    }, [category, query, uncensored]);
    useEffect(() => {
      const first = state.models[recommendedIndex(state.models, query || category !== 'general' ? null : scan)];
      if (!state.loading && first && (choice?.kind !== 'local' || !state.models.some(m => m.ollama_model === choice.id))) {
        setChoice({kind: 'local', id: first.ollama_model, label: modelName(first.repo), size_gb: first.size_gb});
      }
    }, [state]);
    return <>
      <div className="ob-tools">
        {[['general', 'Everyday'], ['coding', 'Coding'], ['small', 'Small and fast']].map(([id, label]) =>
          <button key={id} className={'ob-chip' + (category === id && !query ? ' on' : '')} onClick={() => {setQuery(''); setCategory(id);}}>{label}</button>)}
        <input className="ob-search" type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search Hugging Face, e.g. qwen3 coder" aria-label="Search Hugging Face models"/>
        <label className="ob-check"><input type="checkbox" checked={uncensored} onChange={e => setUncensored(e.target.checked)}/>Include uncensored</label>
      </div>
      {state.loading && <div className="ob-scanning" role="status"><i/>Sizing models for this computer…</div>}
      {state.error && <p className="ob-hint">Couldn't reach Hugging Face. {state.error}</p>}
      <div className="ob-list" role="radiogroup" aria-label="Local models">
        {!state.loading && state.models.map((m, index) => {
          const who = maker(m.repo), on = choice?.id === m.ollama_model;
          return <button key={m.repo + m.quant} role="radio" aria-checked={on} disabled={m.fit === 'too_big'} className={'ob-opt' + (on ? ' on' : '')}
            onClick={() => setChoice({kind: 'local', id: m.ollama_model, label: modelName(m.repo), size_gb: m.size_gb})}>
            <span className="ob-logo"><Logo src={who.logo} alt={who.name}/></span>
            <span>
              <span className="ob-opt-title">{modelName(m.repo)}<code>{m.quant}</code>{m.fine_tuned && <span className="ob-tag warn">Fine-tune</span>}{m.uncensored && <span className="ob-tag warn">Uncensored</span>}</span>
              <span className="ob-opt-sub">{who.name} · {m.size_gb} GB download · {FIT[m.fit]}{m.context_estimate ? ` · ${contextLabel(m)}` : ''}{m.repo.split('/')[0] !== who.name ? ` · packaged by ${m.repo.split('/')[0]}` : ''}</span>
            </span>
            {index === recommendedIndex(state.models, scan) && !query && category === 'general' ? <span className="ob-tag rec">Recommended</span> : <span className="ob-tag">{m.fit === 'gpu' ? 'Fast' : m.fit === 'cpu' ? 'Fits' : 'Too large'}</span>}
          </button>;
        })}
        {!state.loading && !state.models.length && !state.error && <p className="ob-hint">No models matched. Try another name.</p>}
      </div>
      <p className="ob-more">Models run through Ollama, which is free. If it isn't on this computer yet, Vellum shows you where to get it.</p>
    </>;
  }

  // Subscription sign-in exists only where the provider allows other apps to
  // use a plan (p.plan, from api/setup.js): OpenAI's "Sign in with ChatGPT".
  // Anthropic's terms require API keys for apps like Vellum.
  const KEY_ONLY_NOTE = {anthropic: 'Claude Pro and Max plans can’t be used in other apps, so Vellum needs a Claude API key.'};

  function CloudModels({api, choice, setChoice, keys, setKeys, plans, setPlans}) {
    const [providers, setProviders] = useState(null);
    const [via, setVia] = useState({openai: 'plan'});
    const [signing, setSigning] = useState('');
    const [planError, setPlanError] = useState('');
    useEffect(() => {api.providers().then(list => setProviders(list.filter(p => p.requires_key))).catch(() => setProviders([]));}, []);
    if (!providers) return <div className="ob-scanning" role="status"><i/>Loading providers…</div>;
    const free = {groq: 'Free tier, no card needed'};
    const signIn = async id => {
      setSigning(id); setPlanError('');
      try {await api.planSignIn(id); setPlans({...plans, [id]: true});}
      catch (error) {setPlanError(error.message);}
      finally {setSigning('');}
    };
    const keyField = p => <>
      <span className="ob-key-row"><input type="password" autoComplete="off" spellCheck={false} placeholder={`Paste your ${p.name} API key`} aria-label={`${p.name} API key`}
        value={keys[p.id] || ''} onChange={e => setKeys({...keys, [p.id]: e.target.value})}/></span>
      <a href={p.key_url} target="_blank" rel="noreferrer">Get a {p.name} key</a>
    </>;
    return <div className="ob-list" role="radiogroup" aria-label="Cloud providers">
      {providers.map(p => {
        const on = choice?.kind === 'cloud' && choice.id === p.id;
        return <div key={p.id} role="radio" aria-checked={on} tabIndex={0} className={'ob-opt' + (on ? ' on' : '')}
          onClick={() => setChoice({kind: 'cloud', id: p.id, label: p.name, configured: p.configured})}
          onKeyDown={e => {if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {e.preventDefault(); setChoice({kind: 'cloud', id: p.id, label: p.name, configured: p.configured});}}}>
          <span className="ob-logo"><Logo src={p.icon} alt=""/></span>
          <span><span className="ob-opt-title">{p.name}</span><span className="ob-opt-sub">{p.description}{free[p.id] ? ` · ${free[p.id]}` : ''}</span></span>
          {p.configured || plans[p.id] ? <span className="ob-tag">{plans[p.id] ? 'Plan connected' : 'Key saved'}</span>
            : free[p.id] ? <span className="ob-tag rec">Free</span> : p.plan ? <span className="ob-tag">Plan or key</span> : <span/>}
          {on && !p.configured && !plans[p.id] && <span className="ob-key" onClick={e => e.stopPropagation()}>
            {p.plan && <span className="ob-tabs" role="tablist" style={{marginBottom: 2}}>
              <button role="tab" aria-selected={via[p.id] === 'plan'} className={'ob-tab' + (via[p.id] === 'plan' ? ' on' : '')} onClick={() => setVia({...via, [p.id]: 'plan'})}>Use my plan</button>
              <button role="tab" aria-selected={via[p.id] === 'key'} className={'ob-tab' + (via[p.id] === 'key' ? ' on' : '')} onClick={() => setVia({...via, [p.id]: 'key'})}>Use an API key</button>
            </span>}
            {p.plan && via[p.id] === 'plan' ? <>
              <button className="ob-import" style={{alignSelf: 'flex-start'}} disabled={signing === p.id} onClick={() => signIn(p.id)}><Logo src={p.icon}/>{signing === p.id ? 'Waiting for ChatGPT…' : p.plan.label}</button>
              <span className="ob-hint">{planError || (p.plan.available ? p.plan.note : p.plan.reason)}</span>
            </> : keyField(p)}
            {KEY_ONLY_NOTE[p.id] && <span className="ob-hint">{KEY_ONLY_NOTE[p.id]}</span>}
          </span>}
        </div>;
      })}
    </div>;
  }

  function Model(props) {
    const [tab, setTab] = useState(props.scan?.recommendation?.mode === 'cloud' ? 'cloud' : 'local');
    return <>
      <div className="ob-tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'local'} className={'ob-tab' + (tab === 'local' ? ' on' : '')} onClick={() => setTab('local')}><Logo src="provider-icons/huggingface-color.svg"/>On this computer</button>
        <button role="tab" aria-selected={tab === 'cloud'} className={'ob-tab' + (tab === 'cloud' ? ' on' : '')} onClick={() => setTab('cloud')}>Cloud</button>
      </div>
      {tab === 'local' ? <LocalModels {...props}/> : <CloudModels {...props}/>}
    </>;
  }

  function Connectors({api, account, connected, setConnected}) {
    const [list, setList] = useState(null);
    useEffect(() => {api.connectors().then(setList).catch(() => setList([]));}, []);
    if (!list) return <div className="ob-scanning" role="status"><i/>Loading connectors…</div>;
    const yours = account && ['google', 'github'].includes(account.provider) ? list.filter(c => c.account === account.provider) : [];
    const rest = list.filter(c => !yours.includes(c));
    const toggle = id => setConnected(connected.includes(id) ? connected.filter(x => x !== id) : [...connected, id]);
    const card = c => <button key={c.id} className={'ob-conn' + (connected.includes(c.id) ? ' on' : '')} aria-pressed={connected.includes(c.id)} onClick={() => toggle(c.id)}>
      <span className="ob-logo"><Logo src={c.icon} alt=""/></span>
      <span className="ob-conn-text"><strong>{c.name}</strong><small>{c.description}</small></span>
      <span className="ob-conn-state">{connected.includes(c.id) ? 'Added' : 'Add'}</span>
    </button>;
    if (!list.length) return <p className="ob-hint">Connectors aren't available right now. You can add them later in Plugins.</p>;
    return <>
      {yours.length > 0 && <section className="ob-group"><h2><ProviderMark provider={account.provider}/>With your {account.provider === 'google' ? 'Google' : 'GitHub'} account</h2><div className="ob-conns">{yours.map(card)}</div></section>}
      <section className="ob-group"><h2>{yours.length ? 'More connectors' : 'Connectors'}</h2><div className="ob-conns">{rest.map(card)}</div></section>
    </>;
  }

  const PRIVACY = [
    {id: 'local_only', title: 'Local only', sub: 'Nothing personal goes to a cloud model. Answers that need your notes or memory stay on this computer.', example: 'Cloud sees: nothing personal'},
    {id: 'ask_before_sharing', title: 'Ask before sharing', sub: 'When an answer would send personal context to a cloud model, Vellum asks first.', example: 'Vellum asks: share 2 notes about your trip?'},
    {id: 'protect_for_me', title: 'Protect it for me', sub: 'Names, emails, phone numbers and places are masked before anything is sent, then restored in the answer.', example: 'Cloud sees: [PERSON] is meeting [PERSON] in [LOCATION]', rec: true},
    {id: 'full_context', title: 'Full context', sub: 'Send everything relevant for the best answers. Passwords and financial details are still never sent.', example: 'Cloud sees: the full conversation and relevant memory'},
  ];
  function Privacy({privacy, setPrivacy, choice}) {
    return <>
      {choice?.kind === 'local' && <p className="ob-hint" style={{marginTop: -12, marginBottom: 16}}>You chose a local model, so nothing leaves this computer either way. This applies if you switch to a cloud model later.</p>}
      <div className="ob-list" role="radiogroup" aria-label="Privacy">
        {PRIVACY.map(p => <button key={p.id} role="radio" aria-checked={privacy === p.id} className={'ob-opt ob-radio' + (privacy === p.id ? ' on' : '')} onClick={() => setPrivacy(p.id)}>
          <span className="ob-dot"/>
          <span><span className="ob-opt-title">{p.title}</span><span className="ob-opt-sub">{p.sub}</span>{privacy === p.id && <span className="ob-example" style={{display: 'block'}}>{p.example}</span>}</span>
          {p.rec ? <span className="ob-tag rec">Recommended</span> : <span/>}
        </button>)}
      </div>
    </>;
  }

  function Memory({api, learn, setLearn}) {
    const [engines, setEngines] = useState(null);
    useEffect(() => {
      let live = true;
      const read = () => api.engines().then(result => live && setEngines(result)).catch(() => {});
      read();
      const timer = setInterval(read, 3000);
      return () => {live = false; clearInterval(timer);};
    }, []);
    const states = engines ? Object.values(engines.engines || {}).map(e => e.state) : [];
    const ready = states.length > 0 && states.every(s => s === 'ready');
    const waiting = !ready && (!states.length || states.every(s => ['off', 'stopped', 'needs_model'].includes(s)));
    return <>
      <div className="ob-timeline">
        <div><strong>Day 1</strong><small>Knows only what you tell it.</small></div>
        <div><strong>Week 2</strong><small>Remembers your projects, preferences, and how you like answers.</small></div>
        <div><strong>Day 30</strong><small>Suggests things before you ask, and shows you what it has learned.</small></div>
      </div>
      <div className="ob-toggle">
        <div><strong>Learn from conversations</strong><small>Memories stay on this computer. You can see, correct, or delete any of them in Memory.</small></div>
        <button className="ob-switch" role="switch" aria-checked={learn} aria-label="Learn from conversations" onClick={() => setLearn(!learn)}/>
      </div>
      <div className="ob-toggle">
        <div><strong>Keep history tidy</strong><small>Conversations are archived after 30 days and still searchable. After another 60 days they're distilled into memory cards and deleted. Preferences you state are kept.</small></div>
      </div>
      <section className="ob-group" style={{marginTop: 22}}>
        <h2>Bring what other assistants know about you</h2>
        <MemoryImport api={api}/>
      </section>
      <p className={'ob-status' + (ready ? ' ready' : '')} role="status"><i/>{ready ? 'Memory is ready' : waiting ? 'Memory starts once your model is set up' : 'Memory is starting in the background'}</p>
    </>;
  }

  function MemoryImport({api}) {
    const [source, setSource] = useState('');
    const [prompt, setPrompt] = useState('');
    const [text, setText] = useState('');
    const [plan, setPlan] = useState(null);
    const [keep, setKeep] = useState([]);
    const [busy, setBusy] = useState(false);
    const [note, setNote] = useState('');
    const [promptError, setPromptError] = useState('');
    const names = {chatgpt: 'ChatGPT', claude: 'Claude'};
    const loadPrompt = async () => {
      setPromptError('');
      try {setPrompt((await api.importPrompt()).prompt);}
      catch (error) {setPromptError(error.message || 'The message could not be loaded.');}
    };
    const open = async which => {
      setSource(which); setPlan(null); setNote(''); setText('');
      if (!prompt) await loadPrompt();
    };
    const review = async () => {
      setBusy(true); setNote('');
      try {const result = await api.importPlan(text); setPlan(result); setKeep(result.items.map((_, i) => i));}
      catch (error) {setNote(error.message);}
      finally {setBusy(false);}
    };
    const save = async () => {
      setBusy(true);
      try {
        const result = await api.importApply(plan.items.filter((_, i) => keep.includes(i)));
        setNote(`Kept ${result.saved} ${result.saved === 1 ? 'memory' : 'memories'} from ${names[source]}.`);
        setSource(''); setPlan(null);
      } catch (error) {setNote(error.message);}
      finally {setBusy(false);}
    };
    return <>
      <div className="ob-imports">
        <button className={'ob-import' + (source === 'chatgpt' ? ' on' : '')} onClick={() => open('chatgpt')}><Logo src="provider-icons/openai.svg"/>Import from ChatGPT</button>
        <button className={'ob-import' + (source === 'claude' ? ' on' : '')} onClick={() => open('claude')}><Logo src="provider-icons/claude-color.svg"/>Import from Claude</button>
      </div>
      {source && !plan && <div className="ob-importer">
        <p className="ob-hint">1. Copy this message and send it to {names[source]}.</p>
        <div className="ob-prompt"><pre>{prompt || (promptError ? 'Couldn’t load the message.' : 'Loading…')}</pre>{promptError && !prompt
          ? <button className="ob-btn" onClick={loadPrompt}>Try again</button>
          : <button className="ob-btn" disabled={!prompt} onClick={() => navigator.clipboard?.writeText(prompt).then(() => setNote('Copied.'))}>Copy</button>}</div>
        {promptError && !prompt && <p className="ob-hint err" role="alert">{promptError}</p>}
        <p className="ob-hint">2. Paste {names[source]}’s whole reply here.</p>
        <textarea className="ob-paste" rows={6} value={text} onChange={e => setText(e.target.value)} aria-label={`${names[source]}'s reply`}/>
        <div><button className="ob-btn" disabled={busy || !text.trim()} onClick={review}>{busy ? 'Reading…' : 'Review memories'}</button></div>
      </div>}
      {plan && <div className="ob-importer">
        <p className="ob-hint">{plan.items.length ? `Found ${plan.items.length}. Untick anything that’s wrong.` : 'Nothing new to import from that reply.'}{plan.dropped?.sensitive ? ` ${plan.dropped.sensitive} sensitive line(s) were left out.` : ''}</p>
        <div className="ob-review">{plan.items.map((item, i) => <label key={i}><input type="checkbox" checked={keep.includes(i)} onChange={e => setKeep(e.target.checked ? [...keep, i] : keep.filter(x => x !== i))}/><span>{item.text}</span></label>)}</div>
        <div style={{display: 'flex', gap: 8}}>
          {plan.items.length > 0 && <button className="ob-btn primary" disabled={busy || !keep.length} onClick={save}>Keep {keep.length}</button>}
          <button className="ob-btn ghost" onClick={() => setPlan(null)}>Back</button>
        </div>
      </div>}
      <p className="ob-hint" style={{marginTop: 8}} role="status">{note || 'You’ll review every memory before it’s kept.'}</p>
    </>;
  }

  // Local model: Ollama has to be running; then the download runs in the background.
  function OllamaNeeded({status, onRetry, checking}) {
    return <div className="ob-verdict" role="alert" style={{marginTop: 16}}>
      <Logo src="provider-icons/ollama-color.svg"/>
      <div>
        <h3>{status?.installed ? 'Start Ollama to continue' : 'Install Ollama to run models here'}</h3>
        <p className="ob-hint" style={{margin: '0 0 12px'}}>{status?.installed ? 'Ollama is installed but not running. Open it from the Start menu, then check again.' : 'Ollama is the free app that runs local models. Install it, open it once, then check again.'}</p>
        <div style={{display: 'flex', gap: 8, flexWrap: 'wrap'}}>
          {!status?.installed && <a className="ob-btn primary" style={{display: 'inline-grid', placeItems: 'center', textDecoration: 'none'}} href={status?.download_url || 'https://ollama.com/download'} target="_blank" rel="noreferrer">Get Ollama</a>}
          <button className="ob-btn" disabled={checking} onClick={onRetry}>{checking ? 'Checking…' : 'Check again'}</button>
        </div>
      </div>
    </div>;
  }

  // Context windows: "131072" -> "128k". Estimates are floors until the download is measured.
  const kTokens = value => Math.round(value / 1024) + 'k';
  function contextLabel(m) {
    return m.fit === 'cpu' ? `${kTokens(m.context_estimate)} context` : `${kTokens(m.context_estimate)}+ context on your GPU`;
  }
  function readyLabel(pull) {
    if (pull.context_state === 'sizing') return 'Model ready · sizing its context window for your GPU…';
    if (pull.context_state !== 'sized' || !pull.context_window) return 'Model ready';
    const where = {gpu: 'fully on your GPU', cpu: 'on your processor', partial: 'partly on your GPU', settings: 'from your settings'}[pull.context_placement] || '';
    return `Model ready · ${kTokens(pull.context_window)} context window${where ? ', ' + where : ''}`;
  }
  function PullProgress({pull}) {
    if (!pull || pull.state === 'idle') return null;
    const gb = n => (n / 1e9).toFixed(1);
    return <div className="ob-pull" role="status">
      <small>{pull.state === 'done' ? readyLabel(pull) : pull.state === 'error' ? 'Download stopped' : `Downloading · ${pull.total ? `${gb(pull.completed)} of ${gb(pull.total)} GB` : pull.detail}`}</small>
      {pull.state !== 'error' && <i><b style={{width: `${pull.state === 'done' ? 100 : pull.percent}%`}}/></i>}
      {pull.state === 'error' && <small className="err">{pull.error}</small>}
    </div>;
  }

  const COPY = {
    computer: {kicker: 'Step 1 of 5', title: 'First, a look at this computer', lede: 'Vellum can run its model privately on this computer or use one in the cloud. Here’s what this machine can handle, and what we recommend. Nothing about your hardware leaves this computer.'},
    model: {kicker: 'Step 2 of 5', title: 'Choose the model that does the thinking', lede: 'Local models are free and private, and work offline. Each size below is the best quality that fits your memory and graphics card. Cloud models are faster and stronger, but your messages go to that provider. You can switch any time from the model picker, and memory follows.'},
    connectors: {kicker: 'Step 3 of 5', title: 'Connect the tools you already use', lede: 'Vellum reads from these only when a task needs them, and signs in through your browser. Pick a few now or add more later in Plugins.'},
    privacy: {kicker: 'Step 4 of 5', title: 'Decide what may leave this computer', lede: 'This only matters when a cloud model answers. Vellum checks every message before it goes out, and you can change this later in Settings.'},
    memory: {kicker: 'Step 5 of 5', title: 'Vellum learns as you go', lede: 'On the first day it knows nothing about you. Over the first month it learns what you care about and becomes more personal and proactive.'},
  };

  function Onboarding({api, account, onDone}) {
    const [step, setStep] = useState(0);
    const [scan, setScan] = useState(null);
    const [choice, setChoice] = useState(null);
    const [keys, setKeys] = useState({});
    const [plans, setPlans] = useState({});
    const [connected, setConnected] = useState([]);
    const [privacy, setPrivacy] = useState('protect_for_me');
    const [learn, setLearn] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [ollama, setOllama] = useState(null);
    const [pull, setPull] = useState(null);
    const id = STEPS[step].id, copy = COPY[id];
    useEffect(() => {
      // Keep polling through the download and the context measurement that follows it.
      if (!pull || (pull.state !== 'pulling' && pull.context_state !== 'sizing')) return;
      const timer = setInterval(() => api.ollama().then(status => setPull(status.pull)).catch(() => {}), 1500);
      return () => clearInterval(timer);
    }, [pull?.state, pull?.context_state]);
    useEffect(() => {setError(''); setOllama(null);}, [step, choice?.id]);
    const needsKey = choice?.kind === 'cloud' && !keys[choice.id] && !plans[choice.id] && !choice.configured;
    const advance = () => setStep(step + 1);
    const modelStep = async () => {
      if (choice.kind === 'cloud') {
        if (keys[choice.id]) await api.saveKey(choice.id, keys[choice.id]);
        return advance();
      }
      const status = await api.ollama();
      setOllama(status);
      if (!status.running) return;
      setPull(await api.pull(choice.id));
      advance();
    };
    const finish = async () => {
      for (const connector of connected) {try {await api.enableConnector(connector);} catch {}}
      await api.complete({
        model_kind: choice?.kind || '', model_label: choice?.label || '',
        apply_provider: choice?.kind === 'cloud' ? choice.id : '',
        // A local model becomes the default when its download finishes.
        pending_local_model: choice?.kind === 'local' ? choice.id : '',
        connectors: connected, privacy, learn,
      });
      onDone?.({connectors: connected});
    };
    const next = async () => {
      setBusy(true); setError('');
      try {
        if (id === 'model') await modelStep();
        else if (step < STEPS.length - 1) advance();
        else await finish();
      } catch (e) {setError(e.message || 'Something went wrong. Try again.');}
      finally {setBusy(false);}
    };
    const primary = id === 'model' && choice?.kind === 'local' ? `Download ${choice.label}` : id === 'memory' ? 'Start using Vellum' : 'Continue';
    const props = {api, account, scan, setScan, choice, setChoice, keys, setKeys, plans, setPlans, connected, setConnected, privacy, setPrivacy, learn, setLearn};
    return <div className="ob">
      <aside className="ob-rail">
        <div className="ob-brand"><img src="assets/brand/vellum-icon-orange.png" alt=""/>Vellum</div>
        <Who account={account}/>
        <ol className="ob-steps">
          {STEPS.map((s, i) => <li key={s.id} className={i < step ? 'done' : i === step ? 'now' : ''} aria-current={i === step ? 'step' : undefined}><span className="n">{i < step ? '✓' : i + 1}</span>{s.label}</li>)}
        </ol>
        {choice?.kind === 'local' && <PullProgress pull={pull}/>}
        <p className="ob-rail-foot">Everything here can be changed later in Settings.</p>
      </aside>
      <main className="ob-main">
        <div className="ob-page" key={id}>
          <div className="ob-kicker">{copy.kicker}</div>
          <h1>{copy.title}</h1>
          <p className="ob-lede">{copy.lede}</p>
          {id === 'computer' && <Computer {...props}/>}
          {id === 'model' && <Model {...props}/>}
          {id === 'model' && ollama && !ollama.running && <OllamaNeeded status={ollama} checking={busy} onRetry={next}/>}
          {id === 'connectors' && <Connectors {...props}/>}
          {id === 'privacy' && <Privacy {...props}/>}
          {id === 'memory' && <Memory {...props}/>}
        </div>
        <div className="ob-foot"><div className="ob-foot-inner">
          {step > 0 && <button className="ob-btn ghost" onClick={() => setStep(step - 1)}>Back</button>}
          <span className="sp"/>
          {id === 'connectors' && <button className="ob-btn" onClick={() => setStep(step + 1)}>Skip for now</button>}
          {error && <span className="ob-hint err" role="alert">{error}</span>}
          {needsKey && <span className="ob-hint">{choice.id === 'openai' ? 'Sign in or add a key to continue' : 'Add a key to continue'}</span>}
          <button className="ob-btn primary" disabled={busy || (id === 'computer' && !scan) || (id === 'model' && (!choice || needsKey))} onClick={next}>{busy && id === 'memory' ? 'Setting up…' : primary}</button>
        </div></div>
      </main>
    </div>;
  }

  window.VellumUI = window.VellumUI || {};
  window.VellumUI.Onboarding = Onboarding;
})();
