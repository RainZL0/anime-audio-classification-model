import { html, render, useState, useEffect, useRef, useMemo, useCallback } from "/static/vendor/preact-htm.js";

/* ───────────── Language ───────────── */

/* The page comes in Chinese and English. The choice is kept on this machine; the first time, it follows the
   browser. Every string on screen is written as tr(Chinese, English) right where it is used. */
let lang = localStorage.getItem("avs-lang") || (navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en");
const tr = (zh, en) => (lang === "en" ? en : zh);
/* English plural for a count: "1 line", "3 lines". */
const many = (n, word, plural = `${word}s`) => `${n} ${n === 1 ? word : plural}`;
const lines = (n) => tr(`${n} 句`, many(n, "line"));
const showLanguage = () => {
  document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
  document.title = tr("avs · 按角色整理动画台词", "avs · sort anime lines by character");
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
/* "Other": not any of the target characters. It is a human judgment, labeled with Q. Unsure whether it is a
   target, several people talking with no target among them, cheering and sound effects: all get "other". */
const OTHER = "__other__";
/* Each target character has two choices: clean, and "low quality" (Shift + number). Only targets have it;
   "other" is never exported anyway. There used to be a separate "several people", now merged into low quality. */
/* Seconds the video clip extends past each end of the line. Matches avs.app.video.VIDEO_PAD on the server. */
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
    const url = media(kind, clip.id);
    if (!clip || warmed.has(url)) continue;
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
          <span style="font-size:12px;color:var(--text-3)">${tr(html`已有的人按数字键，或按 <kbd>/</kbd> 搜索`,
            html`Existing characters: number keys, or <kbd>/</kbd> to search`)}</span></div>`}

    <div class="hint">
      ${tr(html`<kbd>J</kbd> <kbd>K</kbd> 上下一句 · <kbd>空格</kbd> 重播 · <kbd>1</kbd>–<kbd>9</kbd> 选下面的角色 ·
        <kbd>N</kbd> 新角色 · <kbd>/</kbd> 搜索角色 · <kbd>Z</kbd> 撤销 · <kbd>?</kbd> 全部快捷键`,
        html`<kbd>J</kbd> <kbd>K</kbd> next / previous · <kbd>Space</kbd> replay · <kbd>1</kbd>–<kbd>9</kbd> pick a character below ·
        <kbd>N</kbd> new character · <kbd>/</kbd> search · <kbd>Z</kbd> undo · <kbd>?</kbd> all shortcuts`)}
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
          ${stranger ? tr(`最像 ${labelText[who.name] || who.name}`, `Closest: ${labelText[who.name] || who.name}`)
            : isOther ? labelText[who.name]
            : who ? html`<${RoleName} role=${roles[who.name]} name=${who.name} />` : tr("未知", "Unknown")}</span>
        <${Pill} clip=${clip} />
        ${clip.unusable && !labelText[clip.label] && html`<span class="pill unusable" title=${lowTip()}>${tr("质量低", "Low quality")}</span>`}
        ${clip.maybe && html`<span class="pill maybe" title=${tr("机器没归给这个角色，但听起来有可能是", "The machine didn't give it to this character, but it might be")}>
          ${tr("可能漏掉", "Maybe missed")} ${pct(chanceOf(clip, maybeOf))}</span>`}
        ${showTarget && bestTarget(clip) && html`<span class="pill maybe" title=${tr("机器觉得这句是这个目标角色的概率", "The machine's chance that this line is this target character")}>
          ${tr("最像", "Closest:")} ${bestTarget(clip).name} ${pct(bestTarget(clip).p)}</span>`}
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
  const them = other ? tr("「其他」", "\"other\"") : role;
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
        "At the top left are the target characters, the people you want to collect; everyone else is labeled \"other\". The gray number is lines confirmed, the orange one is lines the machine gave them that no one has confirmed yet, and below is the total length of the confirmed lines.")}</p></div>`
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
                  "Collect this person again: lines labeled \"other\" before will be listed under Maybe missed for you to recheck")}>
              ${current.target ? tr("不再作为目标", "Stop targeting") : tr("设为目标角色", "Make target")}</button>`}
          </div>
        </div>
        ${pending.length > 0 && html`<div class="welcome" style="align-items:center">
          <div style="flex:1"><h3>${tr(`机器把这 ${pending.length} 句归给了${other ? "「其他」" : ` ${role}`}`,
            `The machine gave these ${lines(pending.length)} to ${them}`)}</h3>
            <p>${tr(html`从最没把握的开始排。听到不对的，直接标成对的人或「其他」<kbd>Q</kbd>，它就离开这里；听完一键确认其余的。`,
              html`Least sure first. When one is wrong, label it with the right character or "other" <kbd>Q</kbd> and it leaves this list; when you're done listening, confirm the rest at once.`)}</p></div>
          <button class="primary" onClick=${onConfirmRest}>
            ${tr(`确认其余 ${pending.length} 句`, `Confirm the other ${lines(pending.length)}`)} <kbd style="margin-left:4px">Shift+Enter</kbd></button>
        </div>`}
        ${pending.map((clip) => html`<${Row} key=${clip.id} clip=${clip} roles=${roles} labelText=${labelText}
          selected=${clip.id === focus} flash=${flashes.has(clip.id)} showTarget=${other}
          onSelect=${() => setFocus(clip.id)} />`)}
        ${maybe.length > 0 && html`<div class="section-title">${tr(`可能漏掉的 ${maybe.length} 句`, `Maybe missed: ${lines(maybe.length)}`)}</div>
          <p class="note" style="margin:0 0 8px">${tr(
            `机器没归给 ${role}，但听起来有可能是，最像的排在前面。刚设成目标角色时，以前标成「其他」的台词也会列在这里。`,
            `The machine didn't give these to ${role}, but they might be; most likely first. Right after you make someone a target, lines labeled "other" before are listed here too.`)}</p>
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

