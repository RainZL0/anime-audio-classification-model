import { tr } from "../language";
import { Tip } from "./Tip";

/* This episode's progress, as parts of 1: confirmed, and the machine's confident guesses. */
export interface Progress {
  done: number;
  auto: number;
}

/* The episode's progress, shown in the summary at the top of Groups and Scenes. */
export function EpisodeProgress({ progress }: { progress: Progress }) {
  return (
    <Tip
      text={tr(
        "绿色是已经确认的，浅绿是机器有把握的",
        "Green is confirmed, light green is the machine's confident ones",
      )}
    >
      <div className="flex items-center gap-2 text-xs whitespace-nowrap text-muted-foreground tabular-nums">
        {tr(
          `确认 ${Math.round(progress.done * 100)}%`,
          `${Math.round(progress.done * 100)}% confirmed`,
        )}
        <div className="flex h-1.5 w-28 overflow-hidden rounded-full bg-muted">
          <i className="block bg-success" style={{ width: `${progress.done * 100}%` }}></i>
          <i className="block bg-success/35" style={{ width: `${progress.auto * 100}%` }}></i>
        </div>
      </div>
    </Tip>
  );
}
