# Web Terminal Hub Design

Date: 2026-05-15

## Goal

Add a terminal-first workspace to the Vellum web interface. The terminal should run real shell commands, support multiple shell profiles in separate tabs, and launch the Vellum terminal UI when the user types `vellum`.

The web app should feel like a terminal-native tool surface: a black terminal opens from the sidebar, users can create new terminal pages with `+`, switch shell profiles by command or button, and keep Vellum as a command inside the terminal rather than a separate marketing-style page.

## Product Behavior

The existing web interface gets a `Terminal` entry in the sidebar. Selecting it replaces the chat surface with a terminal workspace while preserving the surrounding Vellum shell.

The terminal workspace contains:

- A black terminal viewport.
- A tab strip with close buttons and a `+` button for new blank terminal tabs.
- A compact shell profile control for the active tab.
- A status line showing shell profile, working directory, and connection state.

Each terminal tab owns one backend session. Users can open several tabs with different shell profiles, for example:

- `PowerShell`
- `CMD`
- `pwsh`
- `WSL Ubuntu`
- `Git Bash`
- `macOS SSH`

Normal text entered in a terminal goes to the active shell process. Slash commands are handled by Vellum before they reach the shell.

## Shell Profiles

The backend exposes a small profile catalog. Each profile defines a label, command, arguments, environment, working directory, and availability check.

Initial local profiles on Windows:

- `powershell`: starts `powershell.exe -NoLogo`
- `cmd`: starts `cmd.exe`
- `pwsh`: starts `pwsh.exe -NoLogo` when available
- `wsl`: starts `wsl.exe -d Ubuntu` when WSL and the Ubuntu distribution are available
- `git-bash`: starts Git Bash when installed

`macos` is a remote profile, not a local emulator. macOS commands only run against a configured SSH target, such as `ssh user@mac-host`. If no macOS SSH target is configured, the profile appears disabled with a clear message.

This distinction is important: Windows can host Windows shells and Linux shells through WSL or Git Bash, but it cannot locally execute true macOS commands without a remote Mac.

## Slash Commands

Slash commands provide terminal-level control without leaving the keyboard:

- `/shell powershell` switches the current tab to PowerShell.
- `/shell cmd` switches the current tab to Windows CMD.
- `/shell pwsh` switches the current tab to PowerShell Core.
- `/shell ubuntu` switches the current tab to WSL Ubuntu.
- `/shell bash` switches the current tab to Git Bash when available.
- `/shell mac` switches the current tab to the macOS SSH profile when configured.
- `/new` opens a new tab with the default shell.
- `/new powershell`, `/new cmd`, `/new ubuntu`, and similar variants open a new tab with that profile.
- `/tabs` lists open terminal tabs.
- `/close` closes the active tab after confirming if a foreground process is still running.
- `/vellum` and `vellum` both launch the Vellum terminal UI mode.

Unknown slash commands should print a short terminal message and should not be forwarded to the shell.

## Vellum Command

Typing `vellum` is special. The command should open the Vellum TUI inside the terminal workspace.

The first implementation can treat Vellum mode as an in-terminal app surface backed by the existing `Vellum TUI` design assets. It does not need to run an OS-level nested TUI process on day one, as long as the interaction model is terminal-native:

- The active tab title changes to `vellum`.
- The terminal viewport shows the Vellum setup/handoff interface.
- Exiting Vellum returns to the shell tab.
- Existing Vellum setup state is reused through the current `/api/setup/state` and `/api/setup/complete` endpoints.

Future work can replace the frontend-rendered Vellum mode with the backend Textual TUI running through the same PTY transport. That is not part of the first implementation.

## Architecture

### Frontend

Use `xterm.js` for the terminal viewport. It provides robust keyboard handling, ANSI rendering, selection, resize behavior, and scrollback. Avoid hand-rolling terminal emulation.

Frontend responsibilities:

- Render the `Terminal` sidebar entry and terminal workspace.
- Manage tab UI state: active tab, title, shell profile label, and connection status.
- Open a WebSocket per terminal session.
- Attach `xterm.js` input/output to the session socket.
- Intercept slash commands before sending them to the shell.
- Intercept bare `vellum` before sending it to the shell.
- Resize the PTY when the browser terminal resizes.
- Render Vellum mode in the terminal workspace when requested.

The terminal view should be isolated from chat state. Chat threads and terminal sessions are separate concepts.