function GroupsView({ groups, loading, roles, labelText, onName, onNew, focus, setFocus, firstRun }) {
  const [out, setOut] = useState({});
  const [names, setNames] = useState({});
  if (loading) return html`<div class="empty"><div class="spinner" style="margin:auto"></div><p>${tr("正在把声音相近的台词分组…", "Grouping lines with similar voices…")}</p></div>`;
  return html`<div>
    ${firstRun && html`<div class="welcome"><div>
      <h3>${tr("第一步：给声音相近的一组起个名字", "Step one: name a group of similar voices")}</h3>
      <p>${tr("机器先把听起来像同一个人的台词放在一起。点一句听一听：是你要收集的人，就按「是新角色」把这一组定成一个目标角色，再从画面里截一张头像，名字可以现在填，也可以以后再起；不是你要的人，就按「都是其他」。",
        "The machine puts lines that sound like the same person together. Click a line to hear it. If it is someone you want to collect, press \"New character\" to make the group a target character, then crop an avatar from the picture; you can type a name now or later. If it is not someone you want, press \"All other\".")}</p>
      <ol><li>${tr("听到混进来的别人，点那一行右边的 × 把它剔出去。", "If you hear someone else mixed in, click the × on the right of that line to take it out.")}</li>
      <li>${tr("每命名一组，机器就会重新学一次，其余台词的猜测随之变准。", "Each group you name retrains the machine, and its guesses for the other lines get better.")}</li>
      <li>${tr("定下目标角色、再标几组「其他」以后，去「场景」视图逐句确认会快得多。",
        "Once you have your target characters and a few groups of \"other\", confirming line by line in the Scenes view goes much faster.")}</li></ol></div></div>`}
    ${groups.length === 0 && html`<div class="empty"><h2>${tr("没有可分的组了", "No groups left")}</h2>
      <p>${tr("这一集还没标的台词，要么彼此都不太像，要么已经全部有了名字。去「场景」视图逐句确认吧。",
        "The unlabeled lines in this episode are either not much alike, or all named already. Go confirm them line by line in the Scenes view.")}</p></div>`}
    <div class="groups">
      ${groups.map((g, gi) => {
        const excluded = out[g.key] || new Set();
        /* Labeled lines stay in the group for you to see, but the group buttons only act on unlabeled ones. */
        const keep = g.clips.filter((c) => !excluded.has(c.id) && !c.label);
        const done = g.clips.every((c) => c.label);
        /* The machine's guess only goes in the placeholder, not in the box: listen first, Enter to accept it. */
        const value = names[g.key] ?? "";
        const chosen = value.trim() || g.hint?.name || "";
        const ids = keep.map((c) => c.id);
        /* With no name typed and no hint from the machine, Enter makes a new character without a name. */
        const submit = (e) => {
          e.preventDefault();
          if (!keep.length) return;
          if (chosen) onName(ids, chosen); else onNew(ids);
        };
        const known = Object.values(roles).filter((r) => r.target && r.name !== g.hint?.name).slice(0, 8);
        return html`<div class="group ${g.clips.some((c) => c.id === focus) ? "sel" : ""} ${done ? "done" : ""}">
          <h3>${tr(`第 ${gi + 1} 组`, `Group ${gi + 1}`)} <span class="meta">${lines(g.size)} · ${tr(`${g.seconds} 秒`, `${g.seconds} s`)}${
            done ? tr(" · 都标好了", " · all labeled") : ""}</span>
            ${g.hint && html`<span class="pill auto hint" title=${tr("机器的分类器在这组里最常猜的角色", "The character the machine guesses most often in this group")}>
              <${Avatar} role=${roles[g.hint.name]} name=${g.hint.name} size="xs" />${tr("可能是", "Maybe")} ${g.hint.name}</span>`}</h3>
          <div class="members">
            ${g.clips.map((c) => html`<div class="member ${excluded.has(c.id) ? "out" : ""} ${c.label ? "labeled" : ""} ${c.id === focus ? "playing" : ""}"
                onClick=${() => setFocus(c.id)}>
              <span>${c.text || tr("（没有字幕文字）", "(no subtitle text)")}</span>
              ${c.label && html`<span class="pill done" title=${tr("已经标了；按 Z 撤销，或在左边改", "Already labeled. Press Z to undo, or change it on the left")}>
                ${labelText[c.label] || c.label}${c.unusable ? tr("·质量低", " · low quality") : ""}</span>`}
              <span class="t">${c.episode} ${stamp(c.start)}</span>
              ${!c.label && html`<button class="x" title=${excluded.has(c.id) ? tr("放回这一组", "Put back in this group") : tr("这句不是这组的人", "This line is not this group's person")}
                onClick=${(e) => { e.stopPropagation(); const next = new Set(excluded); next.has(c.id) ? next.delete(c.id) : next.add(c.id); setOut({ ...out, [g.key]: next }); }}>
                ${excluded.has(c.id) ? "↺" : "×"}</button>`}
            </div>`)}
          </div>
          ${known.length > 0 && html`<div class="pick-row">
            <span class="note">${tr("是已有的人：", "An existing character:")}</span>
            ${known.map((r) => html`<${Avatar} key=${r.name} role=${r} name=${r.name} size="md"
              title=${tr(`这 ${keep.length} 句都是 ${r.name}`, `All ${lines(keep.length)} are ${r.name}`)} onClick=${() => keep.length && onName(ids, r.name)} />`)}
          </div>`}
          <form class="name-form" onSubmit=${submit}>
            <input list="role-names" value=${value}
              placeholder=${g.hint ? tr(`可能是 ${g.hint.name}，听过确认就回车`, `Maybe ${g.hint.name}. Listen, and press Enter if it is`)
                : tr("名字（可以不填）", "Name (optional)")}
              onInput=${(e) => setNames({ ...names, [g.key]: e.target.value })} />
            ${chosen
              ? html`<button class="primary" type="submit" disabled=${!keep.length}>${tr(`${keep.length} 句都是 ${chosen}`, `All ${lines(keep.length)} are ${chosen}`)}</button>
                ${!value.trim() && html`<button type="button" disabled=${!keep.length} onClick=${() => onNew(ids)}>${tr("是新角色", "New character")}</button>`}`
              : html`<button class="primary" type="submit" disabled=${!keep.length}>${tr(`${keep.length} 句是一个新角色`, `${lines(keep.length)}: one new character`)}</button>`}
            <button type="button" disabled=${!keep.length} onClick=${() => onName(ids, OTHER)}
              title=${tr("都不是你要收集的人", "None of them is someone you want to collect")}>${tr(`${keep.length} 句都是其他`, `All ${lines(keep.length)} are other`)}</button>
          </form>
        </div>`;
      })}
    </div>
    <datalist id="role-names">${Object.keys(roles).map((n) => html`<option value=${n} />`)}</datalist>
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
  const [picked, setPicked] = useState(() => new Set());
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
        ${trainable.map((r) => html`<div class="check ${picked.has(r.name) ? "on" : ""}" onClick=${() => toggle(r.name)}>
          <${Avatar} role=${r} name=${r.name} size="md" /><${RoleName} role=${r} name=${r.name} />
          <span class="min">${lines(r.confirmed)}${includeAuto && r.predicted ? ` + ${r.predicted}` : ""}</span></div>`)}
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
    <div class="field"><label class="title">${tr("输出到（相对路径从启动目录算起）", "Output folder (relative paths start from where you launched avs)")}</label>
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

/* The machine checks, the same list as `avs doctor`. Fetched once; torch is loaded for the GPU check, so it can
   take a few seconds. */
function Checks() {
  const [list, setList] = useState(null);
  useEffect(() => { call("/api/doctor").then(setList).catch(() => setList([])); }, []);
  if (!list) return html`<div class="note">${tr("正在检查这台机器…", "Checking this machine…")}</div>`;
  return html`<ul class="checks">${list.map((c) => html`<li class=${c.ok ? "ok" : c.required ? "bad" : "soft"}>
    <span class="mark">${c.ok ? "✓" : c.required ? "✗" : "–"}</span>
    <span>${c.text}${!c.ok && c.fix ? html`<br /><span class="note">${c.fix}</span>` : ""}</span></li>`)}</ul>`;
}

/* The form for one episode, and the progress of the `avs add` the server runs for it. `adding` is the server's job
   status, polled by App. */
function AddEpisode({ state, adding, setAdding, onOpen, toast }) {
  const last = [...state.episodes].reverse().find((e) => e.offset != null);
  const [video, setVideo] = useState("");
  const [subtitles, setSubtitles] = useState("");
  const [textSubtitles, setTextSubtitles] = useState("");
  const [offset, setOffset] = useState(last ? String(last.offset) : "");
  const [busy, setBusy] = useState(false);
  const log = useRef(null);
  useEffect(() => { if (log.current) log.current.scrollTop = log.current.scrollHeight; }, [adding?.lines.length]);
  const run = async (body) => {
    setBusy(true);
    try { setAdding(await call("/api/add", body)); } catch (e) { toast(e.message, true); }
    setBusy(false);
  };
  const start = (e) => {
    e.preventDefault();
    const seconds = offset.trim() === "" ? null : Number(offset);
    if (seconds !== null && !Number.isFinite(seconds)) { toast(tr("字幕偏移要填一个数，比如 -0.95", "The subtitle offset must be a number, such as -0.95"), true); return; }
    run({ video, subtitles, text_subtitles: textSubtitles, offset: seconds });
  };
  const stop = async () => {
    setBusy(true);
    try { setAdding(await call("/api/add/stop", {})); } catch (e) { toast(e.message, true); }
    setBusy(false);
  };
  const running = adding?.state === "running";
  const minutes = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
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
        <input value=${subtitles} onInput=${(e) => setSubtitles(e.target.value)} placeholder="D:\\anime\\Episode 01.ass" /></div>
      <div class="field"><label class="title">${tr("日文台词字幕（可以不填，导出日文文字时用）", "Japanese text subtitles (optional; used for Japanese export text)")}</label>
        <input value=${textSubtitles} onInput=${(e) => setTextSubtitles(e.target.value)} placeholder="D:\\anime\\Episode 01.ja.srt" /></div>
      <div class="field"><label class="title">${tr("字幕偏移（秒）", "Subtitle offset (seconds)")}</label>
        <input class="offset" value=${offset} onInput=${(e) => setOffset(e.target.value)} placeholder=${tr("自动测", "measure")} />
        <div class="note">${tr("字幕时间要加几秒才和声音对上。同一片源、同一字幕组的每一集都一样，所以默认填上一集的值。不知道就填 0，或者空着让它自动测（要 Hugging Face 令牌）。",
          "How many seconds to add to the subtitle times so they line up with the sound. It is the same for every episode from the same source and subtitle group, so the last episode's value is filled in. If you don't know, try 0, or leave it empty to measure it (needs a Hugging Face token).")}</div></div>
      <div class="note">${tr("路径整段粘贴进来就行。Windows 上按住 Shift 右键文件，选「复制文件地址」。",
        "Paste the full paths. On Windows, hold Shift, right-click the file, and choose \"Copy as path\".")}</div>
      <div><button class="primary" type="submit" disabled=${busy || running || !video.trim() || !subtitles.trim()}>${tr("开始", "Start")}</button></div>
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
    <p class="note">${tr(html`也可以在命令行里加：<code>uv run avs add "${props.state.workspace}" 视频 --subs 字幕</code>`,
      html`You can also add one in a terminal: <code>uv run avs add "${props.state.workspace}" VIDEO --subs SUBTITLES</code>`)}</p>
  </div>`;
}

