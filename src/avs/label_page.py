"""姓名标注页面；只展示人工任务，不展示机器分组。

页面把已有角色名当词表给出来，省得每条重敲，但不显示任何分组、组号或候选归属：
标注者一旦看见机器的答案就不再是独立真值。改名与删标签都整份提交，服务端仍按
`apply_names` 校验，页面不做本地增量状态。

角色名排成一行行的小块，不占整行：整集连着标的时候名字有几十个，每个占一行会把
片段推到屏幕外，得来回滚动才能既听见又点得着。展开的详情统一放在一块面板里，
不塞回名字那一行，免得点开一个就把后面的名字全挤走。
"""

PAGE_NAMES = r"""<!doctype html><meta charset="utf-8"><title>角色身份标注</title>
<style>
body{font:16px/1.7 system-ui;max-width:900px;margin:24px auto;padding:0 20px;
background:#fafafa;color:#222}
button,input{font:inherit;padding:8px 12px;border:1px solid #ccc;border-radius:6px;
background:white;cursor:pointer}
button:hover{border-color:#888}
input{cursor:text}
audio{width:100%;margin:6px 0}
h1{margin:0 0 4px;font-size:26px}h2{margin:20px 0 4px;font-size:18px}
.hint{color:#666;font-size:13px;line-height:1.6;margin:4px 0 10px}
#stamp{font-size:28px;font-variant-numeric:tabular-nums}
#status{color:#555;font-variant-numeric:tabular-nums;margin:2px 0}
#bar{height:5px;background:#e4e4e4;border-radius:3px;overflow:hidden;margin:8px 0}
#fill{height:100%;width:0;background:#4a7;transition:width .2s}
#name{width:min(420px,60%)}
#filter{width:min(260px,50%);padding:5px 9px;font-size:14px}
#special button{color:#666;font-size:13px;padding:5px 9px}
nav{margin:12px 0}

/* 名字排成小块横向铺开，一屏能看全，不用为了点名字把片段滚出视野。 */
#known{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
.chip{display:inline-flex;align-items:stretch;border:1px solid #dcdcdc;border-radius:6px;
background:white;overflow:hidden;font-size:14px}
.chip:hover{border-color:#4a7}
.chip .key{color:#bbb;font-size:11px;padding:6px 0 0 6px;font-variant-numeric:tabular-nums}
.chip .pick{border:0;background:none;padding:5px 8px;font-size:14px}
.chip .more{border:0;border-left:1px solid #ededed;background:#fbfbfb;color:#888;
padding:5px 7px;font-size:12px;font-variant-numeric:tabular-nums}
.chip .more:hover{background:#eef5f1;color:#222}
.chip.used{border-color:#bcd9c8;background:#f4faf6}
.chip.here .more{color:#2b6b47;font-weight:600}

#detail{display:none;margin-top:10px;padding:10px 12px;border:1px solid #e2e2e2;
border-radius:8px;background:white}
#detail.on{display:block}
#detail h3{margin:0 0 6px;font-size:15px}
#detail .line{display:flex;gap:5px;flex-wrap:wrap;align-items:center;margin:6px 0}
#detail .line b{font-size:13px;color:#666;font-weight:600;min-width:56px}
#detail button{font-size:13px;padding:4px 8px;font-variant-numeric:tabular-nums}
#detail .here{outline:2px solid #4a7}
</style>
<h1>对照画面确认角色</h1>
<p class="hint">时间相对音轨开头。按顺序到视频里看是谁在说，名字前后一致即可。
这页不显示机器分组，也不该显示：看过机器的答案，标出来的就不再是独立真值。<br>
快捷键：回车保存，← → 上一条／跳过，空格重播，数字 1-9 选下面前九个名字。</p>
<div id="bar"><div id="fill"></div></div>
<p id="status"></p>
<div id="stamp"></div>
<audio id="audio" controls></audio>
<p><input id="name" list="roster" placeholder="角色名，回车保存" autocomplete="off">
<button id="submit">保存并继续</button><button id="drop">清除本条</button></p>
<datalist id="roster"></datalist>
<div id="special"></div>
<nav><button id="prev">上一条</button><button id="next">跳过</button>
<button id="tonew">下一条未标</button></nav>
<h2>角色名 <input id="filter" placeholder="筛名字" autocomplete="off"></h2>
<p class="hint">点名字给当前片段打标；点右边的数字看这个名字下都有哪些片段、改名或撤标签。
试听旧标签只为帮你想起这个名字是谁，判断仍以画面为准，别改成靠耳朵比对。</p>
<div id="known"></div>
<div id="detail"></div>
<audio id="ref" controls hidden></audio>
<script>
const clips=__CLIPS__, special=__SPECIAL__, roster=__KNOWN__, history=__HISTORY__;
let names=__NAMES__, at=0, opened=null;
const el=id=>document.getElementById(id);
const total=clips.length;

function done(){return clips.filter(c=>names[c.id]).length;}
function firstBlank(from){
 for(let i=from;i<total;i++)if(!names[clips[i].id])return i;
 return total;
}
/* 顺序固定：先是旧标签里的名字（常用的在前），再是本轮新敲出来的，按第一次用到排。
   本轮标了多少条只显示，不参与排序，否则数字键会在手底下跳来跳去。 */
function rows(){
 const used=new Map();
 clips.forEach((c,i)=>{
  const n=names[c.id];
  if(!n||n in special)return;
  if(!used.has(n))used.set(n,[]);
  used.get(n).push(i);
 });
 const order=[...roster,...[...used.keys()].filter(n=>!roster.includes(n))];
 const keep=el('filter').value.trim().toLowerCase();
 return order
  .map(n=>[n,used.get(n)||[]])
  .filter(([n])=>!keep||n.toLowerCase().includes(keep));
}

function button(parent,label,fn,cls){
 const b=document.createElement('button');
 b.textContent=label;b.onclick=fn;if(cls)b.className=cls;
 parent.appendChild(b);return b;
}

function renderRoster(){
 const box=el('known');box.replaceChildren();
 const list=rows();
 el('roster').replaceChildren(...list.map(([n])=>{
  const o=document.createElement('option');o.value=n;return o;
 }));
 if(!list.length){box.textContent='没有匹配的名字，直接在上面敲一个新的。';return;}
 list.forEach(([name,where],index)=>{
  const past=history[name]||[];
  const chip=document.createElement('span');
  chip.className='chip'+(where.length?' used':'')+(opened===name?' here':'');
  if(index<9){
   const key=document.createElement('span');
   key.className='key';key.textContent=index+1;chip.appendChild(key);
  }
  button(chip,name,()=>assign(name),'pick');
  const badge=button(chip,`${where.length}·${past.length}`,()=>openName(name),'more');
  badge.title=`本轮 ${where.length} 条，旧标签 ${past.length} 条`;
  box.appendChild(chip);
 });
}

function openName(name){
 opened=opened===name?null:name;
 renderRoster();renderDetail();
}

function renderDetail(){
 const box=el('detail');box.replaceChildren();
 box.className=opened?'on':'';
 if(!opened)return;
 const where=rows().find(([n])=>n===opened)?.[1]||[];
 const past=history[opened]||[];
 const head=document.createElement('h3');
 head.textContent=`${opened} · 本轮 ${where.length} 条 · 旧标签 ${past.length} 条`;
 box.appendChild(head);

 const tools=document.createElement('div');tools.className='line';
 if(where.length)button(tools,'改名',()=>rename(opened,tools));
 if(where.length)button(tools,'撤掉本轮这些标签',()=>{
  submit(n=>{
   const proposed={...n};where.forEach(i=>delete proposed[clips[i].id]);return proposed;
  }).then(()=>{opened=null;render();});
 });
 button(tools,'关闭',()=>{opened=null;renderRoster();renderDetail();});
 box.appendChild(tools);

 if(where.length){
  const line=document.createElement('div');line.className='line';
  line.appendChild(Object.assign(document.createElement('b'),{textContent:'本轮'}));
  where.forEach(i=>{
   const b=button(line,clips[i].stamp,()=>{at=i;render();},i===at?'here':'');
   b.title=`${clips[i].seconds} 秒，点了跳过去`;
  });
  box.appendChild(line);
 }
 if(past.length){
  const line=document.createElement('div');line.className='line';
  line.appendChild(Object.assign(document.createElement('b'),{textContent:'旧标签'}));
  past.forEach(entry=>{
   const b=button(line,`${entry.episode} ${entry.stamp}`,()=>audition(entry));
   b.title=`${entry.seconds} 秒，点了试听`;
  });
  box.appendChild(line);
 }
}

/* 旧标签用单独的播放器，免得盖掉正在标的那一条。 */
function audition(entry){
 const ref=el('ref');
 ref.hidden=false;ref.src=entry.file;ref.play().catch(()=>{});
}

function rename(old,line){
 const box=document.createElement('input');
 box.value=old;box.style.width='180px';box.style.padding='4px 8px';box.style.fontSize='13px';
 const commit=()=>{
  const next=box.value.trim();
  if(!next||next===old){renderDetail();return;}
  submit(n=>{
   const proposed={...n};
   Object.keys(proposed).forEach(id=>{if(proposed[id]===old)proposed[id]=next;});
   return proposed;
  }).then(()=>{opened=next;render();});
 };
 box.onkeydown=e=>{if(e.key==='Enter')commit();if(e.key==='Escape')renderDetail();};
 line.replaceChildren(box);
 button(line,'确定',commit);
 button(line,'取消',()=>renderDetail());
 box.focus();box.select();
}

function render(){
 const had=done();
 el('status').textContent=total
  ? `第 ${Math.min(at+1,total)} / ${total} 条 · 已标 ${had} · 未标 ${total-had}`
  : '本轮没有片段';
 el('fill').style.width=total?`${had/total*100}%`:'0';
 el('special').replaceChildren();
 if(at>=total){
  el('stamp').textContent='本轮到底了，可以回去改任何一条';
  el('audio').removeAttribute('src');el('name').value='';
 }else{
  const c=clips[at];
  el('stamp').textContent=`${c.stamp} · ${c.seconds} 秒`;
  if(!el('audio').src.endsWith('/'+c.id+'.wav')){
   el('audio').src=c.id+'.wav';
   el('audio').play().catch(()=>{});
  }
  el('name').value=names[c.id]||'';
  Object.entries(special).forEach(([v,label])=>button(el('special'),label,()=>assign(v)));
 }
 renderRoster();renderDetail();
}

/* 提交排队，不丢按键：手比一次往返快的时候，先按的先落盘，而不是被 busy 挡掉。
   update 拿到的是排到自己时的 names，所以连着改同一个名字也不会互相覆盖。 */
let queue=Promise.resolve(true);
function submit(update){
 queue=queue.then(async()=>{
  const proposed=update(names);
  if(!proposed)return true;
  try{
   const r=await fetch('/save',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(proposed)});
   if(!r.ok)throw Error(r.statusText||'保存失败');
   names=proposed;return true;
  }catch(e){
   el('status').textContent='保存失败，这一条没有改动，请重试。';return false;
  }
 });
 return queue;
}

/* 先往前走再等回执：慢的是网络不是判断。存不下就退回那一条，不会悄悄跳过。 */
function assign(value){
 value=(value||'').trim();
 const i=at;
 if(i>=total||!value)return;
 at=i+1;render();
 submit(n=>({...n,[clips[i].id]:value})).then(ok=>{if(!ok)at=i;render();});
}

el('submit').onclick=()=>assign(el('name').value);
el('name').onkeydown=e=>{if(e.key==='Enter')assign(el('name').value);};
el('drop').onclick=()=>{
 const i=at;
 if(i>=total)return;
 submit(n=>{const proposed={...n};delete proposed[clips[i].id];return proposed;}).then(render);
};
el('prev').onclick=()=>{if(at>0){at--;render();}};
el('next').onclick=()=>{if(at<total){at++;render();}};
el('tonew').onclick=()=>{at=firstBlank(0);render();};
el('filter').oninput=()=>{opened=null;renderRoster();renderDetail();};
document.addEventListener('keydown',e=>{
 if(e.target.tagName==='INPUT'||e.metaKey||e.ctrlKey||e.altKey)return;
 if(e.key==='ArrowLeft'){e.preventDefault();el('prev').click();}
 else if(e.key==='ArrowRight'){e.preventDefault();el('next').click();}
 else if(e.key===' '){
  e.preventDefault();el('audio').currentTime=0;el('audio').play().catch(()=>{});
 }
 else if(e.key>='1'&&e.key<='9'){
  const row=rows()[Number(e.key)-1];
  if(row){e.preventDefault();assign(row[0]);}
 }
});
at=firstBlank(0);
render();
</script>"""
