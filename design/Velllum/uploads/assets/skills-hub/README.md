# Vellum Skills Hub visual reference

`vellum-skills-hub-concept.png` is an ImageGen concept used to guide the
production Skills Hub implementation. It is not a runtime dependency and must
not be embedded as a background image or UI substitute.

## Direction

- Preserve Vellum's warm near-black glass surfaces and muted ember accent.
- Favor a dense, calm catalog over a marketing-style marketplace.
- Keep installed, discoverable, pending, duplicate-review, and archived skills
  within one information architecture.
- Use a right-side detail drawer for provenance, security, dependencies,
  recent sanitized tasks, and lifecycle actions.
- Surface curator health and pending approvals without attention-grabbing
  notifications.

## Required responsive states

- Desktop: catalog and detail drawer visible together.
- Tablet: catalog remains primary; detail opens as an overlay drawer.
- Mobile: single-column cards and full-screen detail sheet.
- Light and dark themes retain the same hierarchy and accessible contrast.
- Loading, empty, partial-source, offline, rate-limited, conflict, and invalid
  package states use native Vellum components rather than illustrations.

The frontend implementation must be driven by live API data, remain keyboard
navigable, respect reduced motion, and avoid duplicating skill state locally.

`vellum-skills-hub-revalidation.png` is the post-backend contract revalidation.
It adds source health, immutable diff review, verified repository/ref
provenance, support files, and the rendered/raw `SKILL.md` panel used by the
production implementation. It is also a design-only reference.
