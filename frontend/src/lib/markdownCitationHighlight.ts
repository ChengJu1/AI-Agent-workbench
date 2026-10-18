import { fromMarkdown } from "mdast-util-from-markdown";

type Node = {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  position?: { start: { offset?: number }; end: { offset?: number } };
  children?: Node[];
};
type Options = { text: string; start: number; end: number };
type Span = [number, number];

// 在 Markdown 转为 HTML 语法树后标记原文区间，不把 <mark> 插入 Markdown 语法中。
export function rehypeCitationHighlight(options: Options) {
  return (tree: Node) => {
    function visit(parent: Node) {
      if (!parent.children) return;
      const code = parent.type === "element" && parent.tagName === "code";
      parent.children = parent.children.flatMap((node): Node[] => {
        if (node.type !== "text" || !node.value) { visit(node); return [node]; }
        const position = code ? parent.position : node.position;
        const start = position?.start.offset;
        const end = position?.end.offset;
        if (start === undefined || end === undefined || start >= options.end || end <= options.start) return [node];
        const raw = options.text.slice(start, end);
        const spans = code ? codeSpans(raw, node.value, start) : textSpans(raw, node.value, start);
        if (!spans) {
          // 特殊语法无法逐字符映射时，只有整个节点被引用才标记完整显示文本。
          return start >= options.start && end <= options.end ? [mark(node.value)] : [node];
        }
        const parts: Node[] = [];
        let segment = "";
        let selected = false;
        for (let index = 0; index < node.value.length; index += 1) {
          const span = spans[index];
          const next = Boolean(span && span[0] < options.end && span[1] > options.start);
          if (next !== selected && segment) { parts.push(selected ? mark(segment) : { type: "text", value: segment }); segment = ""; }
          segment += node.value[index]; selected = next;
        }
        if (segment) parts.push(selected ? mark(segment) : { type: "text", value: segment });
        return parts;
      });
    }
    visit(tree);
  };
}

function mark(value: string): Node {
  return { type: "element", tagName: "mark", properties: { className: ["citationMarkdownMark"], "data-citation-highlight": true },
    children: [{ type: "text", value }] };
}

function textSpans(raw: string, value: string, offset: number): Span[] | null {
  if (raw === value) return Array.from({ length: value.length }, (_, index) => [offset + index, offset + index + 1]);
  const tokens = raw.matchAll(/\\[\x21-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e]|&(?:#[xX][a-fA-F0-9]+|#[0-9]+|[a-zA-Z][a-zA-Z0-9]+);|[\s\S]/g);
  const spans: Span[] = [];
  let decoded = "";
  for (const match of tokens) {
    const token = match[0];
    let visible = token;
    if (token.startsWith("\\") && token.length === 2) visible = token[1];
    else if (token.startsWith("&") && token.endsWith(";")) {
      const parsed = fromMarkdown(`a${token}z`);
      const paragraph = parsed.children[0];
      if (paragraph?.type === "paragraph" && paragraph.children.length === 1 && paragraph.children[0].type === "text") {
        visible = paragraph.children[0].value.slice(1, -1);
      }
    }
    decoded += visible;
    for (let index = 0; index < visible.length; index += 1) spans.push([offset + match.index!, offset + match.index! + token.length]);
  }
  return decoded === value ? spans : null;
}

function codeSpans(raw: string, value: string, offset: number): Span[] | null {
  const inline = raw.match(/^(`+)([\s\S]*)\1$/);
  if (inline && !raw.startsWith("```\n") && !/^`{3,}[^\n]*\n/.test(raw)) {
    let body = inline[2].replace(/\n/g, " ");
    let padding = 0;
    if (body.startsWith(" ") && body.endsWith(" ") && body.trim()) { body = body.slice(1, -1); padding = 1; }
    if (body === value) return Array.from({ length: value.length }, (_, index) =>
      [offset + inline[1].length + padding + index, offset + inline[1].length + padding + index + 1]);
  }
  const fenced = /^ {0,3}(`{3,}|~{3,})/.test(raw);
  const lines = raw.split("\n");
  const visible = value.split("\n");
  const spans: Span[] = [];
  let lineIndex = fenced ? 1 : 0;
  let lineOffset = fenced ? lines[0].length + 1 : 0;
  for (let index = 0; index < visible.length; index += 1) {
    if (index === visible.length - 1 && visible[index] === "") break;
    const line = lines[lineIndex];
    if (line === undefined) return null;
    const at = line.indexOf(visible[index]);
    if (at < 0) return null;
    for (let char = 0; char < visible[index].length; char += 1) spans.push([offset + lineOffset + at + char, offset + lineOffset + at + char + 1]);
    if (index < visible.length - 1) spans.push([offset + lineOffset + line.length, offset + lineOffset + line.length + 1]);
    lineOffset += line.length + 1; lineIndex += 1;
  }
  return spans.length === value.length ? spans : null;
}