/* ───────────── Search or make a character ───────────── */

function Palette({ roles, onPick, onNew, onClose }) {
  const [query, setQuery] = useState("");
  const [at, setAt] = useState(0);
  const input = useRef(null);
  useEffect(() => input.current?.focus(), []);
  const names = Object.values(roles);
  const q = query.trim().toLowerCase();
  const found = names.filter((r) => !q || r.name.toLowerCase().includes(q)).slice(0, 12);
  const options = [...found.map((r) => ({ name: r.name, role: r }))];
  if (q && !names.some((r) => r.name.toLowerCase() === q)) options.push({ name: query.trim(), fresh: true });
  options.push({ unnamed: true });
  const pick = (o) => (o.unnamed ? onNew() : onPick(o.name));
  const key = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setAt(Math.min(at + 1, options.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setAt(Math.max(at - 1, 0)); }
    else if (e.key === "Enter" && options[at]) { e.preventDefault(); pick(options[at]); }
    else if (e.key === "Escape") onClose();
  };
  return html`<div class="overlay" onClick=${onClose}><div class="palette" onClick=${(e) => e.stopPropagation()}>
    <input ref=${input} placeholder=${tr("搜索角色；敲一个新名字就是新建", "Search characters; type a new name to make one")} value=${query}
      onInput=${(e) => { setQuery(e.target.value); setAt(0); }} onKeyDown=${key} />
    <div class="opts">
      ${options.map((o, i) => html`<div class="opt ${i === at ? "on" : ""}" onMouseEnter=${() => setAt(i)} onClick=${() => pick(o)}>
        ${o.unnamed ? html`<div class="av md unknown">+</div><span>${tr("新角色，先不起名字", "New character, no name yet")}</span><span class="c"><kbd>N</kbd></span>`
          : o.fresh ? html`<div class="av md unknown">+</div><span>${tr(`新建角色「${o.name}」`, `New character "${o.name}"`)}</span>`
          : html`<${Avatar} role=${o.role} name=${o.name} size="md" /><${RoleName} role=${o.role} name=${o.name} />
            <span class="c">${lines(o.role.confirmed)}</span>`}
      </div>`)}
    </div>
  </div></div>`;
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
    ["/", tr("搜索角色，或者敲名字新建", "Search characters, or type a name to make one")],
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

function Cropper({ source, name, role, onSave, onClose }) {
  const canvas = useRef(null);
  const preview = useRef(null);
  const drag = useRef(null);
  const W = source.videoWidth;
  const H = source.videoHeight;
  /* The box is square, in the video's own pixels. By default it is the middle of the picture, 60% of its height. */
  const [box, setBox] = useState(() => {
    const s = Math.round(H * 0.6);
    return { x: Math.round((W - s) / 2), y: Math.round((H - s) / 2), s };
  });
  const [time, setTime] = useState(source.currentTime);
  const [frame, setFrame] = useState(0);

  useEffect(() => {
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
  const save = () => {
    const out = document.createElement("canvas");
    out.width = out.height = AVATAR_SIDE;
    out.getContext("2d").drawImage(canvas.current, box.x, box.y, box.s, box.s, 0, 0, AVATAR_SIDE, AVATAR_SIDE);
    onSave(out.toDataURL("image/jpeg", 0.9));
  };
  useEffect(() => {
    const key = (e) => {
      if (e.key === "Escape") { e.preventDefault(); onClose(); }
      else if (e.key === "Enter") { e.preventDefault(); save(); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  const left = (v, total) => `${v / total * 100}%`;
  return html`<div class="overlay" onClick=${onClose}><div class="cropper" onClick=${(e) => e.stopPropagation()}>
    <h2>${tr(html`给 <${RoleName} role=${role} name=${name} /> 截一张头像`, html`Crop an avatar for <${RoleName} role=${role} name=${name} />`)}</h2>
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
      "Drag the box to move it, drag its bottom-right corner or use the wheel to resize, press outside it to draw a new one.")}</p>
    <div class="crop-actions">
      <button class="ghost" onClick=${onClose}>${tr("放弃", "Cancel")} <kbd>Esc</kbd></button>
      <button class="primary" onClick=${save}>${tr("用这张", "Use this")} <kbd>Enter</kbd></button>
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
  const [focus, setFocus] = useState(() => saved.get("clip"));
  const [onlyWork, setOnlyWork] = useState(() => saved.get("only") === "1");
  /* Whether Whole episode lists the short lines skipped by default (status "skipped"); labeled ones always show. */
  const [showShort, setShowShort] = useState(() => localStorage.getItem("avs-show-short") === "1");
  const [role, setRole] = useState(null);
  const [groups, setGroups] = useState([]);
  const [groupsLoading, setGroupsLoading] = useState(false);
  const [palette, setPalette] = useState(false);
  const [help, setHelp] = useState(false);
  /* The server's job that adds an episode (see AddEpisode), and whether its dialog is open. */
  const [adding, setAdding] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);
  const [sound, setSound] = useState(() => localStorage.getItem("avs-sound") || "vocals");
  const [speed, setSpeed] = useState(() => {
    const s = Number(localStorage.getItem("avs-speed"));
    return SPEEDS.includes(s) ? s : 1;
  });
  /* Extra seconds played around this line, see CONTEXTS. Back to normal on the next line. */
  const [context, setContext] = useState(0);
  const nextContext = () => setContext((c) => CONTEXTS[(CONTEXTS.indexOf(c) + 1) % CONTEXTS.length]);
  const [flashes, setFlashes] = useState(() => new Set());
  const [playing, setPlaying] = useState(false);
  const [crop, setCrop] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem("avs-theme") || "light");
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
    localStorage.setItem("avs-theme", theme);
  }, [theme]);
  useEffect(() => { localStorage.setItem("avs-show-short", showShort ? "1" : "0"); }, [showShort]);
  useEffect(() => { localStorage.setItem("avs-sound", sound); }, [sound]);
  useEffect(() => { localStorage.setItem("avs-speed", String(speed)); }, [speed]);
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
    localStorage.setItem("avs-lang", lang);
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
    const timer = setInterval(async () => {
      try {
        const now = await call("/api/add");
        setAdding(now);
        if (now.state === "running") return;
        setState(await call("/api/state"));
        if (now.state === "done") showToast(tr(`${now.episode} 加好了`, `${now.episode} is added`));
        else if (now.state === "failed") { showToast(tr(`${now.episode} 没加成，点「加一集」看原因`, `${now.episode} failed; open "Add an episode" to see why`), true); }
      } catch {}
    }, 1500);
    return () => clearInterval(timer);
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
    } else if (view === "groups" && episode) {
      setGroupsLoading(true);
      let found;
      try {
        found = (await get(`/api/groups?episode=${encodeURIComponent(episode)}`)).map((g, i) => ({ ...g, key: i }));
      } finally {
        if (seq === loadSeq.current) setGroupsLoading(false);
      }
      setGroups(found);
      setClips(found.flatMap((g) => g.clips));
      setFocus((f) => (found.some((g) => g.clips.some((c) => c.id === f)) ? f : found[0]?.clips[0]?.id));
    }
  }, [view, episode, role, !!state]);
  const reload = () => load().catch((e) => e !== STALE && showToast(e.message, true));
  /* Clear the old list when the view changes: its lines don't always fit the new view (for example lines
     without a guess in the Characters view). */
  useEffect(() => { setClips([]); setGroups([]); }, [view]);
  useEffect(() => { reload(); }, [load]);
  useEffect(() => {
    if (view === "roles" && !role && state?.roles.length) setRole(state.roles[0].name);
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
  const current = focus && (view !== "scene" || order.includes(focus)) ? byId[focus] : null;

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
  const besides = (id) => {
    const at = groupIds.indexOf(id);
    return { after: order.filter((o) => groupIds.indexOf(o) > at), before: order.filter((o) => groupIds.indexOf(o) < at) };
  };
  const move = (step) => {
    const at = order.indexOf(focus);
    if (at < 0 && view === "groups" && groupIds.includes(focus)) {
      const { after, before } = besides(focus);
      const next = step > 0 ? after[0] ?? before.at(-1) : before.at(-1) ?? after[0];
      if (next) setFocus(next);
      return;
    }
    const next = order[Math.min(Math.max(at + step, 0), order.length - 1)];
    if (next) setFocus(next);
  };

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
    setClips((list) => list.map((c) => {
      const next = updated[c.id];
      if (!next) return c;
      return c.maybe && next.label !== role ? { ...next, maybe: true } : next;
    }));
    /* In Groups, labeled lines stay where they are, marked as labeled, instead of leaving the group: the
       unlabeled line next to it doesn't vanish with it, and undo puts things back exactly. */
    if (view === "groups") {
      setGroups((gs) => gs.map((g) => ({ ...g, clips: g.clips.map((c) => updated[c.id] ?? c) })));
    }
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
  const send = (url, body, label, onFail) => {
    setBusy(true);
    pendingCount.current += 1;
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
        pendingCount.current -= 1;
        if (pendingCount.current === 0) setBusy(false);
      }
    });
    queue.current = run.then(() => {});
    return run;
  };

  /* One choice sets both who it is and whether it is low quality: low means "them, low quality"; otherwise it is
     clean, and an earlier low quality mark is turned off. */
  const assign = (name, ids = current ? [current.id] : [], low = false) => {
    if (!ids.length || !name) return;
    const from = focus;
    const who = labelText[name] ? tr(`「${labelText[name]}」`, `"${labelText[name]}"`) : name;
    const what = low ? tr(`${who}·质量低，导出时跳过`, `${who}, low quality, skipped on export`) : who;
    const label = ids.length > 1 ? tr(`${ids.length} 句已标为 ${what}`, `${lines(ids.length)} labeled ${what}`) : tr(`已标为 ${what}`, `Labeled ${what}`);
    send("/api/label", { clips: ids, label: name, unusable: low }, label, () => setFocus(from));
    if (view === "groups") setFocus(nextUnlabeled(ids));
    else if (ids.length === 1) advance(from);
  };
  const accept = () => {
    if (!current) return;
    if (current.label) { move(1); return; }
    if (current.guess.length) assign(current.guess[0].name);
  };
  const clear = () => current?.label && send("/api/label", { clips: [current.id], label: null }, tr("已清掉这句的标签", "Label cleared"));
  const undo = () => state?.can_undo ? send("/api/undo", {}, tr("已撤销", "Undone")) : showToast(tr("没有可以撤销的操作", "Nothing to undo"));

  const playRef = async (name) => {
    try {
      const refs = await call(`/api/references?name=${encodeURIComponent(name)}`);
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
    const pending = pendingOf(clips);
    if (!pending.length) return;
    const changes = pending.map((c) => ({ clip: c.id, label: role }));
    const result = await send("/api/changes", { changes },
      tr(`确认了 ${pending.length} 句是${role === OTHER ? "「其他」" : ` ${role}`}`,
        `Confirmed ${lines(pending.length)} as ${role === OTHER ? "\"other\"" : role}`));
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
  const saveAvatar = async (image) => {
    const name = crop.name;
    closeCrop();
    try {
      setState(await call("/api/roles/avatar", { name, image }));
      showToast(tr(`已换好 ${name} 的头像`, `Avatar of ${name} updated`));
    } catch (e) { showToast(e.message, true); }
  };
  /* Label as a new character without a name. If the current line is in the batch and there is a picture, go on to
     crop an avatar from this frame. */
  const newRole = async (ids = current ? [current.id] : []) => {
    if (!ids.length) return;
    const from = focus;
    const onward = () => {
      if (view === "groups") setFocus(nextUnlabeled(ids));
      else if (ids.length === 1) advance(from);
    };
    const result = await send("/api/label", { clips: ids, new_role: true },
      ids.length > 1 ? tr(`${ids.length} 句标成了一个新角色`, `${lines(ids.length)} labeled as a new character`)
        : tr("已标成一个新角色", "Labeled as a new character"));
    if (!result) return;
    if (ids.includes(from) && hasFrame()) openCrop(result.role, onward);
    else onward();
  };

  /* Replay this line from the start. Clicking a line in the list selects it if not selected (it then plays by
     itself), or replays it if it already is, like Space. */
  const replay = () => {
    const p = playerRef.current;
    if (p) { p.currentTime = 0; p.play().catch(() => {}); }
  };
  const pick = (id) => (id === focus ? replay() : setFocus(id));

  /* Continuous play in the Characters view: when a line ends, jump to the next one to check */
  useEffect(() => {
    if (!playing || view !== "roles") return;
    const player = playerRef.current;
    if (!player) return;
    const onEnd = () => setTimeout(() => move(1), 250);
    player.addEventListener("ended", onEnd);
    return () => player.removeEventListener("ended", onEnd);
  }, [playing, focus, view, order]);

  /* All shortcuts */
  useEffect(() => {
    const onKey = (e) => {
      if (crop) return;
      if (palette || help || addOpen) { if (e.key === "Escape") { setPalette(false); setHelp(false); setAddOpen(false); } return; }
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT" || e.ctrlKey && e.key !== "z" || e.metaKey || e.altKey) return;
      const k = e.key.toLowerCase();
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
        if (name) { handled(); assign(name, undefined, e.shiftKey); }
      }
      else if (k === "q") { handled(); assign(OTHER); }
      else if (e.key === "/") { handled(); setPalette(true); }
      else if (k === "n" && current && view !== "export") { handled(); newRole(); }
      else if (e.key === "?") { handled(); setHelp(true); }
      else if (k === "z") { handled(); undo(); }
      else if (e.key === "Backspace" || e.key === "Delete") { handled(); clear(); }
      else if (k === "r" && current?.guess.length && current.guess[0].name !== OTHER) { handled(); playRef(current.guess[0].name); }
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
  const tabs = [["groups", tr("起步分组", "Groups"), "G"], ["scene", tr("场景", "Scenes"), "S"],
    ["roles", tr("角色", "Characters"), "O"], ["export", tr("导出", "Export"), "E"]];

  return html`<div class="shell">
    <header class="top">
      <div class="brand"><span class="dot"></span>avs</div>
      <select value=${episode} title=${tr("换一集", "Switch episode")}
        onChange=${(e) => { if (e.target.value === "+") { e.target.value = episode; setAddOpen(true); } else setEpisode(e.target.value); }}>
        ${state.episodes.map((e) => html`<option value=${e.name}>${e.name}</option>`)}
        <option value="+">${tr("＋ 加一集…", "+ Add an episode…")}${Object.keys(state.skipped || {}).length
          ? tr(`（${Object.keys(state.skipped).length} 集没做完）`, ` (${Object.keys(state.skipped).length} unfinished)`) : ""}</option>
      </select>
      ${addingState === "running" && !addOpen && html`<button class="ghost adding-chip" onClick=${() => setAddOpen(true)}
        title=${tr("点开看进度", "Click to see the progress")}><span class="spinner small"></span>${tr(`正在加 ${adding.episode}`, `Adding ${adding.episode}`)}</button>`}
      <nav class="tabs">
        ${tabs.map(([v, l, key]) => html`
          <button class=${view === v ? "on" : ""} title=${tr(`快捷键 ${key}`, `Shortcut ${key}`)} onClick=${() => setView(v)}>${l}
            ${v === "scene" && work > 0 ? html`<span class="count">${work}</span>` : ""}</button>`)}
      </nav>
      <span class="spacer"></span>
      <div class="progress" title=${tr("绿色是已经确认的，浅绿是机器有把握的", "Green is confirmed, light green is the machine's confident ones")}>
        <span>${tr(`${episode}：确认 ${Math.round(done / total * 100)}%`, `${episode}: ${Math.round(done / total * 100)}% confirmed`)}</span>
        <div class="bar"><i class="ok" style="width:${done / total * 100}%"></i>
          <i class="auto" style="width:${(counts.auto || 0) / total * 100}%"></i></div>
      </div>
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
          focus=${focus} setFocus=${setFocus} firstRun=${firstRun}
          onName=${(ids, name) => assign(name, ids)} onNew=${(ids) => newRole(ids)} />`}
        ${view === "export" && html`<${ExportView} state=${state} setState=${setState} toast=${showToast} />`}
      </main>
    </div>

    ${view !== "export" && html`<footer class="dock">
      ${dock.slice(0, 9).map((name, i) => html`<div class="chip" key=${name}
          title=${tr(`按 ${i + 1} 标成 ${name}`, `Press ${i + 1} to label as ${name}`)} onClick=${() => assign(name)}>
        <${Avatar} role=${roles[name]} name=${name} size="md" /><${RoleName} role=${roles[name]} name=${name} />
        <span class="k">${i + 1}</span>
        <button class="low" title=${tr(`按 Shift + ${i + 1} 标成 ${name}·质量低：`, `Press Shift + ${i + 1} to label as ${name}, low quality: `) + lowTip()}
          onClick=${(e) => { e.stopPropagation(); assign(name, undefined, true); }}>${tr("质量低", "Low quality")} <span class="k">⇧${i + 1}</span></button></div>`)}
      <div class="chip" title=${tr("不是任何一个目标角色", "Not any of the target characters")} onClick=${() => assign(OTHER)}>
        <${Avatar} blank=${true} size="md" /><span class="rn">${labelText[OTHER]}</span><span class="k">Q</span></div>
      <button class="ghost" onClick=${() => current && newRole()} disabled=${!current}>${tr("新角色", "New character")} <kbd>N</kbd></button>
      <button class="ghost" onClick=${() => setPalette(true)}>${tr("其他角色", "More characters")} <kbd>/</kbd></button>
      <span class="more">${dock.length > 9 ? tr(`另有 ${dock.length - 9} 个目标角色在搜索里`, `${many(dock.length - 9, "more target")} in search`) : ""}</span>
    </footer>`}

    <audio ref=${refAudio} hidden></audio>
    ${palette && html`<${Palette} roles=${roles} onClose=${() => setPalette(false)}
      onPick=${(name) => { setPalette(false); assign(name); }}
      onNew=${() => { setPalette(false); newRole(); }} />`}
    ${crop && html`<${Cropper} source=${playerRef.current} name=${crop.name} role=${roles[crop.name]}
      onSave=${saveAvatar} onClose=${closeCrop} />`}
    ${help && html`<${Help} onClose=${() => setHelp(false)} />`}
    ${addOpen && html`<${AddDialog} onClose=${() => setAddOpen(false)} ...${addProps} />`}
    ${toast && html`<div class="toast ${toast.isError ? "error" : ""}"><span>${toast.message}</span>
      ${toast.extra && html`<button onClick=${undo}>${tr("撤销 Z", "Undo Z")}</button>`}</div>`}
  </div>`;
}

render(html`<${App} />`, document.getElementById("app"));
