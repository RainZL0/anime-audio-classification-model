# Contributing

Thanks for helping. Start with [docs/index.md](docs/index.md): it lists every doc and what each one covers. Before proposing a different approach, read [docs/DECISIONS.md](docs/DECISIONS.md), which lists what is settled and what was already tried and ruled out.

## Python side

Install [uv](https://docs.astral.sh/uv/) and FFmpeg, then `uv sync --locked`. Before sending a change, run:

```bash
uv run ruff check .
uv run ruff format --check .
uvx ty@0.0.91 check src
uv run pytest -q
```

The type checker is [ty](https://github.com/astral-sh/ty). It is not a project dependency, so `uvx` runs it on the fly, at the version CI uses. Changing only Python needs no Node.

## Web app

The labeling app is React and TypeScript, built with Vite, styled with Tailwind CSS and shadcn/ui components ([why](docs/DECISIONS.md#settled)). The source is in `web/`. The built files in `src/avoc/app/static/` are committed, so people who only install the tool never need Node. Do not edit the built files by hand.

Set up once: install Node (the current long-term-support version), then

```bash
npm --prefix web ci
```

Day to day, run two terminals:

```bash
uv run avoc app WORKSPACE --no-open --reload
```

```bash
npm --prefix web run dev
```

Open the address Vite prints (it ends in `/static/`). Edits in `web/` show up in the page right away; requests to `/api` and `/media` go to the running `avoc app` on port 8765. `--reload` restarts that server whenever a Python file in `src/avoc/` changes (it watches with watchfiles, from the dev dependency group). Each restart loads the workspace again, takes a few seconds, and stops an episode being added, so it is for development only.

Before committing a change in `web/`:

```bash
npm --prefix web run check
npm --prefix web run build
```

`check` runs oxlint (finds likely mistakes), Prettier (code layout; `npm --prefix web run format` fixes it), the type check and the tests. `build` writes `src/avoc/app/static/`; commit those files with your change. CI builds again and fails if they differ from the source.

If two branches both changed the built files, git shows a conflict there. Take either side, run `npm --prefix web run build`, and commit the result.

Browser tests open the real page in your installed Chrome, against a small made-up workspace, and click through it (Playwright). They need uv too, which starts the server for them. Run them after a change to how the page looks or works:

```bash
npm --prefix web run e2e
```

Style with Tailwind classes in the markup; there is no hand-written stylesheet. Use only the theme's color names (`bg-muted`, `text-success` and so on, set in `web/src/index.css`), never fixed colors. Before writing a new widget, look in `web/src/components/` for a shared one (`Choice`, `Chip`, `Tip`, `Note`…). To add a shadcn component:

```bash
npx --prefix web shadcn@latest add COMPONENT -c web
```

It is copied into `web/src/components/ui/`, where it can be changed like any other file; say so in a comment at the top when you do.

## Pictures and videos

No pictures, GIFs or videos are committed, so `git clone` stays small. Upload them as attachments to a comment on the GitHub issue for media, and link to their addresses from the Markdown.

The demo GIF at the top of the README is recorded by a script, so it can be made again after the interface changes: [web/demo/demo.spec.ts](web/demo/demo.spec.ts) says how.

## README

The README comes in English (`README.md`) and Simplified Chinese (`README.zh.md`). When you change one, change the other in the same commit. The other docs are in English only.

## Text in the web app

Both languages are written side by side as `tr(Chinese, English)` where the text is used. Use the terms in the [glossary](docs/HOW_IT_WORKS.md#glossary), and follow the design rules in [docs/UI_DESIGN.md](docs/UI_DESIGN.md).
