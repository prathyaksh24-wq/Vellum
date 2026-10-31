# Composer menus and selected tooltip motion — 2026-10-30

## Result

Adapted the local `Downloads/Agent composer.html` menus and motion into the canonical served Vellum interface. The supplied demo's fake models, tools, chat responses, recording timers and shortcut overrides were not imported.

- The slash menu uses Vellum's commands, installed skills, plugins, apps, MCPs, agents and projects. Pointer and keyboard selection share one moving background. Project entries use the same command list instead of the previous disconnected submenu. IME composition does not execute or send a command. Menu placement is above the entire composer, leaving the draft visible.
- The menu list is up to 360px tall (about eight rows), with a 380px outer limit and a viewport cap. Command names retain their natural width, descriptions align beside them, and the internal scrollbar is narrow. The legacy grid stylesheet was overriding these rules; the scoped component stylesheet now follows the legacy styles.
- The model picker keeps the supplied provider rail, search, model rows and effort footer. Its source controls expose Local, OpenRouter and OpenAI. Connected sources use `settings.default_model.set`; an existing chat also receives `model.select`. Public provider metadata determines connection availability. Vendor filtering within OpenRouter does not change the connection source. Missing keys produce an inline explanation. This does not introduce direct inference adapters for providers that the backend does not support.
- Model logos use the existing vendor assets. Monochrome marks use the current foreground color so OpenRouter, OpenAI and Kimi remain visible without rectangular backing. The shared row highlight uses the active theme rather than a fixed black block.
- Low/Medium/High effort stages a draft before the first turn. Existing conversations dispatch `reasoning.set`; new chat and agent requests and records carry the staged setting. Clicking the selected effort returns to the model default.
- One shared tooltip retains the supplied geometry transitions and delayed dismissal. Following user feedback it is opt-in, rather than generated from every title or accessible label. Its colors follow the active Vellum surface; the fixed white fill is removed. Memory keeps its accessible action label without a tooltip.
- Browser settings replaces its native Choice select with the canonical VSelect and opts into the same local row background. Selection callbacks, numeric cursor-size conversion, disabled state and existing Browser App Actions/confirmations are preserved. Group boundaries allow the open menu to escape without clipping.

## Inspection performed

No test suites or production builds were run, as requested.

- Parsed the main inline JSX and the changed VSelect and Browser settings JSX with Babel; parsed `morphic-ui.js` with Node. These syntax checks passed.
- Scoped `git diff --check` passed for the implementation and action inventory changes.
- Inspected the running local UI in isolated Edge at 1440×1000 and 390×844. The actual local picker populated Gemma 4 12B. No chat or inference request was sent and no saved model/provider selection was changed during inspection.
- Confirmed full command names, left-aligned descriptions, flex rows and a gap above the composer. Confirmed Escape restores model-trigger focus, command keyboard navigation, vendor filtering, model search and selection callbacks, effort callbacks, reduced-motion transitions of 0s, and one shared tooltip. Memory hover leaves the tooltip hidden.
- Replayed connected-provider switching with temporary component data: OpenRouter replaces local options with cloud options, and an unconnected OpenAI source gives an inline explanation. This is presentation/callback evidence, not proof of a live cloud completion or a persisted provider switch.
- Inspected Browser settings with its real read-only settings projection and inert save callbacks: pointer movement produced one 34px row highlight with the supplied 240ms curve. Keyboard navigation in Search engine moved to DuckDuckGo, Escape closed the dropdown, and no native selects remained in the displayed settings. No browser preferences were saved.
- Confirmed the final tooltip computes a dark Vellum surface (`rgba(20,18,18,.96)` in the inspected theme) with light text, rather than white fill. No page errors occurred in the inspected flows.

The final increase in slash-menu height is a CSS-only adjustment made after the broader layout inspection. No complete post-change chat/provider or production-build verification is claimed.

## Action Parity review

Registered `components/morphic-ui.js` as a served source and included its createElement event handlers in discovery. Reviewed its presentation-only handlers and the changed composer handlers against a task-start snapshot. Existing Browser settings had a matching inventory before this task; its fingerprint was updated after reviewing the sole handler change from native `select.onChange` to `VSelect.onValueChange`. VSelect's handler fingerprint is unchanged.

Added coverage probes for composer provider selection and reasoning effort and a scoped exemption for transient menu/filter/tooltip presentation. The main HTML already differed from the inventory before this task (929 actual handlers versus 936 locked); that unrelated pre-existing drift is preserved, not certified by a blanket refresh. Main and other dirty-source inventory drift must be reconciled for scoped publication. The full Action Parity suite was not run.

## Proposed draft PR

**Title:** Integrate composer menus, in-picker provider switching and selective tooltip motion

**Description:** Replace Vellum's slash menu and model picker presentation with the supplied shared-background design, while keeping canonical commands, provider scope, model selection and reasoning controls. Add connected provider switching in the picker, improve logo contrast, limit morphing tooltips to explicit controls with themed colors, and apply the same row motion to Browser settings dropdowns. Syntax and local browser inspections passed as described above; tests/builds and live cloud inference were not run. Reconcile the pre-existing main Action Parity drift before publication.

Changes are local. No branch, commit, push or PR was created for this task.
