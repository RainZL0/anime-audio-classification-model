# Plan: move the web app to React + TypeScript + Vite

Written 2026-10-24. Not started yet. Why this was chosen is in [DECISIONS.md](DECISIONS.md#settled). When the move is done, the facts on this page go to the docs listed in [Doc changes](#doc-changes), and this page is deleted.

Words used on this page:

- **TypeScript** is JavaScript with types written in the code, so mistakes such as a wrong field name show up before the page runs.
- **Vite** is a tool that turns the TypeScript and JSX source into the plain JavaScript and CSS files a browser can load. This step is called the **build**, and its result is the **built files**.
- **JSX** is the way React code writes HTML-like tags inside JavaScript. It replaces the `` html`...` `` templates of htm.

## Where things are now

- The whole front end is `src/avoc/app/static/`: `app.js` (about 1630 lines, one file), `style.css` (about 390 lines), `index.html`, `favicon.svg`, and Preact with htm in `vendor/`.
- Preact uses the same hooks as React (`useState`, `useEffect` and so on), so the logic carries over. What changes is the template syntax, the file split and the types.
- The server (`src/avoc/app/server.py`) sends `static/index.html` at `/` and serves the folder at `/static/`. Every page file gets `Cache-Control: no-cache`, so the browser always asks whether a file changed.
- Both languages are written inline as `tr(zh, en)`. The page sends its language in the `X-Language` header, and the server answers in it.
- The API answers are plain dicts (`dict[str, Any]`), so FastAPI's description of the API has no field lists to generate types from.

## Rules for the move

- **Same behavior, nothing new.** The move does not change how anything looks or works. Any difference from the old page is a bug. New features wait until after the move.
- **One change.** The old and new front ends do not live side by side. The work happens on one branch and is merged once the check by hand passes.
- **Only common tools.** React, TypeScript, Vite, npm, ESLint, Prettier and Vitest. No state library, no UI component library, no CSS framework. Someone who knows React should be able to read every file.
- **Language handling stays as it is.** `tr(zh, en)` moves into its own file unchanged. Switching to a translation library is a separate question.
- **The designs in [UI_DESIGN.md](UI_DESIGN.md) stay.** `style.css` moves over as it is, with the same class names.

## Folder layout

```text
web/                          front-end source; a normal Node project
  package.json                scripts and dependencies
  package-lock.json           exact versions, committed
  tsconfig.json               strict type checking
  vite.config.ts              build settings and the development proxy
  eslint.config.js
  .prettierrc.json
  index.html                  page shell, keeps the inline dark theme script
  public/favicon.svg          copied into the built files as it is
  src/
    main.tsx                  starts the app
    App.tsx                   the App component: views, keys, state
    api.ts                    calls to /api/... and the types of their answers
    language.ts               lang, tr(), many(), lines()
    format.ts                 stamp, pct, howLong, minutes
    clips.ts                  helpers about clips: confidence, whoOf, pendingOf ...
    components/               Avatar, Pattern, RoleName, Pill, Stage, Row, Cropper, Help ...
    views/                    SceneView, RoleView, GroupsView, ExportView, Welcome, AddEpisode
    style.css
    *.test.ts                 next to the file they test
src/avoc/app/static/          built files only; made by `npm run build`, never edited by hand
  index.html
  favicon.svg
  assets/index.js
  assets/index.css
```

The split of `app.js` follows its current top-level functions: each view and each larger component gets its own file, and small helpers are grouped by topic.

## Build settings

- `vite.config.ts`:
  - `base: "/static/"`, so the page loads its files from where the server serves them.
  - `build.outDir: "../src/avoc/app/static"` and `emptyOutDir: true`, so old built files never linger.
  - Fixed file names without a content hash (`assets/index.js`, `assets/index.css`). The server already makes the browser check every file, so a hash is not needed, and fixed names keep the git history of the built files readable.
  - In development, `/api` and `/media` are passed on to `avoc app` at `http://127.0.0.1:8765`.
- `npm run build` first runs the type check (`tsc -b`), then `vite build`.
- Server: no change in `server.py` is expected, since `index.html` and `favicon.svg` stay at the root of `static/`. The test `test_page_files_are_checked_on_every_load` changes its paths to `/static/assets/index.js` and `/static/assets/index.css`.
- `vendor/` (Preact and htm, with their license file) is deleted.

## How the built files reach users

**The built files are committed to git.** Users keep installing with `git clone` and `uv sync`, as in the [install standard](ROADMAP.md#first-release-standard), and never need Node.

Why not other ways:

- Installing a ready-made package from PyPI would skip git, but a package from PyPI does not carry the `[tool.uv.sources]` setting in `pyproject.toml`. On Windows it would then get the torch build without CUDA.
- Building on the user's machine would make every user install Node.

Rules that come with it:

- `.gitattributes` marks `src/avoc/app/static/**` as `linguist-generated -diff`, the same as `uv.lock`, so diffs and GitHub reviews fold these files away.
- CI builds again and fails if the result differs from what is committed. A contributor who changes `web/` must commit the built files too.
- If two branches both change the built files, git shows a conflict there. Take either side, run `npm run build`, and commit the result.
- The wheel built by `uv build` contains `static/` as it does now, so the one-click Windows package planned after the first release gets the built files too.

## Development

- One-time setup: install Node (current long-term-support version), then `npm --prefix web ci`.
- Day to day: run `uv run avoc app <workspace>` in one terminal and `npm --prefix web run dev` in another, then open the address Vite prints. Edits show up in the page right away. `/api` and `/media` go to the running `avoc app`.
- Before committing: `npm --prefix web run build`, so `avoc app` alone serves the new page and CI's comparison passes.
- Someone who only changes Python needs no Node at all.

## Types

- `tsconfig.json` uses `strict: true` from the start.
- The answers of each `/api/...` call are typed by hand in `api.ts`, read from what `server.py` returns. `any` is not allowed (an ESLint rule), so every field is written down once.
- Generating these types from the server would need the server to declare the shape of each answer (Pydantic response models). That is a possible later step, not part of this move.

## Checks

Scripts in `web/package.json`:

| Script | What it does |
| --- | --- |
| `dev` | Vite development server |
| `build` | type check, then build into `src/avoc/app/static/` |
| `lint` | ESLint, with the TypeScript and React hooks rules |
| `format` / `format:check` | Prettier: rewrite, or only check |
| `typecheck` | `tsc -b` without building |
| `test` | Vitest, run once |
| `check` | `lint`, `format:check`, `typecheck` and `test` in a row |

Tests: start with the pure helpers (`format.ts`, `clips.ts`, `language.ts`). Testing components in a browser-like setting can come later if needed.

The checks section of `CLAUDE.md` gets two lines after the Python ones:

```powershell
npm --prefix web run check
npm --prefix web run build; git diff --exit-code src/avoc/app/static   # after changing web/
```

CI (`.github/workflows/ci.yml`) gets a second job next to the Python one, on Ubuntu: `actions/setup-node` with the npm cache, `npm ci`, `npm run check`, `npm run build`, then `git diff --exit-code src/avoc/app/static`. The Python job does not need Node.

`.gitignore` gets `web/node_modules/`.

## Order of work

1. Set up `web/` with the files above and empty scripts that pass.
2. Move `app.js` into the files of the layout. Change the htm templates to JSX. Change the `/static/vendor/preact-htm.js` import to imports from `react` and `react-dom`. Small differences between Preact and React to watch for: `class` becomes `className`, `for` becomes `htmlFor`, inline `style` strings become objects, and a text field whose `value` is set needs an `onChange` handler, or React makes it read-only.
3. Add the types until `typecheck` passes with no `any`.
4. Build into `static/`, delete `vendor/` and the old `app.js`, and update the test paths.
5. Add the CI job, the `.gitattributes` line and the `.gitignore` line.
6. Check by hand against the old version, side by side (the old one from the last commit before the move, on another port): the four views, every shortcut in Help, undo, the language switch, the dark theme, the avatar cropper, adding an episode with progress and stop, attaching text subtitles, export, and returning to the same spot after a refresh.
7. Change the docs as below, then delete this page.

## Doc changes

| Doc | Change |
| --- | --- |
| [TOOLS.md](TOOLS.md#interface) | Replace the "Preact + htm" line with React, TypeScript and Vite, where the source and built files are, and that users need no Node |
| `CONTRIBUTING.md` (new, at the repo root) | Setup, the two-terminal development loop, the checks, committing the built files, and fixing a conflict in them. Contributors look for this file first |
| `README.md` | One line linking to `CONTRIBUTING.md` |
| `CLAUDE.md` | The two check lines above |
| [HOW_IT_WORKS.md](HOW_IT_WORKS.md#labeling-and-correction-interface) | The sentence "The front end has no build step" becomes: the source is in `web/`, the built files are in `src/avoc/app/static/`. Add `web/` to the file tree there |
| [STATUS.md](STATUS.md) | Remove the step about the move |
| [index.md](index.md) | Remove this page's lines |
