import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

// 聊天与 Skill 共用排版；表格和代码独立滚动，正文保持正常换行。
export function MarkdownContent({ children, className = "", label, components }: {
  children: string;
  className?: string;
  label?: string;
  components?: Components;
}) {
  return <div className={`markdown ${className}`.trim()} aria-label={label}>
    <ReactMarkdown skipHtml remarkPlugins={[remarkGfm]} components={{
      table: ({ children }) => <div className="markdownTable" role="region" aria-label="表格，可横向滚动" tabIndex={0}>
        <table>{children}</table>
      </div>,
      pre: ({ children }) => <pre tabIndex={0} aria-label="代码块，可横向滚动">{children}</pre>,
      a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
      ...components,
    }}>{children}</ReactMarkdown>
  </div>;
}
