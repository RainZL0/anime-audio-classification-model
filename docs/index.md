# Documentation index

## Plans

| What you want to know | Read | Main sections |
| --- | --- | --- |
| Where things stand now, and what comes next | [STATUS.md](STATUS.md) | [Questions being tested](STATUS.md#questions-being-tested), [Next steps](STATUS.md#next-steps), [Where the files are](STATUS.md#where-the-files-are) |
| Goals, direction and standards up to the first release | [ROADMAP.md](ROADMAP.md) | [Direction](ROADMAP.md#direction), [Labeling interface](ROADMAP.md#labeling-interface), [First release standard](ROADMAP.md#first-release-standard) |
| How the web app moves to React + TypeScript + Vite (temporary, deleted when done) | [FRONTEND_MIGRATION.md](FRONTEND_MIGRATION.md) | [How the built files reach users](FRONTEND_MIGRATION.md#how-the-built-files-reach-users), [Checks](FRONTEND_MIGRATION.md#checks), [Order of work](FRONTEND_MIGRATION.md#order-of-work) |
| Similar tools, and what they lack | [COMPETITORS.md](COMPETITORS.md) | [Bottom line first](COMPETITORS.md#0-bottom-line-first), [Dataset format expected by training](COMPETITORS.md#2-dataset-format-expected-by-training) |

## Usage and how it works

| What you want to know | Read | Main sections |
| --- | --- | --- |
| How to type the commands | [USAGE.md](USAGE.md) | [Processing a new episode](USAGE.md#processing-a-new-episode), [Labeling and correction interface](USAGE.md#labeling-and-correction-interface) |
| How things work, and what the terms mean | [HOW_IT_WORKS.md](HOW_IT_WORKS.md) | [Glossary](HOW_IT_WORKS.md#glossary), [Flow](HOW_IT_WORKS.md#flow), [Labeling and correction interface](HOW_IT_WORKS.md#labeling-and-correction-interface), [Data files](HOW_IT_WORKS.md#data-files) |
| What is cleaned from subtitle text, and what to do when it warns about marks | [SUBTITLES.md](SUBTITLES.md) | [Way 1: convert the file to the plain subtitle format](SUBTITLES.md#way-1-convert-the-file-to-the-plain-subtitle-format), [Way 2: add a rule](SUBTITLES.md#way-2-add-a-rule) |
| Dependencies, models, runtime environment | [TOOLS.md](TOOLS.md) | |
| How the web app must look and behave, so each thing is learned once | [UI_DESIGN.md](UI_DESIGN.md) | [The same thing looks the same everywhere](UI_DESIGN.md#the-same-thing-looks-the-same-everywhere), [Color](UI_DESIGN.md#color), [Typing](UI_DESIGN.md#typing) |

## Conclusions

| What you want to know | Read | Main sections |
| --- | --- | --- |
| Which approaches are settled, and which paths were ruled out | [DECISIONS.md](DECISIONS.md) | [Settled](DECISIONS.md#settled), [Ruled out](DECISIONS.md#ruled-out) |

## What each doc covers

One fact is written in one place only. Elsewhere, only a link.

| Doc | Only covers | Does not cover |
| --- | --- | --- |
| STATUS | Current numbers, questions being tested, next steps, files in use now | Settled approaches, experiment process, long-term route |
| ROADMAP | Goals, users, direction, interface plans, release standards and how to release, all for the first release | Next steps for now, experiment numbers, interface design rules |
| FRONTEND_MIGRATION | The plan for moving the web app: folder layout, how built files are shipped, checks, order of work, doc changes | Why it was chosen (DECISIONS), the current front end's tools (TOOLS) |
| COMPETITORS | Similar tools, training-side formats, survey date, and what was not verified | Our own plans |
| USAGE | Commands and options | Why these were chosen |
| HOW_IT_WORKS | Terms, flow, data formats | Rules, experiment numbers |
| DECISIONS | Settled and ruled-out technical choices, each with one reason | Numeric details, approaches not fully tested yet |
| SUBTITLES | The caption habits removed from subtitle text, the warning about unknown marks, the plain subtitle format | Reading encodings and picking styles (HOW_IT_WORKS), command options (USAGE) |
| TOOLS | What each dependency and model is, and how it is connected | Which one is good or bad |
| UI_DESIGN | Design rules of the web app: what looks the same, colors, when to type, layout | How to use each view (USAGE), how it works inside (HOW_IT_WORKS) |

When maintaining: if the plan for now changes, change STATUS. If the route changes, change ROADMAP. While a question is being tested, its numbers stay in STATUS. When it is settled, the conclusion goes into DECISIONS and the numbers are removed. An approach that is overturned is changed directly or moved into "Ruled out", and no running log is kept. When a new doc is added, add a line for it in the matching section of this page. When one kind of doc grows past 8 files, split it into its own index page. After changing docs, run `lychee --offline --no-progress CLAUDE.md docs` and fix any broken links. Dropping `--offline` also checks the web links.

## How to write

Use plain, easy words. Do not invent abbreviations, and do not use jargon. The first time a borrowed metric name appears, explain in one sentence what it measures. All such terms are collected in the [glossary](HOW_IT_WORKS.md#glossary). Measured facts, guesses that explain them, and plans not yet carried out must be written separately.
