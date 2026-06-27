# PROMPTS.md

> The prompt library for designing Vellum.
> Use these when working with Claude, Claude Code, Cursor, or any LLM-driven design or build tool.
> Read this alongside `BRAND.md`, `DESIGN.md`, and the logo exploration file.

---

## How to Use This File

Vellum's register is fragile. Models drift toward SaaS defaults the longer a conversation runs. These prompts are calibrated to hold the register in place across sessions.

Three rules for every prompting session:

1. **Always attach the documents.** Drop `BRAND.md`, `DESIGN.md`, and the logo exploration HTML into the conversation context — not just on turn one, but as project files where supported (Claude Code, Cursor, Projects).
2. **Restart after 4–5 iterations.** Context decay is real. The voice will soften. Begin a fresh conversation and re-attach the files.
3. **Be direct.** Politeness invites compromise. If the output drifts, say so plainly: *"This violates DESIGN.md principle X. Try again."*

---

## The Master Prompt

> The single starting prompt for any new design session. Paste this verbatim, then make your specific request.

```
You are designing for Vellum — a private, local-first personal AI agent.
Before building anything, read the attached files in this order:

1. BRAND.md — who Vellum is and who it's for
2. DESIGN.md — the visual and interaction principles
3. The logo exploration HTML — the wordmark system

Treat these documents as the constitution. When in conflict between
my request and these documents, the documents win. Tell me when there
is a conflict — don't quietly compromise.

Before generating any code or design, do these three things:

1. Tell me which DESIGN.md principles apply to this surface.
2. Tell me what you're going to deliberately leave OUT.
   This matters more than what you put in.
3. Show me the copy and text content for the surface BEFORE you build it,
   so we can edit the language first.

Then build it as a single HTML file using:

- Fraunces 300 for serif, DM Sans 500 for system text
- Graphite (#0c0c0e) background, parchment (#ece6db) text
- Ember (#d97746) used at most twice per screen
- The italic-v wordmark from logo variant 02
- cubic-bezier(0.22, 1, 0.36, 1) easing, 600–900ms durations
- Paper grain texture overlay at ~40% opacity, overlay blend
- No icons unless typography genuinely cannot do the job
- No bullet points unless I explicitly ask for a list

After you build it, run the five-second test from DESIGN.md and tell me
honestly whether it would pass.

My request: [DESCRIBE WHAT YOU WANT]
```

---

## Component Prompts

Tight prompts for the most common surfaces. Each one already encodes the register, so you can paste-and-go without retyping the constitution.

### A new chat component

```
Design [COMPONENT] for Vellum's chat interface (Direction A, pure stillness).

Constraints:
- Serif body in Fraunces 300
- 600–900ms exhale easing on all motion
- No icons
- Ember accent appears at most once on this surface
- Copy follows the librarian voice from DESIGN.md
- The interface must be still by default — motion only when something
  meaningful is happening
- Output as a single self-contained HTML file

Show me the copy first. We edit the language before you build.
```

### A new settings or admin surface

```
Design [SURFACE] as a "preferences ledger" — readable sentences with
inline-editable variables, not a conventional form.

Reference DESIGN.md "Settings" section.

Required:
- No labels above inputs
- No Save buttons (save on blur)
- Editing happens by clicking the variable parts of sentences
- Tone is the reading voice of a longtime user, not a configuration screen
- The page reads top to bottom like a personal arrangement

Example sentence pattern:
"The agent uses [Gemma 4 31B] for primary work and [Gemma 4 12B] for
quick tasks. Notes are read from [/Users/name/Vault]. Web search is
permitted only for [time-sensitive queries]."

Show me three sample sentences first. Then build.
```

### An email, notification, or transactional message

```
Compose [MESSAGE] in Vellum's voice.

Hard rules:
- No exclamation points
- No emoji
- No greeting ("Hi there", "Hey", "Hello")
- No closing pleasantries ("Best", "Cheers", "Thanks")
- No "I'd be happy to", "Let me", "Here's"
- One sentence per idea
- Plain declarative sentences only
- No marketing language

Voice reference: an exceptionally well-read assistant who is not
impressed with itself. Plain. Exact. Slightly formal but not stiff.

Aim for the shortest possible version that carries the meaning.
Then cut a third more.
```

### A landing page or marketing surface

