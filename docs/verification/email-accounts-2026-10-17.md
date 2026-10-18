# Email signup, account controls and guest access

## Implemented behavior

- Sign up uses email, password and matching password confirmation. It calls
  hosted Supabase Auth and waits for email ownership confirmation before saving
  an identity. Sign in accepts email/password or the existing Google/GitHub flow.
- The same verified hosted user ID identifies an email account across
  installations configured for the same project. Conversations and memory remain
  local; this does not introduce data sync or authentication of the local API.
- Signed-in menus, Accounts settings and the signed-in Add account dialog do not
  show signup. The profile account picker has one Add account action. Guests can
  reach signup through that existing action.
- Continue as guest replaces Continue on this device and is visible above the
  form at a 320px viewport. It opens the workspace without account creation.

## Verification performed

- Backend account and capability checks: **28 passed**. Hosted responses were
  mocked. Tests cover PKCE confirmation and replay, stable identity across two
  independent local stores, wrong/unconfirmed passwords, rate limits, invalid
  configuration, pending signup cancellation on logout, and validation/password
  redaction. Existing Google/GitHub account tests remain included.
- Full frontend suite: **453 passed** across 46 files, using two workers outside
  the sandbox so loopback routing checks could run. Account tests exercise form
  submission, confirmation mismatch, verification before entry, password clearing,
  failure/retry, signup visibility, account management and guest access.
- Production Vite build passed with the existing classic-script warnings.
- Impeccable scan returned no findings on the changed account component and CSS.
- `git diff --check` passed, with existing CRLF conversion warnings.
- Headless Edge exercised production HTML at 1440×960, 390×844 and 320×640 with
  fixture account/API/email-confirmation responses. It verified email signup,
  confirmation return, hidden signed-in signup, the single profile Add account
  action, email sign-in error/retry, and guest entry without another signup.
  There were no page errors or horizontal overflow. Dialog keyboard focus and
  guest-button viewport visibility were checked. Captures and the fixture report
  are in [`email-accounts-2026-10-17/`](email-accounts-2026-10-17/).

The Settings step did not open in the combined repeated-viewport scenario. A
separate fresh browser context received an applied Settings presentation receipt,
opened Accounts settings, confirmed the absence of signup/Add account buttons,
and captured desktop/mobile layouts. No change to the existing presentation or
adaptive-layout runtime was made.

## Live configuration evidence and limits

The user saved Supabase project configuration and the email confirmation redirect
allowlist. A read-only request to the configured project's `/auth/v1/settings`
returned HTTP 200 with email enabled and confirmation required. After restarting
the local API, account status reported email, Google and GitHub available.
No keys, passwords or real saved account details were printed.

No real email/password account was created, no verification email was sent, and
no real email-confirmation link was exercised. Those remain user-browser checks.
Public signup requires custom SMTP because Supabase's default sender is limited
to project-team recipients and testing quotas. Password recovery and hosted
account deletion UI are not part of this change. Native desktop focus was not
physically tested.

## Primary references

- [Supabase password-based authentication](https://supabase.com/docs/guides/auth/passwords)
- [Supabase Auth REST schema](https://github.com/supabase/auth/blob/master/openapi.yaml)
- [Supabase redirect URL configuration](https://supabase.com/docs/guides/auth/redirect-urls)
- [Supabase SMTP restrictions and setup](https://supabase.com/docs/guides/auth/auth-smtp)

## Draft PR publication on 2026-10-18

The account changes were isolated onto the current main branch for publication.
No tests or builds were run during this publication, at the user's request.
The results above describe the earlier development checkout; they are not a
validation of the isolated PR branch. Custom SMTP remains unconfigured and
public email signup delivery is deferred.
