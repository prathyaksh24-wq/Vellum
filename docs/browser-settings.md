# Browser settings and profiles

Open Settings → Browser, or Browser menu → Browser settings. Named profiles
have separate Brave user-data directories, cookies, history and activity. The
original Personal profile keeps `data/browser-session/profile`, preserving
existing sign-ins. New profiles use `data/browser-session/profiles/<id>/profile`.
One profile runs at a time; switching closes the previous session. Creating a
profile, viewing Settings and changing preferences never start Brave. The panel
still stays hidden on startup until a sidebar or chat request opens it.
Reopening a closed browser shows a single homepage tab while retaining cookies
and history. A new delegated browser task takes control back after manual
browsing; an explicit browser Pause still requires Resume.

The Browser section provides profile creation, renaming, selection, opening,
closing and confirmed deletion; recent session/page/download activity; a bounded
view of the latest 500 history entries; persistent download history; and selective
history, cookies/site-data, cache and download-history clearing. Clearing data
closes that profile first. Removing download history preserves saved files.

General preferences cover the five search engines, SearXNG instance URL, search
suggestions, full URL display, web/local link destinations, history reads and
BrowserAgent's screenshot tool. Link destinations apply to HTTP(S) links in
Vellum's UI; in the web build, Default browser opens in the hosting browser.
Preferences can be exported/imported as `vellum-browser-preferences-v1` JSON.
Profiles, sign-ins, history and download paths are excluded from the export.

Routine browser interactions default to **Follow my request**. The BrowserAgent
may click, type and press keys as part of its requested task without stopping for
each interaction. **Ask for each action** restores the previous behavior. The
server retains ownership, current snapshot, mutation-enable and site-policy
checks. Routine actions validate the retained target rather than rejecting
unrelated document changes. Obvious credential, upload, account and transaction controls still
require confirmation, supplementing the planner's manual-takeover instructions.
This is not a complete transaction classifier for every website.

The **Cursor** tab provides Classic, Light, Ember, Mint and Pixel pointers,
four sizes, and a local PNG upload (up to 128 × 128 pixels and 64 KB) with an
adjustable click point. The selected pointer is visible during agent actions
and, for custom styles, manual movement over the browser page. It does not
replace the Windows cursor. Custom Cursor's website is linked as a reference;
its collection installer and extension are not integrated. Uploaded image data
stays in the existing local browser preferences; cursor images are excluded from
the preferences export.

Site access controls the agent's default browsing/download policies and exact
origin exceptions. An Ask browsing approval is bound to the active session and
page revision and grants that origin for the session. Clicks, typing and account
actions retain their existing confirmation and takeover rules. Blocking history
also prevents the existing background YouTube history reader from opening a
profile. Disabling BrowserAgent leaves manual browsing available.

Website permissions cover location, camera, microphone, notifications,
JavaScript, images, pop-ups and third-party cookies. They are written to the
owned profile's Chromium preferences while it is closed and take effect when
explicitly reopened. Third-party cookie policy applies to the whole profile;
the other categories support exact-site exceptions. Brave protections and OS
device permissions can impose additional restrictions. Device requests that
cannot be answered in the streamed preview can be configured as explicit site
permissions. Optional expiry resets unused per-site device grants after 90 days,
checked when that profile opens.

Download locations accept absolute local folders. Ask where to save holds a
download for review in History & downloads, where the user enters a folder and
confirms saving. Transfers may already be staged by Brave before approval; files
are published to the chosen location only after approval. Each download has its
own subfolder to avoid filename collisions. Pending transfers become failed when
the session closes and must be started again. The current web build has no native
Save As dialog. WebMCP and screenshot annotations are not integrated; the UI
labels website tools unavailable and does not claim annotation support.

Preferences remain in the existing `data/browser-session/preferences.json`.
Activity and download metadata live in `activity.json` under the selected profile
root. These are private local runtime data and must not be committed. Browser
mutations use `browser.settings.manage` or the confirmation-bound
`browser.settings.data` App Action; Settings reads use `/api/browser/settings`.
