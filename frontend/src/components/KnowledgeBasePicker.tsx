import type { KnowledgeBaseInfo } from "../types";
import "./KnowledgeBasePicker.css";

type Props = {
  bases: KnowledgeBaseInfo[];
  selected: string[];
  disabled: boolean;
  onChange: (ids: string[]) => void;
};

export function KnowledgeBasePicker({ bases, selected, disabled, onChange }: Props) {
  return (
    <fieldset className="knowledgePicker" disabled={disabled}>
      <legend>可查询的知识库</legend>
      <p className="agentEditorHint">最多选择 10 个。Agent 可通过检索工具查询这些资料；空库需先上传文档。</p>
      {!bases.length && <p>还没有知识库，请先在工具栏“知识库”中创建并上传资料。</p>}
      <div className="knowledgeChoices">
        {bases.map((base) => (
          <label className="knowledgeChoice" key={base.id}>
            <input type="checkbox" checked={selected.includes(base.id)}
              disabled={!selected.includes(base.id) && selected.length >= 10}
              onChange={(event) => onChange(event.target.checked
                ? [...selected, base.id] : selected.filter((id) => id !== base.id))} />
            <span><strong>{base.name}</strong>
              <small>{base.document_count} 个文档 · {base.chunk_count} 个片段</small>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