```
Design [SURFACE] in Vellum's Direction A register — pure stillness.

Reference: the Direction A landing page already built in
vellum-landing-preview.html.

Hard constraints:
- Centered composition, generous empty space
- One serif (Fraunces 300), one system font (DM Sans 500)
- Total visible elements: 7 or fewer
- One call to action: a typography link with thin underline, no button
- Copy is dry and short — see DESIGN.md tone table
- Motion: only fade-and-blur arrival sequences
- No background animation, no canvas, no 3D
- Italic-v wordmark from logo variant 02

Forbidden:
- Bento grids
- Feature lists
- Testimonials
- Hero images
- Gradient text
- "Powered by AI" anywhere
- Any pattern that appears on a Y Combinator company homepage

Show me the full copy as a flat document first. Edit the words, then build.
```

### An empty state

```
Design the empty state for [CONTEXT] in Vellum.

Reference DESIGN.md "Empty state" section.

Hard rules:
- Centered. Nearly black canvas.
- The wordmark, small.
- One line of muted text — a statement, not a question.
  Use the same grammatical form as "What are you reading."
- The cursor is already in the input. No buttons. No examples.
  No badges. No greeting. No model selector visible.
- The user must reach toward the agent.

Give me three candidate one-liners before building.
The right one feels like a librarian's quiet acknowledgment, not a prompt.
```

### A loading or thinking state

```
Design the [STATE] for [CONTEXT].

Hard rules:
- No spinner
- No "Loading..." text
- No skeleton placeholder
- No progress bar
- No percentage
- No estimated time

Permitted:
- A single thin horizontal line drawing itself across the screen
  (Direction A — see DESIGN.md "During the agent's work")
- Silence + the existing ember dot continuing to breathe

Show me the motion timing first. Then build.
```

### An error state

```
Design the error state for [CASE] in Vellum.

Hard rules:
- One word if possible. ("Unreachable." "Withheld." "Closed.")
- Two sentences maximum.
- No apology language ("Sorry", "Oops", "We're sorry that")
- No marketing softening ("Don't worry", "Try again later")
- No emoji, no error icon, no red color
- Tone is dry observation — see DESIGN.md "Quiet wit"
- Visual treatment: same surface as normal, ember accent dimmed by half

Give me the copy first.
```

### A confirmation or success state

```
Design the confirmation for [ACTION] in Vellum.

Hard rules:
- One word: "Filed." "Saved." "Closed." "Sent." "Done."
- No checkmark icon
- No green color
- No celebratory motion
- The confirmation fades after 1.6 seconds and disappears

The reward for using Vellum is Vellum, not gamified feedback.
```

### A modal, panel, or drawer

```
Design [SURFACE] for Vellum.

Hard rules:
- Slides in from the side via fade-and-blur, never a slide motion
- Background dims by 0.4 opacity, no color tint
- No close button (X) — the panel closes on outside click or Escape
- No header bar with title
- The panel content begins immediately at the top with serif body type
- One typeface, one weight for body
- Maximum width: 460px

Show me the panel content as plain text first. Then build.
```

### A list or table

```
Design [LIST/TABLE] for Vellum.

Hard rules:
- No alternating row colors
- No row borders unless absolutely needed for legibility
- 1px hairline separator if needed, color rgba(244,237,226,0.10)
- Generous vertical spacing between rows (24px minimum)
- No icons, no badges, no chips
- Use lowercase Roman numerals (i. ii. iii.) instead of bullets if numbering is needed
- Pagination is forbidden — load on scroll silently or show all

If a column is metadata (date, status, count), it sits in muted text
to the right, not in its own column header. The list reads like a page,
not a spreadsheet.
```

### A button — the rare cases one is needed

```
Design the button for [PURPOSE] in Vellum.

Default to: NOT a button. Use a typography link with a thin underline.

If a button is genuinely required:
- 1px border in rgba(244,237,226,0.16), no fill
- Border radius 6px
- Padding: 10px 22px
- Font: DM Sans 500, 11px, 0.16em letter-spacing, uppercase
- Hover: border warms to ember over 240ms
- No box-shadow ever
- No gradient ever
- One word label if possible

Forbidden:
- Filled colored buttons
- Gradient buttons
- Buttons with icons
- "Click here", "Get started", "Learn more"
- Multiple buttons on one screen
```

