import assert from 'node:assert/strict';
import test from 'node:test';
import {agenda,daysUntil,formatDate,parseDate,sourceLabel,whenLabel} from '../src/lib/applications.ts';

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
