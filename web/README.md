# web/ — new design frontend (HLE-834, Phase 1)

The redesigned UI for create-char-passport, implemented from the Claude Design
handoff (`character-passport-handoff.zip`). Aesthetic: a "production bible /
model sheet" — warm art paper, ink borders, vermilion stamps, blue-pencil AI
assist, halftone grain.

**Status — Phase 1 (HLE-835):** faithful, runnable, clickable frontend with
**sample data** (no backend yet). AI buttons show a shimmering "ИИ думает…"
state while a (simulated) LLM call runs. Phase 2 (HLE-836) wires a FastAPI
backend over the existing `create_char_passport` package and implements the 15
behavioural changes; Phase 3 (HLE-837) deploys it to HF Spaces via Docker.

## Run it locally

It's a React (UMD) + in-browser Babel SPA, so it must be served over HTTP
(not opened as a `file://`):

```bash
python -m http.server 8000 --directory web
# then open http://localhost:8000/
```

## Files

| File | What |
|------|------|
| `index.html` | entry — loads React/Babel + the scripts below |
| `styles.css` | the full design system (tokens, components) |
| `shared.jsx` | reusable components: Stepper, LayerRail, Panel, Field, PromptField, AIButton (with shimmer), Dialog, PresetPicker, TranslateDialog, SceneModal, DebugLastPrompt |
| `app.jsx` | App shell — topbar, stepper, workspace + layer rail, phase router |
| `screens-a/b/c.jsx` | the screens (start / data / passport / emotions / outfit / props) |
| `archive.js` | client-side ZIP stub (real export lands in Phase 2) |

> In-browser Babel prints a "precompile for production" warning — expected for
> the prototype; Phase 2/3 will add a real build step for the Docker image.
