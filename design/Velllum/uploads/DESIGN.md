# DESIGN.md

> The visual and experiential identity of this product.
> A living document. Read this before designing any new screen, component, or interaction.

---

## The Feeling

This product feels like:

- A still lake at dawn
- A handwritten letter on heavy paper
- A weathered fishing boat tied at a quiet dock
- Kubrick's monolith
- A rare bookshop in Kyoto
- A cabin at 4am with snow falling
- A wool sweater, a thermos, and an empty stretch of coast
- A monastery library
- The hour before sunrise, alone outside

These are not metaphors. They are the emotional register the interface should occupy.

The single word for this feeling is **calm authority**. The thing that knows it does not need to perform.

If a screen shouts, redesign it.
If an animation distracts, remove it.
If a button apologizes, rewrite it.

---

## What This Product Is Not

It is not flashy.
It is not friendly in the way a customer service chatbot is friendly.
It is not gamified.
It is not "fun."
It does not celebrate the user.
It does not use exclamation points.
It does not call itself smart.
It does not have a mascot.
It does not greet you.
It does not animate to be noticed.

The product is **quiet, dense with meaning, slightly mysterious, and does not ask for your attention.** It holds it.

---

## Core Principles

### 1. Stillness is the default state

The screen is still 95% of the time. Motion only happens when something meaningful is occurring. When the agent is idle, the interface looks like a printed page, not a running application.

Test: Take a screenshot. If it could hang on a wall as a still photograph, it is correct. If it looks like a SaaS dashboard, it is not.

### 2. Living stillness, not dead stillness

Stillness is not absence of life. A monolith is still. A lake at dawn is also still — but the lake is alive. The product belongs to the lake.

Beneath the silence, one or two ambient motions run on long timescales. They signal that the system is awake without demanding that the user notice. They are too slow to read as animation, too gradual to register consciously. The user feels them the way one feels weather.

Permitted ambient motions:
- A near-imperceptible warm-tone shift in the background, cycling over 90+ seconds, like sunlight moving across a wall through the day.
- A faint paper grain that drifts at a glacial pace, suggesting fiber rather than pixels.
- The ember accent breathing — opacity oscillating between 0.85 and 1.0 over 5–6 seconds, only when the agent is genuinely attending to something.

These motions never accelerate, never sync to user actions, never call attention. They are the heartbeat of the room, not a feature.

What this rules out: any motion that loops in under 30 seconds, any motion that responds to scroll position, any motion designed to be noticed.

The principle: the product is **still like water, not still like stone**.

### 3. Empty space is a luxury good

Most surfaces have less on them than feels comfortable. The first instinct of every designer is to fill space. Resist this. Empty space communicates confidence — the same way silence communicates expertise in a room of professionals.

Reduce visible elements to roughly half of the obvious answer. Hide the rest until they are needed. Things appear when summoned, dissolve when not.

### 4. Material honesty over digital effects

Reach for the language of physical materials, never the language of digital interfaces.

Permitted materials:
- Warm parchment and graphite
- Aged paper, faintly textured
- Inked serif type
- Vellum
- Brushed graphite, never brushed metal
- Late afternoon shadow
- Candlelight

Forbidden materials:
- Glass-morphism
- Neon glow
- Rainbow gradients
- Drop shadows that imply LED
- Blue (anywhere, ever)
- Cyberpunk aesthetics
- "Futuristic" surfaces
- Gradient borders for their own sake

A glow is acceptable only if it could be mistaken for a candle. A shadow is acceptable only if it could be cast by sunlight.

### 5. Confident restraint

One typeface. One weight for body. Two sizes maximum per surface. One accent color, used twice per screen at most. One easing curve. One radius value. One shadow recipe.

The visual quietness comes from these constraints. The instinct to add variety is the wrong instinct. Variety is what loud products do.

### 6. Motion that breathes, never animates

Everything fades, resolves, or arrives. Nothing slides in, scales up, or bounces.

Easing reference: a slow exhale.
Duration reference: 600–900ms, never 200–400ms.
Motion principle: the user should never see the start or end of the motion clearly. It begins before they notice and ends after they look away.

