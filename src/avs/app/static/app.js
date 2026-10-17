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

const media = (kind, id) => `/media/${kind}/${id}.${kind === "audio" ? "wav" : "mp4"}`;
const stamp = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${(s % 60).toFixed(1).padStart(4, "0")}`;
const pct = (p) => `${Math.round(p * 100)}%`;
const STATUS_TEXT = {
  confirmed: "已确认", auto: "机器有把握", review: "待确认", novoice: "太短，没有声纹",
  unlabeled: "还没有模型", special: "特殊",
};
const NEEDS_WORK = new Set(["review", "novoice", "unlabeled"]);
const confidence = (clip) => clip.guess[0]?.p ?? 0;

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

function Avatar({ role, name, size = "", special }) {
  if (special) return html`<div class="av ${size} unknown">·</div>`;
  if (!name) return html`<div class="av ${size} unknown">?</div>`;
  const style = role?.avatar
    ? `background-image:url(/media/avatar/${role.avatar})`
    : `background:${role?.color || "#888"}`;
  return html`<div class="av ${size}" style=${style}>${role?.avatar ? "" : [...name][0]}</div>`;
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

function Stage({ clip, roles, special, sound, setSound, onAssign, onAccept, onPlayRef, hasVideo, videoRef, onAvatar }) {
  const [loading, setLoading] = useState(true);
  const audioRef = useRef(null);
  useEffect(() => { setLoading(true); }, [clip?.id, sound]);

  if (!clip) {
    return html`<aside class="stage"><div class="screen"><div class="wait">在右边选一句台词</div></div></aside>`;
  }
  const useVideo = hasVideo && sound === "original";
  const who = whoOf(clip);
  const isSpecial = clip.label && special[clip.label];
  return html`<aside class="stage">
    <div class="screen">
      ${useVideo
        ? html`<video ref=${videoRef} key=${clip.id} src=${media("video", clip.id)} autoplay playsinline
            onCanPlay=${() => setLoading(false)} onClick=${(e) => { e.target.currentTime = 0; e.target.play(); }}></video>`
        : html`<div class="wait">${hasVideo ? "正在听分离出的人声" : "这一集没有视频，只有人声"}</div>
          <audio ref=${(el) => { audioRef.current = el; if (videoRef) videoRef.current = el; }} key=${clip.id}
            src=${media("audio", clip.id)} autoplay onCanPlay=${() => setLoading(false)}></audio>`}
      <div class="wait ${!useVideo || !loading ? "hide" : ""}"><div class="spinner"></div></div>
    </div>
    <div class="line-text">${clip.text || html`<span style="color:var(--text-3)">（字幕里没有这句的文字）</span>`}</div>
    <div class="line-meta">
      <span>${clip.episode}</span><span>${stamp(clip.start)}</span><span>${clip.duration} 秒</span>
      ${hasVideo && html`<span class="sound seg">
        <button class=${sound === "original" ? "on" : ""} onClick=${() => setSound("original")}>画面原声</button>
        <button class=${sound === "vocals" ? "on" : ""} onClick=${() => setSound("vocals")}>只听人声</button>
      </span>`}
    </div>

    ${clip.label
      ? html`<div class="ask">已经确认</div>
        <div class="confirmed-box">
          <${Avatar} role=${roles[clip.label]} name=${clip.label} special=${isSpecial} />
          <div><div class="who">${isSpecial ? special[clip.label] : clip.label}</div>
          <div style="font-size:12px">要改的话，直接按别的数字键或在下面选</div></div>
          ${!isSpecial && useVideo && html`<button class="ghost" style="margin-left:auto;font-size:12px"
            title="把当前这一帧截下来当这个角色的头像" onClick=${() => onAvatar(clip.label)}>设为头像</button>`}
        </div>`
      : html`<div class="ask">${clip.guess.length ? "这是谁？机器的猜测" : clip.voiced ? "这是谁？" : "这句太短，机器听不出来，请直接选人"}</div>
        ${clip.familiar === false && html`<div class="stranger">
          跟已经确认过的角色都不太像，可能是还没标过的人。是新角色就按 <kbd>/</kbd> 输入名字新建。</div>`}
        ${clip.familiar === null && clip.guess.length > 0 && html`<div class="stranger early">
          机器现在只会在底部这几个角色里挑。都不是就按 <kbd>/</kbd> 新建；确认满 20 句后，它会自己提醒你哪句像新面孔。</div>`}
        <div class="cands">
          ${clip.guess.filter((g) => g.p >= 0.02 || g === clip.guess[0]).map((g, i) => html`
            <div class="cand ${i === 0 ? "top" : ""}" onClick=${() => onAssign(g.name)}>
              <${Avatar} role=${roles[g.name]} name=${g.name} />
              <div><div class="name">${g.name}</div><div class="meter"><i style="width:${pct(g.p)}"></i></div></div>
              <span class="pct">${pct(g.p)}</span>
              <button class="ref" title="听这个角色确认过的一句" onClick=${(e) => { e.stopPropagation(); onPlayRef(g.name); }}>
                参考音${i === 0 ? html` <kbd>R</kbd>` : ""}</button>
            </div>`)}
        </div>
        ${clip.guess.length > 0 && html`<div style="margin-top:10px;display:flex;gap:8px;align-items:center">
          <button class="primary" onClick=${onAccept}>是 ${clip.guess[0].name} <kbd style="margin-left:4px">Enter</kbd></button>
          <span style="font-size:12px;color:var(--text-3)">不是的话按数字键选人，或按 <kbd>/</kbd> 搜索</span></div>`}`}

    <div class="specials">
      ${Object.entries(special).map(([value, label], i) => html`
        <button onClick=${() => onAssign(value)}>${label} <kbd>${["X", "C", "V"][i]}</kbd></button>`)}
    </div>
    ${clip.rejects.length > 0 && html`<div class="note" style="margin-top:8px">你说过这句不是：${clip.rejects.join("、")}</div>`}
    <div class="hint">
      <kbd>J</kbd> <kbd>K</kbd> 上下一句 · <kbd>空格</kbd> 重播 · <kbd>1</kbd>–<kbd>9</kbd> 选下面的角色 ·
      <kbd>/</kbd> 搜索或新建角色 · <kbd>Z</kbd> 撤销 · <kbd>?</kbd> 全部快捷键
    </div>
  </aside>`;
}

/* ───────────── 一句台词 ───────────── */

function Row({ clip, roles, special, selected, marked, onSelect, flash }) {
  const ref = useRef(null);
  useEffect(() => {
    if (selected && ref.current) ref.current.scrollIntoView({ block: "nearest" });
  }, [selected]);
  const who = whoOf(clip);
  const isSpecial = clip.label && special[clip.label];
  const stranger = !clip.label && clip.familiar === false;
  return html`<div ref=${ref} class="row ${selected ? "sel" : ""} ${marked ? "marked" : ""} ${flash ? "done-flash" : ""}"
      onClick=${onSelect}>
    <${Avatar} role=${who && !stranger && roles[who.name]} name=${stranger ? null : who?.name} special=${isSpecial} />
    <div>
      <div class="who">
        <span class="n" style=${who && !who.human ? "color:var(--text-2);font-weight:500" : ""}>
          ${isSpecial ? special[clip.label] : stranger ? `最像 ${who.name}` : who ? who.name : "未知"}</span>
        <${Pill} clip=${clip} />
        ${marked && html`<span class="pill reject">不是这个角色</span>`}
      </div>
      <div class="say ${clip.text ? "" : "empty"}">${clip.text || "（没有字幕文字）"}</div>
    </div>
    <div class="t">${stamp(clip.start)}<br />${clip.duration}s</div>
  </div>`;
}

/* ───────────── 场景视图 ───────────── */

function SceneView({ clips, order, focus, setFocus, roles, special, onlyWork, setOnlyWork, flashes, episode }) {
  const shown = new Set(order);
  const scenes = [];
  for (const clip of clips) {
    if (!shown.has(clip.id)) continue;
    const last = scenes[scenes.length - 1];
    if (!last || last.scene !== clip.scene) scenes.push({ scene: clip.scene, clips: [clip] });
    else last.clips.push(clip);
  }
  const left = clips.filter((c) => NEEDS_WORK.has(c.status)).length;
  return html`<div>
    <div class="toolbar">
      <h2>${episode}</h2>
      <span class="sub">${clips.length} 句 · 还有 ${left} 句要你看</span>
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

