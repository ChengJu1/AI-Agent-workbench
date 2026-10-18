type Node = {
  type: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  position?: { start: { offset?: number }; end: { offset?: number } };
  children?: Node[];
};

const BLOCKS = new Set(["p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "li", "tr"]);

// 仅保留滚动定位锚点，不改变 Markdown 的文字、颜色或背景。
export function rehypeCitationPosition(options: { start: number; end: number }) {
  return (tree: Node) => {
    function visit(node: Node) {
      const start = node.position?.start.offset;
      const end = node.position?.end.offset;
      if (node.type === "element" && BLOCKS.has(node.tagName ?? "")
          && start !== undefined && end !== undefined && start < options.end && end > options.start) {
        node.properties = { ...node.properties, "data-citation-position": true };
      }
      node.children?.forEach(visit);
    }
    visit(tree);
  };
}