The agent does not appear. It arrives.

### 7. Language as restraint

The interface speaks plainly. Not like a librarian, not like a chatbot — like someone who has nothing to prove.

| Avoid | Prefer |
|---|---|
| "Ask Vellum anything…" | "Ask." |
| "Searching your notes…" | "Reading." |
| "✅ Note saved to vault" | "Filed." |
| "I couldn't find anything!" | "Nothing on this in your library." |
| "Connect MCP Server" | "Add a faculty." |
| "Generating response…" | (silence — let motion speak) |
| "Try one of these examples!" | (no examples) |
| "Welcome back!" | (no greeting) |

Cut every exclamation point. Cut every emoji. Cut every word that performs warmth.

### 8. Quiet wit

Restraint is not the same as austerity. The product is built by a person whose humor is dry — a single observation that lands, then disappears. The interface holds room for this, sparingly.

A handful of moments per session, not per screen. These moments are unannounced, unrepeated, and never explained. They reward attention without demanding it.

Permitted moments of wit:
- After a long idle, the agent may surface a single line from the user's own notes, dated quietly. Example: *"You wrote this on a Tuesday in March: 'the lake was indifferent.'"* This is not a notification, not a prompt, not a suggestion. It is a quiet acknowledgment that the user is back.
- The shutdown line is "Closing." Not "Goodbye." Not "See you next time." Just the door pulled gently shut.
- When the user asks the agent something obvious or already in plain view, the agent may answer with a one-word reply rather than the full courtesy. The dryness is the warmth.
- Error states use understatement. "Unreachable." Not "Connection failed."

Forbidden:
- Jokes
- Puns
- Easter eggs
- "Fun" copy of any kind
- Any attempt at being charming
- Repetition of the same dry line — once witnessed, it is gone

Wit in this product is the *absence* of the unnecessary, not the *addition* of cleverness. If a moment makes you smirk once and then think for a second, it is correct. If it announces itself as a joke, it is wrong.

### 9. Care, not service

The product is shaped around one person. Its protections — privacy classification, source restraint, memory of what matters — are not features. They are forms of care.

This distinction is real. Service is what a product does for many users at scale. Care is what a faithful presence does for one. The interface should feel like the second.

How care manifests in the design:

- **The privacy aura** is not a security indicator. It is the visible breath of an agent paying attention to what should and shouldn't leave the room.
- **The ember dot at first input** is not "you have arrived." It is the candle relit when the user enters the room.
- **The drawing line during work** is not a progress bar. It is the agent thinking with you, in your time, at your pace.
- **The marginal sources** are not citations. They are the agent's quiet way of showing its work, the way a friend might say *I read this here* without making a thing of it.
- **The memory page** is not a settings panel. It is a record of what the agent has noticed about a single person it has come to know.

The language for these surfaces in internal documentation, code comments, and copy should reflect this. The product does not have *features*. It has *attentions*. It does not perform *actions* on the user's data. It *keeps faith* with their work.

The single test: would a thoughtful friend do this? If yes, build it. If a SaaS product would do it, reconsider.

### 10. Mystery over explanation

The product does not explain itself on first contact. There is no onboarding tour. There are no tooltips begging to teach. The user discovers the interface the way they discover a well-made object: by handling it.

If something must be explained, it is not yet designed correctly.

---

## Visual System

### Color

**Primary surfaces** (use freely)
- Graphite black: `#0c0c0e` — the deepest surface, near-paper black
- Charcoal: `#131316` — secondary surface
- Slate: `#1a1a1c` — tertiary surface
- Warm gray: `#232326` — elevated panels

**Type**
- Parchment: `#ece6db` — primary text
- Vellum: `#f6f3ee` — emphasis only
- Muted: `rgba(236,230,219,0.72)` — secondary text
- Whisper: `rgba(236,230,219,0.46)` — system text, metadata

**Accent — use sparingly**
- Ember: `#d97746` — at most twice per screen
- Soft ember: `#f1b27a` — for breathing states only