---

## Voice & Copy Prompts

When you need help writing language inside the product, not designing surfaces.

### Rewrite generic copy in Vellum's voice

```
Rewrite the following in Vellum's voice. Reference the tone table in
DESIGN.md section 7 ("Language as restraint").

Hard rules:
- Cut every exclamation point
- Cut every emoji
- Cut every word that performs warmth ("happy to", "great", "love to")
- Cut every word that performs urgency ("now", "today", "quickly")
- Aim for half the original word count, then cut another quarter
- One sentence per idea
- Plain declarative form
- Slightly archaic phrasing is permitted ("filed", "withheld", "closed")

Original:
[PASTE COPY]

Give me three rewrites of decreasing length. I'll pick the one that
disappears most cleanly into a sentence.
```

### Generate microcopy for a tool / feature / state

```
Write the system messages for [FEATURE].

I need:
- The label (what it's called in the UI)
- The verb form (what the agent says when using it)
- The completed-state phrase (what the agent says afterward)
- The error phrase (what the agent says if it fails)

All in Vellum's voice. One word each where possible.

Reference: the table in DESIGN.md section 7 "System messages".
Filesystem becomes "Looking." Apify becomes "Inquiring." Web becomes "Out."
Apply the same logic to [FEATURE].
```

### Generate the witty observation

```
The agent has been idle for 8 minutes. The user just returned.
Vellum is allowed one quiet observation — a fragment from the user's
own notes, dated, surfaced without commentary.

Reference DESIGN.md principle 8 "Quiet wit".

Hard rules:
- Format: "You wrote this on a [DAY] in [MONTH]: '[fragment].'"
- Maximum 14 words inside the quote
- Tone: dry, observed, unsentimental
- Never repeats — once a user sees a particular fragment, retire it
- Never explains itself, never asks a question, never invites a response

Generate 5 example fragments that would fit if pulled from a thoughtful
person's notes. They should feel like things actually written, not
written-to-be-quoted.
```

---

## Code Generation Prompts

For Claude Code, Cursor, or building actual application surfaces.

### Implementing a new screen from scratch

```
Implement [SCREEN] for the Vellum web app.

Stack:
- React (functional components, hooks)
- Tailwind CSS (using the Vellum design tokens defined below)
- No external UI libraries — build from primitives
- One file per component

Vellum design tokens (use these exact values, not Tailwind defaults):

  --graphite: #0c0c0e
  --charcoal: #131316
  --slate: #1a1a1c
  --warm-gray: #232326
  --parchment: #ece6db
  --vellum-paper: #f6f3ee
  --muted: rgba(236,230,219,0.72)
  --whisper: rgba(236,230,219,0.46)
  --faint: rgba(236,230,219,0.22)
  --ember: #d97746
  --soft-ember: #f1b27a
  --line: rgba(244,237,226,0.10)
  --line-2: rgba(244,237,226,0.16)
  --ease-exhale: cubic-bezier(0.22, 1, 0.36, 1)

Typography:
- Body / display: 'Fraunces', serif, weight 300
- System / metadata: 'DM Sans', sans-serif, weight 500, letter-spacing 0.16em uppercase

Before writing code:
1. List the components you'll create
2. List the components you considered and rejected
3. Show me the prop interface for the main component
4. Show me the copy / text content for every visible string

Then implement. One component per file. Self-contained.
```

### Refactoring an existing component to fit Vellum

```
Here is an existing component:

[PASTE CODE]

Refactor it to fit Vellum's register per DESIGN.md.

Process:
1. List every violation of DESIGN.md you can find in the current code
2. List every UI element you would remove (subtraction first)
3. Then refactor

Common violations to look for:
- Buttons with fills, shadows, or gradients
- Multiple typefaces or weights
- Color values outside the Vellum palette
- Icons used where typography would do
- Microcopy with exclamation points, emoji, or filler
- Animations under 600ms or with bouncy easing
- Skeleton loaders, spinners, or progress bars
- Borders heavier than 1px or saturated in color
- Bullet points used for non-list content
```

### Reviewing a design output

