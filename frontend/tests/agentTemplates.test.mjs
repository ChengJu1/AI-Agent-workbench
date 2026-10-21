import assert from 'node:assert/strict';
import test from 'node:test';
import {AGENT_TEMPLATES} from '../src/lib/agentTemplates.ts';

const KNOWN = new Set(['files', 'web', 'browser', 'tracking', 'applications']);
test('模板只使用平台已有能力，且名称唯一', () => {
  assert.equal(new Set(AGENT_TEMPLATES.map(t => t.id)).size, AGENT_TEMPLATES.length);
  for (const t of AGENT_TEMPLATES) {
    assert.ok(t.capabilities.length > 0, t.id);  // A custom Agent needs at least one capability, Skill, knowledge base or MCP tool.
    assert.ok(t.capabilities.every(c => KNOWN.has(c)), t.id);
    assert.ok(t.prompt.length > 40 && t.name.length <= 40, t.id);
  }
});