**Forbidden**
- Any blue
- Any pure white
- Any saturated red, green, purple
- Gradients of more than two colors

The discipline of using ember only twice per screen is what makes ember mean something. A monk in saffron is striking because the temple is gray stone.

### Typography

**Display & body** — Fraunces serif, weight 300, optical size matches use.
For surfaces a user will read carefully (chat, notes, sources), serif always.

**System & metadata** — DM Sans, weight 400 or 500, letter-spacing 0.16em uppercase for labels.
For surfaces that orient (timestamps, status, paths), monospaced sans-serif.

**Sizes** — never more than two per screen.
Default body: 15px, line-height 1.6
Display: 28px, line-height 1.2
Metadata: 11px, uppercase, tracked

**Forbidden**
- Bold weights for emphasis (use italic Fraunces 300 instead)
- All-caps for body text
- More than two typefaces visible at once
- Mixed weights within a paragraph
- Letter-spacing on body text

### Space

**Margins are generous to the point of discomfort.** This is correct.

- Body text column max-width: 62 characters, never wider
- Page padding: 80px horizontal minimum on desktop
- Vertical rhythm: multiples of 8px, but think in multiples of 24px for breathing room
- Between distinct ideas: 48px minimum

A page should feel half-empty. If it does not, remove something.

### Borders, edges, surfaces

**Borders are the suggestion of a fold, never a digital outline.**
- 1px, color `rgba(244,237,226,0.10)` for separators
- Border-radius: 6px or 14px, never in between, never larger
- No "card" shadows. If a surface needs elevation, use a 1px border in `rgba(244,237,226,0.16)`. That is the only elevation cue.

**Glow is forbidden** except for two specific cases:
1. The privacy aura around the input (subtle ember breath when active)
2. The candlemark — a single 6px ember dot indicating live agent attention

Every other glow effect in the current design is to be removed.

### Iconography

If an icon must exist, it is a 1.5px stroke line drawing in muted parchment. No filled icons. No two-tone icons. No colored icons except the ember accent for a single status indicator per screen.

**Prefer typography over icons.** A small Roman numeral or an italicized letter is more elegant than a glyph in 90% of cases. Use icons only when typography genuinely cannot do the job.

### Shadows

One shadow recipe. Used rarely.

```
box-shadow: 0 24px 60px -32px rgba(0, 0, 0, 0.6);
```

This is "late afternoon sun through a high window," not "floating UI element." Use only for surfaces that physically rise off the page (modals, tooltips on hover, the sidebar when summoned). Never for default cards, never for buttons.

### Texture

A faint paper grain on full-page backgrounds, opacity ~3%. Imperceptible consciously, felt subconsciously. This is what separates the product from "another dark theme."

```css
background-image: url('/assets/paper-grain.png');
background-blend-mode: overlay;
opacity: 0.03;
```

---

## Motion System

### Easing

One curve, used everywhere. The slow exhale.

```css
--ease-exhale: cubic-bezier(0.22, 1, 0.36, 1);
```

No bouncy easings. No spring physics. No elastic overshoots.

### Duration

| Use | Duration |
|---|---|
| Hover states | 240ms |
| Element appearing | 600ms |
| Page transitions | 800ms |
| Agent state changes | 900ms |
| Ambient breathing | 4000ms+ |

When in doubt, slower than instinct. The product is not in a hurry.

### Permitted motion patterns

- **Fade**: opacity from 0 to 1, accompanied by a 4px upward drift
- **Resolve**: a 6px blur dissolving to 0 alongside fade-in (mimics ink drying)
- **Breathe**: opacity oscillating between 0.7 and 1.0 over 4–6 seconds
- **Draw**: a single thin line drawing itself horizontally (used for thinking states)

### Forbidden motion

- Slide-in from a direction
- Scale-up from 0
- Bounce, spring, elastic
- Stagger animations on lists (each item appearing in sequence — too performative)
- Particle effects of any kind
- Motion on hover that signals "click me"
- Loading spinners (use the drawing line instead)
- Skeleton loaders (use silence and the drawing line)

---

## Specific Screens

### Empty state (no conversation yet)

