/* What the voices are collected for. Reading text aloud (GPT-SoVITS) needs the words
   actually said, in the language spoken; voice conversion (RVC) needs only the sound. With "audio", the page leaves
   out everything about that text: "No text to export" and its reasons. The choice is kept on
   this machine, like the page language; the caller re-renders the page after a change. Sound only is the default,
   as it asks the least of the person. */

export type Purpose = "tts" | "audio";

let purpose: Purpose = localStorage.getItem("purpose") === "tts" ? "tts" : "audio";

export const currentPurpose = (): Purpose => purpose;

/* Whether the page shows what export needs in the language spoken. */
export const needsText = () => purpose === "tts";

export function setPurpose(next: Purpose) {
  purpose = next;
  localStorage.setItem("purpose", next);
}