### Backend

Add a WebSocket terminal service to the FastAPI backend.

Backend responsibilities:

- List available shell profiles.
- Create terminal sessions.
- Spawn the selected shell in a pseudo-terminal where possible.
- Stream PTY output to the browser.
- Write browser input to the PTY.
- Resize PTY sessions.
- Terminate sessions on tab close or socket disconnect.
- Reject unavailable profiles with structured errors.

On Windows, the PTY implementation should use a Windows-compatible library. The preferred route is `pywinpty` if it works cleanly with the current environment. If that is not available, the implementation can fall back to subprocess pipes for a limited first pass, but the design target remains a real PTY.

### Protocol

The WebSocket messages are JSON envelopes:

- Client to server:
  - `{ "type": "start", "profile": "powershell", "cwd": "..." }`
  - `{ "type": "input", "data": "..." }`
  - `{ "type": "resize", "cols": 120, "rows": 32 }`
  - `{ "type": "terminate" }`
- Server to client:
  - `{ "type": "ready", "sessionId": "...", "profile": "powershell" }`
  - `{ "type": "output", "data": "..." }`
  - `{ "type": "exit", "code": 0 }`
  - `{ "type": "error", "message": "..." }`

The frontend owns slash-command parsing. The backend owns process lifecycle and command execution.

## Data Flow

1. User clicks `Terminal` in the sidebar.
2. Frontend opens a terminal tab using the default profile.
3. Frontend opens a WebSocket to the backend terminal endpoint.
4. Backend starts the selected shell and returns `ready`.
5. Shell output streams into `xterm.js`.
6. User input goes through a small command gate:
   - Slash commands are handled by the terminal workspace.
   - Bare `vellum` opens Vellum mode.
   - Everything else is sent to the active shell.
7. Closing a tab sends `terminate`, then closes the WebSocket.

## Security And Safety

This feature intentionally executes local commands. It should be treated as a trusted-local feature, not an internet-exposed API.

Required safeguards:

- Bind development servers to localhost by default.
- Do not expose the terminal WebSocket to arbitrary origins.
- Keep the existing CORS allowlist restrictive.
- Do not log terminal input by default.
- Do not persist terminal scrollback in the first implementation.
- Warn before closing tabs with active foreground processes when possible.
- Keep macOS SSH credentials outside the frontend and read them from local config or environment.

## Error Handling

Unavailable shell profiles should render as terminal output, not browser alerts. Examples:

- WSL is not installed.
- The requested WSL distribution does not exist.
- Git Bash is not installed.
- `pwsh.exe` is not installed.
- macOS SSH profile is not configured.
- The backend cannot allocate a PTY.

If the terminal WebSocket disconnects, the tab should show a disconnected status and offer a reconnect command.

## Testing

Frontend tests should cover:

- Terminal sidebar item switches to the terminal workspace.
- `+` creates a new terminal tab.
- `/new powershell` creates a PowerShell tab.
- `/shell cmd` switches the active tab profile.
- `vellum` enters Vellum mode instead of being sent to the shell.
- Unknown slash commands produce terminal output.

Backend tests should cover:

- Profile catalog reports available and unavailable profiles.
- Invalid profile names are rejected.
- Terminal sessions can start and terminate.
- Resize messages are accepted.
- Input messages are forwarded only after a session is ready.

Manual verification should cover:

- PowerShell command execution.
- CMD command execution.
- WSL command execution when WSL is installed.
- Git Bash command execution when installed.
- macOS SSH disabled state when no target is configured.
- Vellum command opens and exits the TUI mode.

## Implementation Boundaries

In scope for the first implementation:

- Sidebar `Terminal` entry.
- Multi-tab terminal workspace.
- Shell profile catalog.
- Real local Windows shell sessions.
- WSL/Git Bash profiles when available.
- Disabled macOS SSH profile until configured.
- `vellum` command opens the Vellum terminal UI surface.

Out of scope for the first implementation:

- Full remote terminal management UI.
- Saved terminal layouts.
- Persistent terminal scrollback.
- Sharing terminal sessions between users.
- True local macOS emulation on Windows.
- Exposing terminal sessions outside localhost.

## Open Decisions

The default shell profile should be `powershell` on this Windows workspace.

The default working directory should be the repository root:

`C:\Users\User\OneDrive\Desktop\Vellum\Vellum`

The first macOS profile should remain disabled until the user provides an SSH target.
