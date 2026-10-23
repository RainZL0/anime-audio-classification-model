# Interface design rules

The rules the labeling web app keeps, so a person learns each thing once. To change how something looks or works, change the rule here first, then the code. How to use each view is in [USAGE.md](USAGE.md#labeling-and-correction-interface).

Two words used below:

- A **chip** is a rounded button with a small picture and a name, like the ones in the bottom bar.
- A **pill** is a small rounded label inside a line of text, like "Confirmed" or "Check 52%".

## What the interface is for

- Avatars are the main way to identify people, and names can be left blank. Until an avatar is cropped, a default picture that is easy to tell apart from the others is shown. Users crop the avatars from the picture themselves.
- Keyboard first. Most of the time, pressing Enter accepts the prediction. Every step can be undone.
- The day color scheme is the default.
- Clips that are hard to call do not get a separate view. Filter them out in Scenes with "Only to do". The Characters view starts with the least confident clips, so the wrong ones can be picked out, and the rest are confirmed with one key.
- When a clip is not similar to any known character, show "may be someone not seen before", and do not force a name onto it.
- **Label only the characters you want.** A user may want one character or several, and may change their mind halfway through. They should not be forced to name every line of the whole episode. Only the target characters get names. Everyone else is "Other". Target characters can be added or removed at any time, and existing labels stay valid. [HOW_IT_WORKS.md](HOW_IT_WORKS.md#labeling-and-correction-interface) explains how it works.

## The same thing looks the same everywhere

- **Same action, same look, same words, same key**, wherever it appears. If a person has learned it in one place, they already know it in the next.
- **"Who is it" choices are chips.** A target character is a chip with its avatar, "Other" a chip with a gray dot, "New character" a chip with a "+". They appear in the bottom bar and under each group in Groups, in the same order (target characters, then "Other", then "New character") and with the same keys shown on them: 1 to 9 for the first nine characters, Q for "Other", N for "New character".
- **The machine's guess of who someone is** is always the same pill: a small avatar, "Closest" and the name, and the chance when there is one. It is used in the line lists, in the "Other" list, and at the top of each group.
- **Keys are shown as key caps** right after the button's words, the same way in the top bar, the bottom bar, dialogs and messages.
- **One thing, one name.** The label for everyone else is called "Other" (「其他」) everywhere, and no character can take that name: typing it where a name is asked for is refused. Two buttons side by side must not start with the same word unless they do the same kind of thing.
- **Picking several uses tick boxes**, as in Groups and Export. Picking one of a few uses a row of joined buttons, as in "Whole episode / Only to do". Picking several must never look like picking one.
- **Selecting and playing are kept apart.** In a list with tick boxes, the box selects and the rest of the row plays the line.

## Color

- **Filled purple** is the step the app suggests next: accept the machine's top guess (Enter), confirm the rest (Shift+Enter), save in a dialog, start an export. No button is purple only to stand out.
- **Light purple background** marks the machine's top guess among the choices (on the left, and under a group) or the item that is selected now.
- Green means confirmed, orange means waiting to be checked, red means low quality. A dashed outline means a hint that may be wrong ("Maybe someone new", "Maybe missed").

## Typing

- **No text box unless typing is the only way.** People pick characters by avatar, chip or key, not by typing names; there is no search box for characters.
- The one place to type a character's name is the "New character" dialog, and there it can be left blank. Renaming and merging are in the Characters view.

## Layout

- The top bar stays on one line and inside the window. When there is not enough room, the progress bar and the training note get shorter; the buttons do not move off screen.
- Choices of the same kind sit together in one row.
- A button that cannot be used yet is shown grayed out, not hidden, so nothing jumps when it becomes usable. For example, the chips under a group stay gray until a line is ticked.
- A count is shown once, next to what it counts, not repeated on every button.
