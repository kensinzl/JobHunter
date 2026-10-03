# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
venv/bin/pip install -r requirements.txt      # deps (venv already exists); make install
venv/bin/python -m pytest test_smoke.py -q    # all tests (fast, no network); make test
venv/bin/python -m pytest test_smoke.py::test_split_output -v   # single test
venv/bin/python main.py                     # run at http://127.0.0.1:8000; make dev
venv/bin/python main.py --test-scrape       # live scraper smoke (hits Seek/LinkedIn for real)
lsof -ti :8000 | xargs kill                   # port already in use → kill stale server
```

Config lives in `.env` (`OPEN_AI_KEY`, optional `GLM_MODEL`, default glm-4.6). Tests never hit the network; they redirect the DB via the `JOBSEEKER_DB` env var before importing server. The Makefile is macOS/Linux only (venv paths differ on Windows).

**The server does not hot-reload.** After editing `server.py`, kill and restart it — a stale process silently runs old code (this has caused real "my change does nothing" confusion).

## Architecture

Three code files do everything; keep it that way (no new files without reason — `assets/` holds the donation QR images, that's it):

- `server.py` — FastAPI backend, ordered: sqlite storage (`kv` key-value, `jobs`, `generations` tables; schema auto-created on every `db()` call) → `ATS_RULES` constant → skill word-table (`SKILLS`, `skill_match`) → seniority levels (`LEVELS`) → scrapers → extraction/cleanup (`extract_upload`, `fix_broken_ligatures`) → profile (`render_profile`, `profile_or_master`, `/api/profile/from_cv`) → CRUD + `/api/jobs/{id}/match` + `/api/jobs/{id}/draft` + `/api/render_pdf` → scoring (`SCORER_RUBRICS`, `local_checks`, `/api/score`) → GLM generation (`build_prompt`, `glm_chat`, `/api/jobs/{id}/generate`, `verify_generation`, `compute_dropped`).
- `index.html` — single-page vanilla-JS frontend (LinkedIn-styled), talks only to `/api/*`. Generated docs render via the tiny `md()` markdown subset (h1-h3, bold, bullets); print CSS exports only `#preview`.
- `test_smoke.py` — pure-logic tests plus TestClient endpoint tests with pre-seeded DB rows. External HTTP goes through `--test-scrape` manually, never in tests.

Fact source: the structured `profile` kv (edited on the Profile tab, auto-extracted from the first CV upload via GLM) rendered to markdown by `render_profile`, falling back to raw `cv_master` when profile is empty (`profile_or_master`). `fact_base` = that + `cv_extra`.

Generation flow (two-phase, user gates everything): 生成 button → `GET /match` (local word-table compare, instant) → panel shows have/miss skills → user checks skills they actually have → optional `POST /draft` (GLM drafts one description per checked skill; user edits + ✓/✗ each) → `POST /generate` with `extra` (hand-written note, **persists into cv_extra**) and `extra_once` (approved drafts, **this generation only**). Un-checked skills are forbidden to the model (rule 13); `===ADDED SKILLS===` output is a tripwire, not a permission. After generation, `verify_generation` (dates/employers/knockout-info/links) and `compute_dropped` (skills & whole experiences the model trimmed for JD focus) run as deterministic string checks — the design philosophy is **code verifies, the model only generates** (LLM self-reporting proved unreliable).

Other data flow: user prefs live in kv (`prefs` JSON). `/api/search` scrapes both sites → dedup by UNIQUE(company,title) → filters by exclude keywords and `LEVELS`. JD is fetched lazily at generate time, not at search time (avoids hammering detail pages). Generation output is split on the literal `===COVER LETTER===` delimiter.

## Gotchas

- **LinkedIn**: the guest API (`jobs-guest/jobs/api/...`) returns 404 — it's blocked. `scrape_linkedin` scrapes the public SSR search page (`/jobs/search`) instead, parsed by `parse_linkedin_cards`. No Playwright/headless anywhere: headless browsers get bot-blocked; that's a deliberate constraint from the spec.
- **Seek**: uses the unofficial `api/jobsearch/v5/search` endpoint; if it 404s the version moved — check DevTools on seek.com.au and bump the path. `worktype` codes: 242 full-time, 243 part-time, 244 contract. Seek has no seniority facet — `LEVELS` filters by title words, and titles with no level marker are deliberately kept; LinkedIn gets the native `f_E` param.
- **GLM**: OpenAI-compatible endpoint at open.bigmodel.cn. All calls are slow — scoring ~2 min, profile extraction ~2 min, skill drafting ~1 min; timeout is 600s. Responses may wrap JSON in fences or prose — always parse via `parse_json_response` (extracts a `{...}` object, so prompts must ask for an object, not a bare array).
- **ATS logic**: generation rules (`ATS_RULES`) and the five per-platform scoring rubrics (`SCORER_RUBRICS`) are research-backed — evidence and design history in `docs/ats-research.md`. Update the doc when changing the rules. The fabrication line is now opt-in only: the model may never add skills the user didn't check (rule 13 is a prohibition; user-approved supplements are the only channel).
- **PDF export** (`/api/render_pdf`, fpdf2): produces a text-layer PDF (ATS-parseable — never switch to a rasterizing approach). `PDF_FONT_DIR` points at macOS system fonts; Arial has no CJK glyphs — swap to Arial Unicode.ttf for Chinese CVs, and fix the path when deploying off macOS. Word export is the HTML-disguised-as-.doc trick, done client-side.
- **`fix_broken_ligatures`**: repairs the broken Word/Calibri PDF CMap signature (ti→Q, ft→K, tt→e in URLs). The patterns are deliberately narrow (jQuery/McKinsey/Kubernetes must survive) — widen only with a failing test in hand.
- `local_checks` deliberately ignores `|` in the first 5 lines of a CV (contact-line pipes are ATS-safe); only multi-pipe body lines count as tables.
