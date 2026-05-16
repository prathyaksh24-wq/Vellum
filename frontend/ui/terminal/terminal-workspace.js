import { parseTerminalCommand } from "./commands.js";

const DEFAULT_PROFILES = [
  { id: "powershell", label: "PowerShell", available: true },
  { id: "cmd", label: "CMD", available: true },
  { id: "pwsh", label: "PowerShell Core", available: false },
  { id: "wsl", label: "WSL Ubuntu", available: false },
  { id: "git-bash", label: "Git Bash", available: false },
  { id: "macos", label: "macOS SSH", available: false },
];

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
      `<option value="${profile.id}" ${profile.available === false ? "disabled" : ""}>${profile.label}</option>`
    )).join("");
    root.querySelector("[data-terminal-new]").addEventListener("click", () => newTab());
    select.addEventListener("change", () => switchShell(select.value));
  }

  function renderTabs() {
    const tabHost = root.querySelector("[data-terminal-tabs]");
    tabHost.innerHTML = tabs.map((tab) => `
      <button class="terminal-tab ${tab === activeTab ? "active" : ""}" data-tab-id="${tab.id}" type="button">
        <span>${tab.title}</span>
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
      theme: { background: "#050505", foreground: "#f4f4f4" },
    });
  }

  function attachSocket(tab) {
    tab.socket = socketFactory(tab.profile);
    tab.socket.onopen = () => {
      tab.socket.send(JSON.stringify({ type: "start", profile: tab.profile, cols: 120, rows: 32 }));
      renderStatus(`${activeProfileLabel(tab.profile)} - connecting`);
    };
    tab.socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "ready") renderStatus(`${activeProfileLabel(tab.profile)} - ready`);
      if (message.type === "output") tab.terminal.write(message.data);
      if (message.type === "error") tab.terminal.writeln(`\r\n${message.message}`);
      if (message.type === "exit") renderStatus(`${activeProfileLabel(tab.profile)} - exited`);
    };
    if (tab.socket.readyState === WebSocket.OPEN) {
      tab.socket.send(JSON.stringify({ type: "start", profile: tab.profile, cols: 120, rows: 32 }));
    }
  }

  function newTab(profile = "powershell") {
    const terminal = makeTerminal();
    const tab = {
      id: `term-${++tabCounter}`,
      title: activeProfileLabel(profile),
      profile,
      inputBuffer: "",
      terminal,
      socket: null,
      fit: typeof FitAddonClass === "function" ? new FitAddonClass() : null,
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
    stage.innerHTML = "";
    if (!activeTab) return;
    const host = document.createElement("div");
    host.className = "terminal-host";
    stage.appendChild(host);
    if (activeTab.fit && activeTab.terminal.loadAddon) activeTab.terminal.loadAddon(activeTab.fit);
    activeTab.terminal.open(host);
    if (activeTab.fit) activeTab.fit.fit();
    activeTab.terminal.onData((data) => {
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
    activeTab.terminal.focus();
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
      tab.socket.send(JSON.stringify({ type: "terminate" }));
      tab.socket.close();
    }
    tab.terminal.dispose();
    activeTab = tabs[index] || tabs[index - 1] || null;
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
    renderShell();
    newTab("powershell");
  }

  return {
    mount,
    newTab,
    handleCommand,
    get activeTerminal() {
      return activeTab?.terminal;
    },
  };
}