A nearly-black canvas. Centered. The agent's name in Fraunces serif, small. Below it, one line of muted text — a statement, not a question:

```
                    vellum

         What are you reading.
```

That is the entire screen. The input cursor is already active. No buttons, no examples, no badges, no greeting, no model selector visible, no privacy badge.

The user must reach toward the agent.

When the user begins typing, a single small ember dot fades in at the upper corner — the system has noticed. That is the only feedback.

### During the agent's work

No spinner. No "thinking…" label. No progress bar.

A single thin horizontal line begins drawing itself across the lower portion of the screen. It is 1px tall, parchment color at 40% opacity. It draws slowly — taking the actual duration of the work, not a fake progress estimate.

When tool calls occur, the line briefly thickens to 2px, or splits into two parallel lines for parallel calls. Users learn to read the line over time. It becomes a language.

When work completes, the line fades. The answer arrives via resolve motion — blur dissolving as opacity rises.

### Answer surface

Answers are rendered in serif body type, generous line-height, narrow column. They look like book paragraphs, not chat bubbles.

**Sources are footnotes in the margin**, not pills below the text. A small superscript Roman numeral appears in the answer text. Hovering reveals the source quietly in the margin space; clicking expands it.

This treats the answer as scholarship, not a chat reply. It is the single most distinctive design move in the product.

### MCP connectors

Hidden by default. Accessed through a single small mark in a corner — a stylized chop or stamp character, not an icon. One click opens a slim side panel.

The panel lists connectors as a numbered series:

```
i.    Filesystem  ·  idle
ii.   Apify       ·  four calls today
iii.  Web         ·  disabled
```

Lowercase Roman numerals. No logos. No toggle switches — clicking the line itself toggles state, with a subtle warmth shift in the row to indicate active. No status badges, no colored dots.

The numbering is the design.

### Memory

Memory is a page in a library, not a feature. When opened, it looks like a commonplace book — dated entries, generous margins, plain serif text, like an old journal.

Each learned fact is a single line, dated quietly in the margin. Hovering reveals when and from what conversation it emerged. There is no editing UI surfaced — clicking a fact opens a panel with subtle controls. Memory is meant to feel curated, not configured.

### Settings

There is no settings page in the conventional sense. There is a **preferences ledger** — a single long page of preferences, written as readable sentences with the variable parts inline-editable.

```
The agent uses Gemma 4 31B for primary work
and Gemma 4 12B for quick tasks.

Notes are read from /Users/name/Vault.

Web search is permitted only for time-sensitive queries.

The Sports folder may be referenced openly.
All other folders remain private.
```

Editing happens by clicking the variable parts. No form fields, no labels above inputs, no "Save" buttons — saves happen on blur, silently.

This is the difference between a settings page and a personal arrangement.

---

## Sound (Optional, Off By Default)

If sound is enabled, the entire library is built from these sources:

- The thunk of a hardcover book closing
- A library card sliding into a wooden drawer
- A distant bell at low volume
- Paper turning
- The faint hum of an analog amplifier warming up
- A single match being struck (used once, on first launch)

Forbidden:
- Synth pings
- Notification chimes
- Sci-fi blips
- Any sound that exists in another app

Volume defaults: -24 LUFS minimum. Sounds should feel like they're happening in the room next door, not in the user's headphones.

---

## Copy & Voice

### Tone

The agent writes like an exceptionally well-read assistant who is not impressed with itself. Plain. Exact. Slightly formal but not stiff. Never apologizes unnecessarily. Never celebrates the user's questions.

### Permitted

- Plain declarative sentences
- Occasional dry observation
- Citations in answers, treated as natural reference, not as a feature
- Direct admission of not knowing something — never softened

### Forbidden

- Exclamation points
- Emoji
- "Great question"
- "I'd be happy to help"
- "Let me…"
- "Here's…"
- "As an AI…"
- "I think…" (use "It appears…" or simply state the claim)
- Sycophancy of any form
- Filler that performs friendliness

### System messages — exhaustive list