function RoleView({ state, roles, special, role, setRole, clips, focus, setFocus, marks, toggleMark, onConfirmRest,
  onRename, onToggleTrain, flashes, playing, setPlaying }) {
  const list = state.roles;
  const current = roles[role];
  const pending = clips.filter((c) => !c.label).sort((a, b) => confidence(a) - confidence(b));
  const confirmed = clips.filter((c) => c.label === role);
  const rest = pending.filter((c) => !marks.has(c.id)).length;
  return html`<div class="roles-grid">
    <div class="role-list">
      ${list.map((r) => html`<div class="role-item ${r.name === role ? "on" : ""} ${r.trainable ? "" : "off"}"
          onClick=${() => setRole(r.name)}>
        <${Avatar} role=${r} name=${r.name} size="sm" />
        <span class="nm">${r.name}</span>
        <span class="c">${r.confirmed}${r.predicted ? html` · <b>${r.predicted}</b>` : ""}</span>
      </div>`)}
    </div>
    <div>
      ${!current ? html`<div class="empty"><h2>选一个角色</h2><p>左边是全部角色。灰色数字是确认过的句数，橙色是机器归给 TA、还没人确认的句数。</p></div>`
      : html`
        <div class="role-head">
          <${Avatar} role=${current} name=${role} size="lg" />
          <div><h2>${role}</h2>
            <div class="stats">确认过 ${confirmed.length} 句 · 机器归给 TA ${pending.length} 句
              ${current.trainable ? "" : " · 不参与训练"}</div></div>
          <div class="role-actions">
            <button onClick=${() => setPlaying(!playing)}>${playing ? "停止连播" : "连播待核对"} <kbd>P</kbd></button>
            <button onClick=${onRename}>改名或合并</button>
            <button onClick=${onToggleTrain} title="一群人共用的名字（比如路人）不该拿来训练">
              ${current.trainable ? "不参与训练" : "参与训练"}</button>
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
        ${confirmed.length > 0 && html`<div class="section-title">确认过的 ${confirmed.length} 句</div>
          ${confirmed.map((clip) => html`<${Row} key=${clip.id} clip=${clip} roles=${roles} special=${special}
            selected=${clip.id === focus} flash=${flashes.has(clip.id)} onSelect=${() => setFocus(clip.id)} />`)}`}
      `}
    </div>
  </div>`;
}

