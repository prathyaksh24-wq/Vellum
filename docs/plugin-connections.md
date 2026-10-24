# Plugin connections and management

Settings is a full-page management surface; the sidebar Plugins directory provides categorized discovery and service-owned details. Installed skills expose Markdown, source metadata and lifecycle actions through the existing Skills Hub. The Add menu uses reviewed App Actions for plugins, marketplaces, custom MCP servers and declarative archives.

Linear uses its official hosted MCP endpoint and per-user OAuth/PKCE. Product Hunt uses its official API with a developer credential stored by the operating system. Google uses one account grant with independent Gmail, Drive, Calendar and Contacts switches. See [Linear](linear.md) and [Google Workspace](google-workspace.md) for setup and boundaries.

The main agent and scoped specialists use deferred tool discovery. Reads do not require a fictional service agent. Writes produce an exact-operation review before execution. Permission, enablement, credential and account restrictions remain server-side.

The initial Google reader returns bounded pages; summaries must follow continuation cursors across the requested interval and disclose incomplete coverage. A Calendar read is not a booking receipt. Missing-event follow-ups stay with their conversation and target the event's title and local date/time instead of listing an unrelated agenda.

Prior verification on the development checkout reported 166 affected backend tests passing, a correct Calendar review through the local model, and a 27-message summary across two fixture pages. No new tests or builds were run while assembling the isolated publication branch. Live writes and packaged desktop behavior remain unverified.
