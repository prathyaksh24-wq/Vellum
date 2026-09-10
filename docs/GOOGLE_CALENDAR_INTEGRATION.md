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

The plugin detail view uses `/api/plugins/google-calendar/*` for status, OAuth,
calendar lists, event lists, free/busy checks, and confirmed event changes. The
frontend can change its layout without changing those endpoints. Backend changes
must preserve the capability contract or introduce a new contract version.
