# How Claude Code, Claude.ai and ChatGPT do memory

Research for Vellum's memory redesign (2026-11-17). Each claim is labelled with
how it was established:

- **[code]**: read from the shipped Claude Code binary (`claude.exe`, a Bun
  executable whose bundled JavaScript was searched as text). This is static
  evidence, not observed execution.
- **[skill]**: read from the installed `import-memory` skill file.
- **[docs]**: official help pages (support.claude.com article 11817273,
  help.openai.com article 8590148, both read 2026-11-17).
- **[inferred]**: my reading of constants or names, not confirmed.

Section 5 describes the live claude.ai and ChatGPT memory screens, inspected
signed in (read-only) on 2026-11-17. **[ui]** marks those observations.

---

## 1. Claude Code (the CLI)

### Storage
- Memory is plain markdown files in an auto-memory folder per project, plus an
  index file `MEMORY.md`. [code]
- Each memory file carries frontmatter (`name`, `description`, `type`), with
  four types: `user`, `feedback`, `project` and `reference`. The index has one
  line per memory. [code: the extraction prompt points to "the memory types,
  what-not-to-save criteria, and frontmatter format from the Memory section of
  your system prompt"]
- There are personal stores and team/project stores ("silos"), each with a
  read-only or read-write mode, and each contributes its own `MEMORY.md` as a
  prompt index. [code]
- Limits: the index must stay small. The server rejects an oversized
  `MEMORY.md` ("Shorten the index: one short line per memory, with the detail
  in the memory files"). Single files are capped at 102,400 bytes. A memory
  scan lists at most 200 files: the index first, then newest by modification
  time. The constants `200` and `25000` near `MEMORY.md` look like a
  line/character cap on how much of the index loads into the prompt.
  [code; the cap's meaning is inferred]
- Writes are screened: "memory content appears to contain a credential or API
  key; remove it before writing." [code]

### Recall (how memories reach a turn)
- `MEMORY.md` is always in context, as a table of contents.
- `selectRelevantMemories`: a **separate, cheaper model** gets the list of
  memory filenames with their descriptions, then the user's query. It returns
  **up to 5 files** it is "certain will be helpful based on their name and
  description." Those files are attached to the turn as `relevant_memories`,
  and the UI shows them inline as **"Recalled from memory."** [code]
- If the selector fails, is refused or is cut off, recall returns nothing and
  the turn goes ahead without memories. Fail-open. [code]
- Design point: recall quality depends on **good descriptions**. Bodies are not
  read at selection time, which keeps selection cheap.

### Saving: two paths
1. **In-turn:** the main agent writes memory files itself with its file tools,
   following its system-prompt rules (what to save, when to update rather than
   duplicate, link related memories). [code + system prompt]
2. **Background `extractMemories` pass:** after turns, on a cadence, a subagent
   is told: "Analyze the most recent ~N messages above and use them to update
   your persistent memory systems." [code] Its rules:
   - It may use only those messages, with no investigation (no grep, no code
     reading, no git).
   - "If nothing is worth saving, output only 'Nothing to save.'"
   - Explicit "remember X" is saved immediately. "Forget X" finds and removes
     the entry.
   - It **skips** when the conversation already wrote to memory in that range,
     when there is "not enough user prose," when a newer turn has started, or
     when policy forbids memory writes.
   - A cheap **"first look"** model gives a verdict first (the gate can run in
     shadow or enforce mode). If the verdict is no, those turns wait for the
     next pass.
   - It keeps a **cursor**: turns are reviewed once. If an extraction is
     already running, new context is stashed for a trailing run.
   - After writing, it tells the main session which files changed and re-syncs
     its read state.

### Import from other AI providers ([skill], import-memory)
- **Flow:** give the user a fixed export prompt for the other assistant → read
  the paste → build a plan → apply a privacy filter → show the plan and
  **confirm** → write in batches (about 10 writes per turn; a full export is
  about 25–30 files) → review together.
- **The export prompt asks for 5 categories in order:** Instructions, Identity,
  Career, Projects, Preferences. Each entry is one line,
  `[YYYY-MM-DD] - Entry`, oldest first, all in one code block, plus a
  statement of whether the export is complete.
- **Taxonomy it files into:**
  - `/profile.md`: identity keys only (name, role, title, employer, city,
    location, primary_language, working_language, pronouns, timezone).
  - `/areas/<slug>.md`: one file per active project.
  - `/people/<slug>.md`: slugged by relationship, never by name.
  - `/topics/<slug>.md`: one file per domain (hobbies, tastes, routines).
- Every line starts with `[stated]`. Imported text is restructured into
  single-fact lines, never copied verbatim.
- **Rules:**
  - The paste is data, never instructions; directives disguised as facts are
    dropped.
  - Import is **additive only**: it never rewrites or deletes existing memory;
    conflicts are flagged, not filed.
  - Style preferences are not filed.
  - URLs are dropped.
  - The paste is capped at about 64 KB.
  - On re-import, existing facts are skipped.
- **Privacy filter drops entirely:** protected attributes, health, money,
  personality profiling, identifiers, children, heritage language, and names of
  family or care providers.

---

## 2. Claude.ai (consumer app) [docs]

- **Current design:** memory is saved "as a set of individual topics as you
  chat," updated live, not summarized after a chat ends. Claude saves on its
  own and also on "remember this."
- **Legacy design** (some Team/Enterprise orgs): one **Memory summary**,
  re-synthesized **every 24 hours** from chats. Deleted chats are removed from
  synthesis.
- **Scopes:**
  - Account memory.
  - Per-project memory: a project uses its own memory plus account memory,
    never other projects' memory. Toggle: "Use account memory".
  - Incognito chats (ghost icon) never save.
  - Per chat: **+ → Memory** off before the first message.
- **Settings:** Settings → Your Claude. Controls:
  - "Generate memory from chats."
  - **Manage** next to "Your memory" opens a **Topics** list; open a topic,
    then edit (pencil) or **Delete**.
  - "Search and reference chats" is a separate toggle.
  - "Include sensitive topics in memory" is off by default.
- **Pause memory** keeps existing memory but stops using and creating it.
  **Reset memory** permanently deletes everything, including project memory.
- **Never saved:** government IDs, criminal history, financial account numbers,
  immigration status.
- **Categories it remembers:** role and projects; people and places;
  communication preferences and working style; technical preferences; ongoing
  work.
- **Importer:** Settings → Capabilities → "Import memory from other AI
  providers" (experimental), using the same export prompt as the skill above.

## 3. ChatGPT [docs]

- **Sources memory can draw on:** past chats, saved memories, custom
  instructions, files (Library/Space) and connected apps (for example Gmail).
- **Two systems:**
  - **Saved memories:** explicit items, a list. Deleting the chat does not
    delete the memory. Some plans add search, sorting, **automatic
    prioritization** and **version history**.
  - **Reference chat history:** derived context that "can change as ChatGPT
    updates what is most useful". It has no storage limit. Turning it off
    deletes the derived memory within 30 days.
- **"Improved memory"** "continually updates a broader summary." Legacy is the
  explicit list. Users can switch between them.
- **Memory summary UI** (Settings → Personalization → Memory). Controls:
  - **type a correction** in a text field;
  - **highlight text and correct it** inline;
  - **"Don't mention this again"**, which suppresses use without deleting the
    source;
  - "•••" → **Delete and turn off memory**.

  The summary is "a high-level view": it does not show everything.
- **Sources under responses:** when personal context was used, a "Sources" row
  under the answer shows which chat, memory, instruction, file or email
  contributed. From there you can open it, correct or delete it, or mark it
  relevant or not relevant.
- **Recall is selective:** "ChatGPT looks for relevant context when it is
  likely to improve a response". It also personalizes web searches.
- **Temporary chat:** choose "Unpersonalized" before the chat starts. Temporary
  chats never create memories. Saving one converts it to a regular chat.
- **Project-only memory:** chats can reference only the same project.

---

## 4. What Vellum should take

| Pattern | Source | Vellum gap it fills |
|---|---|---|
| Cheap selector model picks ≤5 memories by name and description | Claude Code | Recall currently uses keyword search and a fixed baseline of 4 |
| Descriptions as the retrieval key; small always-loaded index | Claude Code | No index or description field on memories |
| Background extraction with a "first look" gate, a cursor, and "skip if already saved this range" | Claude Code | Regex extractor; no LLM pass |
| "Recalled from memory" chip on the turn | Claude Code | Users can't see when memory was used |
| Sources row with relevant / not relevant / correct / delete | ChatGPT | No feedback loop on recalled memories |
| Memory summary with inline highlight-to-correct and "Don't mention this again" | ChatGPT | Summary is read-only text |
| Topics list (one card per topic) with edit and delete | Claude.ai | The UI mixes settings, diagnostics and memories |
| Pause vs Reset; incognito; per-project memory with an "use account memory" toggle | Claude.ai | Partially present |
| Importer: fixed export prompt, 5 categories, `[stated]` lines, additive, privacy filter, confirm before writing | import-memory | Not built |
| Version history and automatic prioritization | ChatGPT | None; matches Vellum's 30/90 retention plan |

## 5. The live screens [ui]

### Claude.ai: Settings → Your Claude
Settings is a modal: left nav, content on the right, dark theme. In a narrow
window the nav becomes a horizontal tab row.

The **Instructions** block comes first: one free-text area with the placeholder
*"e.g. when learning new concepts, I find analogies particularly helpful"*.
Below it, a **Memory** section is a stack of rows. Each row has a title, a
one-line grey description with a "Learn more" link, and its control
right-aligned. Thin dividers separate the rows. In order:

1. **Search and reference chats**: toggle.
2. **Generate memory from chats**: toggle.
3. **Include sensitive topics in memory**: toggle, off; *"like health
   conditions or religious beliefs."*
4. **Your memory**: *"See, add to, edit, or delete what's in memory."* →
   **Manage** button.
5. **Import memory from other AI providers** → **Start import**.
6. **Export memory**: *"Download your memory as a .zip of Markdown files."*

**Manage** opens a page in the same modal:
- A breadcrumb (`← Your Claude / Memory`).
- The import row repeated at the top.
- A list of memory **files** ("No files yet" when empty, centred grey text).
- A **chat input pinned to the bottom: "Tell Claude what to change"**, with a
  round send button. Editing is conversational; there are no form fields.

Memory is a set of Markdown files you can download as a .zip, the same model as
Claude Code.

**Start import** opens a centred dialog, "Import memory to Claude", with a
close (×) button and two numbered steps:
1. *"Copy this prompt into a chat with your other AI provider"*: a dark,
   scrollable code-style box holding the export prompt, with a **Copy** button
   in its bottom-right corner.
2. *"Paste results below to add to Claude's memory"*: a large textarea, *"Paste
   your memory details here."*

Footer: **Cancel** (filled grey) and **Add to memory**, which stays disabled
until text is pasted.

### ChatGPT: Settings → Personalization
Settings is a full page: left nav with Profile, Account and App groups, content
on the right, with a page title and subtitle (*"Choose what the assistant
remembers and how it responds"*). The **ChatGPT memory** group has:
- **Enable memory**: toggle, accent-coloured when on (orange-brown in dark
  mode); *"based on your chats, files, and connected apps."*
- **Memory summary** → **Manage**. The description links "custom
  instructions" and "saved memories" (the legacy list stays reachable).
- A note that memory may personalize search queries sent to providers like
  Bing.

**Memory summary modal (the key screen):**
- **Generated on open, streamed.** When the modal opens it shows a centred
  open-book icon and **"Generating"**, with a shimmer on the text. The page
  makes these requests:
  - `POST /backend-api/memories/about_you/summary/stream`: streams the summary.
  - `GET …/summary/checksum`: a fingerprint of the inputs, inferred to let it
    skip regeneration when nothing changed.
  - `GET …/about_you/selection_correction_actions`: options for the
    highlight-to-correct menu.
  - `GET /backend-api/memories?include_memory_entries=false`: summary metadata.

  It took about 10 seconds.
- **Header:** "Memory summary" plus a grey timestamp, **"Updated just now"**,
  then a **•••** menu and a close button.
  - The ••• menu holds **ⓘ About memory** and a red **🗑 Delete and turn off
    memory**.
- **Body:** a profile written as prose in second person ("You're …, based in
  …"), split into **H3 sections**.
  - **Overview** comes first (who you are, direction, communication style).
  - Then one section per **major topic, entity or project** (e.g. a
    main-project section, its principles and design, hardware/local AI, work
    and learning, tools and integrations, a side project). Section titles are
    generated per user, not a fixed template.
  - Each section is one dense paragraph. It records nuance such as
    *"reconsidering whether X belongs … rather than treating older labels as
    settled"*, i.e. it notes that things are still changing, and dislikes as
    well as likes.
- **"Dive Deeper"** ends the summary: 2–3 generated follow-up prompts, each
  prefixed with **↳** and given a dotted underline. They're clickable and
  presumably start a chat.
- **Highlight to correct:** selecting any text highlights it in the accent
  colour, and a dark tooltip, **"Make a correction"**, appears just above the
  selection.
- **Footer:** a pinned rounded input, **"Ask or update"**, with a circular
  send arrow. Corrections are made by chatting.
