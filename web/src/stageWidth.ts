/* The width of the stage on the left, in pixels. The choice is kept on this machine. */
export const STAGE_WIDTH = 440;
const NARROWEST = 300;

/* The stage may take at most 70% of the window, so the list always keeps some room. */
export function fitStage(width: number) {
  return Math.round(Math.min(Math.max(width, NARROWEST), window.innerWidth * 0.7));
}

export function savedStageWidth() {
  const w = Number(localStorage.getItem("stage-width"));
  return w > 0 ? fitStage(w) : STAGE_WIDTH;
}
