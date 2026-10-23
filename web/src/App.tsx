import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  call,
  media,
  warm,
  type Adding,
  type ChangeResult,
  type Clip,
  type Group,
  type Roles,
  type Summary,
} from "./api";
import {
  lowTip,
  maybeListOf,
  NEEDS_WORK,
  otherName,
  OTHER,
  pendingOf,
  type LabelText,
} from "./clips";
import { Avatar } from "./components/Avatar";
import { Cropper } from "./components/Cropper";
import { Guide, GUIDE_SEEN } from "./components/Guide";
import { Help } from "./components/Help";
import { LanguageButton } from "./components/LanguageButton";
import { RoleName } from "./components/RoleName";
import { Stage } from "./components/Stage";
import { currentLanguage, lines, many, setLanguage, tr } from "./language";
import { CONTEXTS, SPEEDS, type Sound } from "./playback";
import { AddDialog } from "./views/AddEpisode";
import { ExportView } from "./views/ExportView";
import { GroupsView, type KeyedGroup, type Picked } from "./views/GroupsView";
import { RoleView } from "./views/RoleView";
import { SceneView } from "./views/SceneView";
import { Welcome } from "./views/Welcome";

type View = "groups" | "scene" | "roles" | "export";
const VIEWS: View[] = ["groups", "scene", "roles", "export"];
/* A list request was overtaken by a later one. Its result is dropped; this is not an error. */
const STALE = new Error("stale");
/* The position saved after # in the address when the page opened; see where App writes it back. */
const saved = new URLSearchParams(location.hash.slice(1));

/* Shortcuts stay off while the keys go into a text box or a menu. A tick box is not typed into, so they still
   work after ticking a line. */
const typing = (el: EventTarget | null) => {
  if (!(el instanceof HTMLElement)) return false;
  return (
    el.tagName === "SELECT" ||
    el.tagName === "TEXTAREA" ||
    (el instanceof HTMLInputElement && !["checkbox", "radio", "button", "range"].includes(el.type))
  );
};

interface ToastState {
  message: string;
  isError: boolean;
  /* Show an Undo button with it. */
  extra: boolean;
}

/* The avatar dialog: whose avatar, what to do after it closes, and for a new character, the name box. */
interface Crop {
  name: string;
  then: (() => void) | null;
  naming?: boolean;
  /* Whether the picture on the stage belongs to the new character's lines. */
  frame?: boolean;
}

/* ───────────── Main ───────────── */

