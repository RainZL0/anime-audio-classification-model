# Manual identity labels

These files come from a person checking each line's character against the video picture. They cannot be recovered by running the pipeline again, so they must be kept.

The labeling commands are in [docs/USAGE.md](../docs/USAGE.md#labeling), and the labeling rules are in [docs/HISTORY.md](../docs/HISTORY.md#labeling).

| File | Contents |
| --- | --- |
| `ep01-full.json`, `ep02-full.json`, `ep03-full.json` | Manual identities for episodes 1 to 3, from blind labeling, with all character names. They have been imported into the interface and converted to target characters and "Other". Later labels live only in the interface's `runs/labels/`, and are no longer written back here. For how far each episode was labeled, see [STATUS](../docs/STATUS.md#where-things-stand). |
| `names.json` | The list of character names. It has names only, with no clip assignments. The labeling page uses it to sort the clickable names. Check it before labeling a new episode. |
| `coverage-ep01.json` | The labeler's judgments, one by one, on the gaps found by listening to episode 1: places where a whole stretch has dialogue but no clips (keep / do not keep). |
| `legacy/` | Name notes taken in the field before the refactor, and early records made by grouping by ear. Kept for reference, not treated as ground truth. |

In each archive, a clip's `name` is a character name, a special label (`__multiple__`, `__unclear__`, `__not_speech__`), or `null` if the clip has not been labeled yet.

Each press is saved to the archive right away, and an existing archive keeps being used. If the clip boundaries are different, a new file name is required, so old manual work is never overwritten.