/* ───────────── 起步分组：给声音相近的一组起名字 ───────────── */

function GroupsView({ groups, loading, roles, onName, focus, setFocus, firstRun }) {
  const [out, setOut] = useState({});
  const [names, setNames] = useState({});
  if (loading) return html`<div class="empty"><div class="spinner" style="margin:auto"></div><p>正在把声音相近的台词分组…</p></div>`;
  return html`<div>
    ${firstRun && html`<div class="welcome"><div>
      <h3>第一步：给声音相近的一组起个名字</h3>
      <p>机器先把听起来像同一个人的台词放在一起。点一句听一听，确认是谁，在下面填上名字。</p>
      <ol><li>听到混进来的别人，点那一行右边的 × 把它剔出去。</li>
      <li>每命名一组，机器就会重新学一次，其余台词的猜测随之变准。</li>
      <li>命名五六个主要角色以后，去「场景」视图逐句确认会快得多。</li></ol></div></div>`}
    ${groups.length === 0 && html`<div class="empty"><h2>没有可分的组了</h2>
      <p>这一集还没标的台词，要么彼此都不太像，要么已经全部有了名字。去「场景」视图逐句确认吧。</p></div>`}
    <div class="groups">
      ${groups.map((g, gi) => {
        const excluded = out[g.key] || new Set();
        const keep = g.clips.filter((c) => !excluded.has(c.id));
        /* 机器的猜测只放在提示里，不直接填进框：先听再认，回车才采用。 */
        const value = names[g.key] ?? "";
        const chosen = value.trim() || g.hint?.name || "";
        const submit = (e) => { e.preventDefault(); if (chosen && keep.length) onName(keep.map((c) => c.id), chosen); };
        return html`<div class="group ${g.clips.some((c) => c.id === focus) ? "sel" : ""}">
          <h3>第 ${gi + 1} 组 <span class="meta">${g.size} 句 · ${g.seconds} 秒</span>
            ${g.hint && html`<span class="pill auto" title="机器的分类器在这组里最常猜的名字">可能是 ${g.hint.name}</span>`}</h3>
          <div class="members">
            ${g.clips.map((c) => html`<div class="member ${excluded.has(c.id) ? "out" : ""} ${c.id === focus ? "playing" : ""}"
                onClick=${() => setFocus(c.id)}>
              <span>${c.text || "（没有字幕文字）"}</span><span class="t">${c.episode} ${stamp(c.start)}</span>
              <button class="x" title=${excluded.has(c.id) ? "放回这一组" : "这句不是这组的人"}
                onClick=${(e) => { e.stopPropagation(); const next = new Set(excluded); next.has(c.id) ? next.delete(c.id) : next.add(c.id); setOut({ ...out, [g.key]: next }); }}>
                ${excluded.has(c.id) ? "↺" : "×"}</button>
            </div>`)}
          </div>
          <form class="name-form" onSubmit=${submit}>
            <input list="role-names" value=${value}
              placeholder=${g.hint ? `可能是 ${g.hint.name}，听过确认是 TA 就回车` : "这是谁？输入名字"}
              onInput=${(e) => setNames({ ...names, [g.key]: e.target.value })} />
            <button class="primary" type="submit" disabled=${!chosen || !keep.length}>
              ${chosen ? `${keep.length} 句都是 ${chosen}` : `命名这 ${keep.length} 句`}</button>
          </form>
        </div>`;
      })}
    </div>
    <datalist id="role-names">${Object.keys(roles).map((n) => html`<option value=${n} />`)}</datalist>
  </div>`;
}

