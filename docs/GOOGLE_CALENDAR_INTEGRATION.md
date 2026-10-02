# Google Calendar Integration

Vellum owns Google Calendar as the portable `google-calendar` connector. The
connector uses Google's Calendar REST API through Vellum's shared capability
registry and CalendarAgent profile. It does not depend on a separate Google
Calendar MCP server.

## Configuration

For a dedicated Calendar OAuth client, set:

```env
GOOGLE_CALENDAR_OAUTH_CLIENT_ID=
GOOGLE_CALENDAR_OAUTH_CLIENT_SECRET=
```

When these values are empty, Calendar reuses `YOUTUBE_OAUTH_CLIENT_ID` and
`YOUTUBE_OAUTH_CLIENT_SECRET`. This lets one Google desktop OAuth client own the
consent screen while Calendar and YouTube keep separate local token records.
Tokens are stored in the operating-system keyring under
`vellum.google-calendar`; token values are not written to repository files.

The desktop callback is `http://127.0.0.1:8000`. Vellum must be running on port
8000 while the connection is completed.

## OAuth Scopes

The connector requests:

- `https://www.googleapis.com/auth/calendar.events`
- `https://www.googleapis.com/auth/calendar.calendarlist.readonly`
- `https://www.googleapis.com/auth/calendar.settings.readonly`

The first scope reads and changes events. The other two read the calendar list
and account time zone. Vellum does not request the full Calendar scope.

If the Google OAuth app remains in Testing, Google may require the account to
authorize again after the refresh token expires. Publishing the OAuth app also
requires the public home page and privacy policy URLs Google asks for. These can
be added later; localhost testing does not require Vellum to pretend those URLs
already exist.

## Runtime Boundaries

- CalendarAgent reads calendars, events, and free/busy data through ToolRegistry.
- Create, update, and delete are external writes. Each requires an explicit
  confirmation before the Google request is sent.
- The main model receives a bounded CalendarAgent result, not raw calendar event
  payloads or local token metadata.
- Calendar events are not automatically treated as user beliefs, memories, or
  Knowledge Core facts.
- Disconnect removes only Vellum's local Calendar tokens. It does not revoke the
  shared Google OAuth grant, because revocation could affect another Vellum
  integration using the same OAuth client.

## Frontend Contract

The Plugins page shows Google Calendar as Connected, Not connected, or Disabled.
Connect opens the existing Google OAuth flow and polls account status, updating
the page automatically after consent. Disable uses `plugin.state.set`, prevents
CalendarAgent and connector reads/writes, and preserves the saved keyring
connection. Re-enabling restores access. Disconnect removes the local tokens.

The frontend uses the existing API adapters for status, calendar lists, event
search, and `calendar.availability`. The default All calendars view merges
visible calendars, includes their source labels and IDs, and disables event
changes for calendars with read-only access. A specific calendar can also be
selected. Event search and Upcoming events cover the
next seven days in the plugin view. CalendarAgent can handle natural requests
for other dates. Calendar changes and connection controls dispatch these plugin
contributions through AppActionRuntime:

- `calendar.connection.start` (Google consent)
- `calendar.connection.disconnect` (operation-bound confirmation)
- `calendar.event.create`, `calendar.event.update`, `calendar.event.delete`
  (operation-bound confirmation)

The typed `/api/plugins/google-calendar/*` endpoints remain compatible. Both
surfaces use the same CalendarCapabilityService and connector/token store.

## Scheduling Conflicts

Before creating or moving an event, availability checks busy events across the
visible connected calendars, including synced F1 events. Cancelled, transparent, and self-declined events are ignored;
all-day busy events are included. Updates exclude only the event being moved.
The service checks again immediately before sending a write to Google.

An overlap returns a proposed slot of the same duration, searched in 15-minute
steps between 9 AM and 6 PM in the requested/calendar time zone for the next
seven days. The frontend asks whether that time works and requires confirmation
before writing. Chat also waits for confirmation. A late collision returns a
new proposal instead of silently changing the event time. If no slot is found
or the bounded event inventory is too large, the user must choose another time.
This checks visible connected calendars, not attendee calendars. Google does not offer an atomic check-and-book operation,
so another client could still write between the final check and event creation.

## Contextual Deletion

CalendarAgent stores a bounded event reference packet in the existing local
MasterThreadStateStore, scoped to the chat and specialist. It contains real
calendar/event IDs, titles, times, and access roles; it does not copy a whole
conversation or write Calendar content into Knowledge Core. Deleting the chat
clears its specialist references and pending authorization. "Delete that"
resolves a unique event from the last read or completed mutation. Multiple
possible targets require clarification. Calendar reads search all visible
calendars by default; explicit calendar names narrow the search.

One confirmation is bound to the exact target. "Yes delete it" completes that
pending deletion. Failed Calendar actions retain the exact pending target so
an explicit retry can reuse its authorization for five minutes. A different
target requires a new preview/confirmation, and cancellation clears the pending
action. No background retries or blanket deletion permission are granted.
