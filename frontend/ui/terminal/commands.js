const SHELL_ALIASES = new Set([
  "powershell",
  "ps",
  "cmd",
  "pwsh",
  "ubuntu",
  "wsl",
  "bash",
  "git-bash",
  "mac",
  "macos",
]);

export function parseTerminalCommand(input) {
  const raw = String(input || "").trim();
  if (!raw) return { type: "empty" };
  if (raw === "vellum" || raw === "/vellum") return { type: "vellum" };
  if (!raw.startsWith("/")) return { type: "shell", raw };

  const [command, arg] = raw.slice(1).split(/\s+/, 2);
  if (command === "shell" && arg && SHELL_ALIASES.has(arg)) {
    return { type: "switch-shell", profile: arg };
  }
  if (command === "new") {
    return { type: "new-tab", profile: arg || null };
  }
  if (command === "tabs") return { type: "tabs" };
  if (command === "close") return { type: "close-tab" };
  return { type: "unknown", command: raw };
}