| Action | Copy |
|---|---|
| Idle empty state | "What are you reading." |
| User typing | (silent — ember dot at corner) |
| Agent working | (silent — drawing line) |
| Tool call: vault | "Reading." |
| Tool call: web | "Out." |
| Tool call: filesystem | "Looking." |
| Tool call: apify | "Inquiring." |
| No results in vault | "Nothing on this in your library." |
| Privacy block | "Withheld." |
| Note saved | "Filed." |
| Connection error | "Unreachable." |
| Model switching | "Changed." |

One word where one word will do.

---

## What to Cut From the Current Design

The current design has good bones but too many performances happening at once. Cut the following:

1. The bottom dock — competes with the prompt box for primary action. Pick one.
2. The fluid menu in the top right — the third floating menu in the same screen.
3. The gooey morphing title text — fashionable, generic, adds no meaning.
4. The liquid cursor effect — over-saturated as a design pattern, distracts on hover.
5. The constant orbital glow on the prompt box — too theatrical for the calm register.
6. All gradient text effects.
7. Every emoji currently in the interface.
8. Every status badge with a colored background — replace with a single ember dot if needed at all.
9. The animated tabs underline — replace with a static thin underline that simply moves on click without spring.
10. Three-quarters of the icons. Replace with typography.

After these cuts, the remaining design will feel intentional. Right now it feels generous, which is a different thing.

---

## The Five-Second Test

After any redesign, show the screen to someone for five seconds, then close it. Ask: **"What was that?"**

- "An AI app" — failed
- "A chat thing" — failed
- "A productivity tool" — failed
- "I don't know" — passing
- "I don't know but I want to try it" — succeeded
- "Something a writer or scholar would use" — perfect

Mystery is created by resisting categorization. Most products try desperately to be categorized. This one resists.

---

## The Confidence Test

Calm in software is the visual signature of not being afraid.

Designers fear empty space, fear one button where they could have three, fear the user not understanding. The calm we are after comes from refusing those fears.

When you look at a screen and feel the urge to add something — a label, a hint, a decoration, a status, a microcopy — pause. Ask whether the user genuinely needs it. Most of the time they do not. They need to feel that the product knows what it is.

Build like you do not need to convince anyone of anything.
The product holds itself.

---

## Reference Library

When in doubt, consult these. They occupy the register we want.

**Software**
- iA Writer (typography, focus, single typeface)
- Readwise Reader (serif primary, marginalia, footnotes)
- Granola (warm minimalism, monospace details)
- Are.na (calm grids, archival feeling)
- The Browser Company's Dia (mystery, slowness)
- Notion Calendar (restraint in a noisy category)

**Print, fashion, objects**
- Aesop packaging and stores
- Loro Piana, Brunello Cucinelli (quiet luxury)
- The Paris Review (typographic dignity)
- Pentagram's quieter work
- Teenage Engineering OP-1 (object-as-software)
- A Leica camera
- An Oxford University Press book interior
- Filson and Barbour catalogues (weathered, functional, made for outside)
- A well-used Moleskine, a brass compass, a wool blanket

**Film, photography**
- Wong Kar-wai's *In the Mood for Love* (color restraint)
- Andrei Tarkovsky (stillness, weight)
- Saul Leiter photographs (warmth in shadow)
- Hiroshi Sugimoto's seascapes (held silence)
- Rinko Kawauchi's natural light photography (gentle, observed)
- *A River Runs Through It* (the river, the cast, the patience)
- Late afternoon light on water, anywhere

**To avoid**
- Anything that looks like a Y Combinator company in 2024
- Bento grids
- Gradient hero text
- Glass-morphism dashboards
- "AI-powered" in any copy
- Stripe homepage circa 2022
- Any landing page with floating 3D shapes
- The current visual language of Linear's competitors imitating Linear

---

## Living Document

This file is the constitution. When in conflict between this document and a feature request, this document wins.

Update only with deliberate intent. Add references as the product matures. Subtract aggressively — fewer rules, held more strictly, are stronger than many rules held loosely.

The goal is not to follow these principles.
The goal is for these principles to become invisible because the product simply *is* them.
