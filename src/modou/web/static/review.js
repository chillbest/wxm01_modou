function wireMainPaste(input){
 input.onpaste=event=>{
  event.preventDefault();
  const match=event.clipboardData?.getData('text/plain').match(/(?:^|[^0-9])([0-9]{6})(?![0-9])/);
  if(!match)return;
  input.setRangeText(match[1],input.selectionStart,input.selectionEnd,'end');
  input.dispatchEvent(new Event('input',{bubbles:true}));
  input.dispatchEvent(new Event('change',{bubbles:true}));
 };
}
function candidateForURL(candidates,url){
 const canonical=value=>{try{return new URL(value).href;}catch{return null;}};
 const target=canonical(url);if(!target)return null;
 const external=candidates.find(c=>c.outlink&&canonical(c.outlink)===target);if(external)return external;
 const match=target.match(/^https:\/\/(?:bgm\.tv|bangumi\.tv|chii\.in)\/subject\/(\d+)\/?$/);
 return match?candidates.find(c=>String(c.bangumi_id||c.id)===match[1]):null;
}
function validExternalURL(value){try{const u=new URL(value);return !/[\s\x00-\x1f\x7f\\]/.test(value)&&['http:','https:'].includes(u.protocol)&&!!u.hostname&&!u.username&&!u.password;}catch{return false;}}
// Shared presentation decisions, independent of the browser DOM.
function wireNotePreview(summary,area,tooltip,label='note'){
 const hide=()=>{tooltip.hidden=true;summary.removeAttribute('aria-describedby');};
 const update=()=>{const has=!!area.value.trim();summary.classList.toggle('web-note-filled',has);summary.setAttribute('aria-label',has?label+'，有内容':label+'，无内容');if(!has)hide();};
 const show=()=>{
  if(!area.value.trim())return;
  tooltip.textContent=area.value;tooltip.hidden=false;summary.setAttribute('aria-describedby',tooltip.id);
  const anchor=summary.getBoundingClientRect(),box=tooltip.getBoundingClientRect();
  tooltip.style.left=Math.max(12,Math.min(anchor.left,globalThis.innerWidth-box.width-12))+'px';
  const top=anchor.top-box.height-8;
  tooltip.style.top=Math.max(12,Math.min(top>=12?top:anchor.bottom+8,globalThis.innerHeight-box.height-12))+'px';
 };
 summary.addEventListener('mouseenter',show);summary.addEventListener('mouseleave',hide);
 summary.addEventListener('focus',show);summary.addEventListener('blur',hide);
 summary.addEventListener('click',hide);summary.addEventListener('keydown',e=>{if(e.key==='Escape')hide();});
 area.addEventListener('input',()=>{update();hide();});update();
}
function bindDraftInput(input,drafts,key,saved){
 input.value=drafts.has(key)?drafts.get(key):(saved||'');
 input.oninput=()=>drafts.set(key,input.value);
 return value=>{if(drafts.get(key)===value)drafts.delete(key);};
}
function normalizeMainInput(value){const parts=value.split('|').map(x=>x.trim());if(!value.trim())return '';if(!parts.every(x=>/^[0-9]+$/.test(x)&&BigInt(x)>0n))throw Error('main请填写正整数ID，多个用|分隔，不得有空项');return [...new Set(parts.map(x=>BigInt(x).toString()))].join('|');}
function mainSubjectURL(value){return /^[0-9]+$/.test(value)?'https://bgm.tv/subject/'+value:value;}
function hitStageSlots(row, final) {
 const stages=['alias','local','api','ds','gamefaqs'],hits=row.stage_hits||{};
 const matches=c=>final.gpc_id&&c.gpc_id?String(final.gpc_id)===String(c.gpc_id):final.outlink&&c.outlink?final.outlink===c.outlink:final.bangumi_id&&String(final.bangumi_id)===String(c.bangumi_id||c.id);
 const original=!row.manual_target&&Object.values(hits).some(matches);
 return stages.map(stage=>({stage,candidate:original?(hits[stage]||null):null}));
}
function fieldPresentation(column, editing, options, value, historicalRed=false) {
 const selected=options.find(([v])=>v===String(value??''))||options[0];
 const unknown=selected[1]==='？'||selected[1]==='?';
 return {dropdown:column===3||editing||unknown||historicalRed,label:selected[1],unknown};
}
function gamefaqsLabel(url) {
 if(!url.startsWith('https://gamefaqs.gamespot.com/')){try{const u=new URL(url);return u.host+u.pathname;}catch{return url;}}
 const slug=url.split('/').pop().replace(/^\d+-/,'');
 return slug.length>20?slug.slice(0,20)+'…':slug;
}
function sameTarget(left, right) {
 const identity=f=>(f.bangumi_id||f.id||f.outlink)?[String(f.bangumi_id||f.id||''),f.outlink||'']:(f.gpc_id?['gpc',String(f.gpc_id)]:null);
 return JSON.stringify(identity(left))===JSON.stringify(identity(right));
}
function candidateSelection(row,c,resolution={},typeResolution={}) {
 if(sameTarget(row.final,c))return {manual_target:true,final:!row.final.type&&typeResolution.type?{type:typeResolution.type}:{}};
 const changes={manual_target:true,final:{gpc_id:c.gpc_id||null,bangumi_id:(c.bangumi_id||c.id)?String(c.bangumi_id||c.id):null,outlink:c.outlink||null,name_zh:c.name_cn||c.name_zh||c.name,name_en:c.name_en||null,type:c.gpc_id&&c.type?c.type:(typeResolution.type||null),bangumi_main:c.bangumi_main||resolution.main_id||null,note:c.note||null,display_name:c.display_name||null}};
 if(sameTarget(row.parse_baseline?.final||{},c))for(const key of ['type','bangumi_main'])if(row.parse_baseline.final[key]!=null)changes.final[key]=row.parse_baseline.final[key];
 for(const key of ['type','bangumi_main','note','display_name'])if((row.manual_fields||[]).includes('final.'+key)&&(!Object.hasOwn(row.candidate_lookup?.applied_fields||{},key)||row.candidate_lookup.applied_fields[key]!==row.final[key]))changes.final[key]=row.final[key];
 return changes;
}
function selectionCounts(rows) {
 const imported=rows.filter(r=>r.imported||r.already_imported).length;
 return {selected:rows.filter(r=>!r.imported&&!r.already_imported&&r.selected).length,pending:rows.length-imported,imported,total:rows.length};
}
function rowHidden(row, onlyUnchecked, onlyUnimported) {
 const done=!!(row.imported||row.already_imported);
 return (!done&&onlyUnchecked&&!!row.selected)||(done&&onlyUnimported);
}
function storedTableLabel(proposal) {
 const names={game_alias:'别名表（game_alias）',game_product_config:'GPC表（Game Product Configuration）',m_low_record:'报价表（m_low_record）'};
 return (names[proposal.table]||proposal.table)+(proposal.operation||'新增/复用未记录');
}
function singleImportState(row,editing,busy,preview){
 const disabled=!!(busy||preview||editing||row.selected||row.imported||row.already_imported||
  !String(row.final?.name_en||'').trim()||(row.eligibility_errors||[]).length);
 return {disabled,highlight:!disabled};
}
function candidateYear(candidate){
 const date=String(candidate.date||'').match(/^(\d{4})(?:\D|$)/);if(date)return date[1];
 const info=candidate.infobox||[],value=Array.isArray(info)?info.filter(f=>f.key==='发行日期').map(f=>f.value||'').join(' '):(String(info).match(/^\|发行日期\s*=([^\r\n]*)/m)?.[1]||'');
 return String(value).trim().match(/(?:^|\D)(\d{4})(?=年|[-/.]|$)/)?.[1]||'';
}
function topmostVisibleOriginal(rects, top, bottom, width, rows=[]) {
 let chosen=-1;
 rects.forEach((r,i)=>{if(!rows[i]?.selected&&!rows[i]?.imported&&!rows[i]?.already_imported&&r&&r.top>=top&&r.top<bottom&&r.bottom>r.top&&r.right>0&&r.left<width&&(chosen<0||r.top<rects[chosen].top))chosen=i;});
 return chosen;
}
function centeredOriginalFits(center, occupied, bounds, gap=8) {
 return center.left>=bounds.left&&center.right<=bounds.right&&occupied.every(r=>
  center.right+gap<=r.left||center.left-gap>=r.right||center.bottom<=r.top||center.top>=r.bottom);
}
function originalFreeSpace(bounds, occupied) {
 const left=Math.max(bounds.left,...occupied.filter(r=>!r.rightAction).map(r=>r.right));
 const right=Math.min(bounds.right,...occupied.filter(r=>r.rightAction).map(r=>r.left));
 return {left,right,center:(left+right)/2};
}
(() => {
'use strict';
let batch=JSON.parse(document.querySelector('#web-batch').textContent),busy=false;
const entries=[...document.querySelectorAll('.entry')];
const status=document.createElement('p');status.className='web-status';status.setAttribute('role','status');document.querySelector('.sticky-header').prepend(status);
const show=message=>{status.textContent=message;};
const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
function askDisplayName(message,value){return new Promise(resolve=>{
 const dialog=el('dialog');dialog.className='web-display-dialog';
 const form=el('form'),label=el('label',message),input=el('input');input.value=value;input.setAttribute('aria-label',message);label.append(input);
 const actions=el('div'),submit=el('button','确认'),cancel=el('button','取消');submit.type='submit';cancel.type='button';actions.append(submit,cancel);form.append(label,actions);dialog.append(form);
 const finish=value=>{dialog.close();dialog.remove();resolve(value);};
 form.onsubmit=e=>{e.preventDefault();finish(input.value);};cancel.onclick=()=>finish(null);dialog.oncancel=e=>{e.preventDefault();finish(null);};document.body.append(dialog);dialog.showModal();input.focus();input.select();
});}
const noteTooltip=el('div');noteTooltip.id='web-note-tooltip';noteTooltip.className='web-note-tooltip';noteTooltip.setAttribute('role','tooltip');noteTooltip.hidden=true;document.body.append(noteTooltip);
for(const event of ['scroll','resize'])window.addEventListener(event,()=>{noteTooltip.hidden=true;},true);
const releaseYears=new Map();
function addCandidateYear(node,candidate,knownYear=''){
 if(knownYear)return;
 const sid=candidate.bangumi_id||candidate.id;if(!sid||!/^\d+$/.test(String(sid)))return;
 const year=candidateYear(candidate);
 if(year){node.prepend(year+' · ');return;}
 if(!releaseYears.has(String(sid)))releaseYears.set(String(sid),fetch('/api/preview/'+sid).then(r=>r.ok?r.json():null).then(data=>/^\d{4}$/.test(data?.year||'')?data.year:'').catch(()=>''));
 releaseYears.get(String(sid)).then(value=>{if(value&&node.isConnected)node.prepend(value+' · ');});
}
let originalFocusFrame=0;
function updateOriginalFocus(){
 const copies=entries.map(entry=>entry.querySelector('.web-original-center'));
 const originals=entries.map(entry=>entry.querySelector('.web-original-text'));
 const headers=entries.map(entry=>entry.querySelector('.original'));
 [...copies,...originals].forEach(node=>node?.classList.remove('web-original-focus'));
 const sticky=document.querySelector('.sticky-header').getBoundingClientRect();
 const top=Math.max(0,sticky.top<innerHeight?sticky.bottom:0);
 const rects=headers.map((header,i)=>header&&!entries[i].hidden&&header.getClientRects().length&&getComputedStyle(header).visibility==='visible'?header.getBoundingClientRect():null);
 const chosen=topmostVisibleOriginal(rects,top,innerHeight,innerWidth,batch.rows);
 if(chosen<0)return;
 fitCenteredOriginal(entries[chosen],false);
 const copy=copies[chosen],visible=copy&&copy.getClientRects().length&&getComputedStyle(copy).visibility==='visible';
 (visible?copy:originals[chosen])?.classList.add('web-original-focus');
}
function scheduleOriginalFocus(){if(!originalFocusFrame)originalFocusFrame=requestAnimationFrame(()=>{originalFocusFrame=0;updateOriginalFocus();});}
window.addEventListener('scroll',scheduleOriginalFocus,{passive:true});
window.addEventListener('resize',scheduleOriginalFocus);
function fitCenteredOriginal(entry,schedule=true){
 if(schedule)scheduleOriginalFocus();
 const header=entry.querySelector('.original'),copy=header?.querySelector('.web-original-center');if(!copy||entry.hidden)return;
 copy.style.visibility='hidden';
 const bounds=header.getBoundingClientRect();
 const occupied=[...header.children].filter(n=>n!==copy&&n.getClientRects().length).map(n=>({...n.getBoundingClientRect().toJSON(),rightAction:n.matches('.web-single,.web-receipt')}));
 const space=originalFreeSpace(bounds,occupied);
 copy.style.left=(space.center-bounds.left)+'px';
 copy.style.visibility=centeredOriginalFits(copy.getBoundingClientRect(),occupied,space)?'visible':'hidden';
}
const originalObserver=new ResizeObserver(changes=>{new Set(changes.map(c=>c.target.closest('.entry')).filter(Boolean)).forEach(fitCenteredOriginal);});
document.fonts?.ready.then(()=>entries.forEach(fitCenteredOriginal));
document.querySelector('.selection-controls').append(document.querySelector('#selection-status'));
async function post(path,payload){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Modou-Review':'1'},body:JSON.stringify(payload)});let data;try{data=await response.json();}catch{throw Error('服务响应异常，请检查日志');}if(!response.ok){const error=Error(typeof data.detail==='string'?data.detail:'请求失败，请检查字段');error.similarProducts=data.similar_products;throw error;}return data;}
let queue=Promise.resolve(),pending=0;
const inputDrafts=new Map();
const candidatePending=new Map();let candidateSequence=0;
function mutate(path,payload={}){pending++;busy=true;syncChecks();const task=queue.then(async()=>{const next=await post('/api/batches/'+batch.id+path,{...payload,revision:batch.revision});await adopt(next);return batch;});queue=task.catch(()=>{});return task.finally(()=>{pending--;busy=pending>0;syncChecks();});}
function syncChecks(){
 const summary=document.querySelector('.web-summary');if(summary)summary.textContent='出价日'+(batch.rows[0]?.quote.published_at||'待确认');
 entries.forEach((entry,i)=>{const row=batch.rows[i];entry.classList.toggle('web-blacklisted',!!row.blacklisted);const done=!!(row.imported||row.already_imported),check=entry.querySelector('.review-check');
  check.checked=!!(row.selected||done);entry.hidden=rowHidden(row,document.querySelector('#show-unchecked').getAttribute('aria-checked')==='true',document.querySelector('#show-unimported')?.getAttribute('aria-checked')==='true');
  check.disabled=busy||entry.dataset.editing==='true'||done||!String(row.final.name_en||'').trim()||(!row.selected&&row.eligibility_errors.length>0);check.title=done?'已入库':row.eligibility_errors.join('；');applyLock(entry,row);fitCenteredOriginal(entry);
  const single=entry.querySelector('.web-single');if(single){const state=singleImportState(row,entry.dataset.editing==='true',busy,batch.preview);single.disabled=state.disabled;single.classList.toggle('web-single-ready',state.highlight);single.title=row.eligibility_errors.join('；');}
 });
 document.querySelectorAll('.ai-group').forEach(group=>{group.hidden=!entries.slice(Number(group.dataset.start)-1,Number(group.dataset.end)).some(entry=>!entry.hidden);});
 const {selected,pending:unimported,imported,total}=selectionCounts(batch.rows);
 document.querySelector('#selection-status').textContent='已勾选'+selected+'/'+unimported+'条 · 已入库'+imported+'/'+total+'条';
 const commit=document.querySelector('#export-unchecked'),complete=batch.state==='ready'&&batch.rows.length>0&&imported===batch.rows.length;
 commit.textContent=complete?'全解析！全入库！':'入库ALL勾选';commit.classList.toggle('web-complete',complete);commit.disabled=!!(complete||busy||batch.preview||entries.some(e=>e.dataset.editing==='true')||!batch.rows.some(r=>r.selected&&!r.imported&&!r.already_imported));
 const aliasButton=document.querySelector('#alias-bulk-open');if(aliasButton)aliasButton.disabled=!!(busy||batch.preview||entries.some(e=>e.dataset.editing==='true'));
}
const lockDetails=new WeakMap();
function applyLock(entry,row){
 const locked=!!(row.selected||row.imported||row.already_imported),wasLocked=entry.classList.contains('web-locked');
 if(locked&&!wasLocked){lockDetails.set(entry,{c:entry.querySelector('.detail')?getComputedStyle(entry.querySelector('.detail')).display!=='none':false,d:getComputedStyle(entry.querySelector('.trace')).display!=='none'});hoverToken++;preview.hidden=true;}
 entry.classList.toggle('web-locked',locked);if(!row.imported&&!row.already_imported)entry.classList.toggle('web-imported-expanded',false);
 const scopes=[entry.querySelector('.children'),entry.querySelector('.web-actions'),entry.querySelector('.web-original-text')].filter(Boolean);
 scopes.forEach(scope=>{scope.inert=locked;scope.querySelectorAll('button,input,select,textarea').forEach(control=>{
  if(locked){if(!control.hasAttribute('data-before-lock'))control.dataset.beforeLock=String(control.disabled);control.disabled=true;}
  else if(control.hasAttribute('data-before-lock')){control.disabled=control.dataset.beforeLock==='true';delete control.dataset.beforeLock;}
 });});
 if(!locked&&wasLocked){const previous=lockDetails.get(entry);if(previous){for(const [key,visible] of Object.entries(previous)){entry.classList.toggle('web-show-'+key,visible);entry.classList.toggle('web-hide-'+key,!visible);}}}
 let state=entry.querySelector('.web-lock-state');if(!state){state=el('span');state.className='web-lock-state';entry.querySelector('.original').append(state);}state.textContent=row.already_imported?'【早已入库】':locked?(row.imported?'已入库 · 已锁定':'已勾选 · 已锁定'):'';
}
for(const selector of ['#toggle-c','#toggle-d','#show-details'])document.querySelector(selector).addEventListener('click',()=>{entries.filter(e=>!e.classList.contains('web-locked')).forEach(e=>e.classList.remove('web-show-c','web-hide-c','web-show-d','web-hide-d'));});
function select(options,value,onchange){if(!options.some(([v])=>v===String(value??'')))value=options[0][0];const control=el('select');options.forEach(([v,label])=>{const option=el('option',label);option.value=v;if((options===methods&&v==='?')||(options===platforms&&v==='')){option.disabled=true;option.hidden=true;}option.selected=(v===String(value??''));control.append(option);});control.onchange=()=>onchange(control.value);return control;}
const types=[['','？'],...['Base','rebase','Expansion','母子集','合集'].map(x=>[x,x])],regions=[['','？'],...['国行','港版','美版','欧版','韩版','日版','海外版'].map(x=>[x,x])],platforms=[['','？'],['PS5','PS5'],['PS4','PS4']],methods=[['?','？'],['直接购买','直接购买'],['福袋8折减80','福袋8折减80'],['积/v3','积/v3'],['凑-50','凑-50'],['积-50','积-50']];
function link(text,url){const a=el('a',text);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;}
async function reloadGPC(i){
 try{
  await queue;
  const response=await fetch('/api/batches/'+batch.id+'/rows/'+i+'/gpc');const preview=await response.json();if(!response.ok)throw new Error(preview.detail||'GPC加载失败');
  const row=batch.rows[i],changes=Object.entries(preview.product).filter(([k,v])=>String((k==='platform'?row.quote.platform:row.final[k])??'')!==String(v??''));
  const dialog=el('dialog');dialog.className='web-similar-dialog';dialog.append(el('p','重新加载GPC '+preview.product.gpc_id+'？将替换本条GPC资料及平台，其他报价字段保留。'));
  const table=el('table'),head=el('tr');['字段','当前草稿','数据库最新值'].forEach(x=>head.append(el('th',x)));table.append(head);
  changes.forEach(([k,v])=>{const tr=el('tr');[k,(k==='platform'?row.quote.platform:row.final[k])??'—',v??'—'].forEach(x=>tr.append(el('td',String(x))));table.append(tr);});
  dialog.append(changes.length?table:el('p','当前显示字段没有差异；确认后重新建立数据库资料基线。'));
  const confirmed=await new Promise(resolve=>{const done=v=>{dialog.close();dialog.remove();resolve(v);};dialog.append(button('确认重新加载',()=>done(true)),button('取消',()=>done(false)));dialog.oncancel=e=>{e.preventDefault();done(false);};document.body.append(dialog);dialog.showModal();});
  if(!confirmed)return;
  await mutate('/rows/'+i+'/reload-gpc',preview);inputDrafts.delete(i+':url');inputDrafts.delete(i+':main');render(i,entries[i].dataset.editing==='true');show('已加载数据库最新GPC资料，请核对后入库');
 }catch(e){show('重新加载失败：'+e.message);}
}
async function quickSave(i,changes){try{await mutate('/rows/'+i,changes);if(pending===0)render(i,entries[i].dataset.editing==='true');show('已即时保存');}catch(e){show('保存失败：'+e.message);}}
function render(i,editing=false){
 noteTooltip.hidden=true;
 const entry=entries[i],row=candidatePending.get(i)?.row||batch.rows[i],f=structuredClone(row.final),q=structuredClone(row.quote),cells=[...entry.querySelectorAll('.b-row td')];
 entry.dataset.candidateLookup=JSON.stringify(row.candidate_lookup||{});
 entry.dataset.editing=String(editing);cells[0].textContent=row.raw_name;cells.slice(1).forEach(c=>{c.replaceChildren();c.classList.remove('web-unknown');});
 entry.querySelector('.web-single')?.remove();entry.querySelector('.web-receipt')?.remove();
 let actions=entry.querySelector('.web-actions');if(!actions){actions=el('span');actions.className='web-actions';entry.querySelector('.original').append(' ',actions);}actions.replaceChildren();
 const button=(label,fn)=>{const b=el('button',label);b.type='button';b.onclick=async()=>{try{await fn();}catch(e){show(e.message);}};return b;};
 if(row.blacklisted){entry.dataset.editing='false';entry.classList.add('web-blacklisted');syncChecks();return;}
 if(editing){const deny=button('🚫',async()=>{
  await queue;const current=batch.rows[i],text=current.raw_name;
  if(!await messageDialog('确定要把【'+text+'】要加入黑名单吗？',true))return;
  await mutate('/rows/'+i+'/blacklist',{text,row_revision:current.revision});
  entries.forEach((_,j)=>{if(batch.rows[j].blacklisted)render(j);});show('已加入黑名单');
 });deny.className='web-blacklist-button';deny.setAttribute('aria-label','加入黑名单');deny.disabled=!!(busy||row.selected);cells[0].append(' ',deny);}
 if(row.imported||row.already_imported){
  const receipt=button(row.already_imported?'早已入库':'已入库',()=>{entry.classList.toggle('web-imported-expanded');});receipt.className='web-receipt';receipt.setAttribute('aria-label','已入库：展开或收拢条目');entry.querySelector('.original').append(receipt);
 }else{
  actions.append(button(editing?'结束edit':'edit',async()=>{await queue;render(i,!editing);}));
  const single=button('单条入库',()=>submitRows(i));single.className='web-single';entry.querySelector('.original').append(single);
 }
 const hitBox=el('div');hitBox.className='web-hit';cells[1].append(hitBox);
 if(candidatePending.has(i)||row.candidate_lookup?.status==='pending'){const saving=el('span',candidatePending.has(i)?'候选保存中…':'候选已保存，正在补查main…');saving.className='web-candidate-status';cells[1].append(saving);}
 const hitContent=el('div');hitContent.className='web-hit-content';hitBox.append(hitContent);

 cells[2].style.color='';
 const hasTarget=!!(f.gpc_id||f.bangumi_id||f.outlink);
 if(hasTarget||editing){
  const sparkle=button('✨',async()=>{const value=await askDisplayName('添加或修改显示名',f.display_name||'');if(value===null)return;return quickSave(i,{final:{display_name:value||null}});});sparkle.className='web-sparkle';sparkle.disabled=row.imported;hitBox.append(sparkle);
  // Stage slots are rendered below; manual targets remain explicitly separate.
  const note=el('details');note.className='web-note';const summary=el('summary','note');note.append(summary);const area=el('textarea');area.value=f.note||'';area.disabled=row.imported;area.setAttribute('aria-label','GPC备注');area.onchange=()=>{quickSave(i,{final:{note:area.value||null}});};wireNotePreview(summary,area,noteTooltip);note.append(area);hitBox.append(note);
  if(f.gpc_id)hitBox.append(button('重新加载此GPC',()=>reloadGPC(i)));
  if(editing&&hasTarget)hitBox.append(button('删除命中',()=>quickSave(i,{final:Object.fromEntries(Object.keys(f).map(k=>[k,null])),manual_target:true})));
 }
 function candidateBadge(candidate){
  const badge=el('code');badge.className='matched-gold';const name=candidate.name_cn||candidate.name_zh||candidate.name||'名称待确认';
  const sid=candidate.bangumi_id||candidate.id;
  const target=candidate.outlink?link(gamefaqsLabel(candidate.outlink),candidate.outlink):sid?link(name+'（'+sid+'）','https://bgm.tv/subject/'+sid):el('span',name);badge.append(target);
  const metadata=[candidate,...(row.candidates||[]),...Object.values(row.stage_hits||{})].find(c=>String(c.bangumi_id||c.id)===String(sid)&&candidateYear(c))||candidate;
  addCandidateYear(target,metadata);return badge;
 }
 const slots=hitStageSlots(row,f);
 if(!row.manual_target)slots.forEach((slot,index)=>{if(index){const separator=el('span',' / ');separator.className='hit-muted';hitContent.append(separator);}if(slot.candidate)hitContent.append(candidateBadge(slot.candidate));else{const empty=el('span','-');empty.className='hit-muted';hitContent.append(empty);}});
 if(hasTarget&&(row.manual_target||!slots.some(slot=>slot.candidate))){const manual=el('span',' 人工：');manual.className='web-manual-target';manual.append(candidateBadge(f));hitContent.append(manual);}
 const display=el('div');display.className='web-display';hitContent.append(display);
 function displayName(){display.replaceChildren();if(f.display_name){const input=el('input');input.value=f.display_name;input.disabled=row.imported;input.setAttribute('aria-label','display_name');input.onchange=()=>{quickSave(i,{final:{display_name:input.value||null}});};display.append('（',input,'）');}}displayName();
 const wrapper=()=>{const w=el('div');w.className='web-editor';return w;};
 if(editing){
  const w=wrapper(),url=el('input');url.placeholder='粘贴产品HTTP/HTTPS URL';url.setAttribute('aria-label','命中URL');const clearURLDraft=bindDraftInput(url,inputDrafts,i+':url',f.outlink|| (f.bangumi_id?'https://bgm.tv/subject/'+f.bangumi_id:''));
  if(row.manual_gamefaqs){const english=el('input');english.value=f.name_en||'';english.placeholder='手动填写英文名';english.setAttribute('aria-label','英文名');english.onchange=()=>quickSave(i,{final:{name_en:english.value.trim()||null}});w.append(english);}
  let requestId=0;
  url.onpaste=()=>setTimeout(()=>url.dispatchEvent(new Event('change')),0);
  url.onchange=async()=>{if(url.disabled||!url.value.trim())return;const current=++requestId,submittedURL=url.value;inputDrafts.set(i+':url',submittedURL);if(!validExternalURL(submittedURL.trim())){show('外链必须是有效的HTTP/HTTPS URL，输入已保留');return;}let displayName=null;if(!/^https:\/\/(?:bgm\.tv|bangumi\.tv|chii\.in)\/subject\/[0-9]+\/?$/.test(submittedURL.trim())){displayName=await askDisplayName('请输入display name',batch.rows[i].final.display_name||batch.rows[i].raw_name||'');if(displayName===null||!displayName.trim()){show('未填写display name，产品链接未保存');return;}displayName=displayName.trim();}url.disabled=true;show(displayName?'正在保存产品链接…':'正在解析产品URL及英文名…');try{await queue;const latest=batch.rows[i];await mutate('/rows/'+i+'/candidate',{url:submittedURL.trim(),display_name:displayName,row_revision:latest.revision,lookup_token:latest.candidate_lookup?.token,lookup_status:latest.candidate_lookup?.status});if(current!==requestId)return;clearURLDraft(submittedURL);render(i,true);show(displayName?'产品链接及显示名已保存，其他字段请手动填写':batch.rows[i].final.name_en?'链接和英文名已保存；main后台补查':'链接已保存；资料未提供可确认的英文名');}catch(e){show('链接未保存：'+e.message);}finally{url.disabled=false;}};w.append(url);cells[1].append(w);
 }
 if(row.main_explicit_null&&f.bangumi_main==null){cells[2].append(el('span','NULL'));}else if(f.bangumi_main){f.bangumi_main.split('|').forEach((id,index)=>{if(index)cells[2].append(' | ');cells[2].append(id===f.bangumi_id?el('span','（'+id+'）'):link('（'+id+'）','https://bgm.tv/subject/'+id));});if(f.bangumi_main===f.bangumi_id)cells[2].style.color='#64748B';}else{cells[2].append('？');cells[2].classList.add('web-unknown');}cells[2].style.background='';
 if(editing){const w=wrapper(),input=el('input');input.placeholder='main数字ID，多个用|分隔，或Bangumi URL；空格表示NULL';input.setAttribute('aria-label','main URL');const clearMainDraft=bindDraftInput(input,inputDrafts,i+':main',row.main_explicit_null?' ':f.bangumi_main);if(row.manual_gamefaqs){input.placeholder='main数字ID，多个用|分隔';}wireMainPaste(input);input.onchange=async()=>{const submittedMain=input.value;inputDrafts.set(i+':main',submittedMain);if(submittedMain.length>0&&!submittedMain.trim()){await quickSave(i,{final:{bangumi_main:submittedMain}});if(batch.rows[i].main_explicit_null){clearMainDraft(submittedMain);render(i,true);}return;}if(row.manual_gamefaqs||submittedMain.includes('|')){let value;try{value=normalizeMainInput(submittedMain);}catch(e){show(e.message);return;}await quickSave(i,{final:{bangumi_main:value||null}});if(batch.rows[i].final.bangumi_main===(value||null)){clearMainDraft(submittedMain);render(i,true);}return;}if(!input.value.trim())return;show('正在解析main…');try{const r=await post('/api/resolve',{url:mainSubjectURL(submittedMain.trim()),kind:'main'});await quickSave(i,{final:{bangumi_main:r.main_id},manual_resolution:r});if(batch.rows[i].final.bangumi_main===r.main_id){clearMainDraft(submittedMain);render(i,true);}}catch(e){show('main未保存，输入已保留：'+e.message);}};w.append(input,button('删除main',async()=>{await quickSave(i,{final:{bangumi_main:null}});if(!batch.rows[i].final.bangumi_main){inputDrafts.delete(i+':main');render(i,true);}}));cells[2].append(w);}
 const specs=[[3,types,f.type,v=>f.type=v||null],[4,platforms,q.platform,v=>{q.platform=v||null;if(f.gpc_id&&v!==row.quote.platform)f.gpc_id=null;}],[5,regions,q.region,v=>q.region=v||null],[7,methods,q.lowprice_method??'?',v=>q.lowprice_method=v==='?'?null:v]];
 specs.forEach(([column,options,value,change])=>{const view=fieldPresentation(column,editing,options,value,(row.red_columns||[]).includes(column));cells[column].classList.toggle('web-unknown',view.unknown||(row.red_columns||[]).includes(column));if(!view.dropdown){cells[column].append(el('span',view.label));return;}const w=wrapper(),control=select(options,value,v=>{change(v);const key={3:'type',4:'platform',5:'region',7:'lowprice_method'}[column];quickSave(i,column===3?{final:{[key]:f[key]}}:{quote:{[key]:q[key]}});if(fieldPresentation(column,true,options,v).unknown)cells[column].classList.add('web-unknown');});control.disabled=row.imported||row.alias_bound||(!editing&&!view.unknown&&!(row.red_columns||[]).includes(column));if(column===3){control.classList.toggle('type-unknown',view.unknown);const candidates=new Set((row.type_resolution?.candidates||[]).map(c=>c.type));[...control.options].forEach(option=>{if(candidates.has(option.value)){option.className='type-candidate';option.textContent=option.value+'（备选）';}});control.title=row.type_resolution?.reason||'';}control.setAttribute('aria-label',['','','','type','平台','地区','','优惠方式'][column]);w.append(control);cells[column].append(w);});
 if(editing&&!row.alias_bound){const input=el('input');input.value=q.lowprice_cny??'';input.inputMode='decimal';input.setAttribute('aria-label','价格');input.onchange=()=>{q.lowprice_cny=input.value;quickSave(i,{quote:{lowprice_cny:input.value}});};const w=wrapper();w.append(el('span','￥'),input);cells[6].append(w);}else cells[6].textContent=q.lowprice_cny==null||q.lowprice_cny===''?'？':'￥'+q.lowprice_cny;
 let errors=entry.querySelector('.web-errors');if(!errors){errors=el('p');errors.className='web-errors web-status';entry.append(errors);}errors.textContent='';
 const errorColumns={'命中目标待确认':1,'游戏名称待确认':1,'main待确认':2,'type待确认':3,'平台待确认':4,'地区待确认':5,'价格无效':6,'优惠方式待确认':7};
 (row.red_columns||[]).forEach(n=>cells[n]?.classList.add('web-unknown'));
 row.eligibility_errors.forEach(e=>{if(errorColumns[e])cells[errorColumns[e]].classList.add('web-unknown');});
 const fields=[[],['final.gpc_id','final.bangumi_id','final.outlink','final.name_zh','final.note','final.display_name'],['final.bangumi_main'],['final.type'],['quote.platform'],['quote.region'],['quote.lowprice_cny'],['quote.lowprice_method']];
 cells.forEach((c,n)=>c.classList.toggle('web-manual',fields[n].some(k=>(row.manual_fields||[]).includes(k))));
 wireCandidates(i,editing);renderProposals(i);wireReparse(i);originalObserver.observe(actions);originalObserver.observe(entry);syncChecks();
}
async function applyResolved(i,row,result){
 const changes=candidateSelection(row,result.candidate,result.main_resolution,result.type_resolution);
 if(result.candidate.outlink){
  const name=await askDisplayName('已解析为外链，请输入display name',row.final.display_name||'');
  if(name===null||!name.trim())return false;
  changes.final.display_name=name.trim();changes.final.name_zh=name.trim();
 }
 await quickSave(i,{...changes,manual_resolution:result});return true;
}
function confirmSimilar(conflicts){return new Promise(resolve=>{
 const dialog=el('dialog');dialog.className='web-similar-dialog';dialog.append(el('p','game_product_config表内已经存在相似数据，是否还要插入。'));
 const table=el('table'),head=el('tr');['GPC ID','名称','Bangumi ID','平台','外链'].forEach(t=>head.append(el('th',t)));table.append(head);
 conflicts.forEach(c=>c.existing.forEach(r=>{const tr=el('tr');['gpc_id','name_zh','bangumi_id','platform','outlink'].forEach(k=>{const td=el('td');td.append(k==='outlink'&&r[k]?link(r[k],r[k]):el('span',r[k]??'—'));tr.append(td);});table.append(tr);}));dialog.append(table);
 function finish(value){dialog.close();dialog.remove();resolve(value);}
 for(const [label,value] of [['继续插入',true],['取消',false]]){const b=el('button',label);b.onclick=()=>finish(value);dialog.append(b);}
 dialog.oncancel=e=>{e.preventDefault();finish(false);};document.body.append(dialog);dialog.showModal();
});}
function confirmRestore(){return new Promise(resolve=>{const dialog=el('dialog');dialog.append(el('p','恢复本条目解析内容？'));for(const [label,value] of [['是',true],['否',false]]){const b=el('button',label);b.onclick=()=>{dialog.close();dialog.remove();resolve(value);};dialog.append(b);}dialog.oncancel=e=>{e.preventDefault();dialog.close();dialog.remove();resolve(false);};document.body.append(dialog);dialog.showModal();});}
function wireCandidates(i,editing){
 const entry=entries[i], candidates=[...(batch.rows[i].candidates||[]),...Object.values(batch.rows[i].stage_hits||{}),...(batch.rows[i].stage_trace||[]).flatMap(t=>t.candidates||[])];
 entry.querySelectorAll('a[href^="https://gamefaqs.gamespot.com/"]').forEach(a=>{a.textContent=gamefaqsLabel(a.href);});
 entry.querySelectorAll('.candidate-code').forEach(badge=>{
  const a=badge.querySelector('a');if(!a)return;
  const candidate=candidateForURL(candidates,a.href);
  const sid=candidate?.bangumi_id||candidate?.id||null;
  if(!candidate)return;
  let name=badge.querySelector('.candidate-pick');
  if(!name){const year=candidateYear(candidate);name=el('button',candidate.name_cn||candidate.name_zh||candidate.name||sid);name.className='candidate-pick';badge.replaceChildren(year?year+' · ':'',name,'（',link(sid||gamefaqsLabel(a.href),a.href),'）');addCandidateYear(badge,candidate,year);}
  name.disabled=!editing||batch.rows[i].imported;
  name.onclick=()=>pickKnownCandidate(i,candidate);
 });
}
async function pickKnownCandidate(i,candidate){
 const original=candidatePending.get(i)?.row||batch.rows[i];
 let displayName=null;
 if(candidate.outlink){displayName=await askDisplayName('已解析为外链，请输入display name',original.final.display_name||'');if(displayName===null||!displayName.trim()){show('未填写display name，产品链接未保存');return;}displayName=displayName.trim();}
 const changes=candidateSelection(original,candidate),optimistic=structuredClone(original),sequence=++candidateSequence;
 Object.assign(optimistic.final,changes.final);optimistic.manual_target=true;
 if(displayName)Object.assign(optimistic.final,{name_zh:displayName,display_name:displayName});
 candidatePending.set(i,{row:optimistic,sequence});render(i,true);show('候选已切换，正在保存…');
 pending++;busy=true;syncChecks();
 const task=queue.then(async()=>{
  const row=batch.rows[i];
  const saved=await post('/api/batches/'+batch.id+'/rows/'+i+'/candidate',{
   revision:batch.revision,row_revision:row.revision,lookup_token:row.candidate_lookup?.token,
   lookup_status:row.candidate_lookup?.status,subject_id:candidate.bangumi_id||candidate.id||null,
   outlink:candidate.outlink||null,display_name:displayName});
  await adopt(saved);
  if(candidatePending.get(i)?.sequence===sequence){candidatePending.delete(i);render(i,true);show('候选已保存；main在后台补查');}
 }).catch(error=>{if(candidatePending.get(i)?.sequence===sequence){candidatePending.delete(i);render(i,true);show('候选保存失败：'+error.message);}}).finally(()=>{pending--;busy=pending>0;syncChecks();});
 queue=task;return task;
}
function renderProposals(i){
 const entry=entries[i],trace=entry.querySelector('.trace');let d=entry.querySelector('.web-d');
 if(!d){d=el('div');d.className='web-d';trace.before(d);d.append(trace);}
 d.querySelector('.web-proposals')?.remove();const proposals=batch.rows[i].proposed_inserts||[];d.classList.toggle('web-d-dual',proposals.length>0);
 if(!proposals.length)return;const panel=el('div');panel.className='web-proposals';
 const stored=!!proposals[0].stored;panel.dataset.stored=String(stored);panel.append(el('strong',stored?'已增：':'拟增：'));
 const ordered=[...proposals].sort((a,b)=>['game_alias','game_product_config','m_low_record'].indexOf(a.table)-['game_alias','game_product_config','m_low_record'].indexOf(b.table));
 ordered.forEach(proposal=>{
  const row=batch.rows[i],stored=!!proposal.stored,block=el('section');
  block.dataset.table=proposal.table;if(stored)block.append(el('small',storedTableLabel(proposal)));
  const scroll=el('div');scroll.className='web-proposal-scroll';const table=el('table'),head=el('tr'),data=el('tr');
  Object.entries(proposal.values).forEach(([key,value])=>{
   if(!stored&&proposal.table==='game_alias'&&key==='gpc_id')return;
   if((stored||['note','display_name','outlink'].includes(key))&&(value===null||value===undefined||value===''))return;
   head.append(el('th',key));const td=el('td');
   if(!stored&&proposal.table==='game_product_config'&&key==='bangumi_id')td.classList.toggle('web-manual',(row.manual_fields||[]).includes('final.bangumi_id')||!!row.final.outlink);
   if(!stored&&proposal.table==='game_product_config'&&key==='name_en'){
    const unknown=!value,red=unknown||row.name_en_unknown;td.classList.toggle('web-unknown',!!red);td.classList.toggle('web-manual',(row.manual_fields||[]).includes('final.name_en'));
    if(entries[i].dataset.editing==='true'&&!row.alias_bound){
     const input=el('input');input.value=value||'';input.setAttribute('aria-label','name_en');input.onchange=()=>quickSave(i,{final:{name_en:input.value.trim()||null}});td.append(input);
    }else td.append(el('span',unknown?'？':String(value)));
   }else td.append(el('span',value===null||value===undefined?'':key==='type'&&!value?'？':String(value)));
   if(key==='type'&&!stored&&!value)td.textContent='？';
   data.append(td);
  });
  table.append(head,data);scroll.append(table);block.append(scroll);panel.append(block);
 });d.append(panel);
}
function wireReparse(i){
 const entry=entries[i];entry.querySelector('.web-d-actions')?.remove();if(batch.rows[i].imported||batch.rows[i].already_imported)return;
 const actions=el('div');actions.className='web-d-actions';const restore=el('button','Restore'),reparse=el('button','重新解析');restore.className='web-restore';reparse.className='web-reparse';actions.append(reparse,restore);entry.querySelector('.web-d').append(actions);
 restore.onclick=async()=>{if(!await confirmRestore())return;try{await mutate('/rows/'+i+'/restore');await replaceEntry(i);}catch(e){await messageDialog(e.message);}};
 reparse.onclick=async()=>{const overlay=el('div');overlay.className='web-wait';overlay.setAttribute('role','status');overlay.append(el('span','正在重新解析…'));document.body.append(overlay);try{await mutate('/rows/'+i+'/reparse');await replaceEntry(i);}catch(e){await messageDialog('重新解析失败：'+e.message);}finally{overlay.remove();}};
}
async function replaceEntry(i){
 const response=await fetch('/api/batches/'+batch.id+'/updates?after='+i);if(!response.ok)throw Error('条目刷新失败');const data=await response.json(),doc=new DOMParser().parseFromString(data.html,'text/html'),fresh=doc.querySelector('.entry');batch=data.batch;entries[i].replaceWith(fresh);entries[i]=fresh;initEntry(fresh,i);syncChecks();
}
function messageDialog(message,confirm=false){return new Promise(resolve=>{const dialog=el('dialog');dialog.className='web-message-dialog';dialog.append(el('p',message));function finish(value){dialog.close();dialog.remove();resolve(value);}for(const [label,value] of (confirm?[['是',true],['否',false]]:[['确定',true]])){const b=el('button',label);b.onclick=()=>finish(value);dialog.append(b);}dialog.oncancel=e=>{e.preventDefault();finish(false);};document.body.append(dialog);dialog.showModal();});}
async function submitRows(index=null){
 await queue;if(busy)return;
 if(index===null){const count=batch.rows.filter(r=>r.selected&&!r.imported&&!r.already_imported).length;if(!count||!await messageDialog('确认入库'+count+'条数据吗？',true))return;}
 let confirmations=[];
 try{for(;;){try{await mutate(index===null?'/commit':'/rows/'+index+'/commit',{similar_confirmations:confirmations});break;}catch(e){if(!e.similarProducts)throw e;if(!await confirmSimilar(e.similarProducts))return;confirmations=e.similarProducts.map(c=>c.token);}}
 entries.forEach((_,i)=>render(i,entries[i].dataset.editing==='true'));show('');
 }catch(e){await messageDialog(e.message);}finally{syncChecks();}
}
async function openAliasBulk(){
 await queue;if(busy||document.querySelector('dialog[open]'))return;
 const dialog=el('dialog');dialog.className='web-alias-dialog';dialog.setAttribute('aria-labelledby','web-alias-title');
 const header=el('div');header.className='web-alias-header';const title=el('h2','一键入库绿&全');title.id='web-alias-title';
 const close=el('button','×');close.type='button';close.className='web-alias-close';close.setAttribute('aria-label','取消批量入库');header.append(title,close);
 const message=el('p','正在读取符合条件的条目…');message.setAttribute('role','status');
 const scroll=el('div');scroll.className='web-alias-scroll';const table=el('table');scroll.append(table);
 const footer=el('div');footer.className='web-alias-footer';const submit=el('button','一键入库');submit.type='button';submit.disabled=true;footer.append(submit);
 const tooltip=el('div');tooltip.id='web-alias-tooltip';tooltip.className='web-note-tooltip';tooltip.hidden=true;tooltip.setAttribute('role','tooltip');
 dialog.append(header,message,scroll,footer,tooltip);document.body.append(dialog);
 let snapshot=null,submitting=false;
 const finish=()=>{if(submitting)return;tooltip.hidden=true;dialog.close();dialog.remove();};
 close.onclick=finish;dialog.oncancel=e=>{e.preventDefault();finish();};
 scroll.addEventListener('scroll',()=>{tooltip.hidden=true;},true);dialog.showModal();
 try{
  const response=await fetch('/api/batches/'+batch.id+'/alias-preview');const data=await response.json();
  if(!response.ok)throw Error(data.detail||'预览读取失败');if(!dialog.isConnected)return;snapshot=data;
  message.textContent=data.rows.length?'共'+data.rows.length+'条，确认后全部入库':'暂无命中别名库且资料齐全的未入库条目';
  const thead=el('thead'),head=el('tr');for(const label of ['解析原名','命中','英文名','main','type','平台','地区','价格','优惠方式'])head.append(el('th',label));thead.append(head);table.append(thead);
  const body=el('tbody');table.append(body);
  data.rows.forEach(item=>{
   const row=item.row,f=row.final,q=row.quote,tr=el('tr');tr.append(el('td',row.raw_name));
   const hit=el('td'),content=el('div');content.className='web-alias-hit';hit.append(content);
   if(f.display_name){const icon=el('button','✨');icon.type='button';icon.className='web-sparkle';wireNotePreview(icon,{value:f.display_name,addEventListener:()=>{}},tooltip,'显示名');content.append(icon);}
   const sid=f.bangumi_id,metadata=[row.stage_hits?.alias,...(row.candidates||[]),...Object.values(row.stage_hits||{})].filter(Boolean).find(c=>String(c.bangumi_id||c.id)===String(sid)&&candidateYear(c));
   const name=f.name_zh||row.raw_name,target=link(name+(sid?'（'+sid+'）':''),f.outlink||'https://bgm.tv/subject/'+sid);if(sid)addCandidateYear(target,metadata||f);content.append(target);
   const note=el('details');note.className='web-note';const summary=el('summary','note'),area=el('textarea');area.value=f.note||'';area.readOnly=true;area.setAttribute('aria-label','备注内容');wireNotePreview(summary,area,tooltip);note.append(summary,area);content.append(note);tr.append(hit);
   for(const value of [f.name_en,row.main_explicit_null&&f.bangumi_main==null?'NULL':f.bangumi_main,f.type,q.platform,q.region,'￥'+q.lowprice_cny,q.lowprice_method])tr.append(el('td',value??''));
   body.append(tr);
  });submit.disabled=!data.rows.length;
 }catch(e){if(dialog.isConnected)message.textContent=e.message;}
 submit.onclick=async()=>{
  if(submitting||!snapshot?.rows.length)return;await queue;if(busy)return;
  submitting=true;submit.disabled=true;close.disabled=true;pending++;busy=true;syncChecks();tooltip.hidden=true;message.textContent='正在入库'+snapshot.rows.length+'条…';
  try{
   const next=await post('/api/batches/'+batch.id+'/alias-commit',{revision:snapshot.revision,rows:snapshot.rows.map(({index,token})=>({index,token}))});
   await adopt(next);entries.forEach((_,i)=>render(i,entries[i].dataset.editing==='true'));submitting=false;finish();show('已完成一键入库');
  }catch(e){message.textContent=e.message.includes('预览')?e.message:e.message+'；请关闭浮窗后重新打开预览。';}
  finally{submitting=false;close.disabled=false;pending--;busy=pending>0;syncChecks();}
 };
}
const preview=el('div');preview.className='web-preview';preview.hidden=true;document.body.append(preview);let hoverToken=0;const previewCache=new Map();
document.addEventListener('mouseover',async e=>{if(e.target.closest('.web-locked'))return;const a=e.target.closest('a')||e.target.closest('.candidate-code')?.querySelector('a');const match=a?.href.match(/^https:\/\/(?:bgm\.tv|bangumi\.tv|chii\.in)\/subject\/(\d+)/);if(!match)return;const token=++hoverToken;preview.replaceChildren(el('span','正在加载…'));preview.hidden=false;preview.style.left=Math.min(e.clientX+12,window.innerWidth-250)+'px';preview.style.top=Math.min(e.clientY+12,window.innerHeight-330)+'px';try{let data=previewCache.get(match[1]);if(!data){const response=await fetch('/api/preview/'+match[1]);if(!response.ok)throw Error();data=await response.json();previewCache.set(match[1],data);}if(token!==hoverToken)return;preview.replaceChildren();if(data.image&&/^https:\/\//.test(data.image)){const img=el('img');img.src=data.image;img.alt='封面';preview.append(img);}preview.append(el('div',data.name));if(data.platform)preview.append(el('div',data.platform));}catch{if(token===hoverToken)preview.textContent='预览加载失败';}});
document.addEventListener('mouseout',e=>{if(e.target.closest('a')||e.target.closest('.candidate-code')){hoverToken++;preview.hidden=true;}});
function initEntry(entry,i){const group=entry.querySelector('.ai-group');if(group){document.querySelectorAll('.ai-group').forEach(g=>{if(g!==group&&g.dataset.group===group.dataset.group&&!g.closest('.entry'))g.remove();});entry.after(group);}const old=entry.querySelector('.review-check'),check=old.cloneNode(),label=old.closest('label'),text=el('span');text.className='web-original-text';old.remove();text.textContent=label.textContent;label.replaceWith(check,text);const copy=el('span',text.textContent.replace(/^\d+\.\s*/,''));copy.className='web-original-center';copy.setAttribute('aria-hidden','true');entry.querySelector('.original').append(copy);originalObserver.observe(entry.querySelector('.original'));check.onchange=async()=>{try{await mutate('/select',{index:i,selected:check.checked});syncChecks();}catch(e){show(e.message);syncChecks();}};render(i);}
const onlyPending=el('button','仅看未入库');onlyPending.id='show-unimported';onlyPending.className='pingpong';onlyPending.setAttribute('role','switch');onlyPending.setAttribute('aria-checked','true');const commitControls=el('span');commitControls.className='web-commit-controls';const commitButton=document.querySelector('#export-unchecked');commitButton.before(commitControls);commitControls.append(onlyPending,commitButton);
for(const selector of ['#show-unchecked','#show-unimported']){const b=document.querySelector(selector);b.onclick=()=>{b.setAttribute('aria-checked',String(b.getAttribute('aria-checked')!=='true'));syncChecks();};}
document.querySelector('#toggle-c').onclick=()=>{const hidden=document.body.classList.toggle('hide-c');document.querySelector('#toggle-c').setAttribute('aria-checked',String(!hidden));};
document.querySelector('#toggle-d').onclick=()=>{const hidden=document.body.classList.toggle('hide-d');document.querySelector('#toggle-d').setAttribute('aria-checked',String(!hidden));};
document.querySelector('#show-details').onclick=()=>{document.body.classList.remove('hide-c','hide-d');for(const sel of ['#toggle-c','#toggle-d'])document.querySelector(sel).setAttribute('aria-checked','true');};
entries.forEach(initEntry);
const commit=document.querySelector('#export-unchecked');commit.onclick=()=>submitRows();
document.querySelector('#clear-selection').onclick=async()=>{try{await mutate('/clear');syncChecks();}catch(e){show(e.message);}};
async function adopt(next,html){
 if(next.rows.length>entries.length){
  if(!html){const response=await fetch('/api/batches/'+next.id+'/updates?after='+entries.length);if(!response.ok)throw Error('追加条目读取失败');const data=await response.json();next=data.batch;html=data.html;}
  const fresh=[...new DOMParser().parseFromString(html,'text/html').querySelectorAll('.entry')];const previous=batch;batch=next;
  fresh.forEach(entry=>{const i=entries.length;const last=entries.at(-1),anchor=last.nextElementSibling?.classList.contains('ai-group')?last.nextElementSibling:last;anchor.after(entry);entries.push(entry);initEntry(entry,i);});
  if(entries.length!==next.rows.length){batch=previous;throw Error('追加条目数量不一致，请刷新');}
 }
 batch=next;
}
async function poll(){
 if(!busy&&!document.querySelector('dialog[open]')){
  const task=queue.then(async()=>{const response=await fetch('/api/batches/'+batch.id+'/updates?after='+entries.length);if(!response.ok)throw Error('动态审核连接中断');const data=await response.json(),old=batch;await adopt(data.batch,data.html);entries.forEach((entry,i)=>{const lookupChanged=entry.dataset.candidateLookup!==JSON.stringify(batch.rows[i].candidate_lookup||{}),focusedInput=entry.contains(document.activeElement)&&document.activeElement.matches('input,textarea,select');if(!candidatePending.has(i)&&!focusedInput&&(lookupChanged||entry.dataset.editing!=='true'&&JSON.stringify(old.rows[i])!==JSON.stringify(batch.rows[i])))render(i,entry.dataset.editing==='true');});syncChecks();if(batch.state==='failed')show(batch.error);});
  queue=task.catch(e=>show(e.message));await queue;
 }
 setTimeout(poll,1500);
}
setTimeout(poll,1500);
const heading=document.querySelector('main>h1+p'),summary=el('span','出价日'+(batch.rows[0]?.quote.published_at||'待确认'));summary.className='web-summary';
const dateBox=el('span');dateBox.className='web-date';const editor=el('span');editor.className='web-date-editor';editor.hidden=true;
const day=el('input');day.type='date';day.setAttribute('aria-label','出价日期');day.value=batch.rows[0]?.quote.published_at||'';
editor.append(el('span','出价日期'),day);const saveDate=el('button','修改出价日');saveDate.type='button';saveDate.setAttribute('aria-expanded','false');
saveDate.onclick=async()=>{if(editor.hidden){day.value=batch.rows[0]?.quote.published_at||'';editor.hidden=false;saveDate.textContent='保存出价日';saveDate.setAttribute('aria-expanded','true');return;}saveDate.disabled=true;try{await mutate('/date',{date:day.value});entries.forEach((_,i)=>render(i,entries[i].dataset.editing==='true'));editor.hidden=true;saveDate.textContent='修改出价日';saveDate.setAttribute('aria-expanded','false');show('日期已更新，请重新勾选');}catch(e){show(e.message);}finally{saveDate.disabled=false;}};
dateBox.append(editor,saveDate,link('返回首页','/'));heading.classList.add('web-heading-meta');heading.replaceChildren(summary,dateBox);const title=document.querySelector('main>h1'),titlebar=el('div');titlebar.className='web-titlebar';title.before(titlebar);titlebar.append(title,heading);
const aliasButton=el('button','一键入库绿&全');aliasButton.id='alias-bulk-open';aliasButton.type='button';aliasButton.className='web-alias-open';aliasButton.onclick=openAliasBulk;title.after(aliasButton);syncChecks();
const stickyTitle=el('span','《'+(batch.display_filename||batch.filename)+'》'),toolbar=document.querySelector('.toolbar');
stickyTitle.className='web-sticky-title';stickyTitle.hidden=true;toolbar.append(stickyTitle);
function updateStickyTitle(){
 stickyTitle.hidden=titlebar.getBoundingClientRect().bottom>0;
 if(stickyTitle.hidden)return;
 const left=document.querySelector('#show-details').getBoundingClientRect(),right=onlyPending.getBoundingClientRect(),bounds=toolbar.getBoundingClientRect();
 const ownRow=right.left-left.right<120;stickyTitle.classList.toggle('web-title-own-row',ownRow);
 if(!ownRow){stickyTitle.style.left=(left.right-bounds.left+8)+'px';stickyTitle.style.width=Math.max(0,right.left-left.right-16)+'px';stickyTitle.style.top=((left.top+left.bottom)/2-bounds.top)+'px';}
}
let titleFrame=0;const scheduleTitle=()=>{if(!titleFrame)titleFrame=requestAnimationFrame(()=>{titleFrame=0;updateStickyTitle();});};
window.addEventListener('scroll',scheduleTitle,{passive:true});window.addEventListener('resize',scheduleTitle);
new ResizeObserver(scheduleTitle).observe(toolbar);updateStickyTitle();

if(batch.preview){commit.disabled=true;show('历史解析界面预览：仅用于检查交互，不可入库。');}
window.addEventListener('beforeunload',e=>{if(busy){e.preventDefault();e.returnValue='';}});
})();
