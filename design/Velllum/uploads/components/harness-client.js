// Vellum harness, client half: typed slots, the client module loader, and the live
// plugin runtime that mounts each active harness entry's client module and
// hot-reloads it when the backend recomposes. A port of DeepSeek Harness' Client
// Slots and module loader.
(function () {
  // Resolve React on use, not at load: the packaged desktop build defines
  // window.React from its bundled module after this classic script has run.
  var React = new Proxy({}, { get: function (_target, key) { return window.React[key]; } });
  var api = function () { return window.VellumApi && window.VellumApi.client; };

  // ------------------------------------------------------------------ slots
  // name -> {cardinality, scope}
  var declarations = new Map();
  // name -> [{options, component, seq, owner}]
  var registrations = new Map();
  // name -> [{callback, disposers}]
  var injectors = new Map();
  var listeners = new Set();
  var version = 0;
  var sequence = 0;
  var collector = null;
  var currentOwner = '';
  var ready = false;

  function notify() {
    version += 1;
    listeners.forEach(function (listener) { try { listener(); } catch (_) {} });
    scheduleManifest();
  }

  function runInjector(name, injector) {
    var previous = collector;
    collector = [];
    try {
      var result = injector.callback();
      if (typeof result === 'function') collector.push(result);
    } catch (error) {
      console.error("slot injector failed in '" + name + "'", error);
    }
    injector.disposers = collector;
    collector = previous;
  }

  function disposeInjector(injector) {
    var disposers = injector.disposers || [];
    injector.disposers = [];
    disposers.reverse().forEach(function (dispose) { try { dispose(); } catch (_) {} });
  }

  var Slots = {
    declare: function (name, spec) {
      if (declarations.has(name)) throw new Error("Slot '" + name + "' is already declared.");
      declarations.set(name, { cardinality: spec.cardinality, description: spec.description || '' });
      (injectors.get(name) || []).forEach(function (injector) { runInjector(name, injector); });
      notify();
      return function () {
        (injectors.get(name) || []).forEach(disposeInjector);
        declarations.delete(name);
        notify();
      };
    },
    register: function (options, component) {
      var name = options && options.name;
      if (!declarations.has(name)) throw new Error("Slot '" + name + "' is not declared.");
      var cardinality = declarations.get(name).cardinality;
      if ((cardinality === 'list' || cardinality === 'keyed') && !options.id) throw new Error("A '" + name + "' registration needs an id.");
      if (cardinality === 'keyed' && !options.key) throw new Error("A '" + name + "' registration needs a key.");
      var record = { options: options, component: component, seq: ++sequence, owner: currentOwner };
      var list = registrations.get(name) || [];
      list.push(record);
      registrations.set(name, list);
      notify();
      var dispose = function () {
        var items = registrations.get(name) || [];
        var index = items.indexOf(record);
        if (index >= 0) { items.splice(index, 1); notify(); }
      };
      if (collector) collector.push(dispose);
      return dispose;
    },
    inject: function (name, callback) {
      var injector = { callback: callback, disposers: [] };
      var list = injectors.get(name) || [];
      list.push(injector);
      injectors.set(name, list);
      if (declarations.has(name)) runInjector(name, injector);
      var dispose = function () {
        disposeInjector(injector);
        var items = injectors.get(name) || [];
        var index = items.indexOf(injector);
        if (index >= 0) items.splice(index, 1);
      };
      if (collector) collector.push(dispose);
      return dispose;
    },
    // Live contributions for one slot, resolved by cardinality.
    resolve: function (name, entryKey) {
      var declaration = declarations.get(name);
      var items = (registrations.get(name) || []).slice();
      var byPriority = function (a, b) {
        return ((a.options.priority || 0) - (b.options.priority || 0)) || (b.seq - a.seq);
      };
      if (!declaration) return [];
      if (declaration.cardinality === 'single') return items.sort(byPriority).slice(0, 1);
      if (declaration.cardinality === 'keyed') items = items.filter(function (r) { return r.options.key === entryKey; });
      // list and keyed: one cell per id; the lowest priority shadows the rest.
      var cells = new Map();
      items.sort(byPriority).forEach(function (record) {
        if (!cells.has(record.options.id)) cells.set(record.options.id, record);
      });
      return Array.from(cells.values()).sort(function (a, b) {
        return ((a.options.order || 0) - (b.options.order || 0)) || (a.seq - b.seq);
      });
    },
    subscribe: function (listener) { listeners.add(listener); return function () { listeners.delete(listener); }; },
    version: function () { return version; },
    tree: function () {
      return Array.from(declarations.entries()).map(function (pair) {
        var name = pair[0];
        return {
          name: name,
          cardinality: pair[1].cardinality,
          description: pair[1].description,
          registrations: (registrations.get(name) || []).map(function (r) {
            return { id: r.options.id || '', key: r.options.key || '', order: r.options.order || 0,
                     priority: r.options.priority || 0, owner: r.owner || 'page', label: r.options.label || '' };
          }),
          rendered: Slots.resolve(name).map(function (r) { return r.options.id || r.owner; }),
        };
      });
    },
  };

  // A crashed contribution blanks only itself.
  var SlotEntryBoundaryClass = null;
  function SlotEntryBoundary() {
    if (!SlotEntryBoundaryClass) SlotEntryBoundaryClass = class extends window.React.Component {
      constructor(props) { super(props); this.state = { failed: false }; }
      static getDerivedStateFromError() { return { failed: true }; }
      componentDidCatch(error) { console.error("slot entry crashed in '" + this.props.slot + "'", error); }
      render() { return this.state.failed ? null : this.props.children; }
    };
    return SlotEntryBoundaryClass;
  }

  function useSlot(name, entryKey) {
    React.useSyncExternalStore(Slots.subscribe, Slots.version);
    return Slots.resolve(name, entryKey);
  }

  // <VellumSlot name="..." props={{...}} entryKey="..." fallback={node}/>
  // fallback renders only until the first harness sync mounts the plugins.
  function VellumSlot(props) {
    var records = useSlot(props.name, props.entryKey);
    if (!records.length) return ready ? null : (props.fallback || null);
    return React.createElement(React.Fragment, null, records.map(function (record) {
      return React.createElement(SlotEntryBoundary(), { key: (record.options.id || '') + ':' + record.seq, slot: props.name },
        React.createElement(record.component, Object.assign({}, props.props || {}, { slotOptions: record.options })));
    }));
  }

  // ------------------------------------------------------------------ module loader
  var factories = new Map();
  var waiting = new Map();
  window.__VellumModuleLoader__ = {
    load: function (definition) {
      if (!definition || typeof definition.id !== 'string' || typeof definition.factory !== 'function') {
        console.error('Vellum module loader: load({id, factory}) needs an id and a factory.');
        return;
      }
      factories.set(definition.id, definition.factory);
      (waiting.get(definition.id) || []).forEach(function (resolve) { resolve(definition.factory); });
      waiting.delete(definition.id);
    },
  };

  function requireModule(name) {
    if (name === 'react') return window.React;
    if (name === 'react-dom') return window.ReactDOM;
    throw new Error("Vellum client modules can require 'react' and 'react-dom'; '" + name + "' is not available.");
  }

  function loadScript(url, id) {
    return new Promise(function (resolve, reject) {
      var timer = setTimeout(function () { reject(new Error('Timed out loading ' + id)); }, 15000);
      var list = waiting.get(id) || [];
      list.push(function (factory) { clearTimeout(timer); resolve(factory); });
      waiting.set(id, list);
      var script = document.createElement('script');
      script.src = url;
      script.async = true;
      script.dataset.harnessModule = id;
      script.onerror = function () { clearTimeout(timer); reject(new Error('Could not load ' + id)); };
      document.head.appendChild(script);
    });
  }

  function factoryFor(entry) {
    if (entry.module === 'builtin') {
      var builtin = factories.get(entry.name);
      return builtin ? Promise.resolve(builtin) : Promise.reject(new Error('No built-in client module ' + entry.name));
    }
    factories.delete(entry.name);
    var base = api() ? api().backendBase() : 'http://127.0.0.1:8000';
    return loadScript(base + entry.module, entry.name);
  }

  // ------------------------------------------------------------------ live plugins
  var mounted = new Map(); // entry id -> {key, dispose, config}
  var configs = new Map();
  var configListeners = new Set();
  var revision = -1;
  var syncing = null;

  function entryKey(entry) { return JSON.stringify([entry.name, entry.module, entry.config]); }

  function mountEntry(entry, factory) {
    var effects = [];
    var previous = collector;
    var previousOwner = currentOwner;
    collector = effects;
    currentOwner = entry.id;
    try {
      var plugin = factory(requireModule);
      var ctx = {
        entry: entry.id,
        config: entry.config,
        slots: Slots,
        effect: function (dispose) { effects.push(dispose); return dispose; },
      };
      if (plugin && typeof plugin.apply === 'function') {
        var result = plugin.apply(ctx);
        if (typeof result === 'function') effects.push(result);
      }
    } catch (error) {
      console.error('Vellum plugin ' + entry.name + ' failed to apply', error);
    } finally {
      collector = previous;
      currentOwner = previousOwner;
    }
    return function () {
      effects.reverse().forEach(function (dispose) { try { dispose(); } catch (_) {} });
    };
  }

  function setConfigs(entries) {
    configs = new Map(entries.map(function (entry) { return [entry.id, entry.config]; }));
    configListeners.forEach(function (listener) { try { listener(); } catch (_) {} });
  }

  async function sync() {
    if (syncing) return syncing;
    syncing = (async function () {
      var client = api();
      if (!client) return;
      var payload = await client.request('/api/harness/client', { cache: 'no-store' });
      if (!payload || payload.revision === revision) return;
      revision = payload.revision;
      var wanted = new Map(payload.entries.map(function (entry) { return [entry.id, entry]; }));
      Array.from(mounted.keys()).reverse().forEach(function (id) {
        var entry = wanted.get(id);
        if (!entry || entryKey(entry) !== mounted.get(id).key) {
          mounted.get(id).dispose();
          mounted.delete(id);
        }
      });
      setConfigs(payload.entries);
      for (var i = 0; i < payload.entries.length; i += 1) {
        var entry = payload.entries[i];
        if (mounted.has(entry.id)) continue;
        try {
          var factory = await factoryFor(entry);
          mounted.set(entry.id, { key: entryKey(entry), dispose: mountEntry(entry, factory) });
        } catch (error) {
          console.error('Vellum plugin ' + entry.name + ' could not load', error);
        }
      }
      setApprovals(payload.approvals || []);
      setFullAccessState(payload.full_access);
      if (!ready) { ready = true; notify(); }
      sendManifest();
    })().finally(function () { syncing = null; });
    return syncing;
  }

  // ------------------------------------------------------------------ permissions
  var fullAccess = false;
  var permissionListeners = new Set();
  function setFullAccessState(value) {
    fullAccess = value === true;
    permissionListeners.forEach(function (listener) { try { listener(); } catch (_) {} });
  }

  // ------------------------------------------------------------------ approvals
  var approvals = [];
  var approvalListeners = new Set();
  function setApprovals(next) {
    approvals = next;
    approvalListeners.forEach(function (listener) { try { listener(); } catch (_) {} });
  }
  function onApproval(event) {
    var others = approvals.filter(function (item) { return item.id !== event.id; });
    setApprovals(event.status === 'pending' ? others.concat([event]) : others);
  }

  // ------------------------------------------------------------------ manifest
  var manifestTimer = null;
  function scheduleManifest() {
    clearTimeout(manifestTimer);
    manifestTimer = setTimeout(sendManifest, 400);
  }
  function themeTokens() {
    var tokens = {};
    var style = getComputedStyle(document.documentElement);
    try {
      Array.from(document.styleSheets).forEach(function (sheet) {
        var rules;
        try { rules = sheet.cssRules; } catch (_) { return; }
        Array.from(rules || []).forEach(function (rule) {
          if (rule.selectorText !== ':root' || !rule.style) return;
          Array.from(rule.style).forEach(function (property) {
            if (property.indexOf('--') === 0 && Object.keys(tokens).length < 150) {
              tokens[property] = style.getPropertyValue(property).trim();
            }
          });
        });
      });
    } catch (_) {}
    var mode = document.documentElement.dataset.theme || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    return { mode: mode, tokens: tokens };
  }
  function sendManifest() {
    var client = api();
    if (!client) return;
    client.request('/api/harness/client/manifest', client.jsonOptions('POST', {
      slots: Slots.tree(), theme: themeTokens(), revision: revision,
    })).catch(function () {});
  }

  // ------------------------------------------------------------------ events
  function connect() {
    var client = api();
    if (!client || typeof window.EventSource !== 'function') return;
    var source = new window.EventSource(client.backendBase() + '/api/harness/events');
    source.onmessage = function (message) {
      var event;
      try { event = JSON.parse(message.data); } catch (_) { return; }
      if (event.event === 'harness/changed') sync();
      else if (event.event === 'harness/approval') onApproval(event);
      else if (event.event === 'harness/permissions') setFullAccessState(event.full_access);
      else if (event.event === 'harness/hello') { setApprovals(event.approvals || []); if (event.revision !== revision) sync(); }
    };
  }

  // ------------------------------------------------------------------ shipped slots
  Slots.declare('shell.background', { cardinality: 'single', description: 'The full-window background behind the app.' });
  Slots.declare('sidebar.panellist', { cardinality: 'list', description: 'Entries in the main sidebar, after Memory.' });
  Slots.declare('settings.sections', { cardinality: 'list', description: 'Extra Settings sections.' });
  Slots.declare('shell.view', { cardinality: 'keyed', description: 'A full page for a view id.' });

  window.VellumHarness = {
    Slots: Slots,
    VellumSlot: VellumSlot,
    useSlot: useSlot,
    sync: sync,
    config: function (entryId) { return configs.get(entryId); },
    useConfig: function (entryId) {
      React.useSyncExternalStore(function (listener) { configListeners.add(listener); return function () { configListeners.delete(listener); }; },
        function () { return configs; });
      return configs.get(entryId);
    },
    useApprovals: function () {
      return React.useSyncExternalStore(function (listener) { approvalListeners.add(listener); return function () { approvalListeners.delete(listener); }; },
        function () { return approvals; });
    },
    useFullAccess: function () {
      return React.useSyncExternalStore(function (listener) { permissionListeners.add(listener); return function () { permissionListeners.delete(listener); }; },
        function () { return fullAccess; });
    },
    setFullAccess: function (enabled) {
      var client = api();
      return client.request('/api/harness/permissions', client.jsonOptions('PUT', { full_access: !!enabled }))
        .then(function (result) { setFullAccessState(result.full_access); return result; });
    },
    decide: function (id, approved) {
      var client = api();
      return client.request('/api/harness/approvals/' + encodeURIComponent(id), client.jsonOptions('POST', { approved: approved }))
        .then(function (result) { onApproval(result); return result; });
    },
    start: function () {
      if (window.VellumHarness.started) return;
      window.VellumHarness.started = true;
      sync().catch(function (error) { console.error('Vellum harness sync failed', error); });
      connect();
      // Keep client inspection fresh while the page is open.
      setInterval(sendManifest, 60000);
    },
  };
})();