/* ───────────── 导出 ───────────── */

function ExportView({ state, toast }) {
  const trainable = state.roles.filter((r) => r.confirmed > 0);
  const [picked, setPicked] = useState(() => new Set());
  const [form, setForm] = useState("gpt-sovits");
  const [language, setLanguage] = useState("ja");
  const [includeAuto, setIncludeAuto] = useState(false);
  const [out, setOut] = useState(() => `exports/${new Date().toISOString().slice(0, 10)}`);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const toggle = (name) => { const next = new Set(picked); next.has(name) ? next.delete(name) : next.add(name); setPicked(next); };
  const run = async () => {
    setBusy(true); setResult(null);
    try {
      setResult(await call("/api/export", { roles: [...picked], include_auto: includeAuto, form, language, out }));
    } catch (e) { toast(e.message, true); }
    setBusy(false);
  };
  return html`<div class="form">
    <div class="toolbar" style="padding-left:0"><h2>导出训练数据</h2>
      <span class="sub">从原采样率的人声轨上切，统一响度，一个角色一个文件夹</span></div>
    <div class="field"><label class="title">导出哪些角色</label>
      <div class="role-checks">
        ${trainable.map((r) => html`<div class="check ${picked.has(r.name) ? "on" : ""}" onClick=${() => toggle(r.name)}>
          <${Avatar} role=${r} name=${r.name} size="sm" /><span>${r.name}</span>
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
      <div class="note warn" style="margin-top:6px">文字取自字幕。字幕是中文译文时，文字和日语声音对不上，训练日语模型前需要另做日语转写。</div></div>`}
    <div class="field"><label class="title">输出到（相对路径从启动目录算起）</label>
      <input style="width:100%" value=${out} onInput=${(e) => setOut(e.target.value)} /></div>
    <div><button class="primary" disabled=${busy || picked.size === 0} onClick=${run}>
      ${busy ? "正在导出…" : `导出 ${picked.size} 个角色`}</button></div>
    ${result && html`<div class="result"><b>导出好了：</b>${result.files} 个文件，共 ${Math.round(result.total_sec / 6) / 10} 分钟<br />
      <span class="note">${result.out}</span></div>`}
  </div>`;
}

