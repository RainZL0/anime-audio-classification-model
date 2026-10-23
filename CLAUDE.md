# anime-voice-sorter

Collects an anime character's lines, one character at a time. For the project overview, see `README.md`.

## Before you start

1. `docs/STATUS.md`: where things stand now, what is being tested, and the next steps.
2. `docs/DECISIONS.md`: approaches that are settled and approaches that were ruled out. **Do not reopen a ruled-out path.** To overturn one, bring new data first.
3. `docs/HISTORY.md`: working rules, especially the two sections on scoring and labeling.

Other docs are found through `docs/index.md`. That page also says what each doc covers and what it does not, and how to maintain them. **One fact is written in one place only. Elsewhere, only a link.**

## Language

Use plain, easy words. **Do not invent abbreviations, and do not use jargon.** Docs, code comments and CLI output are written in plain English with no jargon. The web app has Chinese and English versions. Use the terms in the glossary in `docs/HOW_IT_WORKS.md`. When a borrowed metric name first appears, explain in one sentence what it measures.

## Checks

```powershell
uv run ruff check .
uv run ruff format --check .
ty check src
uv run pytest -q
lychee --offline --no-progress CLAUDE.md docs   # after changing docs
```
