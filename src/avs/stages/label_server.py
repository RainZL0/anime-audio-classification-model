"""标注工具的网页和本地小服务。设计意图见 `label.py` 的开头。

只听 127.0.0.1，音频不出本机。用标准库的 `http.server`，不引新依赖：这是个一次性的
探索工具，不值得为它加一个 web 框架。每标一条就存一次盘，关掉网页也不会丢。
"""

from __future__ import annotations

import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>听音分组</title>
<style>
:root { color-scheme: light dark; --line: #8884; }
body { font: 15px/1.6 system-ui, sans-serif; margin: 0; padding: 24px;
       max-width: 720px; margin-inline: auto; }
h1 { font-size: 18px; margin: 0 0 4px; }
.hint { opacity: .65; font-size: 13px; margin-bottom: 20px; }
.bar { height: 6px; background: var(--line); border-radius: 3px;
       overflow: hidden; margin: 12px 0 20px; }
.bar > i { display: block; height: 100%; background: currentColor; transition: width .2s; }
.now { border: 1px solid var(--line); border-radius: 10px; padding: 18px; margin-bottom: 20px; }
.play { font-size: 17px; padding: 12px 22px; border-radius: 8px; cursor: pointer;
        border: 1px solid var(--line); background: transparent; color: inherit; width: 100%; }
.play:hover { background: #8881; }
.meta { opacity: .6; font-size: 13px; margin-top: 10px; }
.buckets { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
button.b { padding: 10px 14px; border-radius: 8px; border: 1px solid var(--line);
           background: transparent; color: inherit; cursor: pointer; font-size: 14px; }
button.b:hover { background: #8881; }
button.b kbd { opacity: .5; margin-right: 6px; font-size: 12px; }
button.ear { border: none; background: none; cursor: pointer; opacity: .55; padding: 0 0 0 6px;
             color: inherit; font-size: 13px; }
button.ear:hover { opacity: 1; }
.special button.b { opacity: .75; font-size: 13px; }
.foot { margin-top: 22px; display: flex; gap: 12px; align-items: center;
        font-size: 13px; opacity: .7; }
.foot button { background: none; border: none; color: inherit; cursor: pointer;
               text-decoration: underline; font-size: 13px; padding: 0; }
.done { text-align: center; padding: 40px 0; }
.done h1 { font-size: 22px; }
table { border-collapse: collapse; width: 100%; margin-top: 16px; font-size: 14px; }
td, th { border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: left; }
</style>

<h1>听音分组</h1>
<div class="hint">
  听一条，丢进你觉得是同一个人的那一组。<b>不用认识角色，也不用起名。</b>
  拿不准就选「听不清」，别硬猜。快捷键：空格重放，数字键选组，N 新建一组。
</div>

<div id="app"></div>

<script>
const CLIPS = __CLIPS__;
const SPECIAL = __SPECIAL__;
let labels = __LABELS__;
let at = CLIPS.findIndex(c => !(c.id in labels));
if (at < 0) at = CLIPS.length;
const app = document.getElementById("app");
const audio = new Audio();

function buckets() {
  const seen = [];
  for (const id of Object.keys(labels)) {
    const v = labels[id];
    if (!(v in SPECIAL) && !seen.includes(v)) seen.push(v);
  }
  return seen.sort();
}
function firstClipOf(name) {
  return Object.keys(labels).find(id => labels[id] === name);
}
function play(id) { audio.src = id + ".wav"; audio.currentTime = 0; audio.play(); }

function assign(value) {
  if (at >= CLIPS.length) return;
  labels[CLIPS[at].id] = value;
  at++;
  save();
  render();
}
function back() { if (at > 0) { at--; delete labels[CLIPS[at].id]; save(); render(); } }
function save() {
  fetch("save", { method: "POST", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(labels) });
}

function render() {
  if (at >= CLIPS.length) return renderDone();
  const clip = CLIPS[at];
  const names = buckets();
  const rows = names.map((name, i) =>
    `<button class="b" data-pick="${name}"><kbd>${i + 1}</kbd>${name}
       <span style="opacity:.5">${Object.values(labels).filter(v => v === name).length}</span>
     </button>`).join("");
  const specials = Object.keys(SPECIAL).map(key =>
    `<button class="b" data-pick="${key}">${SPECIAL[key]}</button>`).join("");

  app.innerHTML = `
    <div class="bar"><i style="width:${(at / CLIPS.length) * 100}%"></i></div>
    <div class="now">
      <button class="play" id="play">▶  播放第 ${at + 1} 条（共 ${CLIPS.length} 条）</button>
      <div class="meta">这条 ${clip.seconds} 秒</div>
    </div>
    <div>这条属于哪一组？</div>
    <div class="buckets">${rows}
      <button class="b" data-pick="__new__"><kbd>N</kbd>新建一组</button></div>
    <div class="buckets special">${specials}</div>
    <div class="foot">
      ${at > 0 ? '<button id="back">← 改上一条</button>' : ""}
      <span>已标 ${Object.keys(labels).length} 条</span>
      ${names.length ? "<span>点组名旁的耳朵可以试听那组</span>" : ""}
    </div>`;

  for (const name of names) {
    const btn = app.querySelector(`[data-pick="${CSS.escape(name)}"]`);
    const ear = document.createElement("button");
    ear.className = "ear"; ear.textContent = "🔊"; ear.title = "听这组已有的一条";
    ear.onclick = e => { e.stopPropagation(); play(firstClipOf(name)); };
    btn.appendChild(ear);
  }
  app.querySelectorAll("[data-pick]").forEach(btn => {
    btn.onclick = () => {
      const pick = btn.dataset.pick;
      if (pick !== "__new__") return assign(pick);
      const next = String.fromCharCode(65 + names.length);
      assign(next);
    };
  });
  document.getElementById("play").onclick = () => play(clip.id);
  const backBtn = document.getElementById("back");
  if (backBtn) backBtn.onclick = back;
  play(clip.id);
}

function renderDone() {
  const names = buckets();
  const rows = names.map(n =>
    `<tr><td>${n}</td><td>${Object.values(labels).filter(v => v === n).length} 条</td></tr>`)
    .join("")
    + Object.keys(SPECIAL).map(k => {
        const n = Object.values(labels).filter(v => v === k).length;
        return n ? `<tr><td>${SPECIAL[k]}</td><td>${n} 条</td></tr>` : "";
      }).join("");
  app.innerHTML = `
    <div class="done">
      <h1>标完了</h1>
      <p>${CLIPS.length} 条已经存进 <code>labels.json</code>，可以关掉这个页面了。</p>
      <table><tr><th>组</th><th>条数</th></tr>${rows}</table>
      <div class="foot" style="justify-content:center">
        <button id="back">← 改最后一条</button>
      </div>
    </div>`;
  document.getElementById("back").onclick = back;
}

document.addEventListener("keydown", e => {
  if (at >= CLIPS.length) return;
  if (e.code === "Space") { e.preventDefault(); return play(CLIPS[at].id); }
  const names = buckets();
  if (e.key >= "1" && e.key <= "9") {
    const pick = names[Number(e.key) - 1];
    if (pick) assign(pick);
  } else if (e.key.toLowerCase() === "n") {
    assign(String.fromCharCode(65 + names.length));
  }
});

render();
</script>
"""


PAGE_PAIRS = """<!doctype html>
<meta charset="utf-8">
<title>两两比对</title>
<style>
:root { color-scheme: light dark; --line: #8884; }
body { font: 15px/1.6 system-ui, sans-serif; margin: 0; padding: 24px;
       max-width: 720px; margin-inline: auto; }
h1 { font-size: 18px; margin: 0 0 4px; }
.hint { opacity: .65; font-size: 13px; margin-bottom: 20px; }
.bar { height: 6px; background: var(--line); border-radius: 3px;
       overflow: hidden; margin: 12px 0 20px; }
.bar > i { display: block; height: 100%; background: currentColor; transition: width .2s; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 8px; }
.two button { font-size: 16px; padding: 22px 12px; border-radius: 10px; cursor: pointer;
              border: 1px solid var(--line); background: transparent; color: inherit; }
.two button:hover { background: #8881; }
.two button.on { border-color: currentColor; background: #8882; }
.again { width: 100%; padding: 10px; border-radius: 8px; border: 1px dashed var(--line);
         background: transparent; color: inherit; cursor: pointer; font-size: 13px;
         opacity: .7; margin-bottom: 22px; }
.picks { display: flex; gap: 8px; }
.picks button { flex: 1; padding: 14px; border-radius: 8px; border: 1px solid var(--line);
                background: transparent; color: inherit; cursor: pointer; font-size: 15px; }
.picks button:hover { background: #8881; }
.picks kbd { opacity: .5; margin-right: 6px; font-size: 12px; }
.foot { margin-top: 22px; display: flex; gap: 12px; font-size: 13px; opacity: .7; }
.foot button { background: none; border: none; color: inherit; cursor: pointer;
               text-decoration: underline; font-size: 13px; padding: 0; }
.done { text-align: center; padding: 40px 0; }
</style>

<h1>两两比对</h1>
<div class="hint">
  听两条，判断是不是同一个人。<b>答完就忘掉，不用记住任何人。</b>
  拿不准就选「拿不准」，别硬猜。快捷键：空格连放两条，1 同一个人，2 不同的人，3 拿不准。
</div>

<div id="app"></div>

<script>
const PAIRS = __PAIRS__;
const CHOICES = __CHOICES__;
let answers = __ANSWERS__;
let at = PAIRS.findIndex(p => !(p.id in answers));
if (at < 0) at = PAIRS.length;
const app = document.getElementById("app");
const audio = new Audio();

function play(id) { audio.src = id + ".wav"; audio.currentTime = 0; audio.play(); }
function playBoth() {
  const p = PAIRS[at];
  if (!p) return;
  audio.onended = () => { audio.onended = null; setTimeout(() => play(p.right), 250); };
  play(p.left);
}
function answer(value) {
  if (at >= PAIRS.length) return;
  answers[PAIRS[at].id] = value;
  at++;
  save();
  render();
}
function back() { if (at > 0) { at--; delete answers[PAIRS[at].id]; save(); render(); } }
function save() {
  fetch("save", { method: "POST", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(answers) });
}

function render() {
  if (at >= PAIRS.length) return renderDone();
  const p = PAIRS[at];
  const picks = Object.keys(CHOICES).map((key, i) =>
    `<button data-pick="${key}"><kbd>${i + 1}</kbd>${CHOICES[key]}</button>`).join("");
  app.innerHTML = `
    <div class="bar"><i style="width:${(at / PAIRS.length) * 100}%"></i></div>
    <div style="opacity:.6;font-size:13px;margin-bottom:8px">
      第 ${at + 1} 题，共 ${PAIRS.length} 题</div>
    <div class="two">
      <button id="a">▶ 第一条</button>
      <button id="b">▶ 第二条</button>
    </div>
    <button class="again" id="both">↻ 连着放一遍（空格）</button>
    <div>这两条是同一个人吗？</div>
    <div class="picks" style="margin-top:10px">${picks}</div>
    <div class="foot">
      ${at > 0 ? '<button id="back">← 改上一题</button>' : ""}
      <span>已答 ${Object.keys(answers).length} 题</span>
    </div>`;
  document.getElementById("a").onclick = () => play(p.left);
  document.getElementById("b").onclick = () => play(p.right);
  document.getElementById("both").onclick = playBoth;
  app.querySelectorAll("[data-pick]").forEach(b => b.onclick = () => answer(b.dataset.pick));
  const backBtn = document.getElementById("back");
  if (backBtn) backBtn.onclick = back;
  playBoth();
}

function renderDone() {
  const tally = Object.keys(CHOICES).map(k =>
    `${CHOICES[k]} ${Object.values(answers).filter(v => v === k).length} 题`).join("　");
  app.innerHTML = `
    <div class="done">
      <h1>答完了</h1>
      <p>${PAIRS.length} 题已经存进 <code>pair_answers.json</code>，可以关掉这个页面了。</p>
      <p style="opacity:.7">${tally}</p>
      <div class="foot" style="justify-content:center">
        <button id="back">← 改最后一题</button>
      </div>
    </div>`;
  document.getElementById("back").onclick = back;
}

document.addEventListener("keydown", e => {
  if (at >= PAIRS.length) return;
  if (e.code === "Space") { e.preventDefault(); return playBoth(); }
  const keys = Object.keys(CHOICES);
  if (e.key >= "1" && e.key <= String(keys.length)) answer(keys[Number(e.key) - 1]);
});

render();
</script>
"""


PAGE_NAMES = """<!doctype html>
<meta charset="utf-8">
<title>对着画面报名字</title>
<style>
:root { color-scheme: light dark; --line: #8884; }
body { font: 15px/1.6 system-ui, sans-serif; margin: 0; padding: 24px;
       max-width: 720px; margin-inline: auto; }
h1 { font-size: 18px; margin: 0 0 4px; }
.hint { opacity: .65; font-size: 13px; margin-bottom: 18px; }
.bar { height: 6px; background: var(--line); border-radius: 3px;
       overflow: hidden; margin: 12px 0 18px; }
.bar > i { display: block; height: 100%; background: currentColor; transition: width .2s; }
.stamp { font-size: 34px; font-weight: 600; letter-spacing: .5px; user-select: all;
         font-variant-numeric: tabular-nums; }
.stamp small { font-size: 15px; font-weight: 400; opacity: .55; margin-left: 10px; }
.card { border: 1px solid var(--line); border-radius: 10px; padding: 18px; margin-bottom: 16px; }
.play { font-size: 16px; padding: 12px; border-radius: 8px; cursor: pointer; width: 100%;
        border: 1px solid var(--line); background: transparent; color: inherit; margin-top: 12px; }
.play:hover { background: #8881; }
input { width: 100%; box-sizing: border-box; font: inherit; padding: 12px 14px;
        border-radius: 8px; border: 1px solid var(--line); background: transparent;
        color: inherit; margin-bottom: 12px; }
.known { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.known button, .special button { padding: 9px 13px; border-radius: 8px; cursor: pointer;
        border: 1px solid var(--line); background: transparent; color: inherit; font-size: 14px; }
.known button:hover, .special button:hover { background: #8881; }
.known kbd { opacity: .5; margin-right: 6px; font-size: 12px; }
.special { display: flex; gap: 8px; margin-bottom: 14px; }
.special button { opacity: .75; font-size: 13px; }
.foot { margin-top: 20px; display: flex; gap: 14px; font-size: 13px; opacity: .7;
        flex-wrap: wrap; align-items: center; }
.foot button { background: none; border: none; color: inherit; cursor: pointer;
               text-decoration: underline; font-size: 13px; padding: 0; }
.plan { margin-top: 18px; font-size: 13px; opacity: .85; }
.plan th { text-align: left; white-space: nowrap; vertical-align: top;
           padding: 6px 14px 6px 0; font-weight: 600; }
.plan th small { opacity: .45; font-weight: 400; margin-left: 6px; }
.plan td { padding: 4px 0; }
.chip { font: inherit; font-variant-numeric: tabular-nums; cursor: pointer;
        border: 1px solid var(--line); background: transparent; color: inherit;
        border-radius: 6px; padding: 3px 8px; margin: 0 6px 6px 0; }
.chip:hover { background: #8881; }
.chip span { opacity: .45; margin-left: 5px; }
.done { text-align: center; padding: 32px 0 8px; }
</style>

<h1>对着画面报名字</h1>
<div class="hint">
  片段<b>按时间从早到晚排好了</b>，在动画里从头往后拖一遍就行，不用来回找。
  跳到显示的时间点，看画面上是谁在说，把名字打进去。名字怎么写都行，前后一致就够。
</div>

<div id="app"></div>

<script>
const CLIPS = __CLIPS__;
const SPECIAL = __SPECIAL__;
let names = __NAMES__;
let at = CLIPS.findIndex(c => !(c.id in names));
if (at < 0) at = CLIPS.length;
const app = document.getElementById("app");
const audio = new Audio();
let showPlan = false;

function known() {
  const seen = [];
  for (const v of Object.values(names)) {
    if (!(v in SPECIAL) && !seen.includes(v)) seen.push(v);
  }
  return seen;
}
function play(id) { audio.src = id + ".wav"; audio.currentTime = 0; audio.play(); }
function assign(value) {
  if (at >= CLIPS.length || !value) return;
  names[CLIPS[at].id] = value;
  at++;
  save();
  render();
}
function skip() { if (at < CLIPS.length) { at++; render(); } }
function back() { if (at > 0) { at--; delete names[CLIPS[at].id]; save(); render(); } }
function save() {
  fetch("save", { method: "POST", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(names) });
}

// 已经标过的按名字归堆列出来，每条给时间点和一个重听按钮。
// 用处是自查：同一个名字底下的几条听起来该是一个人，不是的话说明标错了。
function review() {
  const grouped = {};
  for (const c of CLIPS) {
    const key = c.id in names ? (SPECIAL[names[c.id]] || names[c.id]) : "还没标";
    (grouped[key] = grouped[key] || []).push(c);
  }
  const order = Object.keys(grouped).sort((a, b) => {
    if (a === "还没标") return 1;
    if (b === "还没标") return -1;
    return grouped[b].length - grouped[a].length;
  });
  const rows = order.map(key => {
    const chips = grouped[key].map(c =>
      `<button class="chip" data-play="${c.id}"
               title="重听这条">${c.stamp}<span>▶</span></button>`).join("");
    return `<tr><th>${key}<small>${grouped[key].length}</small></th><td>${chips}</td></tr>`;
  }).join("");
  return `<div class="plan">
            <div style="margin-bottom:8px">已标的按名字归堆，点时间可以重听</div>
            <table>${rows}</table>
          </div>`;
}

function render() {
  if (at >= CLIPS.length) return renderDone();
  const c = CLIPS[at];
  const next = CLIPS[at + 1];
  const list = known();
  const buttons = list.map((n, i) =>
    `<button data-name="${n}"><kbd>${i + 1}</kbd>${n}</button>`).join("");
  const specials = Object.keys(SPECIAL).map(k =>
    `<button data-name="${k}">${SPECIAL[k]}</button>`).join("");
  const plan = showPlan ? review() : "";

  app.innerHTML = `
    <div class="bar"><i style="width:${(at / CLIPS.length) * 100}%"></i></div>
    <div class="card">
      <div style="opacity:.6;font-size:13px">第 ${at + 1} 条，共 ${CLIPS.length} 条</div>
      <div class="stamp">${c.stamp}<small>到 ${c.stamp_end}，${c.seconds} 秒</small></div>
      <button class="play" id="play">▶ 先听一遍（空格）</button>
    </div>
    <input id="name" placeholder="这是谁？打名字后回车" autocomplete="off"
           list="known" value="">
    <datalist id="known">${list.map(n => `<option value="${n}">`).join("")}</datalist>
    <div class="known">${buttons}</div>
    <div class="special">${specials}</div>
    <div class="foot">
      ${at > 0 ? '<button id="back">← 改上一条</button>' : ""}
      <button id="skipBtn">跳过这条</button>
      <button id="planBtn">${showPlan ? "收起" : "看全部时间点"}</button>
      <span>已标 ${Object.keys(names).length} 条</span>
      ${next ? `<span>下一条在 ${next.stamp}</span>` : "<span>这是最后一条</span>"}
    </div>
    ${plan}`;

  const input = document.getElementById("name");
  input.focus();
  input.onkeydown = e => {
    if (e.key === "Enter") { e.preventDefault(); assign(input.value.trim()); }
    e.stopPropagation();
  };
  document.getElementById("play").onclick = () => play(c.id);
  document.getElementById("skipBtn").onclick = skip;
  document.getElementById("planBtn").onclick = () => { showPlan = !showPlan; render(); };
  const backBtn = document.getElementById("back");
  if (backBtn) backBtn.onclick = back;
  app.querySelectorAll("[data-name]").forEach(b =>
    b.onclick = () => assign(b.dataset.name));
  wirePlay();
  play(c.id);
}

function wirePlay() {
  app.querySelectorAll("[data-play]").forEach(b =>
    b.onclick = e => { e.stopPropagation(); play(b.dataset.play); });
}

function renderDone() {
  app.innerHTML = `
    <div class="done">
      <h1>标完了</h1>
      <p>${Object.keys(names).length} 条已经存进 <code>names.json</code>，可以关掉页面了。</p>
    </div>
    ${review()}
    <div class="foot"><button id="back">← 改最后一条</button></div>`;
  document.getElementById("back").onclick = back;
  wirePlay();
}

document.addEventListener("keydown", e => {
  if (at >= CLIPS.length || e.target.tagName === "INPUT") return;
  if (e.code === "Space") { e.preventDefault(); return play(CLIPS[at].id); }
  const list = known();
  if (e.key >= "1" && e.key <= "9" && list[Number(e.key) - 1]) assign(list[Number(e.key) - 1]);
});

render();
</script>
"""


def write_names_page(out_dir: Path, clips: list[dict[str, Any]], names: dict[str, str]) -> Path:
    """报名字页。片段按时间排好，时间戳是给你在视频里定位用的。"""
    from avs.stages.label import SPECIAL

    page = out_dir / "index.html"
    page.write_text(
        PAGE_NAMES.replace("__CLIPS__", json.dumps(clips, ensure_ascii=False))
        .replace("__SPECIAL__", json.dumps(SPECIAL, ensure_ascii=False))
        .replace("__NAMES__", json.dumps(names, ensure_ascii=False)),
        encoding="utf-8",
    )
    return page


def write_pairs_page(out_dir: Path, pairs: list[Any], answers: dict[str, str]) -> Path:
    """配对页。距离和机器的看法都不发到网页上，只发左右两条的编号。"""
    from avs.stages.label import PAIR_ANSWERS

    public = [{"id": p.pair_id, "left": p.left, "right": p.right} for p in pairs]
    page = out_dir / "index.html"
    page.write_text(
        PAGE_PAIRS.replace("__PAIRS__", json.dumps(public, ensure_ascii=False))
        .replace("__CHOICES__", json.dumps(PAIR_ANSWERS, ensure_ascii=False))
        .replace("__ANSWERS__", json.dumps(answers, ensure_ascii=False)),
        encoding="utf-8",
    )
    return page


def write_page(out_dir: Path, sample: Any, labels: dict[str, str]) -> Path:
    """把网页生成到片段所在的目录，这样音频用相对路径就能引到。"""
    page = out_dir / "index.html"
    page.write_text(
        PAGE.replace("__CLIPS__", json.dumps(sample.public(), ensure_ascii=False))
        .replace("__SPECIAL__", json.dumps(_special(), ensure_ascii=False))
        .replace("__LABELS__", json.dumps(labels, ensure_ascii=False)),
        encoding="utf-8",
    )
    return page


def _special() -> dict[str, str]:
    from avs.stages.label import SPECIAL

    return SPECIAL


def serve(clip_dir: Path, labels_file: Path, port: int) -> None:
    """起服务，直到你按 Ctrl+C。每收到一次提交就整份覆盖写一遍 labels.json。"""

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(clip_dir), **kwargs)

        # 方法名是 http.server 定的，不是我们起的
        def do_POST(self) -> None:
            if self.path.rstrip("/") not in ("/save", "save"):
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            labels_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args: Any) -> None:
            """别把每个音频请求都刷到终端上。"""

    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as httpd:
        httpd.serve_forever()