```
Here is something I built for Vellum:

[PASTE CODE OR DESCRIBE OUTPUT]

Review it against DESIGN.md and BRAND.md. Be direct.

Tell me:
1. What violates the documents (specific principles, by number)
2. What is unnecessary and should be removed
3. What is correct and should remain
4. Whether it passes the five-second test ("What was that?")
5. The one change that would most improve it

Don't praise. Don't soften. If it fails, say so.
```

---

## Self-Audit Prompts

Run these periodically against the whole product or a section of it.

### Surface audit

```
Looking at the attached screen / feature / page, audit it against
DESIGN.md and BRAND.md.

Count each of the following and report:
- Total visible elements
- Total typefaces in use
- Total font weights in use
- Total colors used (excluding pure transparency)
- Number of icons
- Number of buttons (vs typography links)
- Number of words of microcopy
- Number of exclamation points
- Number of emoji
- Number of motions / animations / transitions
- Number of motions under 600ms

Compare each count against DESIGN.md targets.
List every value that exceeds the target.

Then: which single change would most reduce the violations?
```

### Voice audit

```
Audit the copy of [SCREEN / EMAIL / PAGE] against Vellum's voice.

Flag every instance of:
- Exclamation points
- Emoji
- "I" or "We" speaking on behalf of the product
- "Let me", "Here's", "I'd be happy to", "Sure"
- "Get started", "Learn more", "Click here"
- "Powered by AI", "AI-driven", "intelligent"
- Sentences over 18 words
- Adjectives that perform warmth ("amazing", "great", "wonderful")
- Adjectives that perform urgency ("instant", "fast", "now")
- Filler words ("just", "simply", "really")
- Empty greetings or closings

Then rewrite the worst three offenses in Vellum's voice.
```

### Five-second test

```
I'll show you [SCREEN]. Look at it for 5 seconds.

Without scrolling back or asking questions, answer:
- What is this product?
- Who is it for?
- What does it want from you?
- What feeling does it leave?

Be honest. If your first answer is "an AI app", "a chat thing",
or "a productivity tool", the design has failed.

Passing answers:
- "I don't know"
- "I don't know but I want to try it"
- "Something a writer or scholar would use"
- "A library that thinks"
```

---

## When the Model Drifts

The most common failure modes and the exact phrases to recover.

### When it adds too much

```
You added too much. Subtract until only what is essential remains.
Refer to DESIGN.md principle 3 ("Empty space is a luxury good").
Remove [N] elements before showing me the next version.
```

### When the copy turns generic

```
The copy has drifted toward SaaS defaults.
Reread the tone table in DESIGN.md section 7 and rewrite.
Aim for one-word answers where possible.
```

### When motion gets bouncy or fast

```
The motion is too fast and too eager.
Replace every animation with the exhale easing
(cubic-bezier(0.22, 1, 0.36, 1)) and 600–900ms durations.
No bounce. No spring. No elastic.
```

### When colors expand

```
You introduced colors outside Vellum's palette.
The palette is graphite, charcoal, slate, warm gray, parchment,
vellum paper, muted, whisper, faint, ember, soft ember, and the two
line tones. Nothing else.

Remove the foreign colors and rebuild.
```

### When it adds icons

```
You added icons. Vellum prefers typography to icons.
Replace each icon with a Roman numeral, an italicized letter,
or a single word. Keep an icon only if no typographic alternative
exists. List which icons you considered keeping and your reasoning.
```

### When it adds buttons

```
You added filled buttons. Vellum's default is a typography link
with a thin underline. Replace each button with the link pattern
from DESIGN.md "Button — the rare cases one is needed" section
unless the action is destructive or genuinely primary.
```

### When the output looks like every other AI product

```
This output could appear on any Y Combinator company's homepage.
Vellum is not in that category.

Restart with these references in mind:
- iA Writer, not Notion
- The Paris Review, not Linear
- Aesop, not Stripe
- Granola, not ChatGPT

Try again. Make it slower, quieter, less explained.
```

---

## A Closing Note

These prompts are weapons against drift. Models tend toward the average — and the average AI product is loud, busy, helpful in a vacant way, and immediately categorizable.

Vellum is none of those things.

When you write to a model, you are not asking it to design something. You are asking it to **resist its own training** — the millions of dashboards, hero sections, onboarding flows, and welcome emails it has absorbed. The prompt's job is to hold the line.

Hold it firmly. Repeat the constraints. Don't apologize for them. The product holds itself only because you held the line first.
