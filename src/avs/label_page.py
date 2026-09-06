"""姓名标注页面；只展示人工任务，不展示机器分组。

页面把已有角色名当词表给出来，省得每条重敲，但不显示任何分组、组号或候选归属：
标注者一旦看见机器的答案就不再是独立真值。改名与删标签都整份提交，服务端仍按
`apply_names` 校验，页面不做本地增量状态。
"""

PAGE_NAMES = r"""<!doctype html><meta charset="utf-8"><title>角色身份标注</title>
<style>
body{font:16px/1.7 system-ui;max-width:820px;margin:32px auto;padding:0 24px;
background:#fafafa;color:#222}
button,input{font:inherit;padding:8px 12px;border:1px solid #ccc;border-radius:6px;
background:white;cursor:pointer}
button:hover{border-color:#888}
input{cursor:text;width:60%}
audio{width:100%;margin:6px 0}
h1{margin-bottom:4px}h2{margin:28px 0 4px;font-size:19px}
.hint{color:#666;font-size:14px;line-height:1.6;margin:4px 0 12px}
#stamp{font-size:30px;font-variant-numeric:tabular-nums}
#status{color:#555;font-variant-numeric:tabular-nums;margin:2px 0}
#bar{height:6px;background:#e4e4e4;border-radius:3px;overflow:hidden;margin:10px 0}
#fill{height:100%;width:0;background:#4a7;transition:width .2s}
#special button{color:#666;font-size:14px;padding:6px 10px}
nav{margin:14px 0}
.row{display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:3px 0;
border-top:1px solid #ececec}
.row:first-child{border-top:0}
.pick{flex:1;text-align:left;border:0;background:none;padding:6px 4px}
.pick:hover{background:#eef5f1;border-radius:4px}
.pick b{font-weight:600}
.count{border:0;background:none;color:#777;font-size:14px;padding:6px 4px}
.count:hover{color:#222;text-decoration:underline}
.key{color:#aaa;font-size:13px;width:16px;text-align:right}
.edit,.drop{font-size:13px;padding:5px 9px;color:#666}
.clips{flex-basis:100%;padding:2px 0 8px 22px;display:flex;gap:6px;flex-wrap:wrap}
.clips button{font-size:13px;padding:4px 8px;font-variant-numeric:tabular-nums}
.here{outline:2px solid #4a7}
.unused .pick b{color:#888;font-weight:400}
</style>
<h1>对照画面确认角色</h1>
<p class="hint">时间相对音轨开头。按顺序到视频里看是谁在说，名字前后一致即可。<br>
这页不显示机器分组，也不该显示：看过机器的答案，标出来的就不再是独立真值。<br>
快捷键：回车保存，← → 上一条／跳过，空格重播，数字 1-9 选下面的角色名。</p>
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
<h2>角色名</h2>
<p class="hint">点名字给当前片段打标。点条数展开这个角色的全部片段，可跳过去或撤掉。
改名会改掉本轮这个名字下的所有片段。名字多时先在下面筛一下，数字键跟着筛完的顺序走。</p>
<p><input id="filter" placeholder="筛名字" autocomplete="off"></p>
<div id="known"></div>
<script>
const clips=__CLIPS__, special=__SPECIAL__, roster=__KNOWN__;
let names=__NAMES__, at=0, expanded=null;
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
 if(!list.length){box.textContent='还没有可用的角色名，先手动敲一个。';return;}
 list.forEach(([name,where],index)=>{
  const row=document.createElement('div');
  row.className=where.length?'row':'row unused';
  const key=document.createElement('span');
  key.className='key';key.textContent=index<9?index+1:'';
  row.appendChild(key);
  const pick=button(row,'',()=>assign(name),'pick');
  pick.replaceChildren(Object.assign(document.createElement('b'),{textContent:name}));
  if(where.length)button(row,`${where.length} 条`,()=>{
   expanded=expanded===name?null:name;renderRoster();
  },'count');
  else{
   const tag=document.createElement('span');
   tag.className='count';tag.textContent='未用';row.appendChild(tag);
  }
  if(where.length)button(row,'改名',()=>rename(name,row),'edit');
  if(expanded===name){
   const strip=document.createElement('div');strip.className='clips';
   where.forEach(i=>{
    const b=button(strip,clips[i].stamp,()=>{at=i;render();},i===at?'here':'');
    b.title=`${clips[i].seconds} 秒`;
   });
   button(strip,'撤掉这些标签',()=>{
    submit(n=>{
     const proposed={...n};where.forEach(i=>delete proposed[clips[i].id]);return proposed;
    }).then(()=>{expanded=null;render();});
   },'drop');
   row.appendChild(strip);
  }
  box.appendChild(row);
 });
}

function rename(old,row){
 const form=document.createElement('div');form.className='clips';
 const box=document.createElement('input');box.value=old;box.style.width='40%';
 const commit=()=>{
  const next=box.value.trim();
  if(!next||next===old){expanded=null;renderRoster();return;}
  submit(n=>{
   const proposed={...n};
   Object.keys(proposed).forEach(id=>{if(proposed[id]===old)proposed[id]=next;});
   return proposed;
  }).then(()=>{expanded=null;render();});
 };
 box.onkeydown=e=>{if(e.key==='Enter')commit();if(e.key==='Escape'){expanded=null;renderRoster();}};
 form.appendChild(box);
 button(form,'确定',commit);
 button(form,'取消',()=>{expanded=null;renderRoster();});
 row.appendChild(form);box.focus();box.select();
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
 renderRoster();
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
el('filter').oninput=()=>{expanded=null;renderRoster();};
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