/* ───────────── 搜索或新建角色 ───────────── */

function Palette({ roles, onPick, onClose }) {
  const [query, setQuery] = useState("");
  const [at, setAt] = useState(0);
  const input = useRef(null);
  useEffect(() => input.current?.focus(), []);
  const names = Object.values(roles);
  const q = query.trim().toLowerCase();
  const found = names.filter((r) => !q || r.name.toLowerCase().includes(q)).slice(0, 12);
  const options = [...found.map((r) => ({ name: r.name, role: r }))];
  if (q && !names.some((r) => r.name.toLowerCase() === q)) options.push({ name: query.trim(), fresh: true });
  const key = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setAt(Math.min(at + 1, options.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setAt(Math.max(at - 1, 0)); }
    else if (e.key === "Enter" && options[at]) { e.preventDefault(); onPick(options[at].name); }
    else if (e.key === "Escape") onClose();
  };
  return html`<div class="overlay" onClick=${onClose}><div class="palette" onClick=${(e) => e.stopPropagation()}>
    <input ref=${input} placeholder="输入角色名，回车确定；没有就新建" value=${query}
      onInput=${(e) => { setQuery(e.target.value); setAt(0); }} onKeyDown=${key} />
    <div class="opts">
      ${options.map((o, i) => html`<div class="opt ${i === at ? "on" : ""}" onMouseEnter=${() => setAt(i)} onClick=${() => onPick(o.name)}>
        ${o.fresh ? html`<div class="av sm unknown">+</div><span>新建角色「${o.name}」</span>`
          : html`<${Avatar} role=${o.role} name=${o.name} size="sm" /><span>${o.name}</span>
            <span class="c">${o.role.confirmed} 句</span>`}
      </div>`)}
      ${options.length === 0 && html`<div class="opt" style="color:var(--text-3)">输入名字</div>`}
    </div>
  </div></div>`;
}

function Help({ onClose }) {
  const rows = [
    ["J / ↓，K / ↑", "下一句，上一句"], ["空格", "从头重播这一句"], ["Enter", "接受机器猜的第一个"],
    ["1 – 9", "标成底部角色栏里对应的角色"], ["/", "搜索角色，或者新建一个"], ["X / C / V", "不止一个人 / 听不清 / 不是说话"],
    ["Backspace", "清掉这句的标签"], ["R", "听机器最像的那个角色的参考音"], ["Z", "撤销上一步（可以一直往回撤）"],
    ["F", "场景视图里只看要处理的"], ["角色视图里 X", "这句不是这个角色"], ["角色视图里 Shift+Enter", "确认其余，剔除标出来的"],
    ["角色视图里 P", "从最没把握的开始连着播"], ["G / S / O / E", "切到起步分组 / 场景 / 角色 / 导出"],
  ];
  return html`<div class="overlay" onClick=${onClose}><div class="help" onClick=${(e) => e.stopPropagation()}>
    <h2>快捷键</h2><table>${rows.map(([k, v]) => html`<tr><td><kbd>${k}</kbd></td><td>${v}</td></tr>`)}</table>
    <p class="note" style="margin-top:12px">每次标注都立刻保存，并让机器重新学一次。所有操作都能撤销。</p>
  </div></div>`;
}

/* ───────────── 主程序 ───────────── */

