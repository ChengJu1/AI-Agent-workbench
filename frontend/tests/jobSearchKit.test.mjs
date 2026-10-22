import assert from 'node:assert/strict';
import test from 'node:test';
import {agenda,daysUntil,formatDate,parseDate,sourceLabel,whenLabel} from '../src/kits/jobSearch/lib.ts';

const now=new Date(2026,9,21,15,0);
const job=(extra)=>({id:'app_1',company:'合成科技',position:'算法',stage:'saved',deadline:'',next_event_at:'',next_event:'',...extra});

test('按日历日计算距今天数',()=>{
 assert.equal(daysUntil('2026-10-21',now),0);
 assert.equal(daysUntil('2026-10-24 09:00',now),3);
 assert.equal(daysUntil('2026-10-19',now),-2);
 assert.equal(daysUntil('',now),null);
 assert.deepEqual([whenLabel(-2),whenLabel(0),whenLabel(1),whenLabel(5)],['已过 2 天','今天','明天','5 天后']);
});
test('提醒只包含未投递岗位的临近截止和未结束岗位的近期日程',()=>{
 const rows=agenda([
  job({id:'a',deadline:'2026-10-23'}),
  job({id:'b',deadline:'2026-10-23',stage:'applied'}),
  job({id:'c',deadline:'2026-10-30'}),
  job({id:'d',deadline:'2026-10-20',stage:'preparing'}),
  job({id:'e',stage:'test',next_event_at:'2026-10-25 19:00',next_event:'笔试'}),
  job({id:'f',stage:'rejected',next_event_at:'2026-10-22 10:00',next_event:'一面'}),
  job({id:'g',stage:'interview',next_event_at:'2026-10-19 10:00',next_event:'二面'}),
 ],now);
 assert.deepEqual(rows.map(r=>[r.id,r.kind,r.days]),[['d','deadline',-1],['a','deadline',2],['e','event',4]]);
 assert.equal(rows[2].detail,'笔试');
});
test('资料包来源说明',()=>{
 assert.equal(sourceLabel({source:{kind:'profile',ref:'basics.name'},transform:''}),'资料 basics.name');
 assert.equal(sourceLabel({source:{kind:'profile',ref:'education.0.degree'},transform:'option:大学本科'}),'资料 education.0.degree → 选项转换');
 assert.equal(sourceLabel({source:{kind:'inferred',ref:'intro'},transform:''}),'Agent 起草');
});
test('日期保留用户输入的精度，不补日',()=>{
 assert.deepEqual(parseDate('2024-09'),{precision:'month',year:2024,month:9});
 assert.equal(formatDate(parseDate('2024')),'2024');
 assert.equal(formatDate(parseDate('2024-9-1')),'2024-09-01');
 assert.equal(parseDate('09/2024'),null);
});
import {deadlineBadge,shortWhen,GROUPS} from '../src/kits/jobSearch/lib.ts';
test('列表倒计时只给还没投的岗位',()=>{
 const n=new Date(2026,9,21,9);
 assert.deepEqual(deadlineBadge({deadline:'2026-10-21',stage:'saved'},n),{text:'今天截止',tone:'urgent'});
 assert.deepEqual(deadlineBadge({deadline:'2026-10-24',stage:'preparing'},n),{text:'还剩 3 天',tone:'urgent'});
 assert.deepEqual(deadlineBadge({deadline:'2026-10-27',stage:'saved'},n),{text:'还剩 6 天',tone:'soon'});
 assert.deepEqual(deadlineBadge({deadline:'2026-10-20',stage:'saved'},n),{text:'已截止',tone:'muted'});
 assert.equal(deadlineBadge({deadline:'2026-10-24',stage:'applied'},n),null);
 assert.equal(shortWhen('2026-10-23 19:00',n),'10-23 19:00');
 assert.equal(shortWhen('2027-01-05',n),'2027-01-05');
 assert.equal(GROUPS.flatMap(g=>g.stages).length,8);
});
import {dueAlerts} from '../src/kits/jobSearch/lib.ts';
test('浏览器提醒：截止当天和两小时内的日程',()=>{
 const n=new Date(2026,9,21,17,0);
 const rows=dueAlerts([
  job({id:'a',deadline:'2026-10-21'}),
  job({id:'b',deadline:'2026-10-21',stage:'applied'}),
  job({id:'c',stage:'test',next_event_at:'2026-10-21 18:30',next_event:'笔试'}),
  job({id:'d',stage:'interview',next_event_at:'2026-10-21 20:30',next_event:'一面'}),
  job({id:'e',stage:'rejected',next_event_at:'2026-10-21 17:30',next_event:'二面'}),
 ],n);
 assert.deepEqual(rows.map(r=>r.key),['a:deadline:2026-10-21','c:event:2026-10-21 18:30']);
 assert.equal(rows[1].title,'90 分钟后：笔试');
});
