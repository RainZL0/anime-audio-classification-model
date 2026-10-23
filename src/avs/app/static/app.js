import { html, render, useState, useEffect, useRef, useMemo, useCallback } from "/static/vendor/preact-htm.js";

/* ───────────── 和服务端说话 ───────────── */

async function call(url, body) {
  const response = await fetch(url, body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
/* 按 L 依次切换：平常、前后各多放 5 秒、15 秒。跟服务端 CONTEXT_SECONDS 一致。 */
const CONTEXTS = [0, 5, 15];
const stamp = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${(s % 60).toFixed(1).padStart(4, "0")}`;
const pct = (p) => `${Math.round(p * 100)}%`;
const STATUS_TEXT = {
  confirmed: "已确认", auto: "机器有把握", review: "待确认", novoice: "太短，没有声纹",
  unlabeled: "还没有模型", special: "特殊", skipped: "太短，默认跳过",
};
const NEEDS_WORK = new Set(["review", "novoice", "unlabeled"]);
const VIEWS = ["groups", "scene", "roles", "export"];
/* 取列表时被后发的请求取代了，结果丢掉，不算出错。 */
const STALE = new Error("stale");
/* 打开网页时网址 # 后面记着的位置，见 App 里写回网址的那段。 */
const saved = new URLSearchParams(location.hash.slice(1));
const confidence = (clip) => clip.guess[0]?.p ?? 0;
/* 「其他」：不是任何一个目标角色。它是人下的判断，按 Q 标。 */
const OTHER = "__other__";
/* 特殊标签（无法确认、不止一个人、不是说话）不再给键：只问是不是目标角色，拿不准、
   几个人同时说话但没有目标角色、欢呼音效这类不是说话的，都标「其他」；以前标的照样显示。 */
/* 每个目标角色有两个选项：干净的 TA 和「TA·质量低」，后者按 Shift + 数字。只对目标角色有，
   「其他」本来就不导出。以前还有一个「多人」，已并进「质量低」。 */
/* 视频片段比台词前后各多切的秒数，跟服务端 avs.labeling.VIDEO_PAD 一致。 */
const VIDEO_PAD = 0.5;
const LOW_TIP = "背景音太重、有人同时出声之类，不能进干净数据集。不拿来认人，导出时跳过";
const chanceOf = (clip, name) => clip.guess.find((g) => g.name === name)?.p ?? 0;

/* 当前片段属于谁：人标的优先，其次机器最像的那个。 */
function whoOf(clip) {
  if (clip.label) return { name: clip.label, human: true };
  if (clip.guess.length) return { name: clip.guess[0].name, human: false, p: clip.guess[0].p };
  return null;
}

/* 预取接下来几条的画面：服务端按需现切，提前要一下，翻过去时就已经切好了。 */
const warmed = new Set();
function warm(clips, kind) {
  for (const clip of clips) {
    const url = media(kind, clip.id);
    if (!clip || warmed.has(url)) continue;
    warmed.add(url);
    fetch(url, { priority: "low" }).catch(() => warmed.delete(url));
  }
}

/* ───────────── 小部件 ───────────── */

/* 没截头像的角色用的图：底色 × 白色形状 × 花纹。
   编号由服务端分配、存在角色表里，所以同一个角色每次打开都是同一张图。 */
const PALETTE = ["#7F77DD", "#1D9E75", "#D85A30", "#D4537E", "#378ADD", "#639922", "#BA7517", "#E24B4A",
  "#5F5E5A", "#534AB7", "#0F6E56", "#993C1D", "#993556", "#185FA5", "#3B6D11", "#854F0B"];
/* 以 (20, 20) 为中心、半径轮流取 radii 里的值的多边形顶点。 */
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
/* 编号 p 的颜色取 p % 16；形状每过一轮 16 色就错开 3 格（3 与 8 互质），
   所以前 128 个编号的「颜色 × 形状」两两不同，再往后才靠花纹区分。 */
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

function Avatar({ role, name, size = "", special, onClick, title }) {
  if (special) return html`<div class="av ${size} unknown">·</div>`;
  if (!name) return html`<div class="av ${size} unknown">?</div>`;
  const click = onClick ? { onClick, role: "button" } : {};
  if (role?.avatar) {
    return html`<div class="av ${size} ${onClick ? "edit" : ""}" title=${title || name} ...${click}
      style=${`background-image:url(/media/avatar/${role.avatar})`}></div>`;
  }
  return html`<div class="av ${size} ${onClick ? "edit" : ""}" title=${title || name} ...${click}>
    <${Pattern} role=${role} name=${name} /></div>`;
}

/* 角色名：还没起名字的角色显示得淡一些，提醒人这是临时叫法。 */
function RoleName({ role, name, cls = "" }) {
  return html`<span class="rn ${cls} ${role?.named === false ? "unnamed" : ""}"
    title=${role?.named === false ? "还没起名字，在「角色」视图里可以起" : ""}>${name}</span>`;
}

function Pill({ clip }) {
  if (clip.status === "review" && clip.familiar === false) {
    return html`<span class="pill stranger" title="跟已知角色确认过的台词都不太像">可能是没见过的人</span>`;
  }
  if (clip.status === "auto" || clip.status === "review") {
    return html`<span class="pill ${clip.status}">${clip.status === "review" ? "待确认 " : ""}${pct(clip.guess[0].p)}</span>`;
  }
  return html`<span class="pill ${clip.status}">${STATUS_TEXT[clip.status]}</span>`;
}

/* ───────────── 舞台：画面、台词、这是谁 ───────────── */

function Stage({ clip, roles, special, sound, setSound, onAssign, onAccept, onPlayRef, hasVideo, videoRef, onAvatar,
  onNewRole, context, onContext }) {
  const [loading, setLoading] = useState(true);
  const audioRef = useRef(null);
  const startVoice = useRef(0);
  useEffect(() => { setLoading(true); return () => clearTimeout(startVoice.current); }, [clip?.id, sound, context]);

  if (!clip) {
    return html`<aside class="stage"><div class="screen"><div class="wait">在右边选一句台词</div></div></aside>`;
  }
  const vocals = hasVideo && sound === "vocals";
  /* 只听人声时画面照放、静音，声音换成分离出的人声，跟着画面播放、暂停、跳转。视频片段比台词
     早开始 VIDEO_PAD 秒（一集开头不够就少留），人声要等画面走到台词开始才出声。多放前后文时
     人声也多切了同样的秒数，两边从同一时刻开始。 */
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
      startVoice.current = setTimeout(() => voice.play().catch(() => {}), -at * 1000);
    }
  };
  const who = whoOf(clip);
  const isSpecial = clip.label && special[clip.label];
  return html`<aside class="stage">
    <div class="screen">
      ${hasVideo
        ? html`<video ref=${videoRef} key=${`${clip.id}-${sound}-${context}`} src=${media("video", clip.id, context)}
            autoplay playsinline muted=${vocals}
            onCanPlay=${() => setLoading(false)} onClick=${(e) => { e.target.currentTime = 0; e.target.play(); }}
            onPlay=${follow} onPause=${follow} onSeeked=${follow}></video>
          ${vocals && html`<audio ref=${audioRef} key=${`v-${clip.id}-${context}`} src=${media("audio", clip.id, context)}
            preload="auto"></audio>`}`
        : html`<div class="wait">这一集没有视频，只有人声</div>
          <audio ref=${(el) => { audioRef.current = el; if (videoRef) videoRef.current = el; }} key=${`${clip.id}-${context}`}
            src=${media("audio", clip.id, context)} autoplay onCanPlay=${() => setLoading(false)}></audio>`}
      <div class="wait ${!hasVideo || !loading ? "hide" : ""}"><div class="spinner"></div></div>
    </div>
    <div class="line-text">${clip.text || html`<span style="color:var(--text-3)">（字幕里没有这句的文字）</span>`}</div>
    <div class="line-meta">
      <span>${clip.episode}</span><span>${stamp(clip.start)}</span><span>${clip.duration} 秒</span>
      <button class="context ${context ? "on" : ""}" onClick=${onContext}
        title="看不出是谁时，临时前后各多放一些；再按切到 15 秒、再按回到平常。换一句自动回到平常">
        ${context ? `前后多放 ${context} 秒` : "多放前后文"} <kbd>L</kbd></button>
      ${hasVideo && html`<span class="sound seg">
        <button class=${sound === "vocals" ? "on" : ""} onClick=${() => setSound("vocals")}>只听人声</button>
        <button class=${sound === "original" ? "on" : ""} onClick=${() => setSound("original")}>画面原声</button>
      </span>`}
    </div>

    ${clip.label
      ? html`<div class="ask">已经确认</div>
        <div class="confirmed-box">
          <${Avatar} role=${roles[clip.label]} name=${clip.label} special=${isSpecial} size="lg"
            onClick=${!isSpecial && hasVideo ? () => onAvatar(clip.label) : null} title="从画面里截一块当头像" />
          <div><div class="who">${isSpecial ? special[clip.label] : html`<${RoleName} role=${roles[clip.label]} name=${clip.label} />`}
            ${clip.unusable && !special[clip.label] && html` <span class="pill unusable" title=${LOW_TIP}>质量低</span>`}</div>
          <div style="font-size:12px">要改的话，直接按别的数字键或在下面选；Shift + 数字是质量低</div></div>
          ${!isSpecial && hasVideo && html`<button class="ghost" style="margin-left:auto;font-size:12px"
            title="从当前画面里框出一块当这个角色的头像" onClick=${() => onAvatar(clip.label)}>截取头像</button>`}
        </div>`
      : html`<div class="ask">${clip.guess.length ? "这是谁？机器的猜测" : clip.voiced ? "这是谁？" : "这句太短，机器听不出来，请直接选人"}</div>
        ${clip.familiar === false && html`<div class="stranger">
          跟已经确认过的角色都不太像，可能是还没标过的人。是新角色就按 <kbd>N</kbd> 新建，名字以后再起也行。</div>`}
        ${clip.familiar === null && clip.guess.length > 0 && html`<div class="stranger early">
          机器现在只会在底部这几个角色里挑。都不是就按 <kbd>N</kbd> 新建；确认满 20 句后，它会自己提醒你哪句像新面孔。</div>`}
        <div class="cands">
          ${clip.guess.filter((g) => g.p >= 0.02 || g === clip.guess[0]).map((g, i) => html`
            <div class="cand ${i === 0 ? "top" : ""}" onClick=${() => onAssign(g.name)}>
              <${Avatar} role=${roles[g.name]} name=${g.name} special=${g.name === OTHER} size="md" />
              <div><div class="name">${g.name === OTHER ? special[OTHER] : html`<${RoleName} role=${roles[g.name]} name=${g.name} />`}</div>
                <div class="meter"><i style="width:${pct(g.p)}"></i></div></div>
              <span class="pct">${pct(g.p)}</span>
              ${g.name !== OTHER && html`<button class="ref" title="听这个角色确认过的一句" onClick=${(e) => { e.stopPropagation(); onPlayRef(g.name); }}>
                参考音${i === 0 ? html` <kbd>R</kbd>` : ""}</button>`}
            </div>`)}
        </div>
        <div style="margin-top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          ${clip.guess.length > 0 && html`<button class="primary" onClick=${onAccept}>是 ${special[clip.guess[0].name] || clip.guess[0].name}
            <kbd style="margin-left:4px">Enter</kbd></button>`}
          <button onClick=${onNewRole} title="新建一个目标角色，名字可以以后再起；有画面时接着截头像">
            新角色 <kbd style="margin-left:4px">N</kbd></button>
          <span style="font-size:12px;color:var(--text-3)">已有的人按数字键，或按 <kbd>/</kbd> 搜索</span></div>`}

    <div class="specials">
      <button onClick=${() => onAssign(OTHER)} title="不是任何一个目标角色">其他 <kbd>Q</kbd></button>
    </div>
    ${clip.rejects.length > 0 && html`<div class="note" style="margin-top:8px">你说过这句不是：${clip.rejects.join("、")}</div>`}
    <div class="hint">
      <kbd>J</kbd> <kbd>K</kbd> 上下一句 · <kbd>空格</kbd> 重播 · <kbd>1</kbd>–<kbd>9</kbd> 选下面的角色 ·
      <kbd>N</kbd> 新角色 · <kbd>/</kbd> 搜索角色 · <kbd>Z</kbd> 撤销 · <kbd>?</kbd> 全部快捷键
    </div>
  </aside>`;
}

/* ───────────── 一句台词 ───────────── */

function Row({ clip, roles, special, selected, marked, onSelect, flash, maybeOf }) {
  const ref = useRef(null);
  useEffect(() => {
    if (selected && ref.current) ref.current.scrollIntoView({ block: "nearest" });
  }, [selected]);
  const who = whoOf(clip);
  const isSpecial = who && special[who.name];
  const stranger = !clip.label && clip.familiar === false;
  return html`<div ref=${ref} class="row ${selected ? "sel" : ""} ${marked ? "marked" : ""} ${flash ? "done-flash" : ""}"
      onClick=${onSelect}>
    <${Avatar} role=${who && !stranger && roles[who.name]} name=${stranger ? null : who?.name} special=${isSpecial} />
    <div>
      <div class="who">
        <span class="n" style=${who && !who.human ? "color:var(--text-2);font-weight:500" : ""}>
          ${stranger ? `最像 ${special[who.name] || who.name}` : isSpecial ? special[who.name]
            : who ? html`<${RoleName} role=${roles[who.name]} name=${who.name} />` : "未知"}</span>
        <${Pill} clip=${clip} />
        ${marked && html`<span class="pill reject">不是这个角色</span>`}
        ${clip.unusable && !special[clip.label] && html`<span class="pill unusable" title=${LOW_TIP}>质量低</span>`}
        ${clip.maybe && html`<span class="pill maybe" title="机器没归给这个角色，但听起来有可能是">可能漏掉 ${pct(chanceOf(clip, maybeOf))}</span>`}
      </div>
      <div class="say ${clip.text ? "" : "empty"}">${clip.text || "（没有字幕文字）"}</div>
    </div>
    <div class="t">${stamp(clip.start)}<br />${clip.duration}s</div>
  </div>`;
}

/* ───────────── 场景视图 ───────────── */

function SceneView({ clips, order, focus, setFocus, roles, special, onlyWork, setOnlyWork, showShort, setShowShort,
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
      <span class="sub">${clips.length} 句 · 还有 ${left} 句要你看</span>
      ${skipped > 0 && html`<span class="sub" title="短于 1 秒、前后 0.5 秒内没有别的台词，训练用不上，默认不显示">
        · 跳过 ${skipped} 句短句</span>
        ${!onlyWork && html`<button class="short ${showShort ? "on" : ""}" onClick=${() => setShowShort(!showShort)}
          title="在「整集」里显示跳过的短句，想标也可以标">${showShort ? "隐藏短句" : "显示短句"}</button>`}`}
      <span class="spacer"></span>
      <span class="seg">
        <button class=${!onlyWork ? "on" : ""} onClick=${() => setOnlyWork(false)}>整集</button>
        <button class=${onlyWork ? "on" : ""} onClick=${() => setOnlyWork(true)}>只看要处理的 <kbd>F</kbd></button>
      </span>
    </div>
    ${scenes.length === 0 && html`<div class="empty"><h2>这一集都处理完了</h2>
      <p>切到「整集」可以回头翻看，或者去「角色」视图按人核对机器的判断。</p></div>`}
    ${scenes.map((s) => html`<section>
      <div class="scene-head"><b>第 ${s.scene + 1} 场</b><span>${stamp(s.clips[0].start)}</span>
        <span>· ${s.clips.length} 句</span></div>
      ${s.clips.map((clip) => html`<${Row} key=${clip.id} clip=${clip} roles=${roles} special=${special}
        selected=${clip.id === focus} flash=${flashes.has(clip.id)} onSelect=${() => setFocus(clip.id)} />`)}
    </section>`)}
  </div>`;
}

/* ───────────── 角色视图：按人核对机器的判断 ───────────── */

/* 角色视图里待核对的：机器归给这个角色、还没人确认的，从最没把握的排起。 */
const pendingOf = (clips) => clips.filter((c) => !c.label && !c.maybe).sort((a, b) => confidence(a) - confidence(b));
/* 可能漏掉的：机器没归给这个角色，但「是 TA」的概率不低。服务端取列表时已经从最像的排好，
   这里不按重训后的概率重排，免得标完一句、列表在手底下跳。 */
const maybeListOf = (clips) => clips.filter((c) => c.maybe);

function RoleView({ state, roles, special, role, setRole, clips, focus, setFocus, marks, toggleMark, onConfirmRest,
  onRename, onToggleTarget, onAvatar, canCrop, flashes, playing, setPlaying }) {
  const list = state.roles;
  const current = roles[role];
  const pending = pendingOf(clips);
  const maybe = maybeListOf(clips);
  const confirmed = clips.filter((c) => c.label === role);
  const rest = pending.filter((c) => !marks.has(c.id)).length;
  return html`<div class="roles-grid">
    <div class="role-list">
      ${list.map((r) => html`<div class="role-item ${r.name === role ? "on" : ""} ${r.target ? "" : "off"}"
          onClick=${() => setRole(r.name)} title=${r.target ? "" : "不是目标角色：机器不再猜 TA，TA 的标签照样留着"}>
        <${Avatar} role=${r} name=${r.name} size="md" />
        <${RoleName} role=${r} name=${r.name} cls="nm" />
        <span class="c">${r.confirmed}${r.predicted ? html` · <b>${r.predicted}</b>` : ""}</span>
      </div>`)}
      <div class="role-item other" title="不是任何一个目标角色">
        <${Avatar} special=${true} size="md" /><span class="rn nm">其他</span>
        <span class="c">${state.other.confirmed}${state.other.predicted ? html` · <b>${state.other.predicted}</b>` : ""}</span>
      </div>
    </div>
    <div>
      ${!current ? html`<div class="empty"><h2>选一个角色</h2><p>左边上面是目标角色，就是你要收集的人；其余的人一律标「其他」。灰色数字是确认过的句数，橙色是机器归给 TA、还没人确认的句数。</p></div>`
      : html`
        <div class="role-head">
          <${Avatar} role=${current} name=${role} size="xl" onClick=${canCrop ? onAvatar : null}
            title=${canCrop ? "从左边的画面里截一块当头像" : "左边放出画面后，可以从画面里截头像"} />
          <div><h2><${RoleName} role=${current} name=${role} /></h2>
            <div class="stats">确认过 ${confirmed.length} 句 · 机器归给 TA ${pending.length} 句
              ${current.target ? "" : " · 不是目标角色"}</div></div>
          <div class="role-actions">
            <button onClick=${() => setPlaying(!playing)}>${playing ? "停止连播" : "连播待核对"} <kbd>P</kbd></button>
            <button onClick=${onAvatar} disabled=${!canCrop}
              title=${canCrop ? "从左边的画面里框出一块" : "左边放出画面后才能截"}>截取头像</button>
            <button class=${current.named === false ? "primary" : ""} onClick=${onRename}>
              ${current.named === false ? "起名字" : "改名或合并"}</button>
            <button onClick=${onToggleTarget}
              title=${current.target ? "不再收集这个人：机器不再猜 TA，已标的留着，以后还能加回来" : "重新收集这个人：以前标「其他」的台词会列进「可能漏掉的」，要复查"}>
              ${current.target ? "不再作为目标" : "设为目标角色"}</button>
          </div>
        </div>
        ${pending.length > 0 && html`<div class="welcome" style="align-items:center">
          <div style="flex:1"><h3>机器把这 ${pending.length} 句归给了 ${role}</h3>
            <p>从最没把握的开始排。听到不是 TA 的，按 <kbd>X</kbd> 标出来；听完一键确认其余的，标出来的会回到待确认。</p></div>
          <button class="primary" disabled=${rest === 0} onClick=${onConfirmRest}>
            确认其余 ${rest} 句${marks.size ? `，剔除 ${marks.size} 句` : ""} <kbd style="margin-left:4px">Shift+Enter</kbd></button>
        </div>`}
        ${pending.map((clip) => html`<${Row} key=${clip.id} clip=${clip} roles=${roles} special=${special}
          selected=${clip.id === focus} marked=${marks.has(clip.id)} flash=${flashes.has(clip.id)}
          onSelect=${() => setFocus(clip.id)} />`)}
        ${maybe.length > 0 && html`<div class="section-title">可能漏掉的 ${maybe.length} 句</div>
          <p class="note" style="margin:0 0 8px">机器没归给 ${role}，但听起来有可能是，最像的排在前面。刚设成目标角色时，以前标成「其他」的台词也会列在这里。</p>
          ${maybe.map((clip) => html`<${Row} key=${clip.id} clip=${clip} roles=${roles} special=${special} maybeOf=${role}
            selected=${clip.id === focus} marked=${clip.rejects.includes(role)} flash=${flashes.has(clip.id)}
            onSelect=${() => setFocus(clip.id)} />`)}`}
        ${confirmed.length > 0 && html`<div class="section-title">确认过的 ${confirmed.length} 句</div>
          ${confirmed.map((clip) => html`<${Row} key=${clip.id} clip=${clip} roles=${roles} special=${special}
            selected=${clip.id === focus} flash=${flashes.has(clip.id)} onSelect=${() => setFocus(clip.id)} />`)}`}
      `}
    </div>
  </div>`;
}

/* ───────────── 起步分组：给声音相近的一组起名字 ───────────── */

function GroupsView({ groups, loading, roles, special, onName, onNew, focus, setFocus, firstRun }) {
  const [out, setOut] = useState({});
  const [names, setNames] = useState({});
  if (loading) return html`<div class="empty"><div class="spinner" style="margin:auto"></div><p>正在把声音相近的台词分组…</p></div>`;
  return html`<div>
    ${firstRun && html`<div class="welcome"><div>
      <h3>第一步：给声音相近的一组起个名字</h3>
      <p>机器先把听起来像同一个人的台词放在一起。点一句听一听：是你要收集的人，就按「是新角色」把这一组定成一个目标角色，再从画面里截一张头像，名字可以现在填，也可以以后再起；不是你要的人，就按「都是其他」。</p>
      <ol><li>听到混进来的别人，点那一行右边的 × 把它剔出去。</li>
      <li>每命名一组，机器就会重新学一次，其余台词的猜测随之变准。</li>
      <li>定下目标角色、再标几组「其他」以后，去「场景」视图逐句确认会快得多。</li></ol></div></div>`}
    ${groups.length === 0 && html`<div class="empty"><h2>没有可分的组了</h2>
      <p>这一集还没标的台词，要么彼此都不太像，要么已经全部有了名字。去「场景」视图逐句确认吧。</p></div>`}
    <div class="groups">
      ${groups.map((g, gi) => {
        const excluded = out[g.key] || new Set();
        /* 已经标了的句子留在组里给人看，但组按钮只管还没标的。 */
        const keep = g.clips.filter((c) => !excluded.has(c.id) && !c.label);
        const done = g.clips.every((c) => c.label);
        /* 机器的猜测只放在提示里，不直接填进框：先听再认，回车才采用。 */
        const value = names[g.key] ?? "";
        const chosen = value.trim() || g.hint?.name || "";
        const ids = keep.map((c) => c.id);
        /* 没填名字、机器也没提示时，回车就是新建一个还没起名字的角色。 */
        const submit = (e) => {
          e.preventDefault();
          if (!keep.length) return;
          if (chosen) onName(ids, chosen); else onNew(ids);
        };
        const known = Object.values(roles).filter((r) => r.target && r.name !== g.hint?.name).slice(0, 8);
        return html`<div class="group ${g.clips.some((c) => c.id === focus) ? "sel" : ""} ${done ? "done" : ""}">
          <h3>第 ${gi + 1} 组 <span class="meta">${g.size} 句 · ${g.seconds} 秒${done ? " · 都标好了" : ""}</span>
            ${g.hint && html`<span class="pill auto hint" title="机器的分类器在这组里最常猜的角色">
              <${Avatar} role=${roles[g.hint.name]} name=${g.hint.name} size="xs" />可能是 ${g.hint.name}</span>`}</h3>
          <div class="members">
            ${g.clips.map((c) => html`<div class="member ${excluded.has(c.id) ? "out" : ""} ${c.label ? "labeled" : ""} ${c.id === focus ? "playing" : ""}"
                onClick=${() => setFocus(c.id)}>
              <span>${c.text || "（没有字幕文字）"}</span>
              ${c.label && html`<span class="pill special" title="已经标了；按 Z 撤销，或在左边改">
                ${special[c.label] || c.label}${c.unusable ? "·质量低" : ""}</span>`}
              <span class="t">${c.episode} ${stamp(c.start)}</span>
              ${!c.label && html`<button class="x" title=${excluded.has(c.id) ? "放回这一组" : "这句不是这组的人"}
                onClick=${(e) => { e.stopPropagation(); const next = new Set(excluded); next.has(c.id) ? next.delete(c.id) : next.add(c.id); setOut({ ...out, [g.key]: next }); }}>
                ${excluded.has(c.id) ? "↺" : "×"}</button>`}
            </div>`)}
          </div>
          ${known.length > 0 && html`<div class="pick-row">
            <span class="note">是已有的人：</span>
            ${known.map((r) => html`<${Avatar} key=${r.name} role=${r} name=${r.name} size="md"
              title=${`这 ${keep.length} 句都是 ${r.name}`} onClick=${() => keep.length && onName(ids, r.name)} />`)}
          </div>`}
          <form class="name-form" onSubmit=${submit}>
            <input list="role-names" value=${value}
              placeholder=${g.hint ? `可能是 ${g.hint.name}，听过确认是 TA 就回车` : "名字（可以不填）"}
              onInput=${(e) => setNames({ ...names, [g.key]: e.target.value })} />
            ${chosen
              ? html`<button class="primary" type="submit" disabled=${!keep.length}>${keep.length} 句都是 ${chosen}</button>
                ${!value.trim() && html`<button type="button" disabled=${!keep.length} onClick=${() => onNew(ids)}>是新角色</button>`}`
              : html`<button class="primary" type="submit" disabled=${!keep.length}>${keep.length} 句是一个新角色</button>`}
            <button type="button" disabled=${!keep.length} onClick=${() => onName(ids, OTHER)}
              title="都不是你要收集的人">${keep.length} 句都是其他</button>
          </form>
        </div>`;
      })}
    </div>
    <datalist id="role-names">${Object.keys(roles).map((n) => html`<option value=${n} />`)}</datalist>
  </div>`;
}

/* ───────────── 导出 ───────────── */

/* 每集另配一份台词字幕：贴上路径，服务端量偏移、对不上就拒绝。 */
function TextSubtitles({ state, setState, toast }) {
  const [paths, setPaths] = useState({});
  const [busy, setBusy] = useState(null);
  const attach = async (episode) => {
    setBusy(episode);
    try {
      setState(await call("/api/text-subtitles", { episode, path: paths[episode] || "" }));
      setPaths({ ...paths, [episode]: "" });
      toast(`${episode} 的台词字幕配好了`);
    } catch (e) { toast(e.message, true); }
    setBusy(null);
  };
  return html`<div class="text-subs">
    ${state.episodes.map((e) => {
      const t = e.text_subtitles;
      return html`<div class="text-sub">
        <span class="ep">${e.name}</span>
        <span class="now">${t
          ? html`${t.file} <span class="min">偏移 ${t.offset} 秒，重合 ${pct(t.agreement)}</span>`
          : html`<span class="min">还没配</span>`}</span>
        <input placeholder=${t ? "换一份：字幕文件的路径" : "字幕文件的路径（ASS 或 SRT）"} value=${paths[e.name] || ""}
          onInput=${(ev) => setPaths({ ...paths, [e.name]: ev.target.value })} />
        <button disabled=${busy !== null || !(paths[e.name] || "").trim()} onClick=${() => attach(e.name)}>
          ${busy === e.name ? "正在对…" : "对齐并配上"}</button>
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
  /* 用本地日期：toISOString 给的是 UTC，东八区早上八点前会变成前一天。 */
  const [out, setOut] = useState(() => {
    const d = new Date();
    const two = (n) => String(n).padStart(2, "0");
    return `exports/${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`;
  });
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
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
    <div class="toolbar" style="padding-left:0"><h2>导出训练数据</h2>
      <span class="sub">从原采样率的人声轨上切，统一响度，一个角色一个文件夹</span></div>
    <div class="field"><label class="title">导出哪些角色</label>
      <div class="role-checks">
        ${trainable.map((r) => html`<div class="check ${picked.has(r.name) ? "on" : ""}" onClick=${() => toggle(r.name)}>
          <${Avatar} role=${r} name=${r.name} size="md" /><${RoleName} role=${r} name=${r.name} />
          <span class="min">${r.confirmed} 句${includeAuto && r.predicted ? ` + ${r.predicted}` : ""}</span></div>`)}
      </div></div>
    <div class="field"><label class="title">包括哪些台词</label>
      <span class="seg">
        <button class=${!includeAuto ? "on" : ""} onClick=${() => setIncludeAuto(false)}>只要人确认过的</button>
        <button class=${includeAuto ? "on" : ""} onClick=${() => setIncludeAuto(true)}>再加上机器有把握的</button>
      </span>
      <div class="note" style="margin-top:6px">${includeAuto
        ? `机器有把握指把握不低于 ${pct(state.model.auto_confidence)}，第 3 集上这一档约 97% 判对。训练数据里混进别人的声音，模型就会学歪。`
        : "最干净。数据不够时再考虑加上机器有把握的。"}</div></div>
    <div class="field"><label class="title">格式</label>
      <span class="seg">
        ${[["gpt-sovits", "GPT-SoVITS"], ["style-bert-vits2", "Style-Bert-VITS2"], ["folder", "只要音频（RVC）"]].map(([v, l]) =>
          html`<button class=${form === v ? "on" : ""} onClick=${() => setForm(v)}>${l}</button>`)}
      </span></div>
    ${form !== "folder" && html`<div class="field"><label class="title">台词文字的语言</label>
      <span class="seg">${[["ja", "日语"], ["zh", "中文"], ["en", "英语"]].map(([v, l]) =>
        html`<button class=${language === v ? "on" : ""} onClick=${() => setLanguage(v)}>${l}</button>`)}</span>
      </div>`}
    ${form !== "folder" && html`<div class="field"><label class="title">台词文字从哪来</label>
      <span class="seg">
        <button class=${!textSubtitles ? "on" : ""} onClick=${() => setTextSubtitles(false)}>切片段用的字幕</button>
        <button class=${textSubtitles ? "on" : ""} onClick=${() => setTextSubtitles(true)}>每集另配的台词字幕</button>
      </span>
      ${textSubtitles
        ? html`<div class="note" style="margin-top:6px">片段不变，文字换成另配字幕里同一时间的台词。找不全台词、或者混着别人的话的片段不导出，原因写进导出目录的 rejected.tsv。</div>
          <${TextSubtitles} state=${state} setState=${setState} toast=${toast} />`
        : html`<div class="note warn" style="margin-top:6px">切片段用的字幕是中文译文时，文字和日语声音对不上。训练日语模型请改用另配的日文字幕。</div>`}</div>`}
    <div class="field"><label class="title">输出到（相对路径从启动目录算起）</label>
      <input style="width:100%" value=${out} onInput=${(e) => setOut(e.target.value)} /></div>
    <div><button class="primary" disabled=${busy || picked.size === 0} onClick=${run}>
      ${busy ? "正在导出…" : `导出 ${picked.size} 个角色`}</button></div>
    ${result && html`<div class="result"><b>导出好了：</b>${result.files} 个文件，共 ${Math.round(result.total_sec / 6) / 10} 分钟<br />
      ${Object.keys(result.rejected || {}).length > 0 && html`<span>没导出：${Object.entries(result.rejected)
        .map(([why, n]) => `${why} ${n} 条`).join("，")}。明细见 rejected.tsv<br /></span>`}
      <span class="note">${result.out}</span></div>`}
  </div>`;
}

/* ───────────── 搜索或新建角色 ───────────── */

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
    <input ref=${input} placeholder="搜索角色；敲一个新名字就是新建" value=${query}
      onInput=${(e) => { setQuery(e.target.value); setAt(0); }} onKeyDown=${key} />
    <div class="opts">
      ${options.map((o, i) => html`<div class="opt ${i === at ? "on" : ""}" onMouseEnter=${() => setAt(i)} onClick=${() => pick(o)}>
        ${o.unnamed ? html`<div class="av md unknown">+</div><span>新角色，先不起名字</span><span class="c"><kbd>N</kbd></span>`
          : o.fresh ? html`<div class="av md unknown">+</div><span>新建角色「${o.name}」</span>`
          : html`<${Avatar} role=${o.role} name=${o.name} size="md" /><${RoleName} role=${o.role} name=${o.name} />
            <span class="c">${o.role.confirmed} 句</span>`}
      </div>`)}
    </div>
  </div></div>`;
}

function Help({ onClose }) {
  const rows = [
    ["J / ↓，K / ↑", "下一句，上一句"], ["空格", "从头重播这一句；再点一下选中的那句也一样"], ["Enter", "接受机器猜的第一个"],
    ["1 – 9", "标成底部角色栏里对应的目标角色"],
    ["Shift + 1 – 9", "同一个目标角色，但质量低：背景音太重或有人同时出声。不拿来认人，导出时跳过"],
    ["Q", "其他：不是任何一个目标角色"],
    ["N", "标成一个新的目标角色，名字以后再起；有画面时接着截头像"],
    ["/", "搜索角色，或者敲名字新建"],
    ["Backspace", "清掉这句的标签"], ["R", "听机器最像的那个角色的参考音"],
    ["L", "看不出是谁时，这句临时前后各多放 5 秒；再按 15 秒，再按回到平常"], ["Z", "撤销上一步（可以一直往回撤）"],
    ["F", "场景视图里只看要处理的"], ["角色视图里机器归给 TA 的句子按 X", "标出不是 TA 的，Shift+Enter 时记成不是 TA"], ["角色视图里 Shift+Enter", "确认其余，剔除标出来的"],
    ["角色视图里 P", "从最没把握的开始连着播"], ["G / S / O / E", "切到起步分组 / 场景 / 角色 / 导出"],
    ["截头像时 Enter / Esc", "保存 / 放弃"],
  ];
  return html`<div class="overlay" onClick=${onClose}><div class="help" onClick=${(e) => e.stopPropagation()}>
    <h2>快捷键</h2><table>${rows.map(([k, v]) => html`<tr><td><kbd>${k}</kbd></td><td>${v}</td></tr>`)}</table>
    <p class="note" style="margin-top:12px">每次标注都立刻保存，并让机器重新学一次。标注、新建、改名和合并角色都能撤销；头像和设不设目标角色不算标注，直接改回去就行。</p>
  </div></div>`;
}

/* ───────────── 截头像：从画面里框出一块 ───────────── */

const AVATAR_SIDE = 256;

function Cropper({ source, name, role, onSave, onClose }) {
  const canvas = useRef(null);
  const preview = useRef(null);
  const drag = useRef(null);
  const W = source.videoWidth;
  const H = source.videoHeight;
  /* 框是正方形，坐标用视频本身的像素。默认取画面正中、高度六成的一块。 */
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
  /* 拖框里面是挪动，拖右下角是缩放，在框外按下就从那里重新画一个。 */
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
    <h2>给 <${RoleName} role=${role} name=${name} /> 截一张头像</h2>
    <div class="crop-area" onPointerDown=${down} onPointerMove=${moveTo} onPointerUp=${up} onWheel=${wheel}>
      <canvas ref=${canvas} width=${W} height=${H}></canvas>
      <div class="crop-box" style=${`left:${left(box.x, W)};top:${left(box.y, H)};width:${left(box.s, W)};height:${left(box.s, H)}`}>
        <div class="handle"></div></div>
    </div>
    <div class="crop-bar">
      <label class="note">换一帧</label>
      <input type="range" min="0" max=${source.duration || 0} step="0.04" value=${time}
        onInput=${(e) => { const t = Number(e.target.value); setTime(t); source.currentTime = t; }} />
      <canvas ref=${preview} class="crop-preview" width="96" height="96"></canvas>
    </div>
    <p class="note">拖动方框挪位置，拖右下角或滚轮缩放，在框外按下可以重新画。</p>
    <div class="crop-actions">
      <button class="ghost" onClick=${onClose}>放弃 <kbd>Esc</kbd></button>
      <button class="primary" onClick=${save}>用这张 <kbd>Enter</kbd></button>
    </div>
  </div></div>`;
}

/* ───────────── 主程序 ───────────── */

function App() {
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);
  const [view, setView] = useState("scene");
  const [episode, setEpisode] = useState(null);
  const [clips, setClips] = useState([]);
  const [focus, setFocus] = useState(() => saved.get("clip"));
  const [onlyWork, setOnlyWork] = useState(() => saved.get("only") === "1");
  /* 「整集」里是否列出默认跳过的短句（status 为 skipped）；标过的短句总是列出。 */
  const [showShort, setShowShort] = useState(() => localStorage.getItem("avs-show-short") === "1");
  const [role, setRole] = useState(null);
  const [marks, setMarks] = useState(() => new Set());
  const [groups, setGroups] = useState([]);
  const [groupsLoading, setGroupsLoading] = useState(false);
  const [palette, setPalette] = useState(false);
  const [help, setHelp] = useState(false);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);
  const [sound, setSound] = useState(() => localStorage.getItem("avs-sound") || "vocals");
  /* 这一句临时多放的前后秒数，见 CONTEXTS。换一句就回到平常。 */
  const [context, setContext] = useState(0);
  const nextContext = () => setContext((c) => CONTEXTS[(CONTEXTS.indexOf(c) + 1) % CONTEXTS.length]);
  const [flashes, setFlashes] = useState(() => new Set());
  const [playing, setPlaying] = useState(false);
  const [crop, setCrop] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem("avs-theme") || "light");
  const dockOrder = useRef([]);
  const playerRef = useRef(null);
  const refAudio = useRef(null);
  const toastTimer = useRef(null);
  const stableOrder = useRef(null);
  const loadSeq = useRef(0);

  const roles = useMemo(() => Object.fromEntries((state?.roles || []).map((r) => [r.name, r])), [state]);
  /* 显示用：特殊标签加上「其他」。 */
  const special = useMemo(() => (state ? { ...state.special, [OTHER]: "其他" } : {}), [state]);
  const episodeInfo = state?.episodes.find((e) => e.name === episode);
  /* 角色栏的顺序在一次会话里固定不动，新角色排到最后：数字键不会在手底下跳。
     在渲染时就补上，新角色当场出现在栏里，不用等下一次刷新。已经没有的名字留在顺序里不碍事，
     改名时新名字先占在旧名字后面，见 renameRole。 */
  if (state) {
    const known = new Set(dockOrder.current);
    for (const r of state.roles) if (!known.has(r.name)) dockOrder.current.push(r.name);
  }
  /* 底部角色栏只放目标角色，数字键按这个顺序。 */
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
  /* 当前在哪写进网址的 # 后面，刷新后回到同一个视图、同一集、同一个角色、同一句。 */
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

  useEffect(() => {
    call("/api/state").then((s) => {
      setState(s);
      const ep = saved.get("ep");
      if (s.episodes.length) setEpisode(s.episodes.some((e) => e.name === ep) ? ep : s.episodes[0].name);
      if (s.roles.some((r) => r.name === saved.get("role"))) setRole(saved.get("role"));
      if (VIEWS.includes(saved.get("view"))) setView(saved.get("view"));
      else if (!s.roles.some((r) => r.confirmed > 0)) setView("groups");
    }).catch((e) => setError(e.message));
  }, []);

  /* 换集、换视图、换角色时重新取列表。列表取来后顺序固定，标完的句子留在原处，不会突然跳走。 */
  const load = useCallback(async () => {
    if (!state) return;
    /* 只用最后一次取的结果：先发的请求后回来时，不能盖掉已经换了的集、视图或角色。 */
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
      setClips(list); setMarks(new Set());
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
  /* 换视图时先清空旧列表：旧列表里的句子不一定适合新视图（比如没有预测的句子进了角色视图）。 */
  useEffect(() => { setClips([]); setGroups([]); }, [view]);
  useEffect(() => { reload(); }, [load]);
  useEffect(() => {
    if (view === "roles" && !role && state?.roles.length) setRole(state.roles[0].name);
  }, [view, state]);

  /* 当前视图里「上下一句」走的顺序 */
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
  /* 切换时就清掉旧顺序，让下一次算出的顺序固定下来；放进 effect 会在算完之后才清，
     标第一句时顺序重算，刚标的那句就从列表里消失了。 */
  const toggleOnlyWork = (on) => { stableOrder.current = null; setOnlyWork(on); };

  const byId = useMemo(() => Object.fromEntries(clips.map((c) => [c.id, c])), [clips]);
  /* 场景视图筛掉了这一句时舞台留空，免得快捷键改到列表里看不见的句子。 */
  const current = focus && (view !== "scene" || order.includes(focus)) ? byId[focus] : null;

  useEffect(() => {
    const at = order.indexOf(focus);
    if (at < 0) return;
    const next = order.slice(at + 1, at + 4).map((id) => byId[id]).filter(Boolean);
    if (episodeInfo?.video) warm(next, "video");
    if (!episodeInfo?.video || sound === "vocals") warm(next, "audio");
    /* 服务端在后台切好这句前后一分钟的片段；按住 J/K 快速翻时只发停下来的那句。 */
    const wait = setTimeout(() => call("/api/prefetch", { clip: focus }).catch(() => {}), 300);
    return () => clearTimeout(wait);
  }, [focus, order]);

  useEffect(() => { setContext(0); }, [focus]);

  /* 起步分组的顺序只有没标的句子；点开的是一句标过的，就按它在组里的位置找前后。 */
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

  /* 标完一句往下走：场景视图优先跳到下一句还要处理的，免得一句句翻过已经确认的。 */
  const advance = (fromId, list = order) => {
    const at = list.indexOf(fromId);
    for (let i = at + 1; i < list.length; i++) {
      const c = byId[list[i]];
      if (c && (view !== "scene" || NEEDS_WORK.has(c.status) || c.status === "auto")) { setFocus(list[i]); return; }
    }
    if (list[at + 1]) setFocus(list[at + 1]);
  };

  /* 起步分组里标完一批往下走：这批后面第一句没标的，后面没有了再从头找。 */
  const nextUnlabeled = (ids) => {
    const rest = (id) => !ids.includes(id);
    const last = ids.reduce((a, id) => (groupIds.indexOf(id) > groupIds.indexOf(a) ? id : a), ids[0]);
    return besides(last).after.find(rest) ?? order.find(rest);
  };

  const applyResult = (result, label) => {
    setState(result.state);
    const updated = Object.fromEntries(result.updated.map((c) => [c.id, c]));
    /* 「可能漏掉的」是角色视图取列表时才定的，更新回来的句子没有这一项，要留着；
       标成这个角色的就不再算漏掉。 */
    setClips((list) => list.map((c) => {
      const next = updated[c.id];
      if (!next) return c;
      return c.maybe && next.label !== role ? { ...next, maybe: true } : next;
    }));
    /* 起步分组里标完的句子留在原处、标成已标，不从组里拿掉：同组没标的那句不会跟着消失，
       撤销时也能原样回来。 */
    if (view === "groups") {
      setGroups((gs) => gs.map((g) => ({ ...g, clips: g.clips.map((c) => updated[c.id] ?? c) })));
    }
    const flashing = new Set(result.updated.map((c) => c.id));
    setFlashes(flashing);
    setTimeout(() => setFlashes(new Set()), 900);
    if (result.batch !== null) {
      const ripple = result.ripple ? `，另有 ${result.ripple} 句的猜测随之改变` : "";
      showToast(result.undo ? `已撤销${ripple}` : `${label}${ripple}`, false, !result.undo);
    }
  };

  /* 改动排队发送，不丢按键：手比一次往返快的时候，先按的先落盘。界面先往下走，不等回执；
     存不下就提示，并把焦点退回那一句。 */
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
        showToast(`没有保存：${e.message}`, true);
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

  /* 一次选择定下是谁和质量好坏：low 为真就是「TA·质量低」，否则是干净的 TA，以前的「质量低」会关掉。 */
  const assign = (name, ids = current ? [current.id] : [], low = false) => {
    if (!ids.length || !name) return;
    const from = focus;
    const label = special[name] ? `已标为「${special[name]}」` : `已标为 ${name}${low ? "·质量低，导出时跳过" : ""}`;
    send("/api/label", { clips: ids, label: name, unusable: low }, ids.length > 1 ? `${ids.length} 句${label}` : label,
      () => setFocus(from));
    if (view === "groups") setFocus(nextUnlabeled(ids));
    else if (ids.length === 1) advance(from);
  };
  const accept = () => {
    if (!current) return;
    if (current.label) { move(1); return; }
    if (current.guess.length) assign(current.guess[0].name);
  };
  const clear = () => current?.label && send("/api/label", { clips: [current.id], label: null }, "已清掉这句的标签");
  const undo = () => state?.can_undo ? send("/api/undo", {}, "已撤销") : showToast("没有可以撤销的操作");

  const playRef = async (name) => {
    try {
      const refs = await call(`/api/references?name=${encodeURIComponent(name)}`);
      if (!refs.length) { showToast(`${name} 还没有确认过的台词可以当参考`); return; }
      const pick = refs[Math.floor(Math.random() * refs.length)];
      if (playerRef.current) playerRef.current.pause();
      refAudio.current.src = media("audio", pick.id);
      refAudio.current.play().catch(() => {});
      showToast(`参考音：${name}「${pick.text || "…"}」`);
    } catch (e) { showToast(e.message, true); }
  };

  const confirmRest = async () => {
    const pending = pendingOf(clips);
    const changes = pending.map((c) => (marks.has(c.id)
      ? { clip: c.id, reject: role, on: true }
      : { clip: c.id, label: role }));
    if (!changes.length) return;
    const result = await send("/api/changes", { changes },
      `确认了 ${pending.length - marks.size} 句是 ${role}${marks.size ? `，${marks.size} 句退回待确认` : ""}`);
    if (result) { setMarks(new Set()); setPlaying(false); reload(); }
  };
  const toggleMark = (id) => {
    const next = new Set(marks);
    next.has(id) ? next.delete(id) : next.add(id);
    setMarks(next);
  };
  const renameRole = async () => {
    const unnamed = roles[role]?.named === false;
    const next = unnamed
      ? prompt(`给「${role}」起个名字。填一个已有的名字就是把两个角色合并。`, "")
      : prompt(`把「${role}」改成什么名字？填一个已有的名字就是把两个角色合并。`, role);
    if (!next || next.trim() === role) return;
    /* 改名不换数字键：新名字接在旧名字的位置上。合并时旧名字从栏里拿掉。 */
    const renamed = !roles[next.trim()];
    if (renamed) dockOrder.current = dockOrder.current.flatMap((n) => (n === role ? [n, next.trim()] : [n]));
    const result = await send("/api/roles", { name: role, new_name: next.trim() },
      roles[next.trim()] ? `已并进 ${next.trim()}` : `已改名为 ${next.trim()}`);
    if (result) { setRole(next.trim()); }
  };
  const toggleTarget = async () => {
    const message = roles[role].target ? `${role} 不再是目标角色，已标的留着` : `${role} 设为目标角色了`;
    /* 设不设目标角色不改标签，服务端不记批次，提示要自己弹。 */
    const result = await send("/api/roles", { name: role, target: !roles[role].target }, message);
    if (result) { showToast(message); reload(); }
  };
  /* 截头像要用舞台上正在放的视频。`then` 在截完或放弃之后执行，比如标完新角色再往下走。 */
  const hasFrame = () => !!playerRef.current?.videoWidth;
  const openCrop = (name, then = null) => {
    if (!hasFrame()) {
      showToast(episodeInfo?.video ? "画面还没出来" : "这一集没有视频，截不了头像", true);
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
      showToast(`已换好 ${name} 的头像`);
    } catch (e) { showToast(e.message, true); }
  };
  /* 标成一个还没起名字的新角色。当前这句在这批里、又有画面，就接着从这一帧截头像。 */
  const newRole = async (ids = current ? [current.id] : []) => {
    if (!ids.length) return;
    const from = focus;
    const onward = () => {
      if (view === "groups") setFocus(nextUnlabeled(ids));
      else if (ids.length === 1) advance(from);
    };
    const result = await send("/api/label", { clips: ids, new_role: true },
      ids.length > 1 ? `${ids.length} 句标成了一个新角色` : "已标成一个新角色");
    if (!result) return;
    if (ids.includes(from) && hasFrame()) openCrop(result.role, onward);
    else onward();
  };

  /* 从头重播这一句。点列表里的一句：没选中就选中（会自动播），已经选中就重播，跟空格一样。 */
  const replay = () => {
    const p = playerRef.current;
    if (p) { p.currentTime = 0; p.play().catch(() => {}); }
  };
  const pick = (id) => (id === focus ? replay() : setFocus(id));

  /* 角色视图的连播：放完一句自动跳到下一句待核对的 */
  useEffect(() => {
    if (!playing || view !== "roles") return;
    const player = playerRef.current;
    if (!player) return;
    const onEnd = () => setTimeout(() => move(1), 250);
    player.addEventListener("ended", onEnd);
    return () => player.removeEventListener("ended", onEnd);
  }, [playing, focus, view, order]);

  /* 全部快捷键 */
  useEffect(() => {
    const onKey = (e) => {
      if (crop) return;
      if (palette || help) { if (e.key === "Escape") { setPalette(false); setHelp(false); } return; }
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT" || e.ctrlKey && e.key !== "z" || e.metaKey || e.altKey) return;
      const k = e.key.toLowerCase();
      const handled = () => e.preventDefault();
      if (k === "j" || e.key === "ArrowDown") { handled(); move(1); }
      else if (k === "k" || e.key === "ArrowUp") { handled(); move(-1); }
      else if (e.key === " ") { handled(); replay(); }
      else if (e.key === "Enter" && e.shiftKey && view === "roles") { handled(); confirmRest(); }
      else if (e.key === "Enter") { handled(); accept(); }
      else if (/^(Digit|Numpad)[1-9]$/.test(e.code)) {
        /* 按 e.code 认数字：按住 Shift 时 e.key 是「!」「@」之类。Shift + 数字是同一个人、质量低。 */
        const name = dock[Number(e.code.at(-1)) - 1];
        if (name) { handled(); assign(name, undefined, e.shiftKey); }
      }
      else if (k === "q") { handled(); assign(OTHER); }
      else if (e.key === "/") { handled(); setPalette(true); }
      else if (k === "n" && current && view !== "export") { handled(); newRole(); }
      else if (e.key === "?") { handled(); setHelp(true); }
      else if (k === "z") { handled(); undo(); }
      else if (k === "x" && view === "roles" && current && !current.label && !current.maybe) { handled(); toggleMark(current.id); move(1); }
      else if (e.key === "Backspace") { handled(); clear(); }
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

  if (error) return html`<div class="empty"><h2>连不上本地服务</h2><p>${error}</p></div>`;
  if (!state) return html`<div class="empty"><div class="spinner" style="margin:auto"></div><p>正在载入…</p></div>`;
  if (!state.episodes.length) {
    return html`<div class="empty"><h2>工作区里还没有任何一集</h2>
      <p>先用 <code>avs prepare</code> 处理一集（视频和字幕都要有），再重新打开这个页面。</p></div>`;
  }

  const counts = episodeInfo?.counts || {};
  const targetCount = state.roles.filter((r) => r.target).length;
  /* 默认跳过的短句不要人标，不算进进度。 */
  const total = Object.values(counts).reduce((a, b) => a + b, 0) - (counts.skipped || 0) || 1;
  const done = (counts.confirmed || 0) + (counts.special || 0);
  const work = (counts.review || 0) + (counts.novoice || 0) + (counts.unlabeled || 0);
  const showStage = view !== "export";

  return html`<div class="shell">
    <header class="top">
      <div class="brand"><span class="dot"></span>avs</div>
      <select value=${episode} onChange=${(e) => setEpisode(e.target.value)} title="换一集">
        ${state.episodes.map((e) => html`<option value=${e.name}>${e.name}</option>`)}
      </select>
      <nav class="tabs">
        ${[["groups", "起步分组", "G"], ["scene", "场景", "S"], ["roles", "角色", "O"], ["export", "导出", "E"]].map(([v, l, key]) => html`
          <button class=${view === v ? "on" : ""} title=${`快捷键 ${key}`} onClick=${() => setView(v)}>${l}
            ${v === "scene" && work > 0 ? html`<span class="count">${work}</span>` : ""}</button>`)}
      </nav>
      <span class="spacer"></span>
      <div class="progress" title="绿色是已经确认的，浅绿是机器有把握的">
        <span>${episode}：确认 ${Math.round(done / total * 100)}%</span>
        <div class="bar"><i class="ok" style="width:${done / total * 100}%"></i>
          <i class="auto" style="width:${(counts.auto || 0) / total * 100}%"></i></div>
      </div>
      <span class="model-chip ${busy ? "busy" : ""}" title="机器每次标注后都会重新学一次">
        ${busy ? "正在重新学习…" : state.model.labels
          ? `机器学过 ${state.model.labels} 句 · ${targetCount} 个目标角色`
          : "机器还没学过"}</span>
      <button class="ghost" disabled=${!state.can_undo} onClick=${undo} title="撤销上一步">撤销 <kbd>Z</kbd></button>
      <button class="ghost theme" onClick=${() => setTheme(theme === "dark" ? "light" : "dark")}
        title=${theme === "dark" ? "换成白天配色" : "换成夜间配色"}>${theme === "dark" ? "☀" : "☾"}</button>
      <button class="ghost" onClick=${() => setHelp(true)} title="全部快捷键"><kbd>?</kbd></button>
    </header>

    <div class="body" style=${showStage ? "" : "grid-template-columns:1fr"}>
      ${showStage && html`<${Stage} clip=${current} roles=${roles} special=${special} sound=${sound} setSound=${setSound}
        hasVideo=${!!episodeInfo?.video} videoRef=${playerRef} onAssign=${(n) => assign(n)} onAccept=${accept}
        onPlayRef=${playRef} onAvatar=${(name) => openCrop(name)} onNewRole=${() => newRole()}
        context=${context} onContext=${nextContext} />`}
      <main class="main">
        ${view === "scene" && html`<${SceneView} clips=${clips} order=${order} focus=${focus} setFocus=${pick}
          roles=${roles} special=${special} onlyWork=${onlyWork} setOnlyWork=${toggleOnlyWork}
          showShort=${showShort} setShowShort=${setShowShort} flashes=${flashes} episode=${episode} />`}
        ${view === "roles" && html`<${RoleView} state=${state} roles=${roles} special=${special} role=${role} setRole=${setRole}
          clips=${clips} focus=${focus} setFocus=${pick} marks=${marks} toggleMark=${toggleMark}
          onConfirmRest=${confirmRest} onRename=${renameRole} onToggleTarget=${toggleTarget} flashes=${flashes}
          onAvatar=${() => openCrop(role)} canCrop=${!!current && !!episodeInfo?.video}
          playing=${playing} setPlaying=${setPlaying} />`}
        ${view === "groups" && html`<${GroupsView} key=${episode} groups=${groups} loading=${groupsLoading} roles=${roles} special=${special}
          focus=${focus} setFocus=${setFocus} firstRun=${firstRun}
          onName=${(ids, name) => assign(name, ids)} onNew=${(ids) => newRole(ids)} />`}
        ${view === "export" && html`<${ExportView} state=${state} setState=${setState} toast=${showToast} />`}
      </main>
    </div>

    <footer class="dock">
      ${dock.slice(0, 9).map((name, i) => html`<div class="chip" key=${name}
          title=${`按 ${i + 1} 标成 ${name}`} onClick=${() => assign(name)}>
        <${Avatar} role=${roles[name]} name=${name} size="md" /><${RoleName} role=${roles[name]} name=${name} />
        <span class="k">${i + 1}</span>
        <button class="low" title=${`按 Shift + ${i + 1} 标成 ${name}·质量低：${LOW_TIP}`}
          onClick=${(e) => { e.stopPropagation(); assign(name, undefined, true); }}>质量低 <span class="k">⇧${i + 1}</span></button></div>`)}
      <div class="chip" title="不是任何一个目标角色" onClick=${() => assign(OTHER)}>
        <${Avatar} special=${true} size="md" /><span class="rn">其他</span><span class="k">Q</span></div>
      <button class="ghost" onClick=${() => current && newRole()} disabled=${!current || view === "export"}>新角色 <kbd>N</kbd></button>
      <button class="ghost" onClick=${() => setPalette(true)}>其他角色 <kbd>/</kbd></button>
      <span class="more">${dock.length > 9 ? `另有 ${dock.length - 9} 个目标角色在搜索里` : ""}</span>
    </footer>

    <audio ref=${refAudio} hidden></audio>
    ${palette && html`<${Palette} roles=${roles} onClose=${() => setPalette(false)}
      onPick=${(name) => { setPalette(false); assign(name); }}
      onNew=${() => { setPalette(false); newRole(); }} />`}
    ${crop && html`<${Cropper} source=${playerRef.current} name=${crop.name} role=${roles[crop.name]}
      onSave=${saveAvatar} onClose=${closeCrop} />`}
    ${help && html`<${Help} onClose=${() => setHelp(false)} />`}
    ${toast && html`<div class="toast ${toast.isError ? "error" : ""}"><span>${toast.message}</span>
      ${toast.extra && html`<button onClick=${undo}>撤销 Z</button>`}</div>`}
  </div>`;
}

render(html`<${App} />`, document.getElementById("app"));
