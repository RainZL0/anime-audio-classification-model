"""Name labeling page. It only shows the human task, never the machine grouping.

The page offers the existing character names as a name list, so you do not have to type each one
again. But it never shows any grouping, group number or candidate assignment: once a labeler sees
the machine's answer, the labels are no longer an independent ground truth. Renames, reassignments
and label deletions are all submitted as one whole, and the server still checks them with
`apply_names`. The page keeps no local incremental state.

Character names are laid out as small blocks, not full-width rows. When a whole episode is labeled
in one go there can be dozens of names, and one name per row would push the clips off the screen, so
you would have to keep scrolling to both hear and click. Expanded details all go in one shared
panel, not into the name's row, so opening one does not push the others away. Clips in the panel can
be dragged onto another name to change their assignment, because mistakes mostly show up when re-
checking after the whole episode is labeled, and locating each clip again would be too slow."""

PAGE_NAMES = r"""<!doctype html><meta charset="utf-8"><title>Character identity labeling</title>
<style>
body{font:16px/1.7 system-ui;max-width:900px;margin:24px auto;padding:0 20px;
background:#fafafa;color:#222}
button,input{font:inherit;padding:8px 12px;border:1px solid #ccc;border-radius:6px;
background:white;cursor:pointer}
button:hover{border-color:#888}
input{cursor:text}
audio{width:100%;margin:6px 0}
/* The picture shows at its original height, neither enlarged nor filling the space: the name
   blocks must share the screen with it, or you would have to scroll back and forth. */
#clip{width:auto;max-width:min(100%,520px);max-height:30vh;background:#000;
border-radius:8px;margin:6px 0;display:block}
#clip[hidden]{display:none}
h1{margin:0 0 4px;font-size:26px}h2{margin:20px 0 4px;font-size:18px}
.hint{color:#666;font-size:13px;line-height:1.6;margin:4px 0 10px}
#stamp{font-size:28px;font-variant-numeric:tabular-nums}
#status{color:#555;font-variant-numeric:tabular-nums;margin:2px 0}
#bar{height:5px;background:#e4e4e4;border-radius:3px;overflow:hidden;margin:8px 0}
#fill{height:100%;width:0;background:#4a7;transition:width .2s}
#name{width:min(420px,60%)}
#filter{width:min(220px,40%);padding:5px 9px;font-size:14px}
#add{padding:5px 9px;font-size:13px}
#special button{color:#666;font-size:13px;padding:5px 9px}
nav{margin:12px 0}

/* Names are laid out as small blocks across the row, so they all fit on one screen and you do
   not have to scroll clips out of view to click a name. */
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
.chip.mark{border-style:dashed;background:#fbfbfb}
.chip.mark .pick{color:#666}
.chip.over{border-color:#2b6b47;background:#dff0e6;box-shadow:0 0 0 2px #cfe6da}

#detail{display:none;margin-top:10px;padding:10px 12px;border:1px solid #e2e2e2;
border-radius:8px;background:white}
#detail.on{display:block}
#detail h3{margin:0 0 6px;font-size:15px}
#detail .line{display:flex;gap:5px;flex-wrap:wrap;align-items:center;margin:6px 0}
#detail .line b{font-size:13px;color:#666;font-weight:600;min-width:56px}
#detail button{font-size:13px;padding:4px 8px;font-variant-numeric:tabular-nums}
#detail .own{cursor:grab}
#detail .own:active{cursor:grabbing}
#detail .here{outline:2px solid #4a7}
</style>
<h1>Confirm characters against the picture</h1>
<p class="hint">Times are relative to the start of the audio track. Go through the clips in order,
watch the video to see who is speaking, and keep the name consistent before and after.<br>
This page does not show the machine grouping, and it should not: once you have seen the machine's
answer, your labels are no longer an independent ground truth.<br>
Shortcuts: Enter saves, ← → previous / skip, space replays, digits 1-9 pick one of the first nine
names below.<br>
With <code>--video</code>, the picture for this clip is shown above, with half a second of extra
time before and after, so you can see who is speaking.
The player below is the separated vocals, for reference only.</p>
<div id="bar"><div id="fill"></div></div>
<p id="status"></p>
<div id="stamp"></div>
<video id="clip" controls hidden></video>
<audio id="audio" controls></audio>
<p><input id="name" list="roster" placeholder="Character name, Enter to save" autocomplete="off">
<button id="submit">Save and continue</button><button id="drop">Clear this clip</button></p>
<datalist id="roster"></datalist>
<div id="special"></div>
<nav><button id="prev">Previous</button><button id="next">Skip</button>
<button id="tonew">Next unlabeled</button></nav>
<h2>Character names <input id="filter" placeholder="Filter names" autocomplete="off">
<button id="add">+ Create this name</button></h2>
<p class="hint">Click a name to label the current clip. Click the number on the right to open a
panel showing all clips under that name.
Clips in the panel can be dragged onto another name to change their assignment. If you made a
mistake, you do not need to go back and listen to each clip again.
Type a new name in the filter box and click "+ Create this name" to create it first, then you can
drag clips onto it.<br>
Listening to an old label is only to help you remember who this name is. The decision must still be
made from the picture, not by comparing voices by ear.</p>
<div id="known"></div>
<div id="detail"></div>
<audio id="ref" controls hidden></audio>
<script>
const clips=__CLIPS__, special=__SPECIAL__, roster=__KNOWN__, history=__HISTORY__;
const hasVideo=__VIDEO__;
let names=__NAMES__, at=0, opened=null;
/* extra holds names created on this page that are not used yet; hidden holds names hidden from
   the list. Both only live on this page: names that are actually used are already in the archive
   and come back next time the page opens, and unused ones are not worth saving to disk. */
let extra=[], hidden=[];
const el=id=>document.getElementById(id);
const total=clips.length;

function done(){return clips.filter(c=>names[c.id]).length;}
function firstBlank(from){
 for(let i=from;i<total;i++)if(!names[clips[i].id])return i;
 return total;
}
function clipsOf(value){
 const out=[];
 clips.forEach((c,i)=>{if(names[c.id]===value)out.push(i);});
 return out;
}
/* Fixed order: names from the name list (common ones first), then names created on this page,
   then new names typed in this round. How many clips this round labeled is only shown and does
   not affect the order, otherwise the number keys would keep moving under your fingers. */
function allNames(){
 const used=[];
 clips.forEach(c=>{
  const n=names[c.id];
  if(n&&!(n in special)&&!used.includes(n))used.push(n);
 });
 return [...new Set([...roster,...extra,...used])].filter(n=>!hidden.includes(n));
}
function rows(){
 const keep=el('filter').value.trim().toLowerCase();
 return allNames()
  .filter(n=>!keep||n.toLowerCase().includes(keep))
  .map(n=>[n,clipsOf(n)]);
}
/* Special labels are also laid out as small blocks, otherwise clips marked as 'more than one
   person' could never be found again for review. */
function markRows(){
 return Object.keys(special).map(v=>[v,clipsOf(v)]).filter(([,where])=>where.length);
}

function button(parent,label,fn,cls){
 const b=document.createElement('button');
 b.textContent=label;b.onclick=fn;if(cls)b.className=cls;
 parent.appendChild(b);return b;
}

function makeChip(box,value,label,where,index,mark){
 const past=history[value]||[];
 const chip=document.createElement('span');
 chip.className='chip'+(where.length?' used':'')+(opened===value?' here':'')+(mark?' mark':'');
 if(index!==null){
  const key=document.createElement('span');
  key.className='key';key.textContent=index+1;chip.appendChild(key);
 }
 button(chip,label,()=>assign(value),'pick');
 const badge=button(chip,`${where.length}·${past.length}`,()=>openName(value),'more');
 badge.title=`This round: ${where.length} clips, old labels: ${past.length}`;
 chip.ondragover=e=>{e.preventDefault();chip.classList.add('over');};
 chip.ondragleave=()=>chip.classList.remove('over');
 chip.ondrop=e=>{
  e.preventDefault();chip.classList.remove('over');
  const i=Number(e.dataTransfer.getData('text/plain'));
  if(Number.isInteger(i)&&i>=0&&i<total)reassign(i,value);
 };
 box.appendChild(chip);
}

function renderRoster(){
 const box=el('known');box.replaceChildren();
 const list=rows();
 el('roster').replaceChildren(...list.map(([n])=>{
  const o=document.createElement('option');o.value=n;return o;
 }));
 if(!list.length&&!markRows().length){
  box.textContent='No names yet. Type one above, or use "+ Create this name".';return;
 }
 list.forEach(([name,where],index)=>makeChip(box,name,name,where,index<9?index:null,false));
 markRows().forEach(([value,where])=>makeChip(box,value,special[value],where,null,true));
}

function openName(value){
 opened=opened===value?null:value;
 renderRoster();renderDetail();
}

function reassign(i,value){
 if(names[clips[i].id]===value)return;
 submit(n=>({...n,[clips[i].id]:value})).then(()=>render());
}

function renderDetail(){
 const box=el('detail');box.replaceChildren();
 box.className=opened?'on':'';
 if(!opened)return;
 const where=clipsOf(opened);
 const past=history[opened]||[];
 const head=document.createElement('h3');
 const shown=opened in special?special[opened]:opened;
 head.textContent=`${shown} · this round: ${where.length} clips · old labels: ${past.length}`;
 box.appendChild(head);

 const tools=document.createElement('div');tools.className='line';
 if(where.length&&!(opened in special))button(tools,'Rename',()=>rename(opened,tools));
 if(where.length)button(tools,`Remove these ${where.length} labels`,()=>{
  submit(n=>{
   const proposed={...n};where.forEach(i=>delete proposed[clips[i].id]);return proposed;
  }).then(()=>{opened=null;render();});
 });
 if(!where.length&&!(opened in special))button(tools,'Remove this name from the list',()=>{
  extra=extra.filter(n=>n!==opened);
  if(roster.includes(opened))hidden.push(opened);
  opened=null;renderRoster();renderDetail();
 });
 button(tools,'Close',()=>{opened=null;renderRoster();renderDetail();});
 box.appendChild(tools);

 if(where.length){
  const line=document.createElement('div');line.className='line';
  line.appendChild(Object.assign(document.createElement('b'),{textContent:'This round'}));
  where.forEach(i=>{
   const b=button(line,clips[i].stamp,()=>{at=i;render();},'own'+(i===at?' here':''));
   b.draggable=true;
   b.ondragstart=e=>{
    e.dataTransfer.setData('text/plain',String(i));
    e.dataTransfer.effectAllowed='move';
   };
   b.title=`${clips[i].seconds} seconds. Click to jump; drag onto another name to reassign.`;
  });
  box.appendChild(line);
 }
 if(past.length){
  const line=document.createElement('div');line.className='line';
  line.appendChild(Object.assign(document.createElement('b'),{textContent:'Old labels'}));
  past.forEach(entry=>{
   const b=button(line,`${entry.episode} ${entry.stamp}`,()=>audition(entry));
   b.title=`${entry.seconds} seconds. Click to listen. Old archive clip: cannot be reassigned.`;
  });
  box.appendChild(line);
 }
}

/* The picture is cut on demand. Cutting a clip takes a few hundred milliseconds, so the next
   clip is warmed up too, and it is ready by the time you move on. */
function showClip(c){
 const box=el('clip');
 box.hidden=false;
 if(!box.src.endsWith('/'+c.id+'.mp4')){
  box.src='video/'+c.id+'.mp4';
  box.play().catch(()=>{});
 }
 const next=clips[at+1];
 if(next)fetch('video/'+next.id+'.mp4',{method:'HEAD'}).catch(()=>{});
}

/* Old labels use a separate player, so they do not cover the clip being labeled. */
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
 button(line,'OK',commit);
 button(line,'Cancel',()=>renderDetail());
 box.focus();box.select();
}

function render(){
 const had=done();
 el('status').textContent=total
  ? `Clip ${Math.min(at+1,total)} / ${total} · labeled ${had} · unlabeled ${total-had}`
  : 'No clips in this round';
 el('fill').style.width=total?`${had/total*100}%`:'0';
 el('special').replaceChildren();
 if(at>=total){
  el('stamp').textContent='End of this round. You can go back and change any clip.';
  el('audio').removeAttribute('src');el('name').value='';
  el('clip').hidden=true;el('clip').removeAttribute('src');
 }else{
  const c=clips[at];
  el('stamp').textContent=`${c.stamp} · ${c.seconds} seconds`;
  if(!el('audio').src.endsWith('/'+c.id+'.wav')){
   el('audio').src=c.id+'.wav';
   // When there is a picture, the picture is the main source and the vocals are for reference only,
   // so do not play both at once.
   if(!hasVideo)el('audio').play().catch(()=>{});
  }
  if(hasVideo)showClip(c);
  el('name').value=names[c.id]||'';
  Object.entries(special).forEach(([v,label])=>button(el('special'),label,()=>assign(v)));
 }
 renderRoster();renderDetail();
}

/* Submissions are queued so no key press is lost: when your hand is faster than one round trip,
   the earlier press is saved first instead of being blocked by a busy flag. update receives the
   names as they are when its turn comes, so changing the same name several times in a row does
   not overwrite each other. */
let queue=Promise.resolve(true);
function submit(update){
 queue=queue.then(async()=>{
  const proposed=update(names);
  if(!proposed)return true;
  try{
   const r=await fetch('/save',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(proposed)});
   if(!r.ok)throw Error(r.statusText||'Save failed');
   names=proposed;return true;
  }catch(e){
   el('status').textContent=
    'Save failed. This clip was not changed, please try again.';
   return false;
  }
 });
 return queue;
}

/* Move forward first, then wait for the reply: the slow part is the network, not the decision.
   If saving fails, go back to that clip. It is never skipped silently. */
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
el('add').onclick=()=>{
 const value=el('filter').value.trim();
 if(!value){el('filter').focus();return;}
 hidden=hidden.filter(n=>n!==value);
 if(!allNames().includes(value))extra.push(value);
 el('filter').value='';opened=value;renderRoster();renderDetail();
};
document.addEventListener('keydown',e=>{
 if(e.target.tagName==='INPUT'||e.metaKey||e.ctrlKey||e.altKey)return;
 if(e.key==='ArrowLeft'){e.preventDefault();el('prev').click();}
 else if(e.key==='ArrowRight'){e.preventDefault();el('next').click();}
 else if(e.key===' '){
  e.preventDefault();
  const player=hasVideo&&!el('clip').hidden?el('clip'):el('audio');
  player.currentTime=0;player.play().catch(()=>{});
 }
 else if(e.key>='1'&&e.key<='9'){
  const row=rows()[Number(e.key)-1];
  if(row){e.preventDefault();assign(row[0]);}
 }
});
at=firstBlank(0);
render();
</script>"""
