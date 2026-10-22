# Accounts and guest access

Vellum's first-launch **Sign up** screen creates an account with an email,
password and matching confirmation. **Sign in** offers email/password as well as
Google and GitHub. **Continue as guest** opens the local workspace without an
account. It remains visible near the top of the welcome screen on small devices.
Email registration/sign-in use hosted Supabase Auth so the same account works
across installations configured for the same project. SSO is not offered.

The profile account picker contains the single **Add account** action. The
signed-in UI does not show Sign up, including the Add account dialog. Guests can
reach registration from that dialog. Settings → Accounts lists saved identities,
switches the active identity, and offers **Remove account** and **Log out**.
Up to 12 identities can be saved.
The active identity appears first under **Signed in as**. Other identities are
listed separately under **Saved on this device**, with an explicit Saved label.
Guest access never labels a saved account as active. Connected services may use
a different account from the active Vellum identity.
Accounts are identified by provider plus the provider's stable subject ID;
matching email addresses never merge Google and GitHub identities.

## Local data and identity

Accounts identify the person shown in the interface. They share the existing
installation's workspace. Switching identities does not partition conversations,
memory, connected services, settings, or the vault; it does not create cloud
sync, paid entitlements, or a multi-tenant local API security boundary.
The interface states this before sign-in and in Accounts settings.

Identity metadata (provider ID, display name, username and verified email when
available) lives in the operating system credential store under
`vellum.accounts` / `identities-v1`. It is restored locally, including offline;
the UI is not asserting a continuously validated provider session. Provider
revocation does not automatically remove the cached identity. An unavailable or
corrupt store never silently falls back to plaintext or overwrites the record.
Provider access tokens are used only during verification and are not persisted,
returned to the frontend, or shared with agents. No refresh token is requested.
Email passwords are sent only to the configured Supabase project's HTTPS Auth
API. The service manages password storage and verifies email ownership. Neither
passwords nor Supabase access/refresh tokens are stored in Vellum's local account
record. Email account IDs include the project URL and verified hosted user ID;
matching addresses do not silently link email accounts to Google/GitHub identities.

Log out clears the active identity, cancels pending sign-ins, and persists a
logged-out flag in the existing credential-store record. It returns to the
sign-in screen even if a browser has an old local-continuation preference.
Saved identities remain available after signing in again or explicitly choosing
local use; the welcome screen never selects them as a shortcut around logout.
Remove account forgets one saved identity. Neither action deletes local workspace
data, revokes the provider's OAuth grant, or signs the browser out of Google/GitHub.
Explicitly choosing Continue as guest clears the logged-out flag when the
backend is available; local use remains available offline.

## Provider setup before shipping

Configure the **Vellum publisher's** registrations once for a release; ordinary
users should not need to create developer apps or supply credentials. An
unconfigured installation displays the unavailable reason and still allows
local use. Do not enable a provider in the UI independently of backend readiness.

The backend's existing settings loader reads these environment variables or
their values from the untracked repository `.env` file:

```dotenv
VELLUM_ACCOUNT_GOOGLE_CLIENT_ID=
VELLUM_ACCOUNT_GOOGLE_CLIENT_SECRET=
VELLUM_ACCOUNT_GITHUB_CLIENT_ID=
VELLUM_ACCOUNT_GITHUB_CLIENT_SECRET=
VELLUM_ACCOUNT_SUPABASE_URL=
VELLUM_ACCOUNT_SUPABASE_PUBLISHABLE_KEY=
```

- **Google:** create a Google OAuth client of type **Desktop app**, configure
  the app's consent branding/audience, and supply the issued client ID and desktop
  client secret. During testing, add permitted test users; complete Google's
  production publication requirements before broad distribution. Desktop client
  secrets are not confidential server credentials. Vellum uses the system
  browser, authorization code plus S256 PKCE, a one-use random state, and
  `http://127.0.0.1:8000/api/accounts/callback/google`. Keep the local API on port
  8000 for this flow. Only `openid email profile` is requested. The access token
  retrieves identity from Google's fixed HTTPS userinfo endpoint; a verified
  email and stable `sub` are required. ID token contents are not decoded or
  trusted. Calendar and YouTube OAuth registrations remain separate.