function App() {
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);
  const [view, setView] = useState("scene");
  const [episode, setEpisode] = useState(null);
  const [clips, setClips] = useState([]);
  const [focus, setFocus] = useState(null);
  const [onlyWork, setOnlyWork] = useState(false);
  const [role, setRole] = useState(null);
  const [marks, setMarks] = useState(() => new Set());
  const [groups, setGroups] = useState([]);
  const [groupsLoading, setGroupsLoading] = useState(false);
  const [palette, setPalette] = useState(false);
  const [help, setHelp] = useState(false);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);
  const [sound, setSound] = useState("original");
  const [flashes, setFlashes] = useState(() => new Set());
  const [playing, setPlaying] = useState(false);
  const dockOrder = useRef([]);
  const playerRef = useRef(null);
  const refAudio = useRef(null);
  const toastTimer = useRef(null);
  const stableOrder = useRef(null);

  const roles = useMemo(() => Object.fromEntries((state?.roles || []).map((r) => [r.name, r])), [state]);
  const special = state?.special || {};
  const episodeInfo = state?.episodes.find((e) => e.name === episode);
  const totalConfirmed = state ? state.roles.reduce((s, r) => s + r.confirmed, 0) : 0;
  const firstRun = state && totalConfirmed === 0;

  const showToast = useCallback((message, isError = false, extra = null) => {
    clearTimeout(toastTimer.current);
    setToast({ message, isError, extra });
    toastTimer.current = setTimeout(() => setToast(null), isError ? 6000 : 3800);
  }, []);

  /* 角色栏的顺序在一次会话里固定不动，新角色排到最后：数字键不会在手底下跳。 */
  useEffect(() => {
    if (!state) return;
    const known = new Set(dockOrder.current);
    for (const r of state.roles) if (!known.has(r.name)) dockOrder.current.push(r.name);
    dockOrder.current = dockOrder.current.filter((n) => roles[n]);
  }, [state]);

  useEffect(() => {
    call("/api/state").then((s) => {
      setState(s);
      if (s.episodes.length) setEpisode(s.episodes[0].name);
      if (!s.roles.some((r) => r.confirmed > 0)) setView("groups");
    }).catch((e) => setError(e.message));
  }, []);

  /* 换集、换视图、换角色时重新取列表。列表取来后顺序固定，标完的句子留在原处，不会突然跳走。 */
  const load = useCallback(async () => {
    if (!state) return;
    if (view === "scene" && episode) {
      const list = await call(`/api/clips?episode=${encodeURIComponent(episode)}`);
      setClips(list);
      stableOrder.current = null;
      setFocus((f) => (list.some((c) => c.id === f) ? f : (list.find((c) => NEEDS_WORK.has(c.status)) || list[0])?.id));
    } else if (view === "roles" && role) {
      const list = await call(`/api/clips?role=${encodeURIComponent(role)}`);
      setClips(list); setMarks(new Set());
      const firstPending = list.filter((c) => !c.label).sort((a, b) => confidence(a) - confidence(b))[0];
      setFocus((firstPending || list[0])?.id);
    } else if (view === "groups" && episode) {
      setGroupsLoading(true);
      const found = (await call(`/api/groups?episode=${encodeURIComponent(episode)}`)).map((g, i) => ({ ...g, key: i }));
      setGroups(found); setGroupsLoading(false);
      setClips(found.flatMap((g) => g.clips));
      setFocus(found[0]?.clips[0]?.id);
    }
  }, [view, episode, role, !!state]);
  /* 换视图时先清空旧列表：旧列表里的句子不一定适合新视图（比如没有预测的句子进了角色视图）。 */
  useEffect(() => { setClips([]); setGroups([]); }, [view]);
  useEffect(() => { load().catch((e) => showToast(e.message, true)); }, [load]);
  useEffect(() => {
    if (view === "roles" && !role && state?.roles.length) setRole(state.roles[0].name);
  }, [view, state]);

  /* 当前视图里「上下一句」走的顺序 */
  const order = useMemo(() => {
    if (view === "scene") {
      if (!onlyWork) return clips.map((c) => c.id);
      if (!stableOrder.current) stableOrder.current = clips.filter((c) => NEEDS_WORK.has(c.status)).map((c) => c.id);
      return stableOrder.current;
    }
    if (view === "roles") {
      const pending = clips.filter((c) => !c.label).sort((a, b) => confidence(a) - confidence(b));
      return [...pending, ...clips.filter((c) => c.label === role)].map((c) => c.id);
    }
    if (view === "groups") return groups.flatMap((g) => g.clips.map((c) => c.id));
    return [];
  }, [view, clips, onlyWork, role, groups]);
  useEffect(() => { stableOrder.current = null; }, [onlyWork, episode]);

  const byId = useMemo(() => Object.fromEntries(clips.map((c) => [c.id, c])), [clips]);
  const current = focus ? byId[focus] : null;

  useEffect(() => {
    const at = order.indexOf(focus);
    if (at < 0) return;
    const next = order.slice(at + 1, at + 4).map((id) => byId[id]).filter(Boolean);
    warm(next, episodeInfo?.video && sound === "original" ? "video" : "audio");
  }, [focus, order]);

  const move = (step) => {
    const at = order.indexOf(focus);
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

  const applyResult = (result, label) => {
    setState(result.state);
    const updated = Object.fromEntries(result.updated.map((c) => [c.id, c]));
    setClips((list) => list.map((c) => updated[c.id] || c));
    if (view === "groups") {
      setGroups((gs) => gs.map((g) => ({ ...g, clips: g.clips.filter((c) => !(updated[c.id]?.label)) }))
        .filter((g) => g.clips.length > 1));
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

  const assign = (name, ids = current ? [current.id] : []) => {
    if (!ids.length || !name) return;
    const from = focus;
    const label = special[name] ? `已标为「${special[name]}」` : `已标为 ${name}`;
    send("/api/label", { clips: ids, label: name }, ids.length > 1 ? `${ids.length} 句${label}` : label,
      () => setFocus(from));
    if (view === "groups") setFocus(order.find((id) => !ids.includes(id)));
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
    const pending = clips.filter((c) => !c.label);
    const changes = pending.map((c) => (marks.has(c.id)
      ? { clip: c.id, reject: role, on: true }
      : { clip: c.id, label: role }));
    if (!changes.length) return;
    const result = await send("/api/changes", { changes },
      `确认了 ${pending.length - marks.size} 句是 ${role}${marks.size ? `，${marks.size} 句退回待确认` : ""}`);
    if (result) { setMarks(new Set()); setPlaying(false); load(); }
  };
  const toggleMark = (id) => {
    const next = new Set(marks);
    next.has(id) ? next.delete(id) : next.add(id);
    setMarks(next);
  };
  const renameRole = async () => {
    const next = prompt(`把「${role}」改成什么名字？填一个已有的名字就是把两个角色合并。`, role);
    if (!next || next.trim() === role) return;
    const result = await send("/api/roles", { name: role, new_name: next.trim() }, `已改名为 ${next.trim()}`);
    if (result) { setRole(next.trim()); }
  };
  const toggleTrain = () => send("/api/roles", { name: role, trainable: !roles[role].trainable },
    roles[role].trainable ? `${role} 不再参与训练` : `${role} 重新参与训练`);
  const saveAvatar = async (name) => {
    const video = playerRef.current;
    if (!video || !video.videoWidth) { showToast("画面还没出来", true); return; }
    const side = Math.min(video.videoWidth, video.videoHeight);
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 160;
    canvas.getContext("2d").drawImage(video, (video.videoWidth - side) / 2, 0, side, side, 0, 0, 160, 160);
    try {
      setState(await call("/api/roles/avatar", { name, image: canvas.toDataURL("image/jpeg", 0.88) }));
      showToast(`已把这一帧设为 ${name} 的头像`);
    } catch (e) { showToast(e.message, true); }
  };

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
      if (palette || help) { if (e.key === "Escape") { setPalette(false); setHelp(false); } return; }
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT" || e.ctrlKey && e.key !== "z" || e.metaKey || e.altKey) return;
      const k = e.key.toLowerCase();
      const handled = () => e.preventDefault();
      if (k === "j" || e.key === "ArrowDown") { handled(); move(1); }
      else if (k === "k" || e.key === "ArrowUp") { handled(); move(-1); }
      else if (e.key === " ") {
        handled();
        const p = playerRef.current;
        if (p) { p.currentTime = 0; p.play().catch(() => {}); }
      }
      else if (e.key === "Enter" && e.shiftKey && view === "roles") { handled(); confirmRest(); }
      else if (e.key === "Enter") { handled(); accept(); }
      else if (/^[1-9]$/.test(e.key)) {
        const name = dockOrder.current[Number(e.key) - 1];
        if (name) { handled(); assign(name); }
      }
      else if (e.key === "/") { handled(); setPalette(true); }
      else if (e.key === "?") { handled(); setHelp(true); }
      else if (k === "z") { handled(); undo(); }
      else if (k === "x" && view === "roles" && current && !current.label) { handled(); toggleMark(current.id); move(1); }
      else if (k === "x" || k === "c" || k === "v") {
        const value = Object.keys(special)[{ x: 0, c: 1, v: 2 }[k]];
        if (value) { handled(); assign(value); }
      }
      else if (e.key === "Backspace") { handled(); clear(); }
      else if (k === "r" && current?.guess.length) { handled(); playRef(current.guess[0].name); }
      else if (k === "f" && view === "scene") { handled(); setOnlyWork(!onlyWork); }
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
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
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
          ? `机器学过 ${state.model.labels} 句 · ${state.model.roles} 个角色`
          : "机器还没学过"}</span>
      <button class="ghost" disabled=${!state.can_undo} onClick=${undo} title="撤销上一步">撤销 <kbd>Z</kbd></button>
      <button class="ghost" onClick=${() => setHelp(true)} title="全部快捷键"><kbd>?</kbd></button>
    </header>

    <div class="body" style=${showStage ? "" : "grid-template-columns:1fr"}>
      ${showStage && html`<${Stage} clip=${current} roles=${roles} special=${special} sound=${sound} setSound=${setSound}
        hasVideo=${!!episodeInfo?.video} videoRef=${playerRef} onAssign=${(n) => assign(n)} onAccept=${accept}
        onPlayRef=${playRef} onAvatar=${saveAvatar} />`}
      <main class="main">
        ${view === "scene" && html`<${SceneView} clips=${clips} order=${order} focus=${focus} setFocus=${setFocus}
          roles=${roles} special=${special} onlyWork=${onlyWork} setOnlyWork=${setOnlyWork} flashes=${flashes} episode=${episode} />`}
        ${view === "roles" && html`<${RoleView} state=${state} roles=${roles} special=${special} role=${role} setRole=${setRole}
          clips=${clips} focus=${focus} setFocus=${setFocus} marks=${marks} toggleMark=${toggleMark}
          onConfirmRest=${confirmRest} onRename=${renameRole} onToggleTrain=${toggleTrain} flashes=${flashes}
          playing=${playing} setPlaying=${setPlaying} />`}
        ${view === "groups" && html`<${GroupsView} groups=${groups} loading=${groupsLoading} roles=${roles}
          focus=${focus} setFocus=${setFocus} firstRun=${firstRun}
          onName=${(ids, name) => assign(name, ids)} />`}
        ${view === "export" && html`<${ExportView} state=${state} toast=${showToast} />`}
      </main>
    </div>

    <footer class="dock">
      ${dockOrder.current.slice(0, 9).map((name, i) => roles[name] && html`<div class="chip" key=${name}
          title=${`按 ${i + 1} 标成 ${name}`} onClick=${() => assign(name)}>
        <${Avatar} role=${roles[name]} name=${name} size="sm" /><span>${name}</span><span class="k">${i + 1}</span></div>`)}
      <button class="ghost" onClick=${() => setPalette(true)}>其他角色或新建 <kbd>/</kbd></button>
      <span class="more">${dockOrder.current.length > 9 ? `另有 ${dockOrder.current.length - 9} 个角色在搜索里` : ""}</span>
    </footer>

    <audio ref=${refAudio} hidden></audio>
    ${palette && html`<${Palette} roles=${roles} onClose=${() => setPalette(false)}
      onPick=${(name) => { setPalette(false); assign(name); }} />`}
    ${help && html`<${Help} onClose=${() => setHelp(false)} />`}
    ${toast && html`<div class="toast ${toast.isError ? "error" : ""}"><span>${toast.message}</span>
      ${toast.extra && html`<button onClick=${undo}>撤销 Z</button>`}</div>`}
  </div>`;
}

render(html`<${App} />`, document.getElementById("app"));
