function batchTiming(batch,now=Date.now()){
 const started=batch.parse_started_at?new Date(batch.parse_started_at):null;
 const stamp=started&&!Number.isNaN(started.getTime())?new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(started):null;
 const date=stamp?stamp.replace(/^(\d{2})\/(\d{2}),? /,(_,day,month)=>Number(month)+'月'+Number(day)+'日 '):'--月--日 --:--';
 let seconds=batch.parse_elapsed_seconds;
 if(['parsing','reviewable'].includes(batch.state)&&started)seconds=Math.max(0,(now-started.getTime())/1000);
 if(typeof seconds!=='number'||!Number.isFinite(seconds))return date+' 耗时--';
 seconds=Math.floor(Math.max(0,seconds));const hours=Math.floor(seconds/3600),minutes=Math.floor(seconds%3600/60);
 return date+' 耗时'+(hours?hours+'h':'')+(minutes||hours?minutes+'m':'')+seconds%60+'s';
}
function batchAge(batch,now=Date.now()){
 const value=batch.created_at||batch.parse_started_at,date=new Date(value||'');
 if(Number.isNaN(date.getTime()))return 'unknown';
 const day=d=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);
 return day(date)<day(new Date(now))?'older':'today';
}
async function refresh(){
 try{
  const response=await fetch('/api/batches');if(!response.ok)throw Error('批次列表读取失败');
  const rows=await response.json(),list=document.querySelector('#batches');list.replaceChildren();
  rows.reverse().forEach(b=>{
   const li=document.createElement('li'),a=document.createElement('a'),time=document.createElement('span'),age=batchAge(b);
   li.className='batch-item batch-'+age;a.href='/review/'+b.id;
   a.textContent=batchLabel(b);
   time.className='batch-timing';time.textContent=batchTiming(b);li.append(a,time);
   if(age!=='today'){const tag=document.createElement('small');tag.className='batch-age';tag.textContent=age==='older'?'往日批次':'日期未知';li.append(tag);}
   if(b.error){const error=document.createElement('span');error.className='batch-error';error.textContent=b.error;li.append(error);}
   list.append(li);
  });
 }catch(error){document.querySelector('#status').textContent=error.message;}
}
function batchLabel(batch){
 const count=batch.imported_count||0,total=Number.isInteger(batch.total_rows)?batch.total_rows:'解析中';
 const complete=batch.state==='ready'&&count>0&&count===total;
 const state=complete?'完全入库'+count+'条':count?'入库'+count+'/'+total:({ready:'待审核',reviewable:'可审核',failed:'解析失败',queued:'排队中',parsing:'解析中'}[batch.state]||batch.state);
 return state+'：《'+(batch.display_filename||batch.filename)+'》';
}
async function poll(){await refresh();setTimeout(poll,1000);}
async function submitNote(button,input,url,options){
 const status=document.querySelector('#status');button.disabled=true;status.textContent='正在提交…';
 try{
  const response=await fetch(url,options),result=await response.json();if(!response.ok)throw Error(result.detail||'提交失败');
  input.value='';status.textContent='已提交，解析进度见下方批次列表';await refresh();
 }catch(error){status.textContent=error.message;}finally{button.disabled=false;}
}
document.querySelector('#upload').onsubmit=async e=>{
 e.preventDefault();const input=document.querySelector('#file'),data=new FormData();data.append('file',input.files[0]);
 await submitNote(document.querySelector('#parse'),input,'/api/upload',{method:'POST',headers:{'X-Modou-Review':'1'},body:data});
};
document.querySelector('#url-upload').onsubmit=async e=>{
 e.preventDefault();const input=document.querySelector('#note-url');
 await submitNote(document.querySelector('#parse-url'),input,'/api/url',{method:'POST',headers:{'Content-Type':'application/json','X-Modou-Review':'1'},body:JSON.stringify({url:input.value})});
};
poll();
