# Agent Computer-Use Routing Polish Design

## Goal

Give Vellum a code-backed routing policy for computer-use tasks so it consistently chooses the safest useful surface before acting.

## Routing Policy

Vellum should classify automation requests into four route families:

- `browser`: Website and browser-only tasks. Use Playwright/browser tools first. YouTube search tasks should route directly to `https://www.youtube.com/results?search_query=<query>` when a query is present.
- `desktop`: Host laptop app control. Use native Windows desktop mode for installed app launch, host-window observation, and explicit OS screen/mouse/keyboard control.
- `workspace`: Vellum workspace terminal/browser/screenshot actions. Use for terminal commands and visible workspace operations that do not require controlling the host OS.
- `coming_soon`: CUA driver, cloud VM, and simultaneous user/agent laptop sharing modes. These are product roadmap items, not active local driver modes.

## Components

- `agent.computer_use.routing_policy`: Pure classifier that returns a serializable route recommendation.
- `agent.tools.computer_use_route`: LangChain tool wrapper that exposes the classifier to the agent without executing actions.
- `agent.graph.agent`: Prompt and tool list updates so Vellum consults the policy for ambiguous automation tasks and follows the browser-first/desktop-last priority.

## Safety

The policy does not bypass existing permission gates. It only recommends a route. Desktop execution remains guarded by computer-use mode, input lease, environment flags, and runtime permission grants.

## Testing

Tests cover:

- YouTube/browser tasks route to browser automation.
- Installed app tasks route to native desktop app launch.
- Terminal commands route to workspace terminal.
- CUA/cloud-VM requests route to coming soon.
- The tool is included in both sync and async agent tool lists.