- **GitHub:** register an OAuth app with Authorization callback URL
  `http://127.0.0.1:8000/api/accounts/callback/github`. Supply the client ID and
  client secret to enable browser authorization-code flow with S256 PKCE and
  one-use state. Keep **Expire user access tokens** enabled: tokens are only used
  immediately for identity verification. This local desktop installation cannot
  keep a distributed OAuth client secret confidential; PKCE binds the code to
  the originating flow. Scopes remain `read:user user:email`, with no repository
  access. `/user` validates the provider ID; `/user/emails` supplies a verified
  primary email when available, otherwise the GitHub username is shown.
  Existing client-ID-only installations retain device flow, which requires
  **Enable Device Flow** and has no provider callback/automatic browser redirect.
- **Email/password:** create a Supabase project, enable email authentication and
  keep email confirmation enabled. Set its HTTPS project URL and publishable key
  (a legacy `anon` key is also accepted). Secret/service-role keys are rejected.
  Under Authentication → URL Configuration, allow
  `http://127.0.0.1:8000/api/accounts/callback/email**` for the confirmation
  callback and its random state query. Signup uses S256 PKCE. Only a confirmed
  user fetched from `/auth/v1/user` can become a saved Vellum identity. The email
  confirmation callback exchanges its code on the backend and returns to the
  originating local UI without exposing tokens. If the original app has closed
  or restarted, confirm the email and then sign in with email/password again.
  Configure custom SMTP before opening signup to the public: Supabase's default
  sender is restricted to project-team addresses and testing quotas. Password
  recovery and hosted account deletion UI are outside this change.

For browser use, account authorization opens in the current tab. Successful
Google/GitHub and email confirmation callbacks issue HTTP 303 to the originating Vellum page and never
copy provider codes or tokens into that URL. Desktop-shell sign-in continues to
use the system browser; the existing native window command focuses Vellum when
the frontend observes completion. Native focus must be smoke-tested separately.

Restart the local API after configuring these values. Credentials and real
account authorizations are not supplied by this source change. This is the
existing single-process local API, not a hosted authentication service; pending
flows intentionally expire across API restarts. Keep API access logs private:
provider redirects can contain short-lived authorization codes.

## Transport and verification

`agent.accounts.AccountService` owns all saved identity state and OAuth flows.
`agent.account_api` publishes typed contracts under `/api/accounts`; the served
frontend uses only `api/accounts.js`. `/api/capabilities` declares this surface.

Account endpoints, including email credential submissions, require a loopback client/Host, an exact trusted local UI
Origin and `X-Vellum-Accounts: 1`. They return `Cache-Control: no-store`.
All account callbacks instead require a pending, unexpired, single-use
state bound to that provider. Return URLs are captured before leaving Vellum and
allow only the local UI origins on ports 5173/4242 and known entry paths. Callback
query parameters cannot choose the destination. Responses use no-store and
no-referrer headers. Failure pages offer a safe return link without provider text.
Device codes and PKCE verifiers remain backend-only, are bounded in memory and
cleared on completion/cancellation/expiry. Logout, removal and selection cancel pending
flows so a stale authorization cannot unexpectedly replace the chosen identity.

The interactive account protocol is deliberately outside the model tool catalog.
Generic App Action parity for its mutations is recorded as a named deferral in
the served-control inventory, rather than misclassified as presentation only.
Welcome mode, input focus, account disclosure and the add-account dialog are
temporary presentation; the existing device settings action still owns local
display-name editing. A provider profile opens Accounts settings rather than
pretending to change the provider's identity.

Primary provider references: [Google desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
[Google identity endpoints](https://developers.google.com/identity/openid-connect/openid-connect),
[GitHub authorization and device flow](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps).
[Supabase email/password authentication](https://supabase.com/docs/guides/auth/passwords),
[Supabase SMTP delivery requirements](https://supabase.com/docs/guides/auth/auth-smtp).

Focused tests cover state/PKCE, callback replay, denial, expiration, credential
store failures, device polling/backoff, identity collisions, account lifecycle,
HTTP origin/Host/client guards, first-launch local access, and mounted UI states.
Mock-provider checks do not prove live provider registrations, consent approval,
real-email sign-in, or packaged Tauri behavior.
