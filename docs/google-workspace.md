# Google connection bundle

Vellum's Google detail page offers one chooser for Google Drive, Gmail, Google
Calendar and Google Contacts. The same component appears in each service's
details in the directory and Settings. Its marks are shipped locally and its
status comes from the shared connection service. Calendar keeps its existing
event workspace; account management happens in the shared chooser.

The first chooser selects all four services as a draft. Nothing is enabled until
the user saves the selection and, when needed, grants Google access. Subsequent
visits preserve the selected services. Change account deliberately repeats the
Google account chooser. Vellum's application identity and its Google service
account remain separate; the UI shows the actual connected Google account.

Install selected plugins starts OAuth immediately. In a browser it navigates
this tab to the validated Google authorization endpoint; the loopback callback
returns to Vellum. In Electron the same App Action asks the backend to open the
default browser, following the existing account sign-in pattern. A failed browser
launch retains the pending flow and an explicit Continue to Google retry link.

## Owners and authorization

`PluginRegistry` owns service enablement, including atomic bundle selection.
Gmail, Drive and Contacts default off. Each read checks both the Google bundle
and service switches on the server. Native manifests override imported bundles
with the same ID, including their skill roots; no imported files are deleted.

`GoogleWorkspaceService` reuses Google Calendar's existing `GoogleCalendarAuthStore`
and OS keyring entry. There is no second token database or `.env` token writer.
The flow uses S256 PKCE, a one-use state with a ten-minute expiry, and a loopback
callback. Failed consent preserves the previous connection. The callback checks
the returned scopes individually and enables only selected services with the
required permissions. It verifies the account with Google's userinfo endpoint,
then returns HTTP 303 to the validated local Vellum page. The page resumes flow
polling and refreshes the canonical plugin catalog. Refresh credentials remain
in the existing keyring owner. Changing accounts requires a new refresh grant;
the previous account's refresh token is never silently reused.

Status/read endpoints require a loopback client, an approved local UI Origin
and `X-Vellum-Google: 1`; responses are uncached. Connection configuration is a
UI-only `google.connection.configure` App Action. Google consent grants the
access. `google.connection.disconnect` uses operation-bound confirmation.

