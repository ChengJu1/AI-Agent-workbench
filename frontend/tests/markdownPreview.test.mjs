import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { rehypeCitationHighlight } from "../src/lib/markdownCitationHighlight.ts";

function render(text, snippet, at = text.indexOf(snippet)) {
  return renderToStaticMarkup(createElement(ReactMarkdown, {
    skipHtml: true, remarkPlugins: [remarkGfm],
    rehypePlugins: [[rehypeCitationHighlight, { text, start: at, end: at + snippet.length }]],
  }, text));
}

test("Markdown 标题、强调和列表正常渲染，高亮不破坏原语法", () => {
  const text = "# 标题\n\n前文 **重点内容** 后文。\n\n- 第一项\n- 第二项";
  const html = render(text, "重点内容");
  assert.match(html, /<h1>标题<\/h1>/);
  assert.match(html, /<strong><mark[^>]*>重点内容<\/mark><\/strong>/);
  assert.match(html, /<ul>[\s\S]*<li>第一项<\/li>/);
  assert.equal((html.match(/<mark /g) || []).length, 1);
});

test("GFM 表格、任务列表和链接保留结构，只标记来源中的对应文本", () => {
  const text = "| 名称 | 说明 |\n| --- | --- |\n| 注意力 | 聚合上下文 |\n\n- [x] 已完成\n\n[原文](https://example.com)";
  const html = render(text, "聚合上下文");
  assert.match(html, /<table>/);
  assert.match(html, /<td><mark[^>]*>聚合上下文<\/mark><\/td>/);
  assert.match(html, /type="checkbox"/);
  assert.match(html, /<a href="https:\/\/example.com">原文<\/a>/);
});

test("代码块和行内代码能按源位置高亮，不把围栏或反引号显示出来", () => {
  const fenced = "前文\n\n```python\nprint('hello')\nprint('world')\n```\n\n后文";
  const html = render(fenced, "print('world')");
  assert.match(html, /<pre><code class="language-python">/);
  assert.match(html, /<mark[^>]*>print\(&#x27;world&#x27;\)<\/mark>/);
  assert.equal((html.match(/<mark /g) || []).length, 1);
  assert.doesNotMatch(html, /```/);
  const inline = render("使用 `foo(bar)` 执行。", "bar");
  assert.match(inline, /<code>foo\(<mark[^>]*>bar<\/mark>\)<\/code>/);
});

test("emoji、实体和 Markdown 转义不会让高亮偏移", () => {
  assert.match(render("😀 前文 &amp; 后文", "&amp;"), /<mark[^>]*>&amp;<\/mark>/);
  assert.match(render("前文 \\*字面星号 后文", "\\*"), /<mark[^>]*>\*<\/mark>/);
  const text = "😀 重复 **重复**";
  const html = render(text, "重复", text.lastIndexOf("重复"));
  assert.match(html, /😀 重复 <strong><mark[^>]*>重复<\/mark><\/strong>/);
});

test("原文中的 HTML 和危险链接不能注入执行元素", () => {
  const html = render("<script>alert(1)</script>\n\n[点击](javascript:alert(1))\n\n正常正文", "正常正文");
  assert.doesNotMatch(html, /<script|href="javascript:/);
  assert.match(html, /<mark[^>]*>正常正文<\/mark>/);
});
