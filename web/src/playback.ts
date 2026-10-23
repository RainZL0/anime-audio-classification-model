/* Playback speeds to choose from. The choice is kept on this machine. */
export const SPEEDS = [1, 1.25, 1.5, 2];

/* L cycles through: normal, 5 more seconds on each side, 15. Matches CONTEXT_SECONDS on the server. */
export const CONTEXTS = [0, 5, 15];

/* Seconds the video clip extends past each end of the line. Matches avoc.app.video.VIDEO_PAD on the server. */
export const VIDEO_PAD = 0.5;

/* What plays with the picture: the separated vocals, or the picture's own sound. */
export type Sound = "vocals" | "original";
