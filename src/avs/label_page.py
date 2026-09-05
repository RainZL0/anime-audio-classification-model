"""姓名标注页面；只展示人工任务，不展示机器分组。"""

PAGE_NAMES = r"""<!doctype html><meta charset="utf-8"><title>角色身份标注</title>
<style>
body{font:16px/1.7 system-ui;max-width:760px;margin:40px auto;padding:0 24px;
background:#fafafa;color:#222}
button,input{font:inherit;padding:9px 13px;margin:5px;border:1px solid #ccc;
border-radius:6px;background:white}
audio{width:100%}#stamp{font-size:32px}#status{color:#555}input{width:65%}
</style>
<h1>对照画面确认角色</h1><p>时间相对音轨开头。按顺序到视频中查看是谁在说，名字前后一致即可。</p>
<p id="status"></p><div id="stamp"></div><audio id="audio" controls></audio>
<p><input id="name" placeholder="角色名"><button id="submit">保存并继续</button></p>
<div id="known"></div><div id="special"></div>
<button id="prev">上一条</button><button id="next">跳过</button>
<script>
const clips=__CLIPS__, special=__SPECIAL__;let names=__NAMES__;
let at=clips.findIndex(c=>!names[c.id]);if(at<0)at=clips.length;let busy=false;
const el=id=>document.getElementById(id);
function button(parent,label,fn){
 const b=document.createElement('button');
 b.textContent=label;b.onclick=fn;parent.appendChild(b);
}
function render(){
 el('status').textContent=`已标 ${Object.keys(names).length} / ${clips.length} 条`;
 el('known').replaceChildren();el('special').replaceChildren();
 if(at>=clips.length){el('stamp').textContent='本轮完成，可返回修改';el('audio').removeAttribute('src');return;}
 const c=clips[at];el('stamp').textContent=`${c.stamp} · ${c.seconds} 秒`;
 el('audio').src=c.id+'.wav';el('name').value=names[c.id]||'';
 [...new Set(Object.values(names))].filter(n=>!(n in special))
 .forEach(n=>button(el('known'),n,()=>save(n)));
 Object.entries(special).forEach(([v,label])=>button(el('special'),label,()=>save(v)));
}
async function save(value){
 value=value.trim();if(busy||at>=clips.length||!value)return;busy=true;
 const proposed={...names,[clips[at].id]:value};
 try{const r=await fetch('/save',{method:'POST',
 headers:{'Content-Type':'application/json'},body:JSON.stringify(proposed)});
 if(!r.ok)throw Error('保存失败');names=proposed;at++;render();}
 catch(e){el('status').textContent='保存失败，仍停留在本条，请重试。';}finally{busy=false;}
}
el('submit').onclick=()=>save(el('name').value);
el('name').onkeydown=e=>{if(e.key==='Enter')save(el('name').value);};
el('prev').onclick=()=>{if(!busy&&at>0){at--;render();}};
el('next').onclick=()=>{if(!busy&&at<clips.length){at++;render();}};
render();
</script>"""
