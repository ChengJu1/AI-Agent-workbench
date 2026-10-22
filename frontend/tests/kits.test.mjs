import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import { AGENT_TEMPLATES } from '../src/lib/agentTemplates.ts';
import { KIT_MANIFESTS } from '../src/kits/manifests.ts';

const SRC = new URL('../src/', import.meta.url).pathname;
const JOB_WORDS = /投递|网申|岗位|职位|简历|秋招|招聘|面试|applications|[Ll]edger/;
const files = dir => readdirSync(dir).flatMap(name => {
  const path = join(dir, name);
  return statSync(path).isDirectory() ? (name === 'kits' && dir === SRC ? [] : files(path)) : [path];
});

test('工作台核心代码不含求职专用内容，专用内容只在 kits 目录', () => {
  const leaks = files(SRC).filter(path => /\.(tsx?|css)$/.test(path) && JOB_WORDS.test(readFileSync(path, 'utf8')));
  assert.deepEqual(leaks.map(path => path.slice(SRC.length)), []);
});

test('各工具包的模板并入 Agent 模板，且能力名不重复', () => {
  for (const kit of KIT_MANIFESTS) assert.ok(AGENT_TEMPLATES.some(template => template.id === kit.template.id), kit.template.id);
  assert.equal(new Set(KIT_MANIFESTS.map(kit => kit.capability)).size, KIT_MANIFESTS.length);
});

test('样式表的选择器括号成对，避免一条坏选择器让后面的样式全部失效', () => {
  const sheets = [...files(SRC), ...files(join(SRC, 'kits'))].filter(path => path.endsWith('.css'));
  for (const path of sheets) {
    const css = readFileSync(path, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
    for (const [, selector] of css.matchAll(/(?:^|[{}])([^{}]+)\{/g))
      assert.equal(selector.split('(').length, selector.split(')').length, `${path.slice(SRC.length)}: ${selector.trim().slice(0, 80)}`);
  }
});
