/* What the voices are collected for. Reading text aloud (GPT-SoVITS) needs the words
   actually said, in the language spoken; voice conversion (RVC) needs only the sound. With "audio", the page leaves
   out everything about that text: "No text to export" and its reasons. It is chosen once, in the add form before
   the first episode, and kept in the workspace (`purpose` in the state); switching midway is not supported yet.
   Until it is chosen, the add form's pick is kept here, starting at reading text aloud, the choice that keeps both
   ways open. The caller re-renders the page after a change. */

export type Purpose = "tts" | "audio";

let purpose: Purpose = "tts";

export const currentPurpose = (): Purpose => purpose;

/* Whether the page shows what export needs in the language spoken. */
export const needsText = () => purpose === "tts";

export function setPurpose(next: Purpose) {
  purpose = next;
}