Switching a service off blocks Vellum calls but retains Google's grant. A local
disconnect clears the shared credential and switches all four services off.
Disconnecting only Calendar preserves the shared grant for other services.
Revoke provider access through [Google account connections](https://myaccount.google.com/connections).
Local disconnect does not revoke the whole Google Cloud project, which could
also affect other existing Google integrations.

## Configuration

Vellum developers configure the Google Cloud project, consent screen, enabled
APIs, OAuth desktop client and applicable scope verification. Users sign in and
approve access; ordinary users do not create their own Cloud project.

`GOOGLE_WORKSPACE_OAUTH_CLIENT_ID` and optional
`GOOGLE_WORKSPACE_OAUTH_CLIENT_SECRET` configure the bundle. Existing Calendar
credentials remain the compatibility default, followed by the existing YouTube
OAuth client configuration. Tokens are not stored in these settings. A desktop
client cannot keep a client secret confidential; PKCE is required.

The loopback callback uses the existing backend on port 8000. Return URLs are
restricted to Vellum's supported local frontend addresses. A public rollout
still needs Google's applicable verification and enabled APIs. See
[Google desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app).

OAuth permission and API enablement are separate. Enable Google Drive API,
Gmail API, People API (Contacts), and Google Calendar API in the same Cloud
project as the OAuth client. A `SERVICE_DISABLED` response is a project
configuration problem; enabling the corresponding API does not require another
sign-in. The connector reports this explicitly without exposing Google's raw
error body. Existing Cloud consent-screen branding may still say Vellum Calendar.

## Agent tools and permissions

The main agent receives the compact `google_workspace_read` tool directly. It
understands mail/email/inbox, Drive files, upcoming Calendar events and Contacts;
ordinary reads do not depend on a specialist or a successful discovery phrase.
An unspecified Drive list is ordered by modification time. The main-agent Gmail
search returns the requested page of decoded messages with From/To/Subject/Date
headers (20 by default, up to 50 per page), without a three-message cap. Fetches run concurrently within the shared account lock.
Text is bounded to 1,500 characters per message; attachments and base64 payloads
stay out of the model context. HTML fallback strips markup, scripts and styles.
`period=today` uses local-midnight epoch boundaries in the configured user timezone.
`period=last_24_hours` uses a rolling 24-hour interval, distinct from today.
A returned `continuation` contains the exact query, cursor and page size; callers
copy it with an empty period so the original interval cannot drift between pages.
Time-range summaries must continue until the cursor is absent, or state that
coverage is incomplete. Individual message failures also mark the page partial.
Thread reads no longer silently drop messages after the third.
Pagination tokens and truncation are explicit. The published Gmail API tools and
guarded fixed-read endpoint retain their original response shapes.

Current Google permission flags are supplied as runtime capability evidence;
older assistant claims denying access cannot establish current availability.
Linear method schemas use deferred discovery alongside other service methods.
The initial visible core does not include unrelated service schemas. Tool rows
reuse their provider's bundled logo and the shared fallback for missing logos.

The four published API snapshots currently contain 205 methods. Each becomes a
native ToolRegistry capability with its own name and parameters. All of those
method schemas are deferred through the existing tool-search bridge. At most
two Google schemas per source are promoted at a time. Nested schema presentation
is bounded; `google_api_describe` retrieves the complete published method schema
on demand. Server validation always uses that full schema. Neither chat nor
provider data may supply a URL, HTTP verb or authentication header.

Routine Gmail method tools have smaller everyday input views: recipient,
subject and text for drafts/sends; message ID for trash/delete; label changes
for marking read/unread. These are the same native method identities, not
duplicate connectors. Advanced parameters and MIME/media inputs remain
available through the full published description and compatibility bridge.
The main agent does not preload these routines for unrelated services.

This follows the documented progressive-loading pattern in
[OpenAI tool search](https://developers.openai.com/api/docs/guides/tools-tool-search)
and [Claude tool search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool).
Those references establish the public API pattern, not the private implementation
of every Codex or Claude Gmail connector. Vellum implements client-side discovery
for its provider-neutral runtime; local models do not require a provider-specific
hosted tool-search API.

The shared specialist runner uses the same canonical tool search, describe and
call bridge, plus scoped memory and skill helpers. Its catalog contains only
profile-approved read capabilities. Stable function-safe aliases preserve each
underlying capability's identity and authorization. At most two discovered
provider schemas are promoted together. Exact changes retain the existing
action handler and confirmation controls. Legacy read/schema helpers remain
executable for compatibility but are not preloaded. Native model prompts do not
duplicate the tool schemas in their instruction text.

| Service | Methods | Broader consent | Examples |
| --- | --- | --- | --- |
| Gmail v1 | 79 | Full mail; Gmail basic/sharing settings | Messages, threads, labels, drafts, send, modify, trash, delete, attachments and settings |
| Drive v3 | 64 | `drive` | Files, folders, metadata/content edits, sharing, comments, permissions, uploads and downloads |
| Calendar v3 | 38 | `calendar`, alongside existing scopes | Events, calendars, calendar lists, ACLs, settings and channels |
| People v1 | 24 | `contacts` | Contact/group create, update, delete, search and reads |

Existing read grants remain usable. The UI's **Enable changes** control prepares
a separate Google consent with broader scopes for selected services. An OAuth
grant alone never substitutes for operation-bound confirmation. Administrator,
domain-wide delegation, account type, API enablement, quotas and the exact scope
alternatives published for each method still apply. For example, directory and
some Gmail sharing/delegation methods are not ordinary consumer-account features.
Listing a method does not mean this account is authorized to execute it.

`google.api.execute` stages every non-GET operation through the canonical App
Action runtime. Its readable review is bound to the current account, OAuth
client, credential digest, scope set, schema and exact inputs. Account or input
changes invalidate it. Only user confirmation executes the write; the model has
no confirm argument or confirmation tool. Provider failures are not replayed.
Gmail drafts/sends accept structured recipient, subject and text fields, which
Vellum encodes as MIME and decodes back into the actual review. Drive plain text
uploads accept `text_content`; other uploads accept base64 media. Uploads are
bounded to 8 MiB and media reads to 2 MiB; large/resumable transfers are not
implemented by this tool. Native Docs/Sheets document editing needs their own
APIs and is not implied by Drive metadata/content operations.

The source snapshots and revisions live under
`backend/agent/plugins/google_discovery/`. Refresh them deliberately with
`scripts/update-google-api-catalog.py`, review the resulting method/schema diff,
and run the schema/authorization tests. This uses Google's public, credential-free
Discovery service; chat does not download catalogs. Metadata and inline
descriptions are attributed to their `discovery_source` Google URLs. See
[Discovery format](https://developers.google.com/discovery/v1/using) and
[client construction](https://developers.google.com/discovery/v1/building-a-client-library).

## Assets

The existing Gmail and Calendar marks are reused. Added marks are downloaded
from Google's own static asset host and bundled under `assets/plugins/`:

- [Google mark](https://www.gstatic.com/images/branding/product/1x/googleg_48dp.png)
- [Drive mark](https://www.gstatic.com/images/branding/product/1x/drive_2020q4_48dp.png)
- [Contacts mark](https://www.gstatic.com/images/branding/product/1x/contacts_2022_48dp.png)


### Google read and write recovery

Calendar reads accept timezone-aware `time_min` / `time_max` bounds or
`period=today`. Missing-booking follow-ups remain with the main conversation,
which must check a real receipt and the specific event title/date/time; they do
not trigger the Calendar specialist's general agenda listing. Calendar reads
cannot establish that a new event was booked. First-person completion claims
after Google reads are checked against this turn's authoritative action receipts,
and read-only provider text is buffered before the final stream is emitted.
This check is a targeted guard against unsupported completion claims, not a
complete semantic verifier of arbitrary model prose.

Drive's literal `name:filename` shorthand is safely escaped into a Drive name
query. A known Google method mistakenly supplied as an App Action ID returns
the exact published tool name and schema, without executing it. Incorrect Google
operation shapes return field guidance without echoing request values.

The main graph stops a repeated identical failed call or three identical Google
Workspace reads with identical results in one user turn. New page tokens,
corrected arguments and subsequent user turns remain allowed. The stop message
is preserved in chat streaming, and the overall graph limit is reported as a
tool-step limit rather than a network outage. Write confirmations remain bound
to the exact account and request, and a confirmation can execute only once.
