import { parseTerminalCommand } from "./commands.js";

const DEFAULT_PROFILES = [
  { id: "powershell", label: "PowerShell", available: true },
  { id: "cmd", label: "CMD", available: true },
  { id: "pwsh", label: "PowerShell Core", available: false },
  { id: "wsl", label: "WSL Ubuntu", available: false },
  { id: "git-bash", label: "Git Bash", available: false },
  { id: "macos", label: "macOS SSH", available: false },
];
const escapeHTML=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

function wsUrl(apiBase = "") {
  if (apiBase) {
    const url = new URL(apiBase, location.origin);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.pathname = "/api/terminal/ws";
    url.search = "";
    url.hash = "";
    return url.toString();
  }
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/api/terminal/ws`;
}

export function createTerminalWorkspace(root, options = {}) {
  let TerminalClass = options.TerminalClass || null;
  let FitAddonClass = null;
  const socketFactory = options.socketFactory || (() => new WebSocket(wsUrl(options.apiBase || "")));
  const onOpenVellum = options.onOpenVellum || (() => {});
  const profiles = options.profiles || DEFAULT_PROFILES;
  const tabs = [];
  let activeTab = null;
  let tabCounter = 0;
  let disposed = false;

  function renderShell() {
    root.innerHTML = `
      <div class="terminal-workspace">
        <div class="terminal-toolbar">
          <div class="terminal-tabs" data-terminal-tabs></div>
          <button class="terminal-new" type="button" data-terminal-new title="New terminal">+</button>
          <select class="terminal-shell-select" data-terminal-shell></select>
        </div>
        <div class="terminal-stage" data-terminal-stage></div>
        <div class="terminal-status" data-terminal-status>disconnected</div>
      </div>
    `;
    const select = root.querySelector("[data-terminal-shell]");
    select.innerHTML = profiles.map((profile) => (
      `<option value="${escapeHTML(profile.id)}" ${profile.available === false ? "disabled" : ""}>${escapeHTML(profile.label)}</option>`
    )).join("");
    root.querySelector("[data-terminal-new]").addEventListener("click", () => newTab());
    select.addEventListener("change", () => switchShell(select.value));
  }

  function renderTabs() {
    const tabHost = root.querySelector("[data-terminal-tabs]");
    tabHost.innerHTML = tabs.map((tab) => `
      <button class="terminal-tab ${tab === activeTab ? "active" : ""}" data-tab-id="${tab.id}" type="button">
        <span>${escapeHTML(tab.title)}</span>
        <span class="terminal-tab-close" data-close-tab="${tab.id}">x</span>
      </button>
    `).join("");
    tabHost.querySelectorAll("[data-tab-id]").forEach((button) => {
      button.addEventListener("click", (event) => {
        if (event.target.matches("[data-close-tab]")) return;
        activateTab(button.dataset.tabId);
      });
    });
    tabHost.querySelectorAll("[data-close-tab]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        closeTab(button.dataset.closeTab);
      });
    });
  }

  function renderStatus(text) {
    root.querySelector("[data-terminal-status]").textContent = text;
  }

  function activeProfileLabel(profileId) {
    return profiles.find((profile) => profile.id === profileId)?.label || profileId;
  }

  function makeTerminal() {
    return new TerminalClass({
      cursorBlink: true,
      fontFamily: "JetBrains Mono, Consolas, monospace",
      fontSize: 13,
      theme: options.theme || window.VellumUI?.AppThemes?.terminalTheme(root) || { background: "#050505", foreground: "#f4f4f4" },
    });
  }

  function attachSocket(tab) {
    tab.socket = socketFactory(tab.profile);
    tab.socket.onopen = () => {
      if(disposed)return;
      tab.socket.send(JSON.stringify({ type: "start", profile: tab.profile, cols: tab.terminal.cols || 120, rows: tab.terminal.rows || 32 }));
      renderStatus(`${activeProfileLabel(tab.profile)} - connecting`);
    };
    tab.socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "ready") renderStatus(`${activeProfileLabel(tab.profile)} - ready`);
      if (message.type === "output") tab.terminal.write(message.data);
      if (message.type === "error") tab.terminal.writeln(`\r\n${message.message}`);
      if (message.type === "exit") renderStatus(`${activeProfileLabel(tab.profile)} - exited`);
    };
    tab.socket.onerror = () => renderStatus('Terminal connection failed. Close this terminal and open it again.');
    tab.socket.onclose = () => {if(!disposed && activeTab===tab)renderStatus('Terminal disconnected');};
    if (tab.socket.readyState === WebSocket.OPEN) {
      tab.socket.send(JSON.stringify({ type: "start", profile: tab.profile, cols: 120, rows: 32 }));
    }
  }

  function newTab(profile = profiles.find(profile=>profile.available!==false)?.id || "powershell") {
    const terminal = makeTerminal();
    const tab = {
      id: `term-${++tabCounter}`,
      title: activeProfileLabel(profile),
      profile,
      inputBuffer: "",
      terminal,
      socket: null,
      fit: typeof FitAddonClass === "function" ? new FitAddonClass() : null,
      host: document.createElement('div'),
    };
    tabs.push(tab);
    activeTab = tab;
    renderTabs();
    mountActiveTerminal();
    attachSocket(tab);
    return tab;
  }

  function mountActiveTerminal() {
    const stage = root.querySelector("[data-terminal-stage]");
    for(const tab of tabs)tab.host.hidden=tab!==activeTab;
    if (!activeTab) return;
    const tab=activeTab,host=tab.host;
    host.className = "terminal-host";
    if(!host.isConnected)stage.appendChild(host);
    if(!tab.mounted){
    tab.mounted=true;
    if (tab.fit && tab.terminal.loadAddon) tab.terminal.loadAddon(tab.fit);
    tab.terminal.open(host);
    tab.terminal.onResize?.(({cols,rows})=>{if(tab.socket?.readyState===WebSocket.OPEN)tab.socket.send(JSON.stringify({type:'resize',cols,rows}));});
    tab.terminal.onData((data) => {
      if(options.rawInput){
        if(tab.socket?.readyState===WebSocket.OPEN)tab.socket.send(JSON.stringify({type:'input',data}));
        return;
      }
      if (data === "\r") {
        activeTab.terminal.write("\r\n");
        handleCommand(activeTab.inputBuffer);
        activeTab.inputBuffer = "";
        return;
      }
      if (data === "\u007f") {
        if (activeTab.inputBuffer.length > 0) {
          activeTab.inputBuffer = activeTab.inputBuffer.slice(0, -1);
          activeTab.terminal.write("\b \b");
        }
        return;
      }
      activeTab.inputBuffer += data;
      activeTab.terminal.write(data);
    });
    }
    if (tab.fit && root.clientWidth && root.clientHeight) tab.fit.fit();
    tab.terminal.focus();
    root.querySelector("[data-terminal-shell]").value = activeTab.profile;
    renderStatus(`${activeProfileLabel(activeTab.profile)} - active`);
  }

  function activateTab(id) {
    activeTab = tabs.find((tab) => tab.id === id) || activeTab;
    renderTabs();
    mountActiveTerminal();
  }

  function closeTab(id = activeTab?.id, replaceWhenEmpty = true) {
    const index = tabs.findIndex((tab) => tab.id === id);
    if (index === -1) return;
    const [tab] = tabs.splice(index, 1);
    if (tab.socket) {
      if(tab.socket.readyState===WebSocket.OPEN)tab.socket.send(JSON.stringify({ type: "terminate" }));
      tab.socket.close();
    }
    tab.terminal.dispose();
    tab.host.remove();
    activeTab = tabs[index] || tabs[index - 1] || null;
    if(disposed)return;
    if (!activeTab && replaceWhenEmpty) newTab();
    else {
      renderTabs();
      mountActiveTerminal();
    }
  }

  function switchShell(profile) {
    if (!activeTab) return;
    closeTab(activeTab.id, false);
    newTab(profile);
  }

  function handleCommand(input) {
    const parsed = parseTerminalCommand(input);
    if (parsed.type === "empty") return;
    if (parsed.type === "shell") {
      activeTab?.socket?.send(JSON.stringify({ type: "input", data: `${parsed.raw}\r` }));
      return;
    }
    if (parsed.type === "vellum") {
      if (activeTab) activeTab.title = "vellum";
      renderTabs();
      onOpenVellum({ tab: activeTab });
      return;
    }
    if (parsed.type === "new-tab") {
      newTab(parsed.profile || "powershell");
      return;
    }
    if (parsed.type === "switch-shell") {
      switchShell(parsed.profile);
      return;
    }
    if (parsed.type === "tabs") {
      activeTab?.terminal.writeln(tabs.map((tab, index) => `${index + 1}. ${tab.title}`).join("\r\n"));
      return;
    }
    if (parsed.type === "close-tab") {
      closeTab();
      return;
    }
    activeTab?.terminal.writeln(`unknown command: ${parsed.command}`);
  }

  async function loadTerminalAdapter() {
    if (TerminalClass) return;
    const [xterm, fit] = await Promise.all([
      import("@xterm/xterm"),
      import("@xterm/addon-fit"),
      import("@xterm/xterm/css/xterm.css"),
    ]);
    TerminalClass = xterm.Terminal;
    FitAddonClass = fit.FitAddon;
  }

  async function mount() {
    await loadTerminalAdapter();
    if(disposed)return;
    renderShell();
    newTab(profiles.find(profile=>profile.available!==false)?.id || 'powershell');
    window.addEventListener('vellum:appearance-change',updateTerminalTheme);
  }

  function updateTerminalTheme() {
    if(options.theme)return;
    const theme=window.VellumUI?.AppThemes?.terminalTheme(root);
    if(theme)for(const tab of tabs)tab.terminal.options.theme=theme;
  }

  return {
    mount,
    newTab,
    handleCommand,
    focus:()=>activeTab?.terminal.focus(),
    resize:()=>{if(root.clientWidth && root.clientHeight)activeTab?.fit?.fit();},
    dispose:()=>{
      disposed=true;
      window.removeEventListener('vellum:appearance-change',updateTerminalTheme);
      for(const tab of [...tabs])closeTab(tab.id,false);
      root.replaceChildren();
    },
    get activeTerminal() {
      return activeTab?.terminal;
    },
  };
}
