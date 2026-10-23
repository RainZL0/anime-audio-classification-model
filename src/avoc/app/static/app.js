import { html, render, useState, useEffect, useRef, useMemo, useCallback } from "/static/vendor/preact-htm.js";

/* ───────────── Language ───────────── */

/* The page comes in Chinese and English. The choice is kept on this machine; the first time, it follows the
   browser. Every string on screen is written as tr(Chinese, English) right where it is used. */
let lang = localStorage.getItem("lang") || (navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en");
const tr = (zh, en) => (lang === "en" ? en : zh);
/* English plural for a count: "1 line", "3 lines". */
const many = (n, word, plural = `${word}s`) => `${n} ${n === 1 ? word : plural}`;
const lines = (n) => tr(`${n} 句`, many(n, "line"));
const showLanguage = () => {
  document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
  document.title = tr("avoc · 按角色整理动画台词", "avoc · sort anime lines by character");
};
showLanguage();

/* ───────────── Talking to the server ───────────── */

/* Every request says which language the page is in, so the server's messages come back in it too. */
async function call(url, body) {
  const response = await fetch(url, body === undefined ? { headers: { "X-Language": lang } } : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Language": lang },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return response.json();
}

const media = (kind, id, context = 0) =>
  `/media/${kind}/${id}.${kind === "audio" ? "wav" : "mp4"}${context ? `?context=${context}` : ""}`;
/* L cycles through: normal, 5 more seconds on each side, 15. Matches CONTEXT_SECONDS on the server. */
const CONTEXTS = [0, 5, 15];
/* Playback speeds to choose from. The choice is kept on this machine. */
const SPEEDS = [1, 1.25, 1.5, 2];
/* Round to tenths of a second first, then split into minutes and seconds, so 59.96 s is not written ":60.0"
   with the minute not carried. */
const stamp = (s) => {
  const tenths = Math.round(s * 10);
  return `${String(Math.floor(tenths / 600)).padStart(2, "0")}:${((tenths % 600) / 10).toFixed(1).padStart(4, "0")}`;
};
const pct = (p) => `${Math.round(p * 100)}%`;
/* A total length: seconds under a minute, minutes and seconds under an hour, else hours and minutes. */
const howLong = (seconds) => {
  const s = Math.round(seconds);
  if (s < 60) return tr(`${s} 秒`, `${s} s`);
  const m = Math.floor(s / 60);
  return m < 60
    ? tr(`${m} 分 ${s % 60} 秒`, `${m} min ${s % 60} s`)
    : tr(`${Math.floor(m / 60)} 小时 ${m % 60} 分`, `${Math.floor(m / 60)} h ${m % 60} min`);
};
const statusText = (status) => ({
  confirmed: tr("已确认", "Confirmed"), auto: tr("机器有把握", "Confident"), review: tr("待确认", "Check"),
  novoice: tr("太短，没有声纹", "Too short for a voiceprint"), unlabeled: tr("还没有模型", "No model yet"),
  skipped: tr("太短，默认跳过", "Short, skipped"),
})[status];
const NEEDS_WORK = new Set(["review", "novoice", "unlabeled"]);
const VIEWS = ["groups", "scene", "roles", "export"];
/* A list request was overtaken by a later one. Its result is dropped; this is not an error. */
const STALE = new Error("stale");
/* The position saved after # in the address when the page opened; see where App writes it back. */
const saved = new URLSearchParams(location.hash.slice(1));
/* App only rewrites the address with replaceState, which fires no hashchange. So this fires only when the person
   edits the address or opens a link to another spot; reloading reads the new position. */
addEventListener("hashchange", () => location.reload());
const confidence = (clip) => clip.guess[0]?.p ?? 0;
/* Shortcuts stay off while the keys go into a text box or a menu. A tick box is not typed into, so they still
   work after ticking a line. */
const typing = (el) => el.tagName === "SELECT" || el.tagName === "TEXTAREA"
  || el.tagName === "INPUT" && !["checkbox", "radio", "button", "range"].includes(el.type);
/* "Other": not any of the target characters. It is a human judgment, labeled with Q. Unsure whether it is a
   target, several people talking with no target among them, cheering and sound effects: all get "other". */
const OTHER = "__other__";
/* "Other" typed as a name, in either language, means the "other" label, not a new character that looks the same. */
const otherName = (s) => ["其他", "other"].includes(s.trim().toLowerCase());
/* Each target character has two choices: clean, and "low quality" (Shift + number). Only targets have it;
   "other" is never exported anyway. There used to be a separate "several people", now merged into low quality. */
/* Seconds the video clip extends past each end of the line. Matches avoc.app.video.VIDEO_PAD on the server. */
const VIDEO_PAD = 0.5;
const lowTip = () => tr("背景音太重、有人同时出声之类，不能进干净数据集。不拿来认人，导出时跳过",
  "Too much background sound, someone talking at the same time and so on: not fit for a clean dataset. "
  + "Not used to recognize anyone, and skipped on export");
const chanceOf = (clip, name) => clip.guess.find((g) => g.name === name)?.p ?? 0;
/* The target character the machine finds most likely. "Other" does not count. */
const bestTarget = (clip) => clip.guess.find((g) => g.name !== OTHER);

/* Who a clip belongs to now: the human label first, else the machine's top guess. */
function whoOf(clip) {
  if (clip.label) return { name: clip.label, human: true };
  if (clip.guess.length) return { name: clip.guess[0].name, human: false, p: clip.guess[0].p };
  return null;
}

/* Fetch the next few clips' media ahead of time: the server cuts it on demand, so asking early means it is
   already cut by the time you get there. */
const warmed = new Set();
function warm(clips, kind) {
  for (const clip of clips) {
    if (!clip) continue;
    const url = media(kind, clip.id);
    if (warmed.has(url)) continue;
    warmed.add(url);
    fetch(url, { priority: "low" }).catch(() => warmed.delete(url));
  }
}

/* ───────────── Small pieces ───────────── */

/* The picture for a character without an avatar: background color × white shape × pattern.
   The number is given out by the server and kept in the character list, so a character always gets the
   same picture. */
const PALETTE = ["#7F77DD", "#1D9E75", "#D85A30", "#D4537E", "#378ADD", "#639922", "#BA7517", "#E24B4A",
  "#5F5E5A", "#534AB7", "#0F6E56", "#993C1D", "#993556", "#185FA5", "#3B6D11", "#854F0B"];
/* Corners of a polygon centered at (20, 20), its radius taking the values in radii in turn. */
const ring = (corners, radii, turn = -Math.PI / 2) => Array.from({ length: corners }, (_, i) => {
  const r = radii[i % radii.length];
  const a = turn + 2 * Math.PI * i / corners;
  return `${(20 + r * Math.cos(a)).toFixed(1)},${(20 + r * Math.sin(a)).toFixed(1)}`;
}).join(" ");
const SHAPES = [
  html`<circle cx="20" cy="20" r="9" />`,
  html`<polygon points="20,8 32,20 20,32 8,20" />`,
  html`<polygon points="20,9 32,30 8,30" />`,
  html`<rect x="11" y="11" width="18" height="18" rx="2.5" />`,
  html`<polygon points=${ring(10, [12, 5])} />`,
  html`<polygon points=${ring(6, [11], 0)} />`,
  html`<path d="M16 9h8v7h7v8h-7v7h-8v-7H9v-8h7z" />`,
  html`<circle cx="20" cy="20" r="8" fill="none" stroke="#fff" stroke-width="4.5" />`,
];
function hashed(text) {
  let h = 0;
  for (const ch of text) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return h;
}
/* Number p takes color p % 16. The shape shifts by 3 after each round of 16 colors (3 and 8 share no factor),
   so the first 128 numbers all get a different color × shape; only after that does the pattern tell them apart. */
function Pattern({ role, name }) {
  const p = role?.pattern ?? hashed(name);
  const color = role?.color || PALETTE[p % PALETTE.length];
  const round = Math.floor(p / PALETTE.length);
  const shape = (p % SHAPES.length + 3 * round) % SHAPES.length;
  const variant = Math.floor(p / (PALETTE.length * SHAPES.length)) % 3;
  return html`<svg viewBox="0 0 40 40" aria-hidden="true">
    <rect width="40" height="40" fill=${color} />
    ${variant === 1 && html`<path d="M0 40L40 0V40z" fill="rgba(0,0,0,.22)" />`}
    ${variant === 2 && html`<circle cx="20" cy="20" r="17" fill="none" stroke="rgba(255,255,255,.55)" stroke-width="2" />`}
    <g fill="#fff">${SHAPES[shape]}</g>
  </svg>`;
}

function Avatar({ role, name, size = "", blank, onClick, title }) {
  if (blank) return html`<div class="av ${size} unknown">·</div>`;
  if (!name) return html`<div class="av ${size} unknown">?</div>`;
  const click = onClick ? { onClick, role: "button" } : {};
  if (role?.avatar) {
    return html`<div class="av ${size} ${onClick ? "edit" : ""}" title=${title || name} ...${click}
      style=${`background-image:url(/media/avatar/${role.avatar})`}></div>`;
  }
  return html`<div class="av ${size} ${onClick ? "edit" : ""}" title=${title || name} ...${click}>
    <${Pattern} role=${role} name=${name} /></div>`;
}

/* A character's name. Characters not named yet are shown lighter, as a reminder that the name is temporary. */
function RoleName({ role, name, cls = "" }) {
  return html`<span class="rn ${cls} ${role?.named === false ? "unnamed" : ""}"
    title=${role?.named === false ? tr("还没起名字，在「角色」视图里可以起", "Not named yet. You can name it in the Characters view") : ""}>${name}</span>`;
}

/* The machine's guess of who someone is, shown the same way everywhere: a small avatar, "Closest" and the name,
   and the chance when there is one. */
function Closest({ roles, name, p, title }) {
  return html`<span class="pill closest" title=${title || tr("机器觉得最像的角色", "The character the machine finds closest")}>
    <${Avatar} role=${roles[name]} name=${name} size="xs" />${tr("最像", "Closest:")} ${name}${p != null ? ` ${pct(p)}` : ""}</span>`;
}

function Pill({ clip }) {
  if (clip.status === "review" && clip.familiar === false) {
    return html`<span class="pill stranger" title=${tr("跟已知角色确认过的台词都不太像", "Not much like any confirmed line of a known character")}>
      ${tr("可能是没见过的人", "Maybe someone new")}</span>`;
  }
  if (clip.status === "auto" || clip.status === "review") {
    return html`<span class="pill ${clip.status}">${clip.status === "review" ? tr("待确认 ", "Check ") : ""}${pct(clip.guess[0].p)}</span>`;
  }
  return html`<span class="pill ${clip.status}">${statusText(clip.status)}</span>`;
}

/* Switch between Chinese and English. */
function LanguageButton({ onSwitch }) {
  return html`<button class="ghost lang" onClick=${onSwitch} title=${tr("Switch to English", "切换到中文")}>
    ${lang === "en" ? "中文" : "EN"}</button>`;
}

/* ───────────── Stage: picture, line, who is it ───────────── */

function Stage({ clip, roles, labelText, sound, setSound, speed, setSpeed, onAssign, onAccept, onPlayRef, hasVideo, videoRef,
  onAvatar, onNewRole, onClear, context, onContext, dock }) {
  const [loading, setLoading] = useState(true);
  /* The number key of each of the first 9 characters in the bottom bar; Shift + it is that character, low quality. */
  const slot = (name) => { const i = dock.indexOf(name); return i >= 0 && i < 9 ? i + 1 : null; };
  const audioRef = useRef(null);
  const startVoice = useRef(0);
  useEffect(() => { setLoading(true); return () => clearTimeout(startVoice.current); }, [clip?.id, sound, context]);
  /* On a new clip the player resets its speed to defaultPlaybackRate, so set both. */
  useEffect(() => {
    for (const el of [videoRef?.current, audioRef.current]) {
      if (el) { el.defaultPlaybackRate = speed; el.playbackRate = speed; }
    }
  }, [speed, clip?.id, sound, context]);

  if (!clip) {
    return html`<aside class="stage"><div class="screen"><div class="wait">${tr("在右边选一句台词", "Pick a line on the right")}</div></div></aside>`;
  }
  const vocals = hasVideo && sound === "vocals";
  /* With vocals only, the picture plays muted and the separated vocals play instead, following the picture's
     play, pause and seek. The video clip starts VIDEO_PAD seconds before the line (less at the very start of an
     episode), so the vocals wait until the picture reaches the line. With extra context the vocals were cut
     with the same extra seconds, so both start at the same moment. */
  const follow = (e) => {
    const voice = audioRef.current;
    if (!vocals || !voice) return;
    clearTimeout(startVoice.current);
    const at = e.target.currentTime - (context ? 0 : Math.min(VIDEO_PAD, clip.start));
    voice.currentTime = Math.max(0, at);
    if (e.target.paused) voice.pause();
    else if (at >= 0) voice.play().catch(() => {});
    else {
      voice.pause();
      startVoice.current = setTimeout(() => voice.play().catch(() => {}), (-at * 1000) / speed);
    }
  };
  const who = whoOf(clip);
  const isOther = clip.label && labelText[clip.label];
  return html`<aside class="stage">
    <div class="screen">
      ${hasVideo
        ? html`<video ref=${videoRef} key=${`${clip.id}-${sound}-${context}`} src=${media("video", clip.id, context)}
            autoplay playsinline muted=${vocals}
            onCanPlay=${() => setLoading(false)} onClick=${(e) => { e.target.currentTime = 0; e.target.play(); }}
            onPlay=${follow} onPause=${follow} onSeeked=${follow}></video>
          ${vocals && html`<audio ref=${audioRef} key=${`v-${clip.id}-${context}`} src=${media("audio", clip.id, context)}
            preload="auto"></audio>`}`
        : html`<div class="wait">${tr("这一集没有视频，只有人声", "This episode has no video, only vocals")}</div>
          <audio ref=${(el) => { audioRef.current = el; if (videoRef) videoRef.current = el; }} key=${`${clip.id}-${context}`}
            src=${media("audio", clip.id, context)} autoplay onCanPlay=${() => setLoading(false)}></audio>`}
      <div class="wait ${!hasVideo || !loading ? "hide" : ""}"><div class="spinner"></div></div>
    </div>
    <div class="player">
      ${hasVideo && html`<span class="seg">
        <button class=${sound === "vocals" ? "on" : ""} onClick=${() => setSound("vocals")}>${tr("只听人声", "Vocals only")}</button>
        <button class=${sound === "original" ? "on" : ""} onClick=${() => setSound("original")}>${tr("画面原声", "Original sound")}</button>
      </span>`}
      <span class="seg" title=${tr("播放速度，参考音也一样快", "Playback speed, also used for reference clips")}>
        ${SPEEDS.map((s) => html`<button class=${speed === s ? "on" : ""} onClick=${() => setSpeed(s)}>${s}×</button>`)}
      </span>
    </div>
    <div class="line-text">${clip.text || html`<span style="color:var(--text-3)">${tr("（字幕里没有这句的文字）", "(no text for this line in the subtitles)")}</span>`}</div>
    <div class="line-meta">
      <span>${clip.episode}</span><span>${stamp(clip.start)}</span><span>${tr(`${clip.duration.toFixed(2)} 秒`, `${clip.duration.toFixed(2)} s`)}</span>
      <button class="context ${context ? "on" : ""}" onClick=${onContext}
        title=${tr("看不出是谁时，临时前后各多放一些；再按切到 15 秒、再按回到平常。换一句自动回到平常",
          "When you can't tell who it is, play a bit more on each side. Press again for 15 seconds, again for normal. Moving to another line goes back to normal")}>
        ${context ? tr(`前后多放 ${context} 秒`, `±${context} s`) : tr("多放前后文", "More context")} <kbd>L</kbd></button>
    </div>

    ${clip.label
      ? html`<div class="ask">${tr("已经确认", "Confirmed")}</div>
        <div class="confirmed-box">
          <${Avatar} role=${roles[clip.label]} name=${clip.label} blank=${isOther} size="lg"
            onClick=${!isOther && hasVideo ? () => onAvatar(clip.label) : null} title=${tr("从画面里截一块当头像", "Crop an avatar from the picture")} />
          <div><div class="who">${isOther ? labelText[clip.label] : html`<${RoleName} role=${roles[clip.label]} name=${clip.label} />`}
            ${clip.unusable && !labelText[clip.label] && html` <span class="pill unusable" title=${lowTip()}>${tr("质量低", "Low quality")}</span>`}</div>
          <div style="font-size:12px">${tr("要改的话，直接按别的数字键或在下面选；Shift + 数字是质量低",
            "To change it, press another number key or pick below. Shift + number means low quality")}</div></div>
          <span class="actions">
            <button class="ghost" title=${tr("清掉这句的标签，回到机器的猜测", "Clear this line's label and go back to the machine's guess")}
              onClick=${onClear}>${tr("清掉标签", "Clear label")} <kbd>Backspace</kbd></button></span>
        </div>`
      : html`<div class="ask">${clip.guess.length ? tr("这是谁？机器的猜测", "Who is this? The machine's guesses")
          : clip.voiced ? tr("这是谁？", "Who is this?") : tr("这句太短，机器听不出来，请直接选人", "Too short for the machine to tell. Pick the character yourself")}</div>
        ${clip.familiar === false && html`<div class="stranger">
          ${tr(html`跟已经确认过的角色都不太像，可能是还没标过的人。是新角色就按 <kbd>N</kbd> 新建，名字以后再起也行。`,
            html`Not much like any confirmed character, so it may be someone not labeled yet. If it is a new character, press <kbd>N</kbd>; you can name it later.`)}</div>`}
        ${clip.familiar === null && clip.guess.length > 0 && html`<div class="stranger early">
          ${tr(html`机器现在只会在底部这几个角色里挑。都不是就按 <kbd>N</kbd> 新建；确认满 20 句后，它会自己提醒你哪句像新面孔。`,
            html`For now the machine only picks among the characters at the bottom. If it is none of them, press <kbd>N</kbd>. After 20 confirmed lines it will point out lines that sound like someone new.`)}</div>`}
        <div class="cands">
          ${clip.guess.filter((g) => g.p >= 0.02 || g === clip.guess[0]).map((g, i) => html`
            <div class="cand ${i === 0 ? "top" : ""}" onClick=${() => onAssign(g.name)}>
              <${Avatar} role=${roles[g.name]} name=${g.name} blank=${g.name === OTHER} size="md" />
              <div class="name">${g.name === OTHER ? labelText[OTHER] : html`<${RoleName} role=${roles[g.name]} name=${g.name} />`}</div>
              ${g.name !== OTHER && html`<button class="ref" title=${tr("听这个角色确认过的一句", "Hear a confirmed line of this character")}
                onClick=${(e) => { e.stopPropagation(); onPlayRef(g.name); }}>
                ${tr("参考音", "Reference")}${i === 0 ? html` <kbd>R</kbd>` : ""}</button>`}
              ${g.name !== OTHER && html`<button class="low" title=${tr(`标成 ${g.name}·质量低：`, `Label as ${g.name}, low quality: `) + lowTip()}
                onClick=${(e) => { e.stopPropagation(); onAssign(g.name, true); }}>${tr("质量低", "Low quality")}${
                  slot(g.name) ? html` <span class="k">⇧${slot(g.name)}</span>` : ""}</button>`}
              <span class="pct">${pct(g.p)}</span>
              <div class="meter"><i style="width:${pct(g.p)}"></i></div>
            </div>`)}
        </div>
        <div style="margin-top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          ${clip.guess.length > 0 && html`<button class="primary" onClick=${onAccept}>${tr("是", "It's")} ${labelText[clip.guess[0].name] || clip.guess[0].name}
            <kbd style="margin-left:4px">Enter</kbd></button>`}
          <button onClick=${onNewRole} title=${tr("新建一个目标角色，名字可以以后再起；有画面时接着截头像",
            "Make a new target character; you can name it later. With video, crop an avatar next")}>
            ${tr("新角色", "New character")} <kbd style="margin-left:4px">N</kbd></button>
          <span style="font-size:12px;color:var(--text-3)">${tr("已有的人按数字键，或点底部的头像", "Existing characters: number keys, or click an avatar at the bottom")}</span></div>`}

    <div class="hint">
      ${tr(html`<kbd>J</kbd> <kbd>K</kbd> 上下一句 · <kbd>空格</kbd> 重播 · <kbd>1</kbd>–<kbd>9</kbd> 选下面的角色 ·
        <kbd>N</kbd> 新角色 · <kbd>Z</kbd> 撤销 · <kbd>?</kbd> 全部快捷键`,
        html`<kbd>J</kbd> <kbd>K</kbd> next / previous · <kbd>Space</kbd> replay · <kbd>1</kbd>–<kbd>9</kbd> pick a character below ·
        <kbd>N</kbd> new character · <kbd>Z</kbd> undo · <kbd>?</kbd> all shortcuts`)}
    </div>
  </aside>`;
}

/* ───────────── One line ───────────── */

function Row({ clip, roles, labelText, selected, onSelect, flash, maybeOf, showTarget }) {
  const ref = useRef(null);
  useEffect(() => {
    if (selected && ref.current) ref.current.scrollIntoView({ block: "nearest" });
  }, [selected]);
  const who = whoOf(clip);
  const isOther = who && labelText[who.name];
  const stranger = !clip.label && clip.familiar === false;
  return html`<div ref=${ref} class="row ${selected ? "sel" : ""} ${flash ? "done-flash" : ""}"
      onClick=${onSelect}>
    <${Avatar} role=${who && !stranger && roles[who.name]} name=${stranger ? null : who?.name} blank=${isOther} />
    <div>
      <div class="who">
        <span class="n" style=${who && !who.human ? "color:var(--text-2);font-weight:500" : ""}>
          ${stranger ? "" : isOther ? labelText[who.name]
            : who ? html`<${RoleName} role=${roles[who.name]} name=${who.name} />` : tr("未知", "Unknown")}</span>
        <${Pill} clip=${clip} />
        ${stranger && bestTarget(clip) && html`<${Closest} roles=${roles} name=${bestTarget(clip).name} p=${bestTarget(clip).p} />`}
        ${clip.unusable && !labelText[clip.label] && html`<span class="pill unusable" title=${lowTip()}>${tr("质量低", "Low quality")}</span>`}
        ${clip.maybe && html`<span class="pill maybe" title=${tr("机器没归给这个角色，但听起来有可能是", "The machine didn't give it to this character, but it might be")}>
          ${tr("可能漏掉", "Maybe missed")} ${pct(chanceOf(clip, maybeOf))}</span>`}
        ${showTarget && bestTarget(clip) && html`<${Closest} roles=${roles} name=${bestTarget(clip).name} p=${bestTarget(clip).p}
          title=${tr("机器觉得这句是这个目标角色的概率", "The machine's chance that this line is this target character")} />`}
      </div>
      <div class="say ${clip.text ? "" : "empty"}">${clip.text || tr("（没有字幕文字）", "(no subtitle text)")}</div>
    </div>
    <div class="t">${stamp(clip.start)}<br />${clip.duration.toFixed(2)}s</div>
  </div>`;
}

/* ───────────── Scenes view ───────────── */

function SceneView({ clips, order, focus, setFocus, roles, labelText, onlyWork, setOnlyWork, showShort, setShowShort,
  flashes, episode }) {
  const shown = new Set(order);
  const scenes = [];
  for (const clip of clips) {
    if (!shown.has(clip.id)) continue;
    const last = scenes[scenes.length - 1];
    if (!last || last.scene !== clip.scene) scenes.push({ scene: clip.scene, clips: [clip] });
    else last.clips.push(clip);
  }
  const left = clips.filter((c) => NEEDS_WORK.has(c.status)).length;
  const skipped = clips.filter((c) => c.status === "skipped").length;
  return html`<div>
    <div class="toolbar">
      <h2>${episode}</h2>
      <span class="sub">${tr(`${clips.length} 句 · 还有 ${left} 句要你看`, `${lines(clips.length)} · ${left} left for you`)}</span>
      ${skipped > 0 && html`<span class="sub" title=${tr("短于 1 秒、前后 0.5 秒内没有别的台词，训练用不上，默认不显示",
          "Shorter than 1 second with no other line within 0.5 seconds: no use for training, hidden by default")}>
        · ${tr(`跳过 ${skipped} 句短句`, `${skipped} short ${skipped === 1 ? "line" : "lines"} skipped`)}</span>
        ${!onlyWork && html`<button class="short ${showShort ? "on" : ""}" onClick=${() => setShowShort(!showShort)}
          title=${tr("在「整集」里显示跳过的短句，想标也可以标", "Show the skipped short lines under Whole episode; you can still label them")}>
          ${showShort ? tr("隐藏短句", "Hide short lines") : tr("显示短句", "Show short lines")}</button>`}`}
      <span class="spacer"></span>
      <span class="seg">
        <button class=${!onlyWork ? "on" : ""} onClick=${() => setOnlyWork(false)}>${tr("整集", "Whole episode")}</button>
        <button class=${onlyWork ? "on" : ""} onClick=${() => setOnlyWork(true)}>${tr("只看要处理的", "Only to do")} <kbd>F</kbd></button>
      </span>
    </div>
    ${scenes.length === 0 && html`<div class="empty"><h2>${tr("这一集都处理完了", "This episode is done")}</h2>
      <p>${tr("切到「整集」可以回头翻看，或者去「角色」视图按人核对机器的判断。",
        "Switch to Whole episode to look back, or check the machine's calls per character in the Characters view.")}</p></div>`}
    ${scenes.map((s) => html`<section>
      <div class="scene-head"><b>${tr(`第 ${s.scene + 1} 场`, `Scene ${s.scene + 1}`)}</b><span>${stamp(s.clips[0].start)}</span>
        <span>· ${lines(s.clips.length)}</span></div>
      ${s.clips.map((clip) => html`<${Row} key=${clip.id} clip=${clip} roles=${roles} labelText=${labelText}
        selected=${clip.id === focus} flash=${flashes.has(clip.id)} onSelect=${() => setFocus(clip.id)} />`)}
    </section>`)}
  </div>`;
}

/* ───────────── Characters view: check the machine's calls per character ───────────── */

/* To check in the Characters view: given to this character by the machine, not yet confirmed, least sure first. */
const pendingOf = (clips) => clips.filter((c) => !c.label && !c.maybe).sort((a, b) => confidence(a) - confidence(b));
/* Maybe missed: not given to this character, but with a fair chance of being them. The server already sorted
   them most likely first; they are not re-sorted after retraining, so the list doesn't jump under your hand. */
const maybeListOf = (clips) => clips.filter((c) => c.maybe);
/* Confirmed lines in the server's order: by time for a target, most like some target first for "other". */
const confirmedOf = (clips, role) => clips.filter((c) => c.label === role);

/* The numbers on the right of a character row: lines confirmed, lines the machine gave them, and below,
   the total length of the confirmed lines. */
function Counts({ info }) {
  return html`<span class="c">${info.confirmed}${info.predicted ? html` · <b>${info.predicted}</b>` : ""}
    ${info.seconds > 0 && html`<br /><span title=${tr("确认过的台词累计时长", "Total length of confirmed lines")}>${howLong(info.seconds)}</span>`}</span>`;
}

function RoleView({ state, roles, labelText, role, setRole, clips, focus, setFocus, onConfirmRest,
  onRename, onToggleTarget, onAvatar, canCrop, flashes, playing, setPlaying }) {
  const list = state.roles;
  const other = role === OTHER;
  const current = other ? {} : roles[role];
  const info = other ? state.other : list.find((r) => r.name === role);
  const name = other ? labelText[OTHER] : role;
  const pending = pendingOf(clips);
  const maybe = maybeListOf(clips);
  const confirmed = confirmedOf(clips, role);
  /* Who the machine gave these lines to, as written inside a sentence. */
  const them = other ? tr("「其他」", "\"Other\"") : role;
  return html`<div class="roles-grid">
    <div class="role-list">
      ${list.map((r) => html`<div class="role-item ${r.name === role ? "on" : ""} ${r.target ? "" : "off"}"
          onClick=${() => setRole(r.name)} title=${r.target ? "" : tr("不是目标角色：机器不再猜这个角色，已有的标签照样留着",
            "Not a target character: the machine no longer guesses them, their labels stay")}>
        <${Avatar} role=${r} name=${r.name} size="md" />
        <${RoleName} role=${r} name=${r.name} cls="nm" />
        <${Counts} info=${r} />
      </div>`)}
      <div class="role-item other ${other ? "on" : ""}" onClick=${() => setRole(OTHER)} title=${tr("不是任何一个目标角色", "Not any of the target characters")}>
        <${Avatar} blank=${true} size="md" /><span class="rn nm">${labelText[OTHER]}</span>
        <${Counts} info=${state.other} />
      </div>
    </div>
    <div>
      ${!current ? html`<div class="empty"><h2>${tr("选一个角色", "Pick a character")}</h2><p>${tr(
        "左边上面是目标角色，就是你要收集的人；其余的人一律标「其他」。灰色数字是确认过的句数，橙色是机器归进来、还没人确认的句数，下面是确认过的台词累计多长。",
        "At the top left are the target characters, the people you want to collect; everyone else is labeled \"Other\". The gray number is lines confirmed, the orange one is lines the machine gave them that no one has confirmed yet, and below is the total length of the confirmed lines.")}</p></div>`
      : html`
        <div class="role-head">
          ${other ? html`<${Avatar} blank=${true} size="xl" />`
            : html`<${Avatar} role=${current} name=${role} size="xl" onClick=${canCrop ? onAvatar : null}
              title=${canCrop ? tr("从左边的画面里截一块当头像", "Crop an avatar from the picture on the left")
                : tr("左边放出画面后，可以从画面里截头像", "Once the picture on the left shows, you can crop an avatar from it")} />`}
          <div><h2>${other ? name : html`<${RoleName} role=${current} name=${role} />`}</h2>
            <div class="stats">${tr(`确认过 ${confirmed.length} 句`, `${lines(confirmed.length)} confirmed`)}${
              info?.seconds > 0 ? tr(`，共 ${howLong(info.seconds)}`, `, ${howLong(info.seconds)} in total`) : ""}${
              info?.low_seconds > 0 ? tr(`，其中质量低 ${howLong(info.low_seconds)}`, `, ${howLong(info.low_seconds)} of it low quality`) : ""} · ${
              tr(`机器归进来 ${pending.length} 句`, `${lines(pending.length)} given by the machine`)}
              ${other || current.target ? "" : tr(" · 不是目标角色", " · not a target character")}</div></div>
          <div class="role-actions">
            <button onClick=${() => setPlaying(!playing)}>${playing ? tr("停止连播", "Stop playing") : tr("连播待核对", "Play all to check")} <kbd>P</kbd></button>
            ${!other && html`<button class=${current.named === false ? "primary" : ""} onClick=${onRename}>
              ${current.named === false ? tr("起名字", "Name") : tr("改名或合并", "Rename or merge")}</button>
            <button onClick=${onToggleTarget}
              title=${current.target ? tr("不再收集这个人：机器不再猜这个角色，已标的留着，以后还能加回来",
                  "Stop collecting this person: the machine stops guessing them, their labels stay, and you can add them back later")
                : tr("重新收集这个人：以前标「其他」的台词会列进「可能漏掉的」，要复查",
                  "Collect this person again: lines labeled \"Other\" before will be listed under Maybe missed for you to recheck")}>
              ${current.target ? tr("不再作为目标", "Stop targeting") : tr("设为目标角色", "Make target")}</button>`}
          </div>
        </div>
        ${pending.length > 0 && html`<div class="welcome" style="align-items:center">
          <div style="flex:1"><h3>${tr(`机器把这 ${pending.length} 句归给了${other ? "「其他」" : ` ${role}`}`,
            `The machine gave these ${lines(pending.length)} to ${them}`)}</h3>
            <p>${tr(html`从最没把握的开始排。听到不对的，直接标成对的人或「其他」<kbd>Q</kbd>，它就离开这里；听完一键确认其余的。`,
              html`Least sure first. When one is wrong, label it with the right character or "Other" <kbd>Q</kbd> and it leaves this list; when you're done listening, confirm the rest at once.`)}</p></div>
          <button class="primary" onClick=${onConfirmRest}>
            ${tr(`确认其余 ${pending.length} 句`, `Confirm the other ${lines(pending.length)}`)} <kbd style="margin-left:4px">Shift+Enter</kbd></button>
        </div>`}
        ${pending.map((clip) => html`<${Row} key=${clip.id} clip=${clip} roles=${roles} labelText=${labelText}
          selected=${clip.id === focus} flash=${flashes.has(clip.id)} showTarget=${other}
          onSelect=${() => setFocus(clip.id)} />`)}
        ${maybe.length > 0 && html`<div class="section-title">${tr(`可能漏掉的 ${maybe.length} 句`, `Maybe missed: ${lines(maybe.length)}`)}</div>
          <p class="note" style="margin:0 0 8px">${tr(
            `机器没归给 ${role}，但听起来有可能是，最像的排在前面。刚设成目标角色时，以前标成「其他」的台词也会列在这里。`,
            `The machine didn't give these to ${role}, but they might be; most likely first. Right after you make someone a target, lines labeled "Other" before are listed here too.`)}</p>
          ${maybe.map((clip) => html`<${Row} key=${clip.id} clip=${clip} roles=${roles} labelText=${labelText} maybeOf=${role}
            selected=${clip.id === focus} flash=${flashes.has(clip.id)}
            onSelect=${() => setFocus(clip.id)} />`)}`}
        ${confirmed.length > 0 && html`<div class="section-title">${tr(`确认过的 ${confirmed.length} 句`, `Confirmed: ${lines(confirmed.length)}`)}${
          other ? tr("，最像某个目标角色的排在前面", ", most like a target character first") : ""}</div>
          ${confirmed.map((clip) => html`<${Row} key=${clip.id} clip=${clip} roles=${roles} labelText=${labelText} showTarget=${other}
            selected=${clip.id === focus} flash=${flashes.has(clip.id)} onSelect=${() => setFocus(clip.id)} />`)}`}
      `}
    </div>
  </div>`;
}

/* ───────────── Groups view: name a group of similar voices ───────────── */

/* `picked`: the ticked lines in each group. The group's buttons act only on these; the keys too, see App. */
function GroupsView({ groups, loading, roles, dock, labelText, onName, onNew, focus, setFocus, firstRun, picked, setPicked }) {
  /* The last line ticked in each group, so Shift+click can tick the lines between. */
  const [anchor, setAnchor] = useState({});
  if (loading) return html`<div class="empty"><div class="spinner" style="margin:auto"></div><p>${tr("正在把声音相近的台词分组…", "Grouping lines with similar voices…")}</p></div>`;
  return html`<div>
    ${firstRun && html`<div class="welcome"><div>
      <h3>${tr("第一步：给声音相近的一组起个名字", "Step one: name a group of similar voices")}</h3>
      <p>${tr("机器先把听起来像同一个人的台词放在一起。点一句听一听，勾上同一个人的台词，或者按「全选」。再在下面选是谁：是你要收集的新面孔，就按「新角色」把勾上的台词定成一个目标角色，接着可以起名字、从画面里截一张头像，都可以以后再做；不是你要的人，就按「其他」。",
        "The machine puts lines that sound like the same person together. Click a line to hear it, then tick the lines of the same person, or press \"Select all\". Then pick who it is below: if it is a new face you want to collect, press \"New character\" to make the ticked lines a target character, then you can type a name and crop an avatar from the picture, or do both later. If it is not someone you want, press \"Other\".")}</p>
      <ol><li>${tr("一组里混着几个人时，分几次勾、几次标。按住 Shift 点，能一下勾上中间的几句。",
        "When a group mixes several people, tick and label them in turns. Shift+click ticks all the lines in between.")}</li>
      <li>${tr("有勾选时，数字键、Q、N 标勾上的台词；没勾选时，标正在播放的那一句。",
        "While lines are ticked, the number keys, Q and N label the ticked lines; with none ticked, they label the line playing.")}</li>
      <li>${tr("每命名一组，机器就会重新学一次，其余台词的猜测随之变准。", "Each group you name retrains the machine, and its guesses for the other lines get better.")}</li>
      <li>${tr("定下目标角色、再标几组「其他」以后，去「场景」视图逐句确认会快得多。",
        "Once you have your target characters and a few groups of \"Other\", confirming line by line in the Scenes view goes much faster.")}</li></ol></div></div>`}
    ${groups.length === 0 && html`<div class="empty"><h2>${tr("没有可分的组了", "No groups left")}</h2>
      <p>${tr("这一集还没标的台词，要么彼此都不太像，要么已经全部有了名字。去「场景」视图逐句确认吧。",
        "The unlabeled lines in this episode are either not much alike, or all named already. Go confirm them line by line in the Scenes view.")}</p></div>`}
    <div class="groups">
      ${groups.map((g, gi) => {
        const ticked = picked[g.key] || new Set();
        /* Labeled lines stay in the group for you to see, but can't be ticked. */
        const open = g.clips.filter((c) => !c.label);
        const keep = open.filter((c) => ticked.has(c.id));
        const all = open.length > 0 && keep.length === open.length;
        const done = open.length === 0;
        /* Built on the newest ticks, so two clicks before the page draws again both count. */
        const tick = (c, e) => {
          e.stopPropagation();
          const shift = e.shiftKey;
          setPicked((p) => {
            const next = new Set(p[g.key] || []);
            const on = !next.has(c.id);
            const from = open.findIndex((o) => o.id === anchor[g.key]);
            const to = open.findIndex((o) => o.id === c.id);
            const span = shift && from >= 0 ? open.slice(Math.min(from, to), Math.max(from, to) + 1) : [c];
            span.forEach((o) => (on ? next.add(o.id) : next.delete(o.id)));
            return { ...p, [g.key]: next };
          });
          setAnchor((a) => ({ ...a, [g.key]: c.id }));
        };
        const tickAll = () => setPicked((p) => ({ ...p, [g.key]: new Set(all ? [] : open.map((c) => c.id)) }));
        const ids = keep.map((c) => c.id);
        return html`<div class="group ${g.clips.some((c) => c.id === focus) ? "sel" : ""} ${done ? "done" : ""}">
          <h3>${tr(`第 ${gi + 1} 组`, `Group ${gi + 1}`)} <span class="meta">${lines(g.size)} · ${tr(`${g.seconds} 秒`, `${g.seconds} s`)}${
            done ? tr(" · 都标好了", " · all labeled") : ""}</span>
            ${g.hint && html`<${Closest} roles=${roles} name=${g.hint.name}
              title=${tr("机器在这组里最常猜的角色", "The character the machine guesses most often in this group")} />`}</h3>
          <div class="members">
            ${g.clips.map((c) => html`<div class="member ${ticked.has(c.id) && !c.label ? "picked" : ""} ${c.label ? "labeled" : ""} ${c.id === focus ? "playing" : ""}"
                onClick=${() => setFocus(c.id)}>
              ${c.label ? html`<span></span>` : html`<input type="checkbox" checked=${ticked.has(c.id)} onClick=${(e) => tick(c, e)}
                onMouseDown=${(e) => e.preventDefault()}
                title=${tr("勾上，下面的按钮就标这一句；按住 Shift 点，勾上中间的几句", "Tick it for the buttons below to label it; Shift+click ticks the lines in between")} />`}
              <span>${c.text || tr("（没有字幕文字）", "(no subtitle text)")}</span>
              ${c.label ? html`<span class="pill done" title=${tr("已经标了；按 Z 撤销，或在左边改", "Already labeled. Press Z to undo, or change it on the left")}>
                ${labelText[c.label] || c.label}${c.unusable ? tr("·质量低", " · low quality") : ""}</span>` : html`<span></span>`}
              <span class="t">${c.episode} ${stamp(c.start)}</span>
            </div>`)}
          </div>
          ${!done && html`<div class="pick-row">
            <button type="button" onClick=${tickAll}>${all ? tr("全不选", "Select none") : tr("全选", "Select all")}</button>
            <span class="note">${keep.length ? tr(`勾了 ${keep.length} 句；数字键、Q、N 也标勾上的`, `${lines(keep.length)} ticked; number keys, Q and N label them too`)
              : tr("先勾上同一个人的台词，再选是谁", "Tick the lines of one person first, then pick who it is")}</span>
          </div>`}
          ${/* The same choices in the same order as the bottom bar, with the same keys. */ ""}
          ${!done && html`<div class="who-row">
            ${dock.map((name, i) => html`<button type="button" key=${name} class="chip ${name === g.hint?.name ? "top" : ""}" disabled=${!keep.length}
                title=${name === g.hint?.name ? tr("机器在这组里最常猜的角色", "The character the machine guesses most often in this group") : ""}
                onClick=${() => onName(ids, name)}>
              <${Avatar} role=${roles[name]} name=${name} size="sm" /><${RoleName} role=${roles[name]} name=${name} />${
                i < 9 ? html`<span class="k">${i + 1}</span>` : ""}</button>`)}
            <button type="button" class="chip" disabled=${!keep.length} onClick=${() => onName(ids, OTHER)}
                title=${tr("不是你要收集的人", "Not someone you want to collect")}>
              <${Avatar} blank=${true} size="sm" /><span class="rn">${labelText[OTHER]}</span><span class="k">Q</span></button>
            <button type="button" class="chip" disabled=${!keep.length} onClick=${() => onNew(ids)}
                title=${tr("新建一个目标角色，名字可以以后再起；有画面时接着截头像", "Make a new target character; you can name it later. With video, crop an avatar next")}>
              <div class="av sm unknown">+</div><span class="rn">${tr("新角色", "New character")}</span><span class="k">N</span></button>
          </div>`}
        </div>`;
      })}
    </div>

  </div>`;
}

/* ───────────── Export ───────────── */

/* Text subtitles for each episode: paste a path; the server measures the offset and refuses ones that don't fit. */
function TextSubtitles({ state, setState, toast }) {
  const [paths, setPaths] = useState({});
  const [busy, setBusy] = useState(null);
  const attach = async (episode) => {
    setBusy(episode);
    try {
      setState(await call("/api/text-subtitles", { episode, path: paths[episode] || "" }));
      setPaths({ ...paths, [episode]: "" });
      toast(tr(`${episode} 的台词字幕配好了`, `Text subtitles attached to ${episode}`));
    } catch (e) { toast(e.message, true); }
    setBusy(null);
  };
  return html`<div class="text-subs">
    ${state.episodes.map((e) => {
      const t = e.text_subtitles;
      return html`<div class="text-sub">
        <span class="ep">${e.name}</span>
        <span class="now">${t
          ? html`${t.file} <span class="min">${tr(`偏移 ${t.offset} 秒，重合 ${pct(t.agreement)}`, `offset ${t.offset} s, ${pct(t.agreement)} overlap`)}</span>`
          : html`<span class="min">${tr("还没配", "none yet")}</span>`}</span>
        <input placeholder=${t ? tr("换一份：字幕文件的路径", "Replace: path to a subtitle file") : tr("字幕文件的路径（ASS 或 SRT）", "Path to a subtitle file (ASS or SRT)")}
          value=${paths[e.name] || ""}
          onInput=${(ev) => setPaths({ ...paths, [e.name]: ev.target.value })} />
        <button disabled=${busy !== null || !(paths[e.name] || "").trim()} onClick=${() => attach(e.name)}>
          ${busy === e.name ? tr("正在对…", "Aligning…") : tr("对齐并配上", "Align and attach")}</button>
      </div>`;
    })}
  </div>`;
}

function ExportView({ state, setState, toast }) {
  const trainable = state.roles.filter((r) => r.confirmed > 0);
  const [ticked, setPicked] = useState(() => new Set());
  /* Only names still on the list: a character ticked here may have been renamed or merged since. */
  const picked = new Set(trainable.map((r) => r.name).filter((n) => ticked.has(n)));
  const [form, setForm] = useState("gpt-sovits");
  const [language, setLanguage] = useState("ja");
  const [textSubtitles, setTextSubtitles] = useState(() => state.episodes.some((e) => e.text_subtitles));
  const [includeAuto, setIncludeAuto] = useState(false);
  /* Local date: toISOString gives UTC, which is still the day before in UTC+8 until 8 in the morning. */
  const [out, setOut] = useState(() => {
    const d = new Date();
    const two = (n) => String(n).padStart(2, "0");
    return `exports/${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`;
  });
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  /* The result appears below the button, often off screen; bring it into view. */
  const resultBox = useRef(null);
  useEffect(() => { if (result) resultBox.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [result]);
  const toggle = (name) => { const next = new Set(picked); next.has(name) ? next.delete(name) : next.add(name); setPicked(next); };
  const run = async () => {
    setBusy(true); setResult(null);
    try {
      setResult(await call("/api/export", {
        roles: [...picked], include_auto: includeAuto, form, language, out, text_subtitles: textSubtitles,
      }));
    } catch (e) { toast(e.message, true); }
    setBusy(false);
  };
  return html`<div class="form">
    <div class="toolbar" style="padding-left:0"><h2>${tr("导出训练数据", "Export training data")}</h2>
      <span class="sub">${tr("从原采样率的人声轨上切，统一响度，一个角色一个文件夹",
        "Cut from the vocals at the original sample rate, loudness evened out, one folder per character")}</span></div>
    <div class="field"><label class="title">${tr("导出哪些角色", "Characters to export")}</label>
      <div class="role-checks">
        ${trainable.map((r) => html`<label class="check ${picked.has(r.name) ? "on" : ""}">
          <input type="checkbox" checked=${picked.has(r.name)} onChange=${() => toggle(r.name)} />
          <${Avatar} role=${r} name=${r.name} size="md" /><${RoleName} role=${r} name=${r.name} />
          <span class="min">${lines(r.confirmed)}${includeAuto && r.predicted ? ` + ${r.predicted}` : ""}</span></label>`)}
      </div></div>
    <div class="field"><label class="title">${tr("包括哪些台词", "Lines to include")}</label>
      <span class="seg">
        <button class=${!includeAuto ? "on" : ""} onClick=${() => setIncludeAuto(false)}>${tr("只要人确认过的", "Only confirmed by you")}</button>
        <button class=${includeAuto ? "on" : ""} onClick=${() => setIncludeAuto(true)}>${tr("再加上机器有把握的", "Plus the machine's confident ones")}</button>
      </span>
      <div class="note" style="margin-top:6px">${includeAuto
        ? tr(`机器有把握指把握不低于 ${pct(state.model.auto_confidence)}，第 3 集上这一档约 97% 判对。训练数据里混进别人的声音，模型就会学歪。`,
          `Confident means at least ${pct(state.model.auto_confidence)} sure; on episode 3 about 97% of these were right. Other people's voices in the training data make the voice model learn the wrong thing.`)
        : tr("最干净。数据不够时再考虑加上机器有把握的。", "The cleanest. Add the machine's confident ones only if you don't have enough.")}</div></div>
    <div class="field"><label class="title">${tr("格式", "Format")}</label>
      <span class="seg">
        ${[["gpt-sovits", "GPT-SoVITS"], ["style-bert-vits2", "Style-Bert-VITS2"], ["folder", tr("只要音频（RVC）", "Audio only (RVC)")]].map(([v, l]) =>
          html`<button class=${form === v ? "on" : ""} onClick=${() => setForm(v)}>${l}</button>`)}
      </span></div>
    ${form !== "folder" && html`<div class="field"><label class="title">${tr("台词文字的语言", "Language of the text")}</label>
      <span class="seg">${[["ja", tr("日语", "Japanese")], ["zh", tr("中文", "Chinese")], ["en", tr("英语", "English")]].map(([v, l]) =>
        html`<button class=${language === v ? "on" : ""} onClick=${() => setLanguage(v)}>${l}</button>`)}</span>
      </div>`}
    ${form !== "folder" && html`<div class="field"><label class="title">${tr("台词文字从哪来", "Where the text comes from")}</label>
      <span class="seg">
        <button class=${!textSubtitles ? "on" : ""} onClick=${() => setTextSubtitles(false)}>${tr("切片段用的字幕", "The subtitles used to cut clips")}</button>
        <button class=${textSubtitles ? "on" : ""} onClick=${() => setTextSubtitles(true)}>${tr("每集另配的台词字幕", "Text subtitles for each episode")}</button>
      </span>
      ${textSubtitles
        ? html`<div class="note" style="margin-top:6px">${tr("片段不变，文字换成另配字幕里同一时间的台词。找不全台词、或者混着别人的话的片段不导出，原因写进导出目录的 rejected.tsv。",
            "The clips stay the same; the text is taken from the lines at the same time in the text subtitles. Clips whose line can't be found in full, or that include someone else's words, are not exported; the reasons go into rejected.tsv in the export folder.")}</div>
          <${TextSubtitles} state=${state} setState=${setState} toast=${toast} />`
        : html`<div class="note warn" style="margin-top:6px">${tr("切片段用的字幕是中文译文时，文字和日语声音对不上。训练日语模型请改用另配的日文字幕。",
            "If the subtitles used to cut clips are a translation, the text won't match the Japanese voices. For a Japanese voice model, use separate Japanese text subtitles.")}</div>`}</div>`}
    <div class="field"><label class="title">${tr("输出到（相对路径从启动目录算起）", "Output folder (relative paths start from where you launched avoc)")}</label>
      <input style="width:100%" value=${out} onInput=${(e) => setOut(e.target.value)} /></div>
    <div><button class="primary" disabled=${busy || picked.size === 0} onClick=${run}>
      ${busy ? tr("正在导出…", "Exporting…") : tr(`导出 ${picked.size} 个角色`, `Export ${many(picked.size, "character")}`)}</button></div>
    ${result && html`<div class="result" ref=${resultBox}><b>${tr("导出好了：", "Exported: ")}</b>${tr(`${result.files} 个文件，共 ${Math.round(result.total_sec / 6) / 10} 分钟`,
        `${many(result.files, "file")}, ${Math.round(result.total_sec / 6) / 10} minutes in total`)}<br />
      ${Object.keys(result.rejected || {}).length > 0 && html`<span>${tr("没导出：", "Not exported: ")}${Object.entries(result.rejected)
        .map(([why, n]) => tr(`${why} ${n} 条`, `${why} (${n})`)).join(tr("，", ", "))}${tr("。明细见 rejected.tsv", ". Details in rejected.tsv")}<br /></span>`}
      <span class="note">${result.out}</span></div>`}
  </div>`;
}

/* ───────────── Adding an episode and the first-use guide ───────────── */

/* The machine checks, the same list as `avoc doctor`. Fetched once; torch is loaded for the GPU check, so it can
   take a few seconds. */
function Checks() {
  const [list, setList] = useState(null);
  useEffect(() => { call("/api/doctor").then(setList).catch(() => setList([])); }, []);
  if (!list) return html`<div class="note">${tr("正在检查这台机器…", "Checking this machine…")}</div>`;
  return html`<ul class="checks">${list.map((c) => html`<li class=${c.ok ? "ok" : c.required ? "bad" : "soft"}>
    <span class="mark">${c.ok ? "✓" : c.required ? "✗" : "–"}</span>
    <span>${c.text}${!c.ok && c.fix ? html`<br /><span class="note">${c.fix}</span>` : ""}</span></li>`)}</ul>`;
}

const minutes = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s) % 60).padStart(2, "0")}`;

/* What the server read from the dialogue subtitles: the text encoding, and the styles (the named looks an ASS file
   gives its lines, such as "Default" or "OP"). The ticked styles are cut into clips; they start as the ones picked
   automatically. With a single style there is nothing to choose, so only the line count is shown. */
function SubtitleStyles({ found, chosen, setChosen }) {
  /* Subtitle groups often give each sign its own style with a line or two, so only the ticked styles and the next
     few biggest are shown at first. */
  const [all, setAll] = useState(false);
  if (found.error) return html`<div class="note warn">${found.error}</div>`;
  if (!found.styles) return html`<div class="note">${tr("正在读字幕…", "Reading the subtitles…")}</div>`;
  const read = tr(`${found.format.toUpperCase()}，${found.encoding}`, `${found.format.toUpperCase()}, ${found.encoding}`);
  if (found.styles.length === 0) return html`<div class="note warn">${tr(`字幕里没有台词（${read}）`, `There are no dialogue lines in the subtitles (${read})`)}</div>`;
  if (found.styles.length === 1) return html`<div class="note">${tr(`读到 ${found.styles[0].lines} 句台词（${read}）`, `Read ${lines(found.styles[0].lines)} of dialogue (${read})`)}</div>`;
  const toggle = (name) => {
    const next = new Set(chosen);
    if (next.has(name)) next.delete(name); else next.add(name);
    setChosen(next);
  };
  /* Ordered by the automatic choice, not the ticks, so a row stays put when it is clicked. */
  const picked = (s) => found.picked.includes(s.name);
  const ordered = [...found.styles].sort((a, b) => picked(b) - picked(a) || b.lines - a.lines);
  const shown = all ? ordered : ordered.filter((s, i) => chosen.has(s.name) || i < found.picked.length + 3);
  const hidden = ordered.filter((s) => !shown.includes(s));
  return html`<div class="style-list">
    <div class="note">${tr(`字幕（${read}）里的台词分几种样式。勾上的切成片段；歌词、招牌字之类的不用勾。已经自动选好，一般不用改，看看例句对不对就行。`,
      `The lines in these subtitles (${read}) come in several styles. Ticked styles are cut into clips; leave out song lyrics, signs and such. They are already picked automatically and rarely need changing; just check the sample lines.`)}</div>
    ${shown.map((s) => html`<label class="style-row" key=${s.name}>
      <input type="checkbox" checked=${chosen.has(s.name)} onChange=${() => toggle(s.name)} />
      <span><b>${s.name}</b> <span class="note">${lines(s.lines)} · ${minutes(s.first)}–${minutes(s.last)}</span>
        <span class="samples">${s.samples.join(" ／ ")}</span></span></label>`)}
    ${hidden.length > 0 && html`<div><button type="button" class="ghost" onClick=${() => setAll(true)}>${tr(
      `还有 ${hidden.length} 种样式，共 ${hidden.reduce((n, s) => n + s.lines, 0)} 句`,
      `${many(hidden.length, "more style")}, ${lines(hidden.reduce((n, s) => n + s.lines, 0))} in all`)}</button></div>`}
    ${chosen.size === 0 && html`<div class="note warn">${tr("至少勾一种", "Tick at least one")}</div>`}
  </div>`;
}

/* The form for one episode, and the progress of the `avoc add` the server runs for it. `adding` is the server's job
   status, polled by App. */
function AddEpisode({ state, adding, setAdding, onOpen, toast }) {
  const last = [...state.episodes].reverse().find((e) => e.offset != null);
  const [video, setVideo] = useState("");
  const [subtitles, setSubtitles] = useState("");
  const [textSubtitles, setTextSubtitles] = useState("");
  const [offset, setOffset] = useState(last ? String(last.offset) : "");
  const [busy, setBusy] = useState(false);
  /* null: no subtitle path yet. {}: reading. Otherwise the server's description, or {error}. */
  const [found, setFound] = useState(null);
  const [chosen, setChosen] = useState(new Set());
  const log = useRef(null);
  useEffect(() => { if (log.current) log.current.scrollTop = log.current.scrollHeight; }, [adding?.lines.length]);
  /* Read the subtitles shortly after the path stops changing. An answer for an older path is dropped. */
  useEffect(() => {
    const path = subtitles.trim();
    setFound(path ? {} : null);
    if (!path) return;
    let current = true;
    const timer = setTimeout(() => call("/api/subtitle-styles", { path })
      .then((f) => { if (current) { setFound(f); setChosen(new Set(f.picked)); } })
      .catch((e) => { if (current) setFound({ error: e.message }); }), 300);
    return () => { current = false; clearTimeout(timer); };
  }, [subtitles]);
  const run = async (body) => {
    setBusy(true);
    try { setAdding(await call("/api/add", body)); } catch (e) { toast(e.message, true); }
    setBusy(false);
  };
  const start = (e) => {
    e.preventDefault();
    const seconds = offset.trim() === "" ? null : Number(offset);
    if (seconds !== null && !Number.isFinite(seconds)) { toast(tr("字幕偏移要填一个数，比如 -0.95", "The subtitle offset must be a number, such as -0.95"), true); return; }
    /* While the subtitles are still being read, or could not be read, the server picks the styles itself. */
    const styles = found?.styles ? found.styles.map((s) => s.name).filter((n) => chosen.has(n)) : null;
    run({ video, subtitles, text_subtitles: textSubtitles, offset: seconds, styles });
  };
  const stop = async () => {
    setBusy(true);
    try { setAdding(await call("/api/add/stop", {})); } catch (e) { toast(e.message, true); }
    setBusy(false);
  };
  const running = adding?.state === "running";
  const unfinished = Object.entries(state.skipped || {});
  return html`<div class="add-episode">
    ${adding && adding.state !== "idle" && html`<div class="add-run ${adding.state}">
      <div class="add-head"><b>${{
        running: tr(`正在加 ${adding.episode}…`, `Adding ${adding.episode}…`),
        done: tr(`${adding.episode} 加好了`, `${adding.episode} is added`),
        failed: tr(`${adding.episode} 没加成`, `${adding.episode} failed`),
        stopped: tr(`${adding.episode} 已停下`, `${adding.episode} was stopped`),
      }[adding.state]}</b>
        <span class="note">${minutes(adding.seconds)}</span>
        <span class="spacer"></span>
        ${running && html`<button disabled=${busy} onClick=${stop}>${tr("停下", "Stop")}</button>`}
        ${adding.state === "done" && state.episodes.some((e) => e.name === adding.episode)
          && html`<button class="primary" onClick=${() => onOpen(adding.episode)}>${tr(`打开 ${adding.episode}`, `Open ${adding.episode}`)}</button>`}</div>
      <pre class="add-log" ref=${log}>${adding.lines.join("\n") || tr("正在启动…", "Starting…")}</pre>
      ${running && adding.bar && html`<div class="note add-bar">${adding.bar}</div>`}
      ${adding.state === "failed" && adding.errors?.length > 0 && html`<pre class="add-log errors">${adding.errors.slice(-15).join("\n")}</pre>`}
      ${running && html`<div class="note">${tr("有显卡时一集要几分钟，只用 CPU 会慢很多。可以关掉这个窗口接着标别的集，做完会提示。",
        "With a GPU one episode takes a few minutes; on the CPU it takes much longer. You can close this and keep labeling other episodes; you will be told when it is done.")}</div>`}
      ${(adding.state === "failed" || adding.state === "stopped") && html`<div class="note">${tr("改好问题以后再点「开始」。做完的步骤会留着，从停下的地方接着做。",
        "Fix the problem, then press Start again. Finished steps are kept, and it carries on from where it stopped.")}</div>`}
    </div>`}
    ${unfinished.length > 0 && html`<div class="field"><label class="title">${tr("没做完的集", "Unfinished episodes")}</label>
      ${unfinished.map(([name, why]) => html`<div class="unfinished"><b>${name}</b><span class="note">${why}</span>
        <button disabled=${busy || running} onClick=${() => run({ resume: name })}>${tr("接着做", "Carry on")}</button></div>`)}</div>`}
    <form class="add-form" onSubmit=${start}>
      <div class="field"><label class="title">${tr("视频文件", "Video file")}</label>
        <input value=${video} onInput=${(e) => setVideo(e.target.value)} placeholder="D:\\anime\\Episode 01.mkv" /></div>
      <div class="field"><label class="title">${tr("对白字幕（ASS 或 SRT，按它切台词）", "Dialogue subtitles (ASS or SRT; lines are cut from it)")}</label>
        <input value=${subtitles} onInput=${(e) => setSubtitles(e.target.value)} placeholder="D:\\anime\\Episode 01.ass" />
        ${found && html`<${SubtitleStyles} key=${subtitles} found=${found} chosen=${chosen} setChosen=${setChosen} />`}</div>
      <div class="field"><label class="title">${tr("日文台词字幕（可以不填，导出日文文字时用）", "Japanese text subtitles (optional; used for Japanese export text)")}</label>
        <input value=${textSubtitles} onInput=${(e) => setTextSubtitles(e.target.value)} placeholder="D:\\anime\\Episode 01.ja.srt" /></div>
      <div class="field"><label class="title">${tr("字幕偏移（秒）", "Subtitle offset (seconds)")}</label>
        <input class="offset" value=${offset} onInput=${(e) => setOffset(e.target.value)} placeholder=${tr("自动测", "measure")} />
        <div class="note">${tr("字幕时间要加几秒才和声音对上。同一片源、同一字幕组的每一集都一样，所以默认填上一集的值。不知道就填 0，或者空着让它自动测（要 Hugging Face 令牌）。",
          "How many seconds to add to the subtitle times so they line up with the sound. It is the same for every episode from the same source and subtitle group, so the last episode's value is filled in. If you don't know, try 0, or leave it empty to measure it (needs a Hugging Face token).")}</div></div>
      <div class="note">${tr("路径整段粘贴进来就行。Windows 上按住 Shift 右键文件，选「复制文件地址」。",
        "Paste the full paths. On Windows, hold Shift, right-click the file, and choose \"Copy as path\".")}</div>
      <div><button class="primary" type="submit" disabled=${busy || running || !video.trim() || !subtitles.trim() || (found?.styles && chosen.size === 0)}>${tr("开始", "Start")}</button></div>
    </form>
  </div>`;
}

function AddDialog({ onClose, ...props }) {
  return html`<div class="overlay" onClick=${onClose}><div class="help add-dialog" onClick=${(e) => e.stopPropagation()}>
    <h2>${tr("加一集", "Add an episode")}</h2><${AddEpisode} ...${props} /></div></div>`;
}

/* The page for a workspace with no usable episode yet: what the tool does, the machine checks, and the form. */
function Welcome(props) {
  return html`<div class="form welcome-page">
    <div><h2>${tr("欢迎", "Welcome")}</h2>
      <p>${tr("这个工具把一个动画角色说的每一句台词收集成干净的单人音频，带上台词文字，可以直接拿去训练语音模型。",
        "This tool collects every line one anime character speaks as clean single-speaker audio with its text, ready for training a voice model.")}</p>
      <ol class="steps">
        <li>${tr("加一集：给出视频和对白字幕。机器按字幕切台词，再把人声和音乐分开。", "Add an episode: give its video and dialogue subtitles. The machine cuts the lines along the subtitles and separates the voices from the music.")}</li>
        <li>${tr("在「起步分组」里给你要的角色起名，其他人都标「其他」。", "In Groups, name the character you want, and label everyone else \"Other\".")}</li>
        <li>${tr("在「场景」和「角色」里改机器猜错的。每改一次，机器马上重学。", "In Scenes and Characters, fix the machine's wrong guesses. It retrains after every fix.")}</li>
        <li>${tr("在「导出」里导出成 GPT-SoVITS、Style-Bert-VITS2 或 RVC 用的格式。", "In Export, export for GPT-SoVITS, Style-Bert-VITS2 or RVC.")}</li>
      </ol></div>
    <div class="field"><label class="title">${tr("这台机器", "This machine")}</label><${Checks} key=${lang} /></div>
    <div class="field"><label class="title">${tr("加第一集", "Add the first episode")}</label><${AddEpisode} ...${props} /></div>
    <p class="note">${tr(html`也可以在命令行里加：<code>uv run avoc add "${props.state.workspace}" 视频 --subs 字幕</code>`,
      html`You can also add one in a terminal: <code>uv run avoc add "${props.state.workspace}" VIDEO --subs SUBTITLES</code>`)}</p>
  </div>`;
}

function Help({ onClose }) {
  const rows = [
    [tr("J / ↓，K / ↑", "J / ↓, K / ↑"), tr("下一句，上一句", "Next line, previous line")],
    [tr("空格", "Space"), tr("从头重播这一句；再点一下选中的那句也一样", "Replay this line from the start; clicking the selected line again does the same")],
    ["Enter", tr("接受机器猜的第一个", "Accept the machine's top guess")],
    ["1 – 9", tr("标成底部角色栏里对应的目标角色", "Label as the matching target character in the bottom bar")],
    ["Shift + 1 – 9", tr("同一个目标角色，但质量低：背景音太重或有人同时出声。不拿来认人，导出时跳过",
      "The same target character, but low quality: too much background sound or someone talking at the same time. Not used to recognize anyone, skipped on export")],
    ["Q", tr("其他：不是任何一个目标角色", "Other: not any of the target characters")],
    ["N", tr("标成一个新的目标角色，名字以后再起；有画面时接着截头像", "Label as a new target character, to be named later; with video, crop an avatar next")],
   ["Backspace", tr("清掉这句的标签，回到机器的猜测（Z 是撤回上一步，不一定是清掉）",
      "Clear this line's label and go back to the machine's guess (Z undoes the last step, which is not always the same)")],
    ["R", tr("听机器最像的那个角色的参考音", "Hear a reference line of the machine's top guess")],
    ["L", tr("看不出是谁时，这句临时前后各多放 5 秒；再按 15 秒，再按回到平常",
      "When you can't tell who it is, play 5 more seconds on each side; press again for 15, again for normal")],
    ["Z", tr("撤销上一步（可以一直往回撤）", "Undo the last step (you can keep going back)")],
    ["F", tr("场景视图里只看要处理的", "In the Scenes view, show only what needs work")],
    [tr("角色视图里 Shift+Enter", "Shift+Enter in Characters"), tr("确认机器归给这个角色、还没人确认的全部句子",
      "Confirm all lines the machine gave this character that no one has confirmed yet")],
    [tr("角色视图里 P", "P in Characters"), tr("从最没把握的开始连着播", "Play one after another, least sure first")],
    ["G / S / O / E", tr("切到起步分组 / 场景 / 角色 / 导出", "Go to Groups / Scenes / Characters / Export")],
    [tr("截头像时 Enter / Esc", "Enter / Esc when cropping"), tr("保存 / 放弃", "Save / cancel")],
  ];
  return html`<div class="overlay" onClick=${onClose}><div class="help" onClick=${(e) => e.stopPropagation()}>
    <h2>${tr("快捷键", "Keyboard shortcuts")}</h2><table>${rows.map(([k, v]) => html`<tr><td><kbd>${k}</kbd></td><td>${v}</td></tr>`)}</table>
    <p class="note" style="margin-top:12px">${tr("每次标注都立刻保存，并让机器重新学一次。标注、新建、改名和合并角色都能撤销；头像和设不设目标角色不算标注，直接改回去就行。",
      "Every label is saved at once and retrains the machine. Labeling, making, renaming and merging characters can all be undone; avatars and target settings are not labels, just change them back.")}</p>
  </div></div>`;
}

/* ───────────── Cropping an avatar from the picture ───────────── */

const AVATAR_SIDE = 256;

function Cropper({ source, name, role, naming, taken, onSave, onClose }) {
  const canvas = useRef(null);
  const preview = useRef(null);
  const drag = useRef(null);
  const nameBox = useRef(null);
  /* For a new character there is also a name box. Without a picture (no video, or the frame shows someone else),
     there is only the name box. */
  const W = source?.videoWidth || 0;
  const H = source?.videoHeight || 0;
  const [typed, setTyped] = useState("");
  const [problem, setProblem] = useState("");
  /* The box is square, in the video's own pixels. By default it is the middle of the picture, 60% of its height. */
  const [box, setBox] = useState(() => {
    const s = Math.round(H * 0.6);
    return { x: Math.round((W - s) / 2), y: Math.round((H - s) / 2), s };
  });
  const [time, setTime] = useState(source?.currentTime || 0);
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    if (naming) nameBox.current?.focus();
    if (!source) return;
    source.pause();
    const draw = () => {
      canvas.current?.getContext("2d").drawImage(source, 0, 0, W, H);
      setFrame((n) => n + 1);
    };
    draw();
    source.addEventListener("seeked", draw);
    return () => source.removeEventListener("seeked", draw);
  }, []);

  useEffect(() => {
    if (!canvas.current || !preview.current) return;
    const ctx = preview.current.getContext("2d");
    ctx.clearRect(0, 0, 96, 96);
    ctx.drawImage(canvas.current, box.x, box.y, box.s, box.s, 0, 0, 96, 96);
  }, [box, frame]);

  const clamp = (b) => {
    const s = Math.max(24, Math.min(b.s, W, H));
    return { s, x: Math.min(Math.max(b.x, 0), W - s), y: Math.min(Math.max(b.y, 0), H - s) };
  };
  const at = (e) => {
    const r = canvas.current.getBoundingClientRect();
    return { x: (e.clientX - r.left) / r.width * W, y: (e.clientY - r.top) / r.height * H };
  };
  /* Drag inside the box to move it, drag the bottom-right corner to resize, press outside to draw a new one. */
  const down = (e) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    const p = at(e);
    const inside = p.x >= box.x && p.x <= box.x + box.s && p.y >= box.y && p.y <= box.y + box.s;
    if (e.target.classList.contains("handle")) drag.current = { mode: "size", ox: box.x, oy: box.y };
    else if (inside) drag.current = { mode: "move", dx: p.x - box.x, dy: p.y - box.y };
    else { drag.current = { mode: "size", ox: p.x, oy: p.y }; setBox(clamp({ x: p.x, y: p.y, s: 24 })); }
  };
  const moveTo = (e) => {
    const d = drag.current;
    if (!d) return;
    const p = at(e);
    if (d.mode === "move") setBox(clamp({ ...box, x: p.x - d.dx, y: p.y - d.dy }));
    else {
      const s = Math.max(p.x - d.ox, p.y - d.oy, 24);
      setBox(clamp({ x: d.ox, y: d.oy, s: Math.min(s, W - d.ox, H - d.oy) }));
    }
  };
  const up = () => { drag.current = null; };
  const wheel = (e) => {
    e.preventDefault();
    const grow = e.deltaY < 0 ? 1.06 : 1 / 1.06;
    const s = box.s * grow;
    setBox(clamp({ x: box.x + (box.s - s) / 2, y: box.y + (box.s - s) / 2, s }));
  };
  /* withAvatar false: keep only the name. */
  const save = (withAvatar = true) => {
    /* Read the box itself: a quick Enter can come before the page has drawn the last letter typed. */
    const newName = naming ? (nameBox.current?.value ?? typed).trim() : "";
    const wrong = newName ? taken(newName) : "";
    if (wrong) { setProblem(wrong); nameBox.current?.focus(); return; }
    let image = null;
    if (source && withAvatar) {
      const out = document.createElement("canvas");
      out.width = out.height = AVATAR_SIDE;
      out.getContext("2d").drawImage(canvas.current, box.x, box.y, box.s, box.s, 0, 0, AVATAR_SIDE, AVATAR_SIDE);
      image = out.toDataURL("image/jpeg", 0.9);
    }
    onSave(image, newName);
  };
  useEffect(() => {
    const key = (e) => {
      /* While an input method is still putting a word together, Enter and Escape belong to it. */
      if (e.isComposing || e.keyCode === 229) return;
      if (e.key === "Escape") { e.preventDefault(); onClose(); }
      else if (e.key === "Enter") { e.preventDefault(); save(); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  const left = (v, total) => `${v / total * 100}%`;
  return html`<div class="overlay" onClick=${onClose}><div class="cropper" onClick=${(e) => e.stopPropagation()}>
    <h2>${naming ? tr("新角色", "New character")
      : tr(html`给 <${RoleName} role=${role} name=${name} /> 截一张头像`, html`Crop an avatar for <${RoleName} role=${role} name=${name} />`)}</h2>
    ${naming && html`<div class="crop-name">
      <input ref=${nameBox} value=${typed} placeholder=${tr(`名字，可以不填，先叫「${name}」`, `Name, optional. For now it is "${name}"`)}
        onInput=${(e) => { setTyped(e.target.value); setProblem(""); }} />
      ${problem && html`<p class="note bad">${problem}</p>`}
    </div>`}
    ${source && html`${naming && html`<p class="note">${tr("再从画面里截一张头像：", "And crop an avatar from the picture:")}</p>`}
    <div class="crop-area" onPointerDown=${down} onPointerMove=${moveTo} onPointerUp=${up} onWheel=${wheel}>
      <canvas ref=${canvas} width=${W} height=${H}></canvas>
      <div class="crop-box" style=${`left:${left(box.x, W)};top:${left(box.y, H)};width:${left(box.s, W)};height:${left(box.s, H)}`}>
        <div class="handle"></div></div>
    </div>
    <div class="crop-bar">
      <label class="note">${tr("换一帧", "Pick a frame")}</label>
      <input type="range" min="0" max=${source.duration || 0} step="0.04" value=${time}
        onInput=${(e) => { const t = Number(e.target.value); setTime(t); source.currentTime = t; }} />
      <canvas ref=${preview} class="crop-preview" width="96" height="96"></canvas>
    </div>
    <p class="note">${tr("拖动方框挪位置，拖右下角或滚轮缩放，在框外按下可以重新画。",
      "Drag the box to move it, drag its bottom-right corner or use the wheel to resize, press outside it to draw a new one.")}</p>`}
    <div class="crop-actions">
      <button class="ghost" onClick=${onClose}>${naming ? tr("跳过", "Skip") : tr("放弃", "Cancel")} <kbd>Esc</kbd></button>
      ${naming && source && html`<button onClick=${() => save(false)}>${tr("不要头像", "No avatar")}</button>`}
      <button class="primary" onClick=${() => save()}>${naming ? tr("保存", "Save") : tr("用这张", "Use this")} <kbd>Enter</kbd></button>
    </div>
  </div></div>`;
}

/* ───────────── Main ───────────── */

function App() {
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);
  const [view, setView] = useState("scene");
  const [episode, setEpisode] = useState(null);
  const [clips, setClips] = useState([]);
  const [focus, setFocusState] = useState(() => saved.get("clip"));
  /* The newest focus, set at once. Keys pressed faster than the page draws read it, so each press acts on the
     line the press before moved to, not on the one still on screen. */
  const focusNow = useRef(focus);
  const setFocus = useCallback((next) => {
    focusNow.current = typeof next === "function" ? next(focusNow.current) : next;
    setFocusState(focusNow.current);
  }, []);
  const [onlyWork, setOnlyWork] = useState(() => saved.get("only") === "1");
  /* Whether Whole episode lists the short lines skipped by default (status "skipped"); labeled ones always show. */
  const [showShort, setShowShort] = useState(() => localStorage.getItem("show-short") === "1");
  const [role, setRole] = useState(null);
  const roleNow = useRef(role);
  roleNow.current = role;
  const [groups, setGroups] = useState([]);
  const [groupsLoading, setGroupsLoading] = useState(false);
  /* The ticked lines in Groups, per group. Kept here because the keys label them too. Like focusNow, the newest
     ticks are kept in a ref as well, so a second quick key press doesn't label the same lines again. */
  const [picked, setPickedState] = useState({});
  const pickedNow = useRef(picked);
  const setPicked = useCallback((next) => {
    pickedNow.current = typeof next === "function" ? next(pickedNow.current) : next;
    setPickedState(pickedNow.current);
  }, []);
 const [help, setHelp] = useState(false);
  /* The server's job that adds an episode (see AddEpisode), and whether its dialog is open. */
  const [adding, setAdding] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);
  const [sound, setSound] = useState(() => localStorage.getItem("sound") || "vocals");
  const [speed, setSpeed] = useState(() => {
    const s = Number(localStorage.getItem("speed"));
    return SPEEDS.includes(s) ? s : 1;
  });
  /* Extra seconds played around this line, see CONTEXTS. Back to normal on the next line. */
  const [context, setContext] = useState(0);
  const nextContext = () => setContext((c) => CONTEXTS[(CONTEXTS.indexOf(c) + 1) % CONTEXTS.length]);
  const [flashes, setFlashes] = useState(() => new Set());
  const [playing, setPlaying] = useState(false);
  const [crop, setCrop] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem("theme") || "light");
  /* Only here to re-render everything when the language changes; the strings read the module's `lang`. */
  const [language, setLanguage] = useState(lang);
  const dockOrder = useRef([]);
  const playerRef = useRef(null);
  const refAudio = useRef(null);
  const toastTimer = useRef(null);
  const stableOrder = useRef(null);
  const loadSeq = useRef(0);

  const roles = useMemo(() => Object.fromEntries((state?.roles || []).map((r) => [r.name, r])), [state]);
  /* How labels that are not character names are shown; for now only "other". */
  const labelText = useMemo(() => ({ [OTHER]: tr("其他", "Other") }), [language]);
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
  const firstRun = state && totalConfirmed === 0;

  useEffect(() => {
    if (theme === "dark") document.documentElement.dataset.theme = "dark";
    else delete document.documentElement.dataset.theme;
    localStorage.setItem("theme", theme);
  }, [theme]);
  useEffect(() => { localStorage.setItem("show-short", showShort ? "1" : "0"); }, [showShort]);
  useEffect(() => { localStorage.setItem("sound", sound); }, [sound]);
  useEffect(() => { localStorage.setItem("speed", String(speed)); }, [speed]);
  /* Write where you are after # in the address, so a refresh comes back to the same view, episode, character
     and line. */
  useEffect(() => {
    if (!state) return;
    const at = new URLSearchParams({ view, ep: episode || "", role: role || "", clip: focus || "", only: onlyWork ? "1" : "" });
    for (const [k, v] of [...at]) if (!v) at.delete(k);
    history.replaceState(null, "", `#${at}`);
  }, [state, view, episode, role, focus, onlyWork]);

  const showToast = useCallback((message, isError = false, extra = null) => {
    clearTimeout(toastTimer.current);
    setToast({ message, isError, extra });
    toastTimer.current = setTimeout(() => setToast(null), isError ? 6000 : 3800);
  }, []);

  /* Switch the page language. The overview is fetched again because it holds a few messages from the server,
     such as why an episode was not loaded. */
  const switchLanguage = () => {
    lang = lang === "en" ? "zh" : "en";
    localStorage.setItem("lang", lang);
    showLanguage();
    setLanguage(lang);
    call("/api/state").then(setState).catch(() => {});
  };

  useEffect(() => {
    call("/api/state").then((s) => {
      setState(s);
      const ep = saved.get("ep");
      if (s.episodes.length) setEpisode(s.episodes.some((e) => e.name === ep) ? ep : s.episodes[0].name);
      const r = saved.get("role");
      if (r === OTHER || s.roles.some((x) => x.name === r)) setRole(r);
      if (VIEWS.includes(saved.get("view"))) setView(saved.get("view"));
      else if (!s.roles.some((r) => r.confirmed > 0)) setView("groups");
    }).catch((e) => setError(e.message));
  }, []);

  /* Follow an episode being added. When it ends, the overview is fetched again, since the server has reloaded the
     workspace with the new episode. */
  useEffect(() => { call("/api/add").then(setAdding).catch(() => {}); }, []);
  const addingState = adding?.state;
  useEffect(() => {
    if (addingState !== "running") return;
    const timer = setInterval(() => call("/api/add").then(setAdding).catch(() => {}), 1500);
    return () => clearInterval(timer);
  }, [addingState]);
  /* However it ended (done, failed, or stopped from the dialog), fetch the overview again: a new episode, or one
     left unfinished, shows up only then. */
  const addingBefore = useRef(addingState);
  useEffect(() => {
    const before = addingBefore.current;
    addingBefore.current = addingState;
    if (before !== "running" || addingState === "running" || !adding) return;
    call("/api/state").then(setState).catch(() => {});
    if (addingState === "done") showToast(tr(`${adding.episode} 加好了`, `${adding.episode} is added`));
    else if (addingState === "failed") showToast(tr(`${adding.episode} 没加成，点「加一集」看原因`, `${adding.episode} failed; open "Add an episode" to see why`), true);
  }, [addingState]);
  /* The first episode added from the welcome page: open it, starting in Groups. */
  useEffect(() => {
    if (state && !episode && state.episodes.length) {
      setEpisode(state.episodes[0].name);
      if (!state.roles.some((r) => r.confirmed > 0)) setView("groups");
    }
  }, [state, episode]);
  const openEpisode = (name) => { setAddOpen(false); setEpisode(name); };

  /* Fetch the list again on a new episode, view or character. Once fetched its order stays fixed: labeled lines
     stay where they are instead of jumping away. */
  const load = useCallback(async () => {
    if (!state) return;
    /* Use only the latest request: an earlier one that comes back later must not overwrite an episode, view
       or character that has already changed. */
    const seq = ++loadSeq.current;
    const get = async (url) => {
      const result = await call(url);
      if (seq !== loadSeq.current) throw STALE;
      return result;
    };
    if (view === "scene" && episode) {
      const list = await get(`/api/clips?episode=${encodeURIComponent(episode)}`);
      setClips(list);
      stableOrder.current = null;
      setFocus((f) => (list.some((c) => c.id === f) ? f : (list.find((c) => NEEDS_WORK.has(c.status)) || list[0])?.id));
    } else if (view === "roles" && role) {
      const list = await get(`/api/clips?role=${encodeURIComponent(role)}`);
      setClips(list);
      setFocus((f) => (list.some((c) => c.id === f) ? f : (pendingOf(list)[0] || maybeListOf(list)[0] || list[0])?.id));
    } else if (view === "roles") {
      /* No character open, for example after the open one was undone: no list, and no line on the stage. */
      setClips([]);
    } else if (view === "groups" && episode) {
      setGroupsLoading(true);
      let found;
      try {
        found = (await get(`/api/groups?episode=${encodeURIComponent(episode)}`)).map((g, i) => ({ ...g, key: i }));
      } finally {
        if (seq === loadSeq.current) setGroupsLoading(false);
      }
      setGroups(found);
      setPicked({});
      setClips(found.flatMap((g) => g.clips));
      setFocus((f) => (found.some((g) => g.clips.some((c) => c.id === f)) ? f : found[0]?.clips[0]?.id));
    }
  }, [view, episode, role, !!state]);
  const reload = () => load().catch((e) => e !== STALE && showToast(e.message, true));
  /* Clear the old list when the view, episode or character changes: its lines don't always fit the new view (for
     example lines without a guess in the Characters view), and until the new list comes, keys and "Confirm the
     rest" must not act on the old one under the new name. */
  useEffect(() => { setClips([]); setGroups([]); }, [view, episode, role]);
  useEffect(() => { reload(); }, [load]);
  useEffect(() => {
    /* Also when the open character is gone, for example after undoing the step that made or renamed it. */
    const gone = role && role !== OTHER && state && !state.roles.some((r) => r.name === role);
    if (view === "roles" && (!role || gone) && state?.roles.length) setRole(state.roles[0].name);
    else if (gone) setRole(null);
  }, [view, state]);

  /* The order "next / previous line" follows in the current view */
  const order = useMemo(() => {
    if (view === "scene") {
      if (!onlyWork) return clips.filter((c) => showShort || c.status !== "skipped").map((c) => c.id);
      if (!stableOrder.current) stableOrder.current = clips.filter((c) => NEEDS_WORK.has(c.status)).map((c) => c.id);
      return stableOrder.current;
    }
    if (view === "roles") {
      return [...pendingOf(clips), ...maybeListOf(clips), ...clips.filter((c) => c.label === role)].map((c) => c.id);
    }
    if (view === "groups") return groups.flatMap((g) => g.clips.filter((c) => !c.label).map((c) => c.id));
    return [];
  }, [view, clips, onlyWork, showShort, role, groups]);
  /* Drop the old order right when switching, so the next computed order is the one that stays. Doing it in an
     effect clears it only after the order is computed: labeling the first line recomputes the order, and the
     line just labeled disappears from the list. */
  const toggleOnlyWork = (on) => { stableOrder.current = null; setOnlyWork(on); };

  const byId = useMemo(() => Object.fromEntries(clips.map((c) => [c.id, c])), [clips]);
  /* When the Scenes view filters out the focused line, the stage stays empty, so shortcuts can't change a line
     you can't see in the list. */
  const shownClip = (id) => (id && (view !== "scene" || order.includes(id)) ? byId[id] : null);
  const current = shownClip(focus);
  /* What the shortcuts and buttons act on; see focusNow. */
  const now = () => shownClip(focusNow.current);

  useEffect(() => {
    const at = order.indexOf(focus);
    if (at < 0) return;
    const next = order.slice(at + 1, at + 4).map((id) => byId[id]).filter(Boolean);
    if (episodeInfo?.video) warm(next, "video");
    if (!episodeInfo?.video || sound === "vocals") warm(next, "audio");
    /* The server first cuts the clips within a minute of this line in the background, then on to the end of the
       episode. While J/K is held down to flip fast, only the line you stop on is sent. */
    const wait = setTimeout(() => call("/api/prefetch", { clip: focus }).catch(() => {}), 300);
    return () => clearTimeout(wait);
  }, [focus, order]);

  useEffect(() => { setContext(0); }, [focus]);

  /* The Groups order only has unlabeled lines. When a labeled one is open, find next and previous by its place
     in the group. */
  const groupIds = useMemo(() => groups.flatMap((g) => g.clips.map((c) => c.id)), [groups]);
  /* What the number keys, Q, N and the bottom bar label: in Groups the ticked lines if there are any, else the
     line playing. The ticks are used up, so the next press goes to the line playing. */
  const keyTargets = () => {
    if (view !== "groups") return undefined;
    const ticked = groups.flatMap((g) => g.clips.filter((c) => !c.label && pickedNow.current[g.key]?.has(c.id)));
    if (!ticked.length) return undefined;
    setPicked({});
    return ticked.map((c) => c.id);
  };
  const besides = (id) => {
    const at = groupIds.indexOf(id);
    return { after: order.filter((o) => groupIds.indexOf(o) > at), before: order.filter((o) => groupIds.indexOf(o) < at) };
  };
  /* Step from the newest focus, not the one this render saw: two quick presses of J come before the page has
     drawn again, and each must move one line. */
  const move = (step) => setFocus((f) => {
    const at = order.indexOf(f);
    if (at < 0 && view === "groups" && groupIds.includes(f)) {
      const { after, before } = besides(f);
      return (step > 0 ? after[0] ?? before.at(-1) : before.at(-1) ?? after[0]) ?? f;
    }
    return order[Math.min(Math.max(at + step, 0), order.length - 1)] ?? f;
  });

  /* Move on after labeling a line. The Scenes view jumps to the next line that still needs work, instead of
     going through confirmed lines one by one. */
  const advance = (fromId, list = order) => {
    const at = list.indexOf(fromId);
    for (let i = at + 1; i < list.length; i++) {
      const c = byId[list[i]];
      if (c && (view !== "scene" || NEEDS_WORK.has(c.status) || c.status === "auto")) { setFocus(list[i]); return; }
    }
    if (list[at + 1]) setFocus(list[at + 1]);
  };

  /* Move on after labeling a batch in Groups: the first unlabeled line after the batch, else from the top. */
  const nextUnlabeled = (ids) => {
    const rest = (id) => !ids.includes(id);
    const last = ids.reduce((a, id) => (groupIds.indexOf(id) > groupIds.indexOf(a) ? id : a), ids[0]);
    return besides(last).after.find(rest) ?? order.find(rest);
  };

  const applyResult = (result, label) => {
    setState(result.state);
    const updated = Object.fromEntries(result.updated.map((c) => [c.id, c]));
    /* "Maybe missed" is decided when the Characters view fetches its list, and updated lines don't carry it, so
       keep it; a line labeled as this character is no longer missed. */
    /* The answer may come after you switched view or character, so read the ones open now. */
    setClips((list) => list.map((c) => {
      const next = updated[c.id];
      if (!next) return c;
      return c.maybe && next.label !== roleNow.current ? { ...next, maybe: true } : next;
    }));
    /* In Groups, labeled lines stay where they are, marked as labeled, instead of leaving the group: the
       unlabeled line next to it doesn't vanish with it, and undo puts things back exactly. Done in every view:
       with no groups loaded it changes nothing. */
    setGroups((gs) => gs.map((g) => ({ ...g, clips: g.clips.map((c) => updated[c.id] ?? c) })));
    const flashing = new Set(result.updated.map((c) => c.id));
    setFlashes(flashing);
    setTimeout(() => setFlashes(new Set()), 900);
    if (result.batch !== null) {
      const ripple = result.ripple ? tr(`，另有 ${result.ripple} 句的猜测随之改变`, `; guesses changed for ${lines(result.ripple)} more`) : "";
      showToast(result.undo ? tr(`已撤销${ripple}`, `Undone${ripple}`) : `${label}${ripple}`, false, !result.undo);
    }
  };

  /* Changes are queued, so no key press is lost: when your hands are faster than a round trip, the first press
     is saved first. The page moves on without waiting for the answer; if saving fails, it says so and moves the
     focus back to that line. */
  const queue = useRef(Promise.resolve());
  const pendingCount = useRef(0);
  /* Lines with a label change still on its way, and how many changes each has queued. */
  const saving = useRef(new Map());
  const send = (url, body, label, onFail) => {
    setBusy(true);
    pendingCount.current += 1;
    const ids = body.clips || [];
    for (const id of ids) saving.current.set(id, (saving.current.get(id) || 0) + 1);
    const run = queue.current.then(async () => {
      try {
        const result = await call(url, body);
        applyResult(result, label);
        return result;
      } catch (e) {
        showToast(tr(`没有保存：${e.message}`, `Not saved: ${e.message}`), true);
        onFail?.();
        return null;
      } finally {
        for (const id of ids) {
          const left = saving.current.get(id) - 1;
          if (left > 0) saving.current.set(id, left); else saving.current.delete(id);
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
  const assign = (name, ids = now() ? [now().id] : [], low = false) => {
    if (!ids.length || !name) return;
    const from = focusNow.current;
    const who = labelText[name] ? tr(`「${labelText[name]}」`, `"${labelText[name]}"`) : name;
    const what = low ? tr(`${who}·质量低，导出时跳过`, `${who}, low quality, skipped on export`) : who;
    const label = ids.length > 1 ? tr(`${ids.length} 句已标为 ${what}`, `${lines(ids.length)} labeled ${what}`) : tr(`已标为 ${what}`, `Labeled ${what}`);
    send("/api/label", { clips: ids, label: name, unusable: low }, label, () => setFocus(from));
    if (view === "groups") setFocus(nextUnlabeled(ids));
    else if (ids.length === 1) advance(from);
  };
  const accept = () => {
    const clip = now();
    if (!clip) return;
    if (clip.label) { move(1); return; }
    if (clip.guess.length) assign(clip.guess[0].name);
  };
  const clear = () => {
    const clip = now();
    if (clip?.label) send("/api/label", { clips: [clip.id], label: null }, tr("已清掉这句的标签", "Label cleared"));
  };
  /* A save still on its way can be undone too, though the overview doesn't know of it yet. Afterwards go back to
     the line that was undone, if it is in this list. */
  const undo = async () => {
    if (!state?.can_undo && pendingCount.current === 0) { showToast(tr("没有可以撤销的操作", "Nothing to undo")); return; }
    const result = await send("/api/undo", {}, tr("已撤销", "Undone"));
    /* `updated` lists the lines undone first, then the ones whose guess changed along with them. */
    const back = result?.updated.slice(0, result.updated.length - result.ripple).map((c) => c.id).filter((id) => order.includes(id) || groupIds.includes(id));
    if (back?.length) setFocus(back.sort((a, b) => order.indexOf(a) - order.indexOf(b))[0]);
  };

  const playRef = async (name) => {
    const asked = focusNow.current;
    try {
      const refs = await call(`/api/references?name=${encodeURIComponent(name)}`);
      if (focusNow.current !== asked) return;  // Moved on while waiting.
      if (!refs.length) { showToast(tr(`${name} 还没有确认过的台词可以当参考`, `${name} has no confirmed lines to use as a reference yet`)); return; }
      const pick = refs[Math.floor(Math.random() * refs.length)];
      if (playerRef.current) playerRef.current.pause();
      refAudio.current.src = media("audio", pick.id);
      refAudio.current.defaultPlaybackRate = speed;
      refAudio.current.playbackRate = speed;
      refAudio.current.play().catch(() => {});
      showToast(tr(`参考音：${name}「${pick.text || "…"}」`, `Reference: ${name} "${pick.text || "…"}"`));
    } catch (e) { showToast(e.message, true); }
  };

  const confirmRest = async () => {
    /* Leave out lines you just labeled whose answer hasn't come back: confirming them here would undo your fix. */
    /* And only lines the machine gave to the character open now: right after switching character, for a moment
       the list on hand can still be the last one's. */
    const pending = pendingOf(clips).filter((c) => !saving.current.has(c.id) && c.guess[0]?.name === role);
    if (!pending.length) return;
    const changes = pending.map((c) => ({ clip: c.id, label: role }));
    const result = await send("/api/changes", { changes },
      tr(`确认了 ${pending.length} 句是${role === OTHER ? "「其他」" : ` ${role}`}`,
        `Confirmed ${lines(pending.length)} as ${role === OTHER ? "\"Other\"" : role}`));
    if (result) { setPlaying(false); reload(); }
  };
  const renameRole = async () => {
    const unnamed = roles[role]?.named === false;
    const next = unnamed
      ? prompt(tr(`给「${role}」起个名字。填一个已有的名字就是把两个角色合并。`,
        `Name "${role}". Typing an existing name merges the two characters.`), "")
      : prompt(tr(`把「${role}」改成什么名字？填一个已有的名字就是把两个角色合并。`,
        `Rename "${role}" to what? Typing an existing name merges the two characters.`), role);
    if (!next || next.trim() === role) return;
    /* A rename keeps the number key: the new name takes the old name's place. On a merge the old name leaves the bar. */
    const renamed = !roles[next.trim()];
    if (renamed) dockOrder.current = dockOrder.current.flatMap((n) => (n === role ? [n, next.trim()] : [n]));
    const result = await send("/api/roles", { name: role, new_name: next.trim() },
      roles[next.trim()] ? tr(`已并进 ${next.trim()}`, `Merged into ${next.trim()}`) : tr(`已改名为 ${next.trim()}`, `Renamed to ${next.trim()}`));
    if (result) { setRole(next.trim()); }
  };
  const toggleTarget = async () => {
    const message = roles[role].target
      ? tr(`${role} 不再是目标角色，已标的留着`, `${role} is no longer a target character; their labels stay`)
      : tr(`${role} 设为目标角色了`, `${role} is now a target character`);
    /* Target settings don't change labels, so the server records no batch and the page shows the message itself. */
    const result = await send("/api/roles", { name: role, target: !roles[role].target }, message);
    if (result) { showToast(message); reload(); }
  };
  /* Cropping an avatar uses the video playing on the stage. `then` runs after cropping or cancelling, for example
     moving on after labeling a new character. */
  const hasFrame = () => !!playerRef.current?.videoWidth;
  const openCrop = (name, then = null) => {
    if (!hasFrame()) {
      showToast(episodeInfo?.video ? tr("画面还没出来", "The picture hasn't loaded yet")
        : tr("这一集没有视频，截不了头像", "This episode has no video, so there is nothing to crop"), true);
      then?.();
      return;
    }
    setCrop({ name, then });
  };
  const closeCrop = () => { const then = crop?.then; setCrop(null); then?.(); };
  /* A name for a new character must not be taken: that would be a merge, which belongs in the Characters view. */
  const nameTaken = (typed) => otherName(typed) ? tr("「其他」是标签，不能当名字", "\"Other\" is a label, not a name")
    : roles[typed] ? tr(`已经有叫「${typed}」的角色了。换一个名字；是同一个人的话，以后在「角色」里合并`,
      `There is already a character called "${typed}". Pick another name; if it is the same person, merge them later in Characters`)
    : "";
  const saveCrop = async (image, typed) => {
    let name = crop.name;
    closeCrop();
    if (typed && typed !== name) {
      /* Like a rename in the Characters view: the new name keeps the number key. */
      dockOrder.current = dockOrder.current.flatMap((n) => (n === name ? [n, typed] : [n]));
      if (!(await send("/api/roles", { name, new_name: typed }, tr(`已起名为 ${typed}`, `Named ${typed}`)))) return;
      name = typed;
    }
    if (!image) return;
    try {
      setState(await call("/api/roles/avatar", { name, image }));
      showToast(tr(`已换好 ${name} 的头像`, `Avatar of ${name} updated`));
    } catch (e) { showToast(e.message, true); }
  };
  /* Label as a new character, then ask for a name (optional). If the current line is in the batch and there is a
     picture, the same dialog also crops an avatar from this frame. */
  /* Each request makes a fresh character, so a second press before the answer would make an empty second one. */
  const makingRole = useRef(false);
  const newRole = async (ids = now() ? [now().id] : []) => {
    if (!ids.length || makingRole.current) return;
    makingRole.current = true;
    const from = focusNow.current;
    let result;
    try {
      result = await send("/api/label", { clips: ids, new_role: true },
        ids.length > 1 ? tr(`${ids.length} 句标成了一个新角色`, `${lines(ids.length)} labeled as a new character`)
          : tr("已标成一个新角色", "Labeled as a new character"));
    } finally {
      makingRole.current = false;
    }
    /* If you moved to another line while waiting, stay there: no cropping from that line's frame. */
    if (!result || focusNow.current !== from) return;
    const onward = () => {
      if (view === "groups") setFocus(nextUnlabeled(ids));
      else if (ids.length === 1) advance(from);
    };
    setCrop({ name: result.role, then: onward, naming: true, frame: ids.includes(from) && hasFrame() });
  };

  /* Replay this line from the start. Clicking a line in the list selects it if not selected (it then plays by
     itself), or replays it if it already is, like Space. */
  const replay = () => {
    const p = playerRef.current;
    if (p) { p.currentTime = 0; p.play().catch(() => {}); }
  };
  const pick = (id) => (id === focus ? replay() : setFocus(id));

  /* Continuous play in the Characters view: when a line ends, jump to the next one to check */
  /* L and the sound buttons make a new player, so listen again then too. Playing stops after the last line still
     to check; the lines below it are already settled. */
  useEffect(() => {
    if (!playing || view !== "roles") return;
    const player = playerRef.current;
    if (!player) return;
    let timer = null;
    const onEnd = () => {
      timer = setTimeout(() => {
        const toCheck = pendingOf(clips).map((c) => c.id);
        const at = toCheck.indexOf(focusNow.current);
        if (at >= 0 && at + 1 < toCheck.length) setFocus(toCheck[at + 1]);
        else setPlaying(false);
      }, 250);
    };
    player.addEventListener("ended", onEnd);
    return () => { player.removeEventListener("ended", onEnd); clearTimeout(timer); };
  }, [playing, focus, view, clips, sound, context]);
  useEffect(() => { setPlaying(false); }, [view, role]);
  /* Playing starts from the first line to check, or replays the open one if it is one of them: it may have
     finished already, and then no end would come to move on from. */
  useEffect(() => {
    if (!playing) return;
    const toCheck = pendingOf(clips);
    if (toCheck.some((c) => c.id === focusNow.current)) replay();
    else if (toCheck.length) setFocus(toCheck[0].id);
  }, [playing]);
  /* A reference clip belongs to the line it was asked on. */
  useEffect(() => { refAudio.current?.pause(); }, [focus]);

  /* All shortcuts */
  useEffect(() => {
    const onKey = (e) => {
      if (crop) return;
      if (help || addOpen) { if (e.key === "Escape") { setHelp(false); setAddOpen(false); } return; }
      if (typing(e.target) || e.ctrlKey && e.key !== "z" || e.metaKey || e.altKey) return;
      const k = e.key.toLowerCase();
      /* Holding a key down repeats only moving between lines; a held Enter, digit or Z would label or undo a
         whole run of lines. */
      if (e.repeat && !["j", "k", "arrowdown", "arrowup"].includes(k)) { e.preventDefault(); return; }
      const handled = () => e.preventDefault();
      if (k === "j" || e.key === "ArrowDown") { handled(); move(1); }
      else if (k === "k" || e.key === "ArrowUp") { handled(); move(-1); }
      else if (e.key === " ") { handled(); replay(); }
      else if (e.key === "Enter" && e.shiftKey && view === "roles") { handled(); confirmRest(); }
      else if (e.key === "Enter") { handled(); accept(); }
      else if (/^(Digit|Numpad)[1-9]$/.test(e.code)) {
        /* Read the digit from e.code: with Shift held, e.key is "!", "@" and so on. Shift + number is the same
           character, low quality. */
        const name = dock[Number(e.code.at(-1)) - 1];
        if (name) { handled(); assign(name, keyTargets(), e.shiftKey); }
      }
      else if (k === "q") { handled(); assign(OTHER, keyTargets()); }
     else if (k === "n" && now() && view !== "export") { handled(); newRole(keyTargets()); }
      else if (e.key === "?") { handled(); setHelp(true); }
      else if (k === "z") { handled(); undo(); }
      else if (e.key === "Backspace" || e.key === "Delete") { handled(); clear(); }
      else if (k === "r" && now()?.guess.length && now().guess[0].name !== OTHER) { handled(); playRef(now().guess[0].name); }
      else if (k === "l" && current) { handled(); nextContext(); }
      else if (k === "f" && view === "scene") { handled(); toggleOnlyWork(!onlyWork); }
      else if (k === "p" && view === "roles") { handled(); setPlaying(!playing); }
      else if (k === "g") { handled(); setView("groups"); }
      else if (k === "s") { handled(); setView("scene"); }
      else if (k === "o") { handled(); setView("roles"); }
      else if (k === "e") { handled(); setView("export"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const corner = html`<div class="corner"><${LanguageButton} onSwitch=${switchLanguage} /></div>`;
  if (error) return html`${corner}<div class="empty"><h2>${tr("连不上本地服务", "Can't reach the local server")}</h2><p>${error}</p></div>`;
  if (!state) return html`<div class="empty"><div class="spinner" style="margin:auto"></div><p>${tr("正在载入…", "Loading…")}</p></div>`;
  const addProps = { state, adding, setAdding, onOpen: openEpisode, toast: showToast };
  if (!state.episodes.length) {
    return html`${corner}<${Welcome} ...${addProps} />
      ${toast && html`<div class="toast ${toast.isError ? "error" : ""}"><span>${toast.message}</span></div>`}`;
  }

  const counts = episodeInfo?.counts || {};
  const targetCount = state.roles.filter((r) => r.target).length;
  /* Short lines skipped by default need no labeling and don't count toward progress. */
  const total = Object.values(counts).reduce((a, b) => a + b, 0) - (counts.skipped || 0) || 1;
  const done = counts.confirmed || 0;
  const work = (counts.review || 0) + (counts.novoice || 0) + (counts.unlabeled || 0);
  const showStage = view !== "export";
  /* Groups and Scenes show the episode picked on the left; Characters and Export cover all episodes. */
  const episodeTabs = [["groups", tr("起步分组", "Groups"), "G"], ["scene", tr("场景", "Scenes"), "S"]];
  const allTabs = [["roles", tr("角色", "Characters"), "O"], ["export", tr("导出", "Export"), "E"]];
  const perEpisode = episodeTabs.some(([v]) => v === view);
  const tabButtons = (list) => list.map(([v, l, key]) => html`
    <button class=${view === v ? "on" : ""} title=${tr(`快捷键 ${key}`, `Shortcut ${key}`)} onClick=${() => setView(v)}>${l}
      ${v === "scene" && work > 0 ? html`<span class="count">${work}</span>` : ""}</button>`);

  return html`<div class="shell">
    <header class="top">
      <div class="brand"><span class="dot"></span>avoc</div>
      <nav class="tabs ${perEpisode ? "" : "away"}">
        <select value=${episode} title=${perEpisode ? tr("换一集", "Switch episode")
            : tr("「角色」和「导出」看的是全部集数，换集只影响「起步分组」和「场景」", "Characters and Export cover all episodes; switching only changes Groups and Scenes")}
          onChange=${(e) => {
            /* Let go of the menu, or the arrow keys meant for the next line would switch the episode again. */
            e.target.blur();
            if (e.target.value === "+") { e.target.value = episode; setAddOpen(true); } else setEpisode(e.target.value);
          }}>
          ${state.episodes.map((e) => html`<option value=${e.name}>${e.name}</option>`)}
          <option value="+">${tr("＋ 加一集…", "+ Add an episode…")}${Object.keys(state.skipped || {}).length
            ? tr(`（${Object.keys(state.skipped).length} 集没做完）`, ` (${Object.keys(state.skipped).length} unfinished)`) : ""}</option>
        </select>
        ${tabButtons(episodeTabs)}
      </nav>
      <nav class="tabs">
        <span class="scope">${tr("全部集数", "All episodes")}</span>
        ${tabButtons(allTabs)}
      </nav>
      ${addingState === "running" && !addOpen && html`<button class="ghost adding-chip" onClick=${() => setAddOpen(true)}
        title=${tr("点开看进度", "Click to see the progress")}><span class="spinner small"></span>${tr(`正在加 ${adding.episode}`, `Adding ${adding.episode}`)}</button>`}
      <span class="spacer"></span>
      ${perEpisode && html`<div class="progress" title=${tr("绿色是已经确认的，浅绿是机器有把握的", "Green is confirmed, light green is the machine's confident ones")}>
        <span>${tr(`${episode}：确认 ${Math.round(done / total * 100)}%`, `${episode}: ${Math.round(done / total * 100)}% confirmed`)}</span>
        <div class="bar"><i class="ok" style="width:${done / total * 100}%"></i>
          <i class="auto" style="width:${(counts.auto || 0) / total * 100}%"></i></div>
      </div>`}
      <span class="model-chip ${busy ? "busy" : ""}" title=${tr("机器每次标注后都会重新学一次", "The machine retrains after every label")}>
        ${busy ? tr("正在重新学习…", "Retraining…") : state.model.labels
          ? tr(`机器学过 ${state.model.labels} 句 · ${targetCount} 个目标角色`,
            `Trained on ${lines(state.model.labels)} · ${many(targetCount, "target")}`)
          : tr("机器还没学过", "Not trained yet")}</span>
      <button class="ghost" disabled=${!state.can_undo} onClick=${undo} title=${tr("撤销上一步", "Undo the last step")}>${tr("撤销", "Undo")} <kbd>Z</kbd></button>
      <${LanguageButton} onSwitch=${switchLanguage} />
      <button class="ghost theme" onClick=${() => setTheme(theme === "dark" ? "light" : "dark")}
        title=${theme === "dark" ? tr("换成白天配色", "Switch to light colors") : tr("换成夜间配色", "Switch to dark colors")}>${theme === "dark" ? "☀" : "☾"}</button>
      <button class="ghost" onClick=${() => setHelp(true)} title=${tr("全部快捷键", "All shortcuts")}><kbd>?</kbd></button>
    </header>

    <div class="body" style=${showStage ? "" : "grid-template-columns:1fr"}>
      ${showStage && html`<${Stage} clip=${current} roles=${roles} labelText=${labelText} sound=${sound} setSound=${setSound}
        speed=${speed} setSpeed=${setSpeed}
        hasVideo=${!!episodeInfo?.video} videoRef=${playerRef} onAssign=${(n, low) => assign(n, undefined, low)} onAccept=${accept}
        onPlayRef=${playRef} onAvatar=${(name) => openCrop(name)} onNewRole=${() => newRole()} onClear=${clear}
        context=${context} onContext=${nextContext} dock=${dock} />`}
      <main class="main">
        ${view === "scene" && html`<${SceneView} clips=${clips} order=${order} focus=${focus} setFocus=${pick}
          roles=${roles} labelText=${labelText} onlyWork=${onlyWork} setOnlyWork=${toggleOnlyWork}
          showShort=${showShort} setShowShort=${setShowShort} flashes=${flashes} episode=${episode} />`}
        ${view === "roles" && html`<${RoleView} state=${state} roles=${roles} labelText=${labelText} role=${role} setRole=${setRole}
          clips=${clips} focus=${focus} setFocus=${pick}
          onConfirmRest=${confirmRest} onRename=${renameRole} onToggleTarget=${toggleTarget} flashes=${flashes}
          onAvatar=${() => openCrop(role)} canCrop=${!!current && !!episodeInfo?.video}
          playing=${playing} setPlaying=${setPlaying} />`}
        ${view === "groups" && html`<${GroupsView} key=${episode} groups=${groups} loading=${groupsLoading} roles=${roles} labelText=${labelText}
          dock=${dock} focus=${focus} setFocus=${pick} firstRun=${firstRun} picked=${picked} setPicked=${setPicked}
          onName=${(ids, name) => assign(name, ids)} onNew=${(ids) => newRole(ids)} />`}
        ${view === "export" && html`<${ExportView} state=${state} setState=${setState} toast=${showToast} />`}
      </main>
    </div>

    ${view !== "export" && html`<footer class="dock">
      ${dock.map((name, i) => html`<div class="chip" key=${name}
          title=${i < 9 ? tr(`按 ${i + 1} 标成 ${name}`, `Press ${i + 1} to label as ${name}`) : tr(`标成 ${name}`, `Label as ${name}`)}
          onClick=${() => assign(name, keyTargets())}>
        <${Avatar} role=${roles[name]} name=${name} size="md" /><${RoleName} role=${roles[name]} name=${name} />
        ${i < 9 && html`<span class="k">${i + 1}</span>`}
        <button class="low" title=${(i < 9 ? tr(`按 Shift + ${i + 1} 标成 ${name}·质量低：`, `Press Shift + ${i + 1} to label as ${name}, low quality: `)
            : tr(`标成 ${name}·质量低：`, `Label as ${name}, low quality: `)) + lowTip()}
          onClick=${(e) => { e.stopPropagation(); assign(name, keyTargets(), true); }}>${tr("质量低", "Low quality")}${
            i < 9 ? html` <span class="k">⇧${i + 1}</span>` : ""}</button></div>`)}
      <div class="chip" title=${tr("不是任何一个目标角色", "Not any of the target characters")} onClick=${() => assign(OTHER, keyTargets())}>
        <${Avatar} blank=${true} size="md" /><span class="rn">${labelText[OTHER]}</span><span class="k">Q</span></div>
      <div class="chip ${current ? "" : "off"}" title=${tr("新建一个目标角色，名字可以以后再起；有画面时接着截头像", "Make a new target character; you can name it later. With video, crop an avatar next")}
          onClick=${() => current && newRole(keyTargets())}>
        <div class="av md unknown">+</div><span class="rn">${tr("新角色", "New character")}</span><span class="k">N</span></div>
    </footer>`}

    <audio ref=${refAudio} hidden></audio>
   ${crop && html`<${Cropper} source=${!crop.naming || crop.frame ? playerRef.current : null} name=${crop.name} role=${roles[crop.name]}
      naming=${crop.naming} taken=${nameTaken} onSave=${saveCrop} onClose=${closeCrop} />`}
    ${help && html`<${Help} onClose=${() => setHelp(false)} />`}
    ${addOpen && html`<${AddDialog} onClose=${() => setAddOpen(false)} ...${addProps} />`}
    ${toast && html`<div class="toast ${toast.isError ? "error" : ""}"><span>${toast.message}</span>
      ${toast.extra && html`<button onClick=${undo}>${tr("撤销", "Undo")} <kbd>Z</kbd></button>`}</div>`}
  </div>`;
}

render(html`<${App} />`, document.getElementById("app"));
