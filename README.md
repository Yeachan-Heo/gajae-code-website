# Gajae Code Website

Static GitHub Pages website for [Gajae Code](https://github.com/Yeachan-Heo/gajae-code): the external coding-agent forge for shaping tasks, acting in controlled sessions, and proving results with checks and evidence.

## Contents

- `index.html` — landing page using the Gajae Code hero assets.
- `css/styles.css` — shared dark red-claw design system.
- `js/main.js` — mobile navigation, copy buttons, scroll reveal, and docs sidebar behavior.
- `docs/` — static documentation pages:
  - getting started
  - architecture
  - harness
  - bridge & RPC
  - skills
  - receipts
  - Gajae Remote
  - troubleshooting

## Local preview

No build step is required.

```bash
python3 -m http.server 8080
open http://localhost:8080
```

## Deployment

The site is GitHub Pages friendly: serve from the `main` branch root with `.nojekyll` enabled.

## Validation

Before publishing, run a lightweight static sanity check:

```bash
python3 scripts/validate-site.py
```
