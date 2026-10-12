# Diagrams

| File | Audience | Use |
|---|---|---|
| `architecture-overview.svg` | Anyone — investors, buyers, new joiners | Pitch decks, writeups, README hero |
| [`../ARCHITECTURE.md`](../ARCHITECTURE.md) | Engineers | Component and sequence detail |

## architecture-overview.svg

High-level, non-technical. Reads top to bottom as a story:

1. **Surfaces** — Teams for the team, dashboard for the admin
2. **The coworker** — understands, plans, acts, reports
3. **Four capability layers** — knowledge, action, memory, automation
4. **Enterprise guardrails** — the band every action passes through
5. **Connected systems** — what it reaches

Deliberately says nothing about queues, workers, or RLS. Those belong in `ARCHITECTURE.md`.

### Using it

- **Slides / Google Slides / PowerPoint** — insert the SVG directly; it stays sharp at any
  size. PowerPoint can ungroup it for recolouring.
- **GitHub / Markdown** — `![Architecture](docs/diagrams/architecture-overview.svg)`
- **PNG, if a tool demands raster** — export at 2x or 3x from any browser or vector editor.
  Avoid screenshotting; it defeats the point of vector.

### Editing

Plain hand-written SVG, so it diffs cleanly in git. Colours are per-layer and consistent:

| Layer | Colour | Tint |
|---|---|---|
| Surfaces | `#5B5BD6` | `#EEF0FF` |
| Coworker | `#4F46E5` → `#8B5CF6` gradient | — |
| Knowledge | `#0D9488` | `#CCFBF1` |
| Action | `#EA580C` | `#FFEDD5` |
| Memory | `#7C3AED` | `#EDE9FE` |
| Automation | `#2563EB` | `#DBEAFE` |
| Guardrails | `#059669` | `#ECFDF5` |
| Systems | `#475569` | — |

### Icons

The glyphs are hand-drawn vector paths that *suggest* each system — a speech bubble, a
database cylinder, an envelope. They are **not** official brand marks.

To use real logos (Teams, Azure, PostgreSQL, Salesforce), drop the official assets in
place of the glyph groups. Microsoft publishes an Azure architecture icon set for exactly
this. Worth doing for a customer-facing deck; the generic glyphs are fine internally and
carry no trademark questions.