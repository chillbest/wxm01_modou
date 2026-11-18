const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
class Element{
 constructor(){this.children=[];this.value='kept';this.files=['file'];this.disabled=false;this.textContent='';}
 append(...items){this.children.push(...items);} replaceChildren(){this.children=[];}
}
const nodes=Object.fromEntries(['#batches','#status','#parse','#parse-url','#file','#note-url','#upload','#url-upload'].map(k=>[k,new Element()]));
let fail=false,calls=[];
const batch={id:'abc',display_filename:'游戏.txt（3）',state:'ready',created_at:'2026-11-15T00:00:00Z'};
const context={document:{querySelector:s=>nodes[s],createElement:()=>new Element()},FormData:class{append(){}},setTimeout(){},console,
 location:new Proxy({}, {set(){throw Error('Unexpected navigation');}}),
 fetch:async(url,opts)=>{calls.push(url);return {ok:!fail,json:async()=>url==='/api/batches'?[batch]:fail?{detail:'提交失败'}:{id:'abc',url:'/review/abc'}};}};
vm.createContext(context);vm.runInContext(fs.readFileSync('src/modou/web/static/home.js','utf8'),context);
(async()=>{
 assert.equal(vm.runInContext("batchAge({created_at:'2026-11-16T15:59:59Z'},Date.parse('2026-11-16T16:00:00Z'))",context),'older');
 assert.equal(vm.runInContext("batchAge({created_at:'2026-11-16T16:00:00Z'},Date.parse('2026-11-17T15:59:59Z'))",context),'today');
 assert.equal(vm.runInContext('batchAge({})',context),'unknown');
 for(const [form,button,input] of [['#upload','#parse','#file'],['#url-upload','#parse-url','#note-url']]){
  nodes[input].value='source';await nodes[form].onsubmit({preventDefault(){}});
  assert.equal(nodes[input].value,'');assert.equal(nodes[button].disabled,false);assert.match(nodes['#status'].textContent,/已提交/);
  fail=true;nodes[input].value='preserved';await nodes[form].onsubmit({preventDefault(){}});
  assert.equal(nodes[input].value,'preserved');assert.equal(nodes[button].disabled,false);assert.equal(nodes['#status'].textContent,'提交失败');fail=false;
 }
 await vm.runInContext('refresh()',context);
 assert.equal(nodes['#batches'].children[0].children[0].textContent,'待审核：《游戏.txt（3）》');
 assert.equal(nodes['#batches'].children[0].className,'batch-item batch-older');
 console.log('PASS: submission, no navigation, naming, day boundary and errors');
})().catch(e=>{console.error(e);process.exitCode=1;});
