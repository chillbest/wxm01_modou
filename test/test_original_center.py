"""Focused geometry check; no broad UI regression suite needed."""
from pathlib import Path
import subprocess


def test_center_copy_hides_before_controls_touch_and_returns_when_wider():
    source = Path('src/modou/web/static/review.js').read_text(encoding='utf-8')
    helper = source[source.index('function centeredOriginalFits('):source.index('(() => {')]
    checks = '''
const assert=require('node:assert/strict');
const text={left:600,right:900,top:0,bottom:25};
const row={left:0,right:1500};
assert.equal(centeredOriginalFits(text,[{left:0,right:580,top:0,bottom:30}],row),true);
assert.equal(centeredOriginalFits(text,[{left:0,right:600,top:0,bottom:30}],row),false);
assert.equal(centeredOriginalFits(text,[{left:0,right:595,top:0,bottom:30}],row),false);
assert.equal(centeredOriginalFits(text,[],{left:0,right:700}),false);
assert.equal(centeredOriginalFits(text,[{left:0,right:580,top:0,bottom:30}],row),true);
'''
    subprocess.run(['node', '-e', helper + checks], check=True, capture_output=True, text=True)


def test_center_uses_free_space_between_left_controls_and_right_button():
    source = Path('src/modou/web/static/review.js').read_text(encoding='utf-8')
    helpers = source[source.index('function centeredOriginalFits('):source.index('(() => {')]
    checks = '''
const assert=require('node:assert/strict');
const bounds={left:26,right:2484};
const occupied=[{left:26,right:907,top:40,bottom:90},{left:2350,right:2484,top:40,bottom:90,rightAction:true}];
const space=originalFreeSpace(bounds,occupied);
assert.equal(space.center,(907+2350)/2);
const width=730;
const oldCenter=(bounds.left+bounds.right)/2;
assert.equal(centeredOriginalFits({left:oldCenter-width/2,right:oldCenter+width/2,top:40,bottom:90},occupied,bounds),false);
assert.equal(centeredOriginalFits({left:space.center-width/2,right:space.center+width/2,top:40,bottom:90},occupied,space),true);
assert.equal(centeredOriginalFits({left:space.center-800,right:space.center+800,top:40,bottom:90},occupied,space),false);
assert.deepEqual(originalFreeSpace(bounds,[]),{left:26,right:2484,center:1255});
'''
    subprocess.run(['node', '-e', helpers + checks], check=True, capture_output=True, text=True)


def test_highlight_falls_back_to_same_row_original_instead_of_next_copy():
    source = Path('src/modou/web/static/review.js').read_text(encoding='utf-8')
    helper = source[source.index('function topmostVisibleOriginal('):source.index('function centeredOriginalFits(')]
    controller = source[source.index('function updateOriginalFocus()'):source.index('function scheduleOriginalFocus()')]
    checks = '''
const assert=require('node:assert/strict');
const node=(top,visibility='visible')=>({visibility,getClientRects:()=>[1],getBoundingClientRect:()=>({top,bottom:top+30,left:100,right:500}),classList:{values:new Set(),remove(k){this.values.delete(k);},add(k){this.values.add(k);}}});
const copies=[node(150,'hidden'),node(350)],originals=[node(150),node(350)],headers=[node(150),node(350)];
const entries=headers.map((h,i)=>({hidden:false,querySelector:s=>s==='.original'?h:s==='.web-original-center'?copies[i]:originals[i]}));
const batch={rows:[{},{}]},innerHeight=650,innerWidth=1200;
const document={querySelector:()=>({getBoundingClientRect:()=>({top:0,bottom:100})})};
const getComputedStyle=n=>({visibility:n.visibility});
let fitCalls=0;const fitCenteredOriginal=(entry,schedule)=>{fitCalls++;assert.equal(schedule,false);};
const focused=()=>[...copies,...originals].filter(n=>n.classList.values.has('web-original-focus'));
updateOriginalFocus();assert.deepEqual(focused(),[originals[0]]);
copies[0].visibility='visible';updateOriginalFocus();assert.deepEqual(focused(),[copies[0]]);
batch.rows[0].imported=true;updateOriginalFocus();assert.deepEqual(focused(),[copies[1]]);
copies[1].visibility='hidden';updateOriginalFocus();assert.deepEqual(focused(),[originals[1]]);
batch.rows[1].already_imported=true;updateOriginalFocus();assert.deepEqual(focused(),[]);
assert.equal(fitCalls,4);
'''
    subprocess.run(['node', '-e', helper + controller + checks], check=True, capture_output=True, text=True)


def test_only_topmost_visible_copy_is_chosen_after_scroll_filter_and_occlusion():
    source = Path('src/modou/web/static/review.js').read_text(encoding='utf-8')
    helper = source[source.index('function topmostVisibleOriginal('):source.index('function centeredOriginalFits(')]
    checks = '''
const assert=require('node:assert/strict');
const rect=(top,left=100,right=400)=>({top,bottom:top+25,left,right});
assert.equal(topmostVisibleOriginal([rect(150),rect(350),rect(550)],100,650,1200),0);
assert.equal(topmostVisibleOriginal([rect(80),rect(280),rect(480)],100,650,1200),1);
assert.equal(topmostVisibleOriginal([null,rect(280),rect(480)],100,650,1200),1);
assert.equal(topmostVisibleOriginal([rect(280),rect(150)],100,650,1200),1);
assert.equal(topmostVisibleOriginal([rect(-30),rect(90),rect(650),null],100,650,1200),-1);
assert.equal(topmostVisibleOriginal([rect(120,1300,1500),rect(200)],100,650,1200),1);
assert.equal(topmostVisibleOriginal([],100,650,1200),-1);
assert.equal(topmostVisibleOriginal([rect(150),rect(350),rect(550)],100,650,1200,[{imported:true},{},{}]),1);
assert.equal(topmostVisibleOriginal([rect(150),rect(350),rect(550)],100,650,1200,[{already_imported:true},{imported:true},{}]),2);
assert.equal(topmostVisibleOriginal([rect(150),rect(350)],100,650,1200,[{already_imported:true},{imported:true}]),-1);
assert.equal(topmostVisibleOriginal([rect(150),rect(350)],100,650,1200,[{selected:true},{}]),1);
assert.equal(topmostVisibleOriginal([rect(150),rect(350)],100,650,1200,[{selected:true},{selected:true}]),-1);
const selectionRows=[{},{}];
assert.equal(topmostVisibleOriginal([rect(150),rect(350)],100,650,1200,selectionRows),0);
selectionRows[0].selected=true;
assert.equal(topmostVisibleOriginal([rect(150),rect(350)],100,650,1200,selectionRows),1);
selectionRows[0].selected=false;
assert.equal(topmostVisibleOriginal([rect(150),rect(350)],100,650,1200,selectionRows),0);
const rows=[{},{}];
assert.equal(topmostVisibleOriginal([rect(150),rect(350)],100,650,1200,rows),0);
rows[0].imported=true;
assert.equal(topmostVisibleOriginal([rect(150),rect(350)],100,650,1200,rows),1);
'''
    subprocess.run(['node', '-e', helper + checks], check=True, capture_output=True, text=True)
