import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { rehypeCitationPosition } from "../src/lib/markdownCitationPosition.ts";

function render(text, snippet, at = text.indexOf(snippet)) {
  return renderToStaticMarkup(createElement(ReactMarkdown, {
    skipHtml: true, remarkPlugins: [remarkGfm],
    rehypePlugins: [[rehypeCitationPosition, { start: at, end: at + snippet.length }]],
  }, text));
}

test("Markdown 正常排版，引用只保留定位锚点，不插入高亮标签", () => {
  const text = "# 标题\n\n前文 **重点内容** 后文。\n\n- 第一项\n- 第二项";
  const html = render(text, "重点内容");
  assert.match(html, /<h1>标题<\/h1>/);
  assert.match(html, /<strong>重点内容<\/strong>/);
  assert.match(html, /<ul>[\s\S]*<li>第一项<\/li>/);
  assert.match(html, /<p data-citation-position="true">/);
  assert.doesNotMatch(html, /<mark|citationMarkdownMark|background:/);
});

test("GFM 表格、任务列表和链接保留结构，引用行可定位", () => {
  const text = "| 名称 | 说明 |\n| --- | --- |\n| 注意力 | 聚合上下文 |\n\n- [x] 已完成\n\n[原文](https://example.com)";
  const html = render(text, "聚合上下文");
  assert.match(html, /<table>/);
  assert.match(html, /<tr data-citation-position="true"><td>注意力<\/td><td>聚合上下文<\/td><\/tr>/);
  assert.match(html, /type="checkbox"/);
  assert.match(html, /<a href="https:\/\/example.com">原文<\/a>/);
});

test("代码块和行内代码按原格式显示，无额外颜色标记", () => {
  const fenced = "前文\n\n```python\nprint('hello')\nprint('world')\n```\n\n后文";
  const html = render(fenced, "print('world')");
  assert.match(html, /<pre data-citation-position="true"><code class="language-python">/);
  assert.match(html, /print\(&#x27;world&#x27;\)/);
  assert.doesNotMatch(html, /<mark/);
  assert.doesNotMatch(html, /```/);
  const inline = render("使用 `foo(bar)` 执行。", "bar");
  assert.match(inline, /<code>foo\(bar\)<\/code>/);
});

test("emoji、实体和 Markdown 转义保持原来的可见内容", () => {
  assert.match(render("😀 前文 &amp; 后文", "&amp;"), /😀 前文 &amp; 后文/);
  assert.match(render("前文 \\*字面星号 后文", "\\*"), /前文 \*字面星号 后文/);
  const text = "😀 重复 **重复**";
  const html = render(text, "重复", text.lastIndexOf("重复"));
  assert.match(html, /😀 重复 <strong>重复<\/strong>/);
});

test("原文中的 HTML 和危险链接不能注入执行元素", () => {
  const html = render("<script>alert(1)</script>\n\n[点击](javascript:alert(1))\n\n正常正文", "正常正文");
  assert.doesNotMatch(html, /<script|href="javascript:/);
  assert.match(html, /<p data-citation-position="true">正常正文<\/p>/);
});