export function App() {
  const [state, setState] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("scene");
  const [episode, setEpisode] = useState<string | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [focus, setFocusState] = useState<string | null>(() => saved.get("clip"));
  /* The newest focus, set at once. Keys pressed faster than the page draws read it, so each press acts on the
     line the press before moved to, not on the one still on screen. */
  const focusNow = useRef(focus);
  const setFocus = useCallback(
    (next: string | null | undefined | ((f: string | null) => string | null | undefined)) => {
      const value = typeof next === "function" ? next(focusNow.current) : next;
      focusNow.current = value ?? null;
      setFocusState(focusNow.current);
    },
    [],
  );
  const [onlyWork, setOnlyWork] = useState(() => saved.get("only") === "1");
  /* Whether Whole episode lists the short lines skipped by default (status "skipped"); labeled ones always show. */
  const [showShort, setShowShort] = useState(() => localStorage.getItem("show-short") === "1");
  const [role, setRole] = useState<string | null>(null);
  const roleNow = useRef(role);
  roleNow.current = role;
  const [groups, setGroups] = useState<KeyedGroup[]>([]);
  const [groupsLoading, setGroupsLoading] = useState(false);
  /* The ticked lines in Groups, per group. Kept here because the keys label them too. Like focusNow, the newest
     ticks are kept in a ref as well, so a second quick key press doesn't label the same lines again. */
  const [picked, setPickedState] = useState<Picked>({});
  const pickedNow = useRef(picked);
  const setPicked = useCallback((next: Picked | ((p: Picked) => Picked)) => {
    pickedNow.current = typeof next === "function" ? next(pickedNow.current) : next;
    setPickedState(pickedNow.current);
  }, []);
  const [help, setHelp] = useState(false);
  const [guide, setGuide] = useState(false);
  /* The server's job that adds an episode (see AddEpisode), and whether its dialog is open. */
  const [adding, setAdding] = useState<Adding | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [busy, setBusy] = useState(false);
  const [sound, setSound] = useState<Sound>(() =>
    localStorage.getItem("sound") === "original" ? "original" : "vocals",
  );
  const [speed, setSpeed] = useState(() => {
    const s = Number(localStorage.getItem("speed"));
    return SPEEDS.includes(s) ? s : 1;
  });
  /* Extra seconds played around each line, see CONTEXTS. The choice is kept on this machine. */
  const [context, setContext] = useState(() => {
    const c = Number(localStorage.getItem("context"));
    return CONTEXTS.includes(c) ? c : 0;
  });
  const nextContext = () =>
    setContext((c) => CONTEXTS[(CONTEXTS.indexOf(c) + 1) % CONTEXTS.length]);
  const [flashes, setFlashes] = useState(() => new Set<string>());
  const [playing, setPlaying] = useState(false);
  const [crop, setCrop] = useState<Crop | null>(null);
  const [theme, setTheme] = useState(() => localStorage.getItem("theme") || "light");
  /* Only here to re-render everything when the language changes; the strings read the module's language. */
  const [language, setLanguageState] = useState(currentLanguage());
  const dockOrder = useRef<string[]>([]);
  const playerRef = useRef<HTMLMediaElement | null>(null);
  const refAudio = useRef<HTMLAudioElement>(null);
  const toastTimer = useRef(0);
  const stableOrder = useRef<string[] | null>(null);
  const loadSeq = useRef(0);

  const roles: Roles = useMemo(
    () => Object.fromEntries((state?.roles || []).map((r) => [r.name, r])),
    [state],
  );
  /* How labels that are not character names are shown; for now only "other". `tr` reads the language, which
     `language` follows. */
  const labelText: LabelText = useMemo(
    () => ({ [OTHER]: tr("其他", "Other") }),
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- see above
    [language],
  );
  const episodeInfo = state?.episodes.find((e) => e.name === episode);
  /* The order of the bottom bar stays fixed for the session, with new characters added at the end, so number keys
     don't move under your hand. It is filled in while rendering, so a new character shows up at once without
     waiting for the next refresh. Names that are gone can stay in the order. On a rename the new name first takes
     the place right after the old one; see renameRole. */
  if (state) {
    const known = new Set(dockOrder.current);
    for (const r of state.roles) if (!known.has(r.name)) dockOrder.current.push(r.name);
  }
  /* The bottom bar holds only target characters; number keys follow its order. */
  const dock = dockOrder.current.filter((n) => roles[n]?.target);
  const totalConfirmed = state ? state.roles.reduce((s, r) => s + r.confirmed, 0) : 0;
  const firstRun = !!state && totalConfirmed === 0;

  useEffect(() => {
    if (theme === "dark") document.documentElement.dataset.theme = "dark";
    else delete document.documentElement.dataset.theme;
    localStorage.setItem("theme", theme);
  }, [theme]);
  useEffect(() => {
    localStorage.setItem("show-short", showShort ? "1" : "0");
  }, [showShort]);
  useEffect(() => {
    localStorage.setItem("sound", sound);
  }, [sound]);
  useEffect(() => {
    localStorage.setItem("speed", String(speed));
  }, [speed]);
  useEffect(() => {
    localStorage.setItem("context", String(context));
  }, [context]);
  /* Write where you are after # in the address, so a refresh comes back to the same view, episode, character
     and line. */
  useEffect(() => {
    if (!state) return;
    const at = new URLSearchParams({
      view,
      ep: episode || "",
      role: role || "",
      clip: focus || "",
      only: onlyWork ? "1" : "",
    });
    for (const [k, v] of [...at]) if (!v) at.delete(k);
    history.replaceState(null, "", `#${at}`);
  }, [state, view, episode, role, focus, onlyWork]);

  const showToast = useCallback((message: string, isError = false, extra = false) => {
    clearTimeout(toastTimer.current);
    setToast({ message, isError, extra });
    toastTimer.current = setTimeout(() => setToast(null), isError ? 6000 : 3800);
  }, []);

  /* Switch the page language. The overview is fetched again because it holds a few messages from the server,
     such as why an episode was not loaded. */
  const switchLanguage = () => {
    setLanguage(currentLanguage() === "en" ? "zh" : "en");
    setLanguageState(currentLanguage());
    call<Summary>("/api/state")
      .then(setState)
      .catch(() => {});
  };

  useEffect(() => {
    call<Summary>("/api/state")
      .then((s) => {
        setState(s);
        const ep = saved.get("ep");
        if (s.episodes.length)
          setEpisode(ep && s.episodes.some((e) => e.name === ep) ? ep : s.episodes[0].name);
        const r = saved.get("role");
        if (r === OTHER || s.roles.some((x) => x.name === r)) setRole(r);
        const v = saved.get("view") as View | null;
        if (v && VIEWS.includes(v)) setView(v);
        else if (!s.roles.some((r) => r.confirmed > 0)) setView("groups");
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  /* Follow an episode being added. When it ends, the overview is fetched again, since the server has reloaded the
     workspace with the new episode. */
  useEffect(() => {
    call<Adding>("/api/add")
      .then(setAdding)
      .catch(() => {});
  }, []);
  const addingState = adding?.state;
  useEffect(() => {
    if (addingState !== "running") return;
    const timer = setInterval(
      () =>
        call<Adding>("/api/add")
          .then(setAdding)
          .catch(() => {}),
      1500,
    );
    return () => clearInterval(timer);
  }, [addingState]);
  /* However it ended (done, failed, or stopped from the dialog), fetch the overview again: a new episode, or one
     left unfinished, shows up only then. */
  const addingBefore = useRef(addingState);
  useEffect(() => {
    const before = addingBefore.current;
    addingBefore.current = addingState;
    if (before !== "running" || addingState === "running" || !adding) return;
    call<Summary>("/api/state")
      .then(setState)
      .catch(() => {});
    if (addingState === "done")
      showToast(tr(`${adding.episode} 加好了`, `${adding.episode} is added`));
    else if (addingState === "failed")
      showToast(
        tr(
          `${adding.episode} 没加成，点「加一集」看原因`,
          `${adding.episode} failed; open "Add an episode" to see why`,
        ),
        true,
      );
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- only when the job's state changes
  }, [addingState]);
  /* The first episode added from the welcome page: open it, starting in Groups. */
  useEffect(() => {
    if (state && !episode && state.episodes.length) {
      setEpisode(state.episodes[0].name);
      if (!state.roles.some((r) => r.confirmed > 0)) setView("groups");
    }
  }, [state, episode]);
  const openEpisode = (name: string) => {
    setAddOpen(false);
    setEpisode(name);
  };

  /* Fetch the list again on a new episode, view or character. Once fetched its order stays fixed: labeled lines
     stay where they are instead of jumping away. */
  const hasState = !!state;
  const load = useCallback(async () => {
    if (!hasState) return;
    /* Use only the latest request: an earlier one that comes back later must not overwrite an episode, view
       or character that has already changed. */
    const seq = ++loadSeq.current;
    const get = async <T,>(url: string) => {
      const result = await call<T>(url);
      if (seq !== loadSeq.current) throw STALE;
      return result;
    };
    if (view === "scene" && episode) {
      const list = await get<Clip[]>(`/api/clips?episode=${encodeURIComponent(episode)}`);
      setClips(list);
      stableOrder.current = null;
      setFocus((f) =>
        list.some((c) => c.id === f)
          ? f
          : (list.find((c) => NEEDS_WORK.has(c.status)) || list[0])?.id,
      );
    } else if (view === "roles" && role) {
      const list = await get<Clip[]>(`/api/clips?role=${encodeURIComponent(role)}`);
      setClips(list);
      setFocus((f) =>
        list.some((c) => c.id === f)
          ? f
          : (pendingOf(list)[0] || maybeListOf(list)[0] || list[0])?.id,
      );
    } else if (view === "roles") {
      /* No character open, for example after the open one was undone: no list, and no line on the stage. */
      setClips([]);
    } else if (view === "groups" && episode) {
      setGroupsLoading(true);
      let found: KeyedGroup[];
      try {
        found = (await get<Group[]>(`/api/groups?episode=${encodeURIComponent(episode)}`)).map(
          (g, i) => ({ ...g, key: i }),
        );
      } finally {
        if (seq === loadSeq.current) setGroupsLoading(false);
      }
      setGroups(found);
      setPicked({});
      setClips(found.flatMap((g) => g.clips));
      setFocus((f) =>
        found.some((g) => g.clips.some((c) => c.id === f)) ? f : found[0]?.clips[0]?.id,
      );
    }
  }, [view, episode, role, hasState, setFocus, setPicked]);
  const reload = () =>
    load().catch((e: Error) => {
      if (e !== STALE) showToast(e.message, true);
    });
  /* Clear the old list when the view, episode or character changes: its lines don't always fit the new view (for
     example lines without a guess in the Characters view), and until the new list comes, keys and "Confirm the
     rest" must not act on the old one under the new name. */
  useEffect(() => {
    /* Keep the same empty list when it is already empty, so React has nothing to draw again. */
    setClips((c) => (c.length ? [] : c));
    setGroups((g) => (g.length ? [] : g));
  }, [view, episode, role]);
  useEffect(() => {
    reload();
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- `load` changes exactly when the list must be fetched
  }, [load]);
  useEffect(() => {
    /* Also when the open character is gone, for example after undoing the step that made or renamed it. */
    const gone = role && role !== OTHER && state && !state.roles.some((r) => r.name === role);
    if (view === "roles" && (!role || gone) && state?.roles.length) setRole(state.roles[0].name);
    else if (gone) setRole(null);
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- only when the view or the overview changes
  }, [view, state]);

  /* The order "next / previous line" follows in the current view */
  const order = useMemo(() => {
    if (view === "scene") {
      if (!onlyWork)
        return clips.filter((c) => showShort || c.status !== "skipped").map((c) => c.id);
      if (!stableOrder.current)
        stableOrder.current = clips.filter((c) => NEEDS_WORK.has(c.status)).map((c) => c.id);
      return stableOrder.current;
    }
    if (view === "roles") {
      return [
        ...pendingOf(clips),
        ...maybeListOf(clips),
        ...clips.filter((c) => c.label === role),
      ].map((c) => c.id);
    }
    if (view === "groups")
      return groups.flatMap((g) => g.clips.filter((c) => !c.label).map((c) => c.id));
    return [];
  }, [view, clips, onlyWork, showShort, role, groups]);
  /* Drop the old order right when switching, so the next computed order is the one that stays. Doing it in an
     effect clears it only after the order is computed: labeling the first line recomputes the order, and the
     line just labeled disappears from the list. */
  const toggleOnlyWork = (on: boolean) => {
    stableOrder.current = null;
    setOnlyWork(on);
  };

  const byId = useMemo(() => Object.fromEntries(clips.map((c) => [c.id, c])), [clips]);
  /* When the Scenes view filters out the focused line, the stage stays empty, so shortcuts can't change a line
     you can't see in the list. */
  const shownClip = (id: string | null): Clip | null =>
    id && (view !== "scene" || order.includes(id)) ? (byId[id] ?? null) : null;
  const current = shownClip(focus);
  /* What the shortcuts and buttons act on; see focusNow. */
  const now = () => shownClip(focusNow.current);

  useEffect(() => {
    if (!focus) return;
    const at = order.indexOf(focus);
    if (at < 0) return;
    const next = order.slice(at + 1, at + 4).map((id) => byId[id]);
    if (episodeInfo?.video) warm(next, "video", context);
    if (!episodeInfo?.video || sound === "vocals") warm(next, "audio", context);
    /* The server first cuts the clips within a minute of this line in the background, then on to the end of the
       episode. While J/K is held down to flip fast, only the line you stop on is sent. */
    const wait = setTimeout(() => call("/api/prefetch", { clip: focus }).catch(() => {}), 300);
    return () => clearTimeout(wait);
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- only on moving to another line, not on every save
  }, [focus, order, context]);

  /* The Groups order only has unlabeled lines. When a labeled one is open, find next and previous by its place
     in the group. */
  const groupIds = useMemo(() => groups.flatMap((g) => g.clips.map((c) => c.id)), [groups]);
  /* What the number keys, Q, N and the bottom bar label: in Groups the ticked lines if there are any, else the
     line playing. The ticks are used up, so the next press goes to the line playing. */
  const keyTargets = () => {
    if (view !== "groups") return undefined;
    const ticked = groups.flatMap((g) =>
      g.clips.filter((c) => !c.label && pickedNow.current[g.key]?.has(c.id)),
    );
    if (!ticked.length) return undefined;
    setPicked({});
    return ticked.map((c) => c.id);
  };
  const besides = (id: string) => {
    const at = groupIds.indexOf(id);
    return {
      after: order.filter((o) => groupIds.indexOf(o) > at),
      before: order.filter((o) => groupIds.indexOf(o) < at),
    };
  };
  /* Step from the newest focus, not the one this render saw: two quick presses of J come before the page has
     drawn again, and each must move one line. */
  const move = (step: number) =>
    setFocus((f) => {
      const at = f ? order.indexOf(f) : -1;
      if (f && at < 0 && view === "groups" && groupIds.includes(f)) {
        const { after, before } = besides(f);
        return (step > 0 ? (after[0] ?? before.at(-1)) : (before.at(-1) ?? after[0])) ?? f;
      }
      return order[Math.min(Math.max(at + step, 0), order.length - 1)] ?? f;
    });

  /* Move on after labeling a line. The Scenes view jumps to the next line that still needs work, instead of
     going through confirmed lines one by one. */
  const advance = (fromId: string | null, list = order) => {
    const at = fromId ? list.indexOf(fromId) : -1;
    for (let i = at + 1; i < list.length; i++) {
      const c = byId[list[i]];
      if (c && (view !== "scene" || NEEDS_WORK.has(c.status) || c.status === "auto")) {
        setFocus(list[i]);
        return;
      }
    }
    if (list[at + 1]) setFocus(list[at + 1]);
  };

  /* Move on after labeling a batch in Groups: the first unlabeled line after the batch, else from the top. */
  const nextUnlabeled = (ids: string[]) => {
    const rest = (id: string) => !ids.includes(id);
    const last = ids.reduce(
      (a, id) => (groupIds.indexOf(id) > groupIds.indexOf(a) ? id : a),
      ids[0],
    );
    return besides(last).after.find(rest) ?? order.find(rest);
  };

  const applyResult = (result: ChangeResult, label: string) => {
    setState(result.state);
    const updated: Record<string, Clip | undefined> = Object.fromEntries(
      result.updated.map((c) => [c.id, c]),
    );
    /* "Maybe missed" is decided when the Characters view fetches its list, and updated lines don't carry it, so
       keep it; a line labeled as this character is no longer missed. */
    /* The answer may come after you switched view or character, so read the ones open now. */
    setClips((list) =>
      list.map((c) => {
        const next = updated[c.id];
        if (!next) return c;
        return c.maybe && next.label !== roleNow.current ? { ...next, maybe: true } : next;
      }),
    );
    /* In Groups, labeled lines stay where they are, marked as labeled, instead of leaving the group: the
       unlabeled line next to it doesn't vanish with it, and undo puts things back exactly. Done in every view:
       with no groups loaded it changes nothing. */
    setGroups((gs) => gs.map((g) => ({ ...g, clips: g.clips.map((c) => updated[c.id] ?? c) })));
    const flashing = new Set(result.updated.map((c) => c.id));
    setFlashes(flashing);
    setTimeout(() => setFlashes(new Set()), 900);
    if (result.batch !== null) {
      const ripple = result.ripple
        ? tr(
            `，另有 ${result.ripple} 句的猜测随之改变`,
            `; guesses changed for ${lines(result.ripple)} more`,
          )
        : "";
      showToast(
        result.undo ? tr(`已撤销${ripple}`, `Undone${ripple}`) : `${label}${ripple}`,
        false,
        !result.undo,
      );
    }
  };

  /* Changes are queued, so no key press is lost: when your hands are faster than a round trip, the first press
     is saved first. The page moves on without waiting for the answer; if saving fails, it says so and moves the
     focus back to that line. */
  const queue = useRef<Promise<void>>(Promise.resolve());
  const pendingCount = useRef(0);
  /* Lines with a label change still on its way, and how many changes each has queued. */
  const saving = useRef(new Map<string, number>());
  const send = (
    url: string,
    body: { clips?: string[] } & Record<string, unknown>,
    label: string,
    onFail?: () => void,
  ): Promise<ChangeResult | null> => {
    setBusy(true);
    pendingCount.current += 1;
    const ids = body.clips || [];
    for (const id of ids) saving.current.set(id, (saving.current.get(id) || 0) + 1);
    const run = queue.current.then(async () => {
      try {
        const result = await call<ChangeResult>(url, body);
        applyResult(result, label);
        return result;
      } catch (e) {
        showToast(
          tr(`没有保存：${(e as Error).message}`, `Not saved: ${(e as Error).message}`),
          true,
        );
        onFail?.();
        return null;
      } finally {
        for (const id of ids) {
          const left = (saving.current.get(id) ?? 1) - 1;
          if (left > 0) saving.current.set(id, left);
          else saving.current.delete(id);
        }
        pendingCount.current -= 1;
        if (pendingCount.current === 0) setBusy(false);
      }
    });
    queue.current = run.then(() => {});
    return run;
  };

  /* One choice sets both who it is and whether it is low quality: low means "them, low quality"; otherwise it is
     clean, and an earlier low quality mark is turned off. */
  const assign = (name: string, ids?: string[], low = false) => {
    const clip = now();
    const targets = ids ?? (clip ? [clip.id] : []);
    if (!targets.length || !name) return;
    const from = focusNow.current;
    const who = labelText[name] ? tr(`「${labelText[name]}」`, `"${labelText[name]}"`) : name;
    const what = low
      ? tr(`${who}·质量低，导出时跳过`, `${who}, low quality, skipped on export`)
      : who;
    const label =
      targets.length > 1
        ? tr(`${targets.length} 句已标为 ${what}`, `${lines(targets.length)} labeled ${what}`)
        : tr(`已标为 ${what}`, `Labeled ${what}`);
    send("/api/label", { clips: targets, label: name, unusable: low }, label, () => setFocus(from));
    if (view === "groups") setFocus(nextUnlabeled(targets));
    else if (targets.length === 1) advance(from);
  };
  const accept = () => {
    const clip = now();
    if (!clip) return;
    if (clip.label) {
      move(1);
      return;
    }
    if (clip.guess.length) assign(clip.guess[0].name);
  };
  const clear = () => {
    const clip = now();
    if (clip?.label)
      send(
        "/api/label",
        { clips: [clip.id], label: null },
        tr("已清掉这句的标签", "Label cleared"),
      );
  };
  /* A save still on its way can be undone too, though the overview doesn't know of it yet. Afterwards go back to
     the line that was undone, if it is in this list. */
  const undo = async () => {
    if (!state?.can_undo && pendingCount.current === 0) {
      showToast(tr("没有可以撤销的操作", "Nothing to undo"));
      return;
    }
    const result = await send("/api/undo", {}, tr("已撤销", "Undone"));
    /* `updated` lists the lines undone first, then the ones whose guess changed along with them. */
    const back = result?.updated
      .slice(0, result.updated.length - result.ripple)
      .map((c) => c.id)
      .filter((id) => order.includes(id) || groupIds.includes(id));
    if (back?.length) setFocus(back.sort((a, b) => order.indexOf(a) - order.indexOf(b))[0]);
  };

  const playRef = async (name: string) => {
    const asked = focusNow.current;
    try {
      const refs = await call<Clip[]>(`/api/references?name=${encodeURIComponent(name)}`);
      if (focusNow.current !== asked) return; // Moved on while waiting.
      if (!refs.length) {
        showToast(
          tr(
            `${name} 还没有确认过的台词可以当参考`,
            `${name} has no confirmed lines to use as a reference yet`,
          ),
        );
        return;
      }
      const pick = refs[Math.floor(Math.random() * refs.length)];
      if (playerRef.current) playerRef.current.pause();
      const audio = refAudio.current;
      if (!audio) return;
      audio.src = media("audio", pick.id);
      audio.defaultPlaybackRate = speed;
      audio.playbackRate = speed;
      audio.play().catch(() => {});
      showToast(
        tr(`参考音：${name}「${pick.text || "…"}」`, `Reference: ${name} "${pick.text || "…"}"`),
      );
    } catch (e) {
      showToast((e as Error).message, true);
    }
  };

  const confirmRest = async () => {
    /* Leave out lines you just labeled whose answer hasn't come back: confirming them here would undo your fix. */
    /* And only lines the machine gave to the character open now: right after switching character, for a moment
       the list on hand can still be the last one's. */
    const pending = pendingOf(clips).filter(
      (c) => !saving.current.has(c.id) && c.guess[0]?.name === role,
    );
    if (!pending.length) return;
    const changes = pending.map((c) => ({ clip: c.id, label: role }));
    const result = await send(
      "/api/changes",
      { changes },
      tr(
        `确认了 ${pending.length} 句是${role === OTHER ? "「其他」" : ` ${role}`}`,
        `Confirmed ${lines(pending.length)} as ${role === OTHER ? '"Other"' : role}`,
      ),
    );
    if (result) {
      setPlaying(false);
      reload();
    }
  };
  const renameRole = async () => {
    if (!role) return;
    const unnamed = roles[role]?.named === false;
    const next = unnamed
      ? prompt(
          tr(
            `给「${role}」起个名字。填一个已有的名字就是把两个角色合并。`,
            `Name "${role}". Typing an existing name merges the two characters.`,
          ),
          "",
        )
      : prompt(
          tr(
            `把「${role}」改成什么名字？填一个已有的名字就是把两个角色合并。`,
            `Rename "${role}" to what? Typing an existing name merges the two characters.`,
          ),
          role,
        );
    if (!next || next.trim() === role) return;
    /* A rename keeps the number key: the new name takes the old name's place. On a merge the old name leaves the bar. */
    const renamed = !roles[next.trim()];
    if (renamed)
      dockOrder.current = dockOrder.current.flatMap((n) => (n === role ? [n, next.trim()] : [n]));
    const result = await send(
      "/api/roles",
      { name: role, new_name: next.trim() },
      roles[next.trim()]
        ? tr(`已并进 ${next.trim()}`, `Merged into ${next.trim()}`)
        : tr(`已改名为 ${next.trim()}`, `Renamed to ${next.trim()}`),
    );
    if (result) {
      setRole(next.trim());
    }
  };
  const toggleTarget = async () => {
    const info = role ? roles[role] : undefined;
    if (!role || !info) return;
    const message = info.target
      ? tr(
          `${role} 不再是目标角色，已标的留着`,
          `${role} is no longer a target character; their labels stay`,
        )
      : tr(`${role} 设为目标角色了`, `${role} is now a target character`);
    /* Target settings don't change labels, so the server records no batch and the page shows the message itself. */
    const result = await send("/api/roles", { name: role, target: !info.target }, message);
    if (result) {
      showToast(message);
      reload();
    }
  };
  /* Cropping an avatar uses the video playing on the stage. `then` runs after cropping or cancelling, for example
     moving on after labeling a new character. */
  const stageVideo = () =>
    playerRef.current instanceof HTMLVideoElement ? playerRef.current : null;
  const hasFrame = () => !!stageVideo()?.videoWidth;
  const openCrop = (name: string | null, then: (() => void) | null = null) => {
    if (!hasFrame() || !name) {
      showToast(
        episodeInfo?.video
          ? tr("画面还没出来", "The picture hasn't loaded yet")
          : tr(
              "这一集没有视频，截不了头像",
              "This episode has no video, so there is nothing to crop",
            ),
        true,
      );
      then?.();
      return;
    }
    setCrop({ name, then });
  };
  const closeCrop = () => {
    const then = crop?.then;
    setCrop(null);
    then?.();
  };
  /* A name for a new character must not be taken: that would be a merge, which belongs in the Characters view. */
  const nameTaken = (typed: string) =>
    otherName(typed)
      ? tr("「其他」是标签，不能当名字", '"Other" is a label, not a name')
      : roles[typed]
        ? tr(
            `已经有叫「${typed}」的角色了。换一个名字；是同一个人的话，以后在「角色」里合并`,
            `There is already a character called "${typed}". Pick another name; if it is the same person, merge them later in Characters`,
          )
        : "";
  /* Cancel in the New character dialog takes the new character back: the lines return to how they were. */
  const cancelNew = () => {
    setCrop(null);
    undo();
  };
  const saveCrop = async (image: string | null, typed: string) => {
    if (!crop) return;
    let name = crop.name;
    closeCrop();
    if (typed && typed !== name) {
      /* Like a rename in the Characters view: the new name keeps the number key. */
      const old = name;
      dockOrder.current = dockOrder.current.flatMap((n) => (n === old ? [n, typed] : [n]));
      if (
        !(await send(
          "/api/roles",
          { name, new_name: typed },
          tr(`已起名为 ${typed}`, `Named ${typed}`),
        ))
      )
        return;
      name = typed;
    }
    if (!image) return;
    try {
      setState(await call<Summary>("/api/roles/avatar", { name, image }));
      showToast(tr(`已换好 ${name} 的头像`, `Avatar of ${name} updated`));
    } catch (e) {
      showToast((e as Error).message, true);
    }
  };
  /* Label as a new character, then ask for a name (optional). If the current line is in the batch and there is a
     picture, the same dialog also crops an avatar from this frame. */
  /* Each request makes a fresh character, so a second press before the answer would make an empty second one. */
  const makingRole = useRef(false);
  const newRole = async (ids?: string[]) => {
    const clip = now();
    const targets = ids ?? (clip ? [clip.id] : []);
    if (!targets.length || makingRole.current) return;
    makingRole.current = true;
    const from = focusNow.current;
    let result: ChangeResult | null;
    try {
      result = await send(
        "/api/label",
        { clips: targets, new_role: true },
        targets.length > 1
          ? tr(
              `${targets.length} 句标成了一个新角色`,
              `${lines(targets.length)} labeled as a new character`,
            )
          : tr("已标成一个新角色", "Labeled as a new character"),
      );
    } finally {
      makingRole.current = false;
    }
    /* If you moved to another line while waiting, stay there: no cropping from that line's frame. */
    if (!result?.role || focusNow.current !== from) return;
    const onward = () => {
      if (view === "groups") setFocus(nextUnlabeled(targets));
      else if (targets.length === 1) advance(from);
    };
    setCrop({
      name: result.role,
      then: onward,
      naming: true,
      frame: !!from && targets.includes(from) && hasFrame(),
    });
  };

  /* Replay this line from the start. Clicking a line in the list selects it if not selected (it then plays by
     itself), or replays it if it already is, like Space. */
  const replay = () => {
    const p = playerRef.current;
    if (p) {
      p.currentTime = 0;
      p.play().catch(() => {});
    }
  };
  const pick = (id: string) => (id === focus ? replay() : setFocus(id));

  /* Continuous play in the Characters view: when a line ends, jump to the next one to check */
  /* L and the sound buttons make a new player, so listen again then too. Playing stops after the last line still
     to check; the lines below it are already settled. */
  useEffect(() => {
    if (!playing || view !== "roles") return;
    const player = playerRef.current;
    if (!player) return;
    let timer = 0;
    const onEnd = () => {
      timer = setTimeout(() => {
        const toCheck = pendingOf(clips).map((c) => c.id);
        const at = focusNow.current ? toCheck.indexOf(focusNow.current) : -1;
        if (at >= 0 && at + 1 < toCheck.length) setFocus(toCheck[at + 1]);
        else setPlaying(false);
      }, 250);
    };
    player.addEventListener("ended", onEnd);
    return () => {
      player.removeEventListener("ended", onEnd);
      clearTimeout(timer);
    };
  }, [playing, focus, view, clips, sound, context, setFocus]);
  useEffect(() => {
    setPlaying(false);
  }, [view, role]);
  /* Playing starts from the first line to check, or replays the open one if it is one of them: it may have
     finished already, and then no end would come to move on from. */
  useEffect(() => {
    if (!playing) return;
    const toCheck = pendingOf(clips);
    if (toCheck.some((c) => c.id === focusNow.current)) replay();
    else if (toCheck.length) setFocus(toCheck[0].id);
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- only when playing starts
  }, [playing]);
  /* A reference clip belongs to the line it was asked on. */
  useEffect(() => {
    refAudio.current?.pause();
  }, [focus]);

  /* All shortcuts */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (crop) return;
      if (help || addOpen || guide) {
        if (e.key === "Escape") {
          setHelp(false);
          setAddOpen(false);
          closeGuide();
        }
        return;
      }
      if (typing(e.target) || (e.ctrlKey && e.key !== "z") || e.metaKey || e.altKey) return;
      const k = e.key.toLowerCase();
      /* Holding a key down repeats only moving between lines; a held Enter, digit or Z would label or undo a
         whole run of lines. */
      if (e.repeat && !["j", "k", "arrowdown", "arrowup"].includes(k)) {
        e.preventDefault();
        return;
      }
      const handled = () => e.preventDefault();
      const clip = now();
      if (k === "j" || e.key === "ArrowDown") {
        handled();
        move(1);
      } else if (k === "k" || e.key === "ArrowUp") {
        handled();
        move(-1);
      } else if (e.key === " ") {
        handled();
        replay();
      } else if (e.key === "Enter" && e.shiftKey && view === "roles") {
        handled();
        confirmRest();
      } else if (e.key === "Enter") {
        handled();
        accept();
      } else if (/^(Digit|Numpad)[1-9]$/.test(e.code)) {
        /* Read the digit from e.code: with Shift held, e.key is "!", "@" and so on. Shift + number is the same
           character, low quality. */
        const name = dock[Number(e.code.at(-1)) - 1];
        if (name) {
          handled();
          assign(name, keyTargets(), e.shiftKey);
        }
      } else if (k === "q") {
        handled();
        assign(OTHER, keyTargets());
      } else if (k === "n" && clip && view !== "export") {
        handled();
        newRole(keyTargets());
      } else if (e.key === "?") {
        handled();
        setHelp(true);
      } else if (k === "z") {
        handled();
        undo();
      } else if (e.key === "Backspace" || e.key === "Delete") {
        handled();
        clear();
      } else if (k === "r" && clip?.guess.length && clip.guess[0].name !== OTHER) {
        handled();
        playRef(clip.guess[0].name);
      } else if (k === "l" && current) {
        handled();
        nextContext();
      } else if (k === "f" && view === "scene") {
        handled();
        toggleOnlyWork(!onlyWork);
      } else if (k === "p" && view === "roles") {
        handled();
        setPlaying(!playing);
      } else if (k === "g") {
        handled();
        setView("groups");
      } else if (k === "s") {
        handled();
        setView("scene");
      } else if (k === "o") {
        handled();
        setView("roles");
      } else if (k === "e") {
        handled();
        setView("export");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  /* The guide opens by itself once: the first time there are episodes but nothing is labeled. */
  const firstLook = !!state?.episodes.length && !state.model.labels;
  useEffect(() => {
    if (firstLook && !localStorage.getItem(GUIDE_SEEN)) setGuide(true);
  }, [firstLook]);
  const closeGuide = () => {
    localStorage.setItem(GUIDE_SEEN, "1");
    setGuide(false);
  };

  const corner = (
    <div className="corner">
      <LanguageButton onSwitch={switchLanguage} />
    </div>
  );
  if (error)
    return (
      <>
        {corner}
        <div className="empty">
          <h2>{tr("连不上本地服务", "Can't reach the local server")}</h2>
          <p>{error}</p>
        </div>
      </>
    );
  if (!state)
    return (
      <div className="empty">
        <div className="spinner" style={{ margin: "auto" }}></div>
        <p>{tr("正在载入…", "Loading…")}</p>
      </div>
    );
  const addProps = { state, adding, setAdding, onOpen: openEpisode, toast: showToast };
  if (!state.episodes.length) {
    return (
      <>
        {corner}
        <Welcome {...addProps} />
        {toast && (
          <div className={`toast ${toast.isError ? "error" : ""}`}>
            <span>{toast.message}</span>
          </div>
        )}
      </>
    );
  }

  const counts = episodeInfo?.counts || {};
  const targetCount = state.roles.filter((r) => r.target).length;
  /* Short lines skipped by default need no labeling and don't count toward progress. */
  const total =
    Object.values(counts).reduce((a: number, b) => a + (b ?? 0), 0) - (counts.skipped || 0) || 1;
  const done = counts.confirmed || 0;
  const work = (counts.review || 0) + (counts.novoice || 0) + (counts.unlabeled || 0);
  const showStage = view !== "export";
  /* Groups and Scenes show the episode picked on the left; Characters and Export cover all episodes. */
  const episodeTabs: [View, string, string][] = [
    ["groups", tr("起步分组", "Groups"), "G"],
    ["scene", tr("场景", "Scenes"), "S"],
  ];
  const allTabs: [View, string, string][] = [
    ["roles", tr("角色", "Characters"), "O"],
    ["export", tr("导出", "Export"), "E"],
  ];
  const perEpisode = episodeTabs.some(([v]) => v === view);
  const tabButtons = (list: [View, string, string][]) =>
    list.map(([v, l, key]) => (
      <button
        key={v}
        className={view === v ? "on" : ""}
        title={tr(`快捷键 ${key}`, `Shortcut ${key}`)}
        onClick={() => setView(v)}
      >
        {l}
        {v === "scene" && work > 0 ? <span className="count">{work}</span> : ""}
      </button>
    ));
  const unfinishedCount = Object.keys(state.skipped || {}).length;
  const cropRole = crop ? roles[crop.name] : undefined;

  return (
    <div className="shell">
      <header className="top">
        <div className="brand">
          <span className="dot"></span>avoc
        </div>
        <nav className={`tabs ${perEpisode ? "" : "away"}`}>
          <select
            value={episode ?? ""}
            title={
              perEpisode
                ? tr("换一集", "Switch episode")
                : tr(
                    "「角色」和「导出」看的是全部集数，换集只影响「起步分组」和「场景」",
                    "Characters and Export cover all episodes; switching only changes Groups and Scenes",
                  )
            }
            onChange={(e) => {
              /* Let go of the menu, or the arrow keys meant for the next line would switch the episode again. */
              e.target.blur();
              if (e.target.value === "+") {
                e.target.value = episode ?? "";
                setAddOpen(true);
              } else setEpisode(e.target.value);
            }}
          >
            {state.episodes.map((e) => (
              <option key={e.name} value={e.name}>
                {e.name}
              </option>
            ))}
            <option value="+">
              {tr("＋ 加一集…", "+ Add an episode…")}
              {unfinishedCount
                ? tr(`（${unfinishedCount} 集没做完）`, ` (${unfinishedCount} unfinished)`)
                : ""}
            </option>
          </select>
          {tabButtons(episodeTabs)}
        </nav>
        <nav className="tabs">
          <span className="scope">{tr("全部集数", "All episodes")}</span>
          {tabButtons(allTabs)}
        </nav>
        {addingState === "running" && !addOpen && (
          <button
            className="ghost adding-chip"
            onClick={() => setAddOpen(true)}
            title={tr("点开看进度", "Click to see the progress")}
          >
            <span className="spinner small"></span>
            {tr(`正在加 ${adding?.episode}`, `Adding ${adding?.episode}`)}
          </button>
        )}
        <span className="spacer"></span>
        {perEpisode && (
          <div
            className="progress"
            title={tr(
              "绿色是已经确认的，浅绿是机器有把握的",
              "Green is confirmed, light green is the machine's confident ones",
            )}
          >
            <span>
              {tr(
                `${episode}：确认 ${Math.round((done / total) * 100)}%`,
                `${episode}: ${Math.round((done / total) * 100)}% confirmed`,
              )}
            </span>
            <div className="bar">
              <i className="ok" style={{ width: `${(done / total) * 100}%` }}></i>
              <i className="auto" style={{ width: `${((counts.auto || 0) / total) * 100}%` }}></i>
            </div>
          </div>
        )}
        <span
          className={`model-chip ${busy ? "busy" : ""}`}
          title={tr("机器每次标注后都会重新学一次", "The machine retrains after every label")}
        >
          {busy
            ? tr("正在重新学习…", "Retraining…")
            : state.model.labels
              ? tr(
                  `机器学过 ${state.model.labels} 句 · ${targetCount} 个目标角色`,
                  `Trained on ${lines(state.model.labels)} · ${many(targetCount, "target")}`,
                )
              : tr("机器还没学过", "Not trained yet")}
        </span>
        <button
          className="ghost"
          disabled={!state.can_undo}
          onClick={undo}
          title={tr("撤销上一步", "Undo the last step")}
        >
          {tr("撤销", "Undo")} <kbd>Z</kbd>
        </button>
        <LanguageButton onSwitch={switchLanguage} />
        <button
          className="ghost theme"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          title={
            theme === "dark"
              ? tr("换成白天配色", "Switch to light colors")
              : tr("换成夜间配色", "Switch to dark colors")
          }
        >
          {theme === "dark" ? "☀" : "☾"}
        </button>
        <button
          className="ghost"
          onClick={() => setGuide(true)}
          title={tr(
            "四个页面是做什么的，怎么上手",
            "What the four views are for, and how to start",
          )}
        >
          {tr("指南", "Guide")}
        </button>
        <button
          className="ghost"
          onClick={() => setHelp(true)}
          title={tr("全部快捷键", "All shortcuts")}
        >
          <kbd>?</kbd>
        </button>
      </header>
      {state.outdated !== false && (
        <div className="banner warn">
          {tr(
            "avoc 已经更新，但正在运行的服务还是旧的，有些内容会显示不出来。关掉运行 avoc app 的窗口（或按 Ctrl+C），再重新运行它，然后刷新这个页面。",
            "avoc was updated, but the running server is still the old one, so some things will not show. Close the window running avoc app (or press Ctrl+C), run it again, then refresh this page.",
          )}
        </div>
      )}

      <div className="body" style={showStage ? undefined : { gridTemplateColumns: "1fr" }}>
        {showStage && (
          <Stage
            clip={current}
            roles={roles}
            labelText={labelText}
            sound={sound}
            setSound={setSound}
            speed={speed}
            setSpeed={setSpeed}
            hasVideo={!!episodeInfo?.video}
            videoRef={playerRef}
            onAssign={(n, low) => assign(n, undefined, low)}
            onAccept={accept}
            onPlayRef={playRef}
            onAvatar={(name) => openCrop(name)}
            onNewRole={() => newRole()}
            onClear={clear}
            context={context}
            setContext={setContext}
            dock={dock}
          />
        )}
        <main className="main">
          {view === "scene" && (
            <SceneView
              clips={clips}
              order={order}
              focus={focus}
              setFocus={pick}
              roles={roles}
              labelText={labelText}
              onlyWork={onlyWork}
              setOnlyWork={toggleOnlyWork}
              showShort={showShort}
              setShowShort={setShowShort}
              flashes={flashes}
              episode={episode}
            />
          )}
          {view === "roles" && (
            <RoleView
              state={state}
              roles={roles}
              labelText={labelText}
              role={role}
              setRole={setRole}
              clips={clips}
              focus={focus}
              setFocus={pick}
              onConfirmRest={confirmRest}
              onRename={renameRole}
              onToggleTarget={toggleTarget}
              flashes={flashes}
              onAvatar={() => openCrop(role)}
              canCrop={!!current && !!episodeInfo?.video}
              playing={playing}
              setPlaying={setPlaying}
            />
          )}
          {view === "groups" && (
            <GroupsView
              key={episode}
              groups={groups}
              loading={groupsLoading}
              roles={roles}
              labelText={labelText}
              dock={dock}
              focus={focus}
              setFocus={pick}
              firstRun={firstRun}
              picked={picked}
              setPicked={setPicked}
              onName={(ids, name, low) => assign(name, ids, low)}
              onNew={(ids) => newRole(ids)}
            />
          )}
          {view === "export" && <ExportView state={state} setState={setState} toast={showToast} />}
        </main>
      </div>

      {view !== "export" && (
        <footer className="dock">
          {dock.map((name, i) => (
            <div
              className="chip"
              key={name}
              title={
                i < 9
                  ? tr(`按 ${i + 1} 标成 ${name}`, `Press ${i + 1} to label as ${name}`)
                  : tr(`标成 ${name}`, `Label as ${name}`)
              }
              onClick={() => assign(name, keyTargets())}
            >
              <Avatar role={roles[name]} name={name} size="md" />
              <RoleName role={roles[name]} name={name} />
              {i < 9 && <span className="k">{i + 1}</span>}
              <button
                className="low"
                title={
                  (i < 9
                    ? tr(
                        `按 Shift + ${i + 1} 标成 ${name}·质量低：`,
                        `Press Shift + ${i + 1} to label as ${name}, low quality: `,
                      )
                    : tr(`标成 ${name}·质量低：`, `Label as ${name}, low quality: `)) + lowTip()
                }
                onClick={(e) => {
                  e.stopPropagation();
                  assign(name, keyTargets(), true);
                }}
              >
                {tr("质量低", "Low quality")}
                {i < 9 ? (
                  <>
                    {" "}
                    <span className="k">⇧{i + 1}</span>
                  </>
                ) : (
                  ""
                )}
              </button>
            </div>
          ))}
          <div
            className="chip"
            title={tr("不是任何一个目标角色", "Not any of the target characters")}
            onClick={() => assign(OTHER, keyTargets())}
          >
            <Avatar blank={true} size="md" />
            <span className="rn">{labelText[OTHER]}</span>
            <span className="k">Q</span>
          </div>
          <div
            className={`chip ${current ? "" : "off"}`}
            title={tr(
              "新建一个目标角色，名字可以以后再起；有画面时接着截头像",
              "Make a new target character; you can name it later. With video, crop an avatar next",
            )}
            onClick={() => current && newRole(keyTargets())}
          >
            <div className="av md unknown">+</div>
            <span className="rn">{tr("新角色", "New character")}</span>
            <span className="k">N</span>
          </div>
        </footer>
      )}

      <audio ref={refAudio} hidden></audio>
      {crop && (
        <Cropper
          source={!crop.naming || crop.frame ? stageVideo() : null}
          name={crop.name}
          role={cropRole}
          naming={crop.naming}
          taken={nameTaken}
          onSave={saveCrop}
          onClose={crop.naming ? cancelNew : closeCrop}
        />
      )}
      {help && (
        <Help
          onClose={() => setHelp(false)}
          onGuide={() => {
            setHelp(false);
            setGuide(true);
          }}
        />
      )}
      {guide && (
        <Guide
          onClose={closeGuide}
          onStart={() => {
            closeGuide();
            setView("groups");
          }}
        />
      )}
      {addOpen && <AddDialog onClose={() => setAddOpen(false)} {...addProps} />}
      {toast && (
        <div className={`toast ${toast.isError ? "error" : ""}`}>
          <span>{toast.message}</span>
          {toast.extra && (
            <button onClick={undo}>
              {tr("撤销", "Undo")} <kbd>Z</kbd>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
