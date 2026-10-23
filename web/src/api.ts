import { currentLanguage } from "./language";

/* ───────────── What the server sends back ─────────────
   Written by hand from src/avoc/app/server.py. When an answer there changes, change it here too. */

/* Where a line stands: confirmed by a person, the machine is confident, needs a person to check, too short for a
   voiceprint, no model yet, or a short line skipped by default. */
export type Status = "confirmed" | "auto" | "review" | "novoice" | "unlabeled" | "skipped";

export interface Guess {
  name: string;
  p: number;
}

/* One line, as AppState.view writes it. */
export interface Clip {
  id: string;
  episode: string;
  start: number;
  end: number;
  duration: number;
  gap: number | null;
  text: string;
  scene: number;
  voiced: boolean;
  label: string | null;
  rejects: string[];
  unusable: boolean;
  guess: Guess[];
  familiar: boolean | null;
  status: Status;
  /* Only in the Characters view's list: not given to this character, but it might be them. */
  maybe?: boolean;
}

/* Lines confirmed, lines the machine gave them, and the seconds of the confirmed ones. */
export interface Counts {
  confirmed: number;
  predicted: number;
  seconds: number;
  low_seconds: number;
}

export interface Role extends Counts {
  name: string;
  named: boolean;
  pattern: number;
  target: boolean;
  color?: string | null;
  avatar?: string | null;
}

/* The characters by name. A name may be missing: a label can name a character that has just been renamed. */
export type Roles = Record<string, Role | undefined>;

export interface TextSubtitleInfo {
  file: string;
  offset: number | null;
  agreement: number | null;
  marked: string | null;
}

export interface Episode {
  name: string;
  video: boolean;
  offset: number | null;
  counts: Partial<Record<Status, number>>;
  text_subtitles: TextSubtitleInfo | null;
}

export interface Model {
  labels?: number;
  roles?: number;
  seconds?: number;
  familiar_threshold?: number | null;
  auto_confidence: number;
}

/* The overview: /api/state. */
export interface Summary {
  episodes: Episode[];
  workspace: string;
  skipped: Record<string, string>;
  roles: Role[];
  other: Counts;
  model: Model;
  can_undo: boolean;
}

/* The answer to a label change, an undo or a character change. */
export interface ChangeResult {
  batch: number | null;
  undo?: boolean;
  updated: Clip[];
  ripple: number;
  state: Summary;
  /* Only when a new character was made: its name. */
  role?: string;
}

export interface Group {
  size: number;
  seconds: number;
  hint: { name: string; share: number } | null;
  clips: Clip[];
}

/* One machine check, the same as a line of `avoc doctor`. */
export interface Check {
  ok: boolean;
  text: string;
  fix: string;
  required: boolean;
}

export interface SubtitleStyle {
  name: string;
  lines: number;
  first: number;
  last: number;
  samples: string[];
}

/* What the server read from a subtitle file: /api/subtitle-styles. */
export interface SubtitleStyles {
  format: string;
  encoding: string;
  styles: SubtitleStyle[];
  picked: string[];
  marked: string | null;
}

/* The server's job that adds an episode: /api/add. */
export interface Adding {
  state: "idle" | "running" | "done" | "failed" | "stopped";
  episode: string | null;
  lines: string[];
  errors: string[];
  bar: string | null;
  seconds: number;
}

export interface ExportResult {
  out: string;
  files: number;
  total_sec: number;
  rejected: Record<string, number>;
}

/* ───────────── Talking to the server ───────────── */

/* Every request says which language the page is in, so the server's messages come back in it too. */
export async function call<T>(url: string, body?: unknown): Promise<T> {
  const lang = currentLanguage();
  const response = await fetch(
    url,
    body === undefined
      ? { headers: { "X-Language": lang } }
      : {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Language": lang },
          body: JSON.stringify(body),
        },
  );
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = ((await response.json()) as { detail?: string }).detail || detail;
    } catch {
      /* Not JSON: keep the status text. */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export type MediaKind = "audio" | "video";

export const media = (kind: MediaKind, id: string, context = 0) =>
  `/media/${kind}/${id}.${kind === "audio" ? "wav" : "mp4"}${context ? `?context=${context}` : ""}`;

/* Fetch the next few clips' media ahead of time: the server cuts it on demand, so asking early means it is
   already cut by the time you get there. */
const warmed = new Set<string>();
export function warm(clips: (Clip | undefined)[], kind: MediaKind) {
  for (const clip of clips) {
    if (!clip) continue;
    const url = media(kind, clip.id);
    if (warmed.has(url)) continue;
    warmed.add(url);
    fetch(url, { priority: "low" }).catch(() => warmed.delete(url));
  }
}
