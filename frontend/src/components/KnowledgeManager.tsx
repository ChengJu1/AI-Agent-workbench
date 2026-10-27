import { useEffect, useRef, useState } from "react";
import { useKnowledgeManager } from "../hooks/useKnowledgeManager";
import { chunkingLabel, documentSize, rankingLabel, retrievalFeedback } from "../lib/knowledge";
import "./KnowledgeManager.css";
import { KnowledgeEvaluation } from "./KnowledgeEvaluation";

type DeleteTarget = { kind: "base" | "document"; id: string; name: string };

export function KnowledgeManager({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const confirmation = useRef<HTMLDivElement>(null);
  const knowledge = useKnowledgeManager();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [query, setQuery] = useState("");
  const [deleting, setDeleting] = useState<DeleteTarget | null>(null);
  const locked = knowledge.busy || Boolean(deleting);

  useEffect(() => { if (deleting) confirmation.current?.focus(); }, [deleting]);

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);

  return (
    <dialog className="knowledgeManager" ref={dialog} aria-labelledby="knowledgeTitle"
      onCancel={(event) => { event.preventDefault(); onClose(); }}>
      <header className="knowledgeHeader">
        <div><h2 id="knowledgeTitle">知识库</h2><p>建立文档库，查看分段内容并测试检索效果。</p></div>
        <button type="button" onClick={onClose}>关闭</button>
      </header>
      {knowledge.error && <p className="knowledgeError" role="alert">{knowledge.error}</p>}
      <div className="knowledgeLayout">
        <aside className="knowledgeSidebar" aria-label="知识库列表">
          <form onSubmit={async (event) => {
            event.preventDefault();
            if (await knowledge.createBase(name, description)) { setName(""); setDescription(""); }
          }}>
            <h3>新建知识库</h3>
            <label>知识库名称<input required maxLength={100} value={name} disabled={locked}
              placeholder="例如：团队制度" onChange={(event) => setName(event.target.value)} /></label>
            <label>说明（可选）<input maxLength={1000} value={description} disabled={locked}
              onChange={(event) => setDescription(event.target.value)} /></label>
            <button type="submit" disabled={locked || !name.trim()}>
              {knowledge.operation === "creating" ? "正在创建…" : "创建知识库"}
            </button>
          </form>
          {knowledge.loadingBases && <p role="status">正在加载知识库…</p>}
          {!knowledge.loadingBases && !knowledge.bases.length && <p className="knowledgeHint">还没有知识库，从创建一个开始。</p>}
          <div className="knowledgeBaseList">
            {knowledge.bases.map((base) => (
              <button key={base.id} type="button" aria-pressed={base.id === knowledge.selectedId}
                disabled={locked} onClick={() => { knowledge.selectBase(base.id); setQuery(""); }}>
                <strong>{base.name}</strong><span>{base.document_count} 个文档 · {base.chunk_count} 个片段</span>
              </button>
            ))}
          </div>
        </aside>
        <section className="knowledgeContent" aria-label="知识库内容" aria-busy={knowledge.busy}>
          {!knowledge.selectedBase ? <div className="knowledgeEmpty">创建知识库后，即可上传文档。</div> : (
            <>
              <div className="knowledgeBaseHeader">
                <div><h3>{knowledge.selectedBase.name}</h3>
                  {knowledge.selectedBase.description && <p>{knowledge.selectedBase.description}</p>}
                  <span>{knowledge.selectedBase.document_count} 个文档 · {knowledge.selectedBase.chunk_count} 个片段</span>
                </div>
                <button type="button" className="dangerText" disabled={locked}
                  onClick={() => setDeleting({ kind: "base", id: knowledge.selectedId, name: knowledge.selectedBase!.name })}>
                  删除知识库
                </button>
              </div>
              <label className="knowledgeUpload">上传文档
                <input type="file" accept=".md,.markdown,.txt,.pdf,.docx" multiple disabled={locked}
                  onChange={(event) => {
                    const files = Array.from(event.target.files ?? []);
                    event.target.value = "";
                    void knowledge.uploadFiles(files);
                  }} />
              </label>
              <p className="knowledgeHint">支持 UTF-8 编码的 Markdown、TXT，单文件最大 2 MB。同名文件会更新版本，相同内容不会重复入库。</p>
              <p className="knowledgeHint">Markdown 按相邻两个标题块分段，重叠一个完整块；无标题文档和 TXT 按字符分段。</p>
              {knowledge.uploads.length > 0 && (
                <ul className="knowledgeUploads" aria-label="文档入库状态" aria-live="polite">
                  {knowledge.uploads.map((upload, index) => (
                    <li key={`${index}-${upload.name}`} className={upload.status}>
                      <strong>{upload.name}</strong><span>{upload.message}</span>
                    </li>
                  ))}
                </ul>
              )}
              {knowledge.loadingDocuments ? <p role="status">正在加载文档…</p> : !knowledge.documents.length ? (
                <p className="knowledgeEmpty">这个知识库还没有文档，上传后会自动分段并建立索引。</p>
              ) : (
                <div className="knowledgeDocuments" aria-label="已入库文档">
                  {knowledge.documents.map((document) => (
                    <article className="knowledgeDocument" key={document.id}>
                      <div><strong>{document.filename}</strong>
                        <span>已就绪 · v{document.version} · {documentSize(document.byte_size)} · {document.chunk_count} 个片段</span>
                        <span>{chunkingLabel(document.chunking_strategy)}</span>
                      </div>
                      <div className="knowledgeActions">
                        <button type="button" disabled={locked} onClick={() => void knowledge.previewDocument(document)}>预览分段</button>
                        <button type="button" className="dangerText" disabled={locked}
                          onClick={() => setDeleting({ kind: "document", id: document.id, name: document.filename })}>删除</button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
              <form className="knowledgeSearch" onSubmit={(event) => { event.preventDefault(); void knowledge.search(query); }}>
                <label>检索测试（关键词）<input maxLength={200} value={query} disabled={locked}
                  placeholder="输入文档中的关键词，例如 GPU、工时" onChange={(event) => setQuery(event.target.value)} /></label>
                <button type="submit" disabled={locked || !query.trim() || !knowledge.documents.length}>
                  {knowledge.operation === "searching" ? "正在检索…" : "检索"}
                </button>
              </form>
              <p className="knowledgeHint">当前使用本地关键词检索，结果直接来自文档原文，不生成 AI 回答。</p>
              <KnowledgeEvaluation key={knowledge.selectedId} busy={locked} operation={knowledge.operation}
                documentRevision={knowledge.documents.map((document) => `${document.id}:${document.version}:${document.indexing_version}:${document.chunk_count}`).join(",")}
                onRun={knowledge.evaluate} />
              {knowledge.searchResult && (
                <section className="knowledgeResults" aria-label="检索结果">
                  <h4>“{knowledge.searchResult.query}”的检索结果</h4>
                  <p className="knowledgeHint" role="status">{retrievalFeedback(knowledge.searchResult.diagnostics, knowledge.searchResult.matches.length)}</p>
                  <p className="knowledgeHint">同一文档的重叠原文已合并。耗时包含后端候选检索与去重，不含网络传输和模型回答。每条结果下方列出它在关键词、向量两路的名次与分数，以及融合和重排序得分。</p>
                  {knowledge.searchResult.diagnostics.merge_limit_skipped > 0 && <p className="knowledgeHint">部分重叠候选超过合并长度上限，已优先保留相关性更高的结果。</p>}
                  {knowledge.searchResult.notice && <p className="knowledgeHint" role="alert">{knowledge.searchResult.notice}</p>}
                  {knowledge.searchResult.matches.length === 0 && <p>没有找到相关片段，请尝试文档中的其他关键词。</p>}
                  {knowledge.searchResult.matches.map((chunk) => (
                    <article className="knowledgeChunk" key={chunk.id}>
                      <strong>{chunk.filename} · v{chunk.document_version} · 第 {chunk.start_line}–{chunk.end_line} 行</strong>
                      {chunk.source_chunk_ids.length > 1 && <span>已合并 {chunk.source_chunk_ids.length} 个命中片段，重叠原文只保留一次</span>}
                      {chunk.ranking && <span className="knowledgeRanking">{rankingLabel(chunk.ranking)}</span>}
                      {chunk.section && <span>{chunk.section}</span>}<pre>{chunk.content}</pre>
                    </article>
                  ))}
                </section>
              )}
              {knowledge.preview && (
                <section className="knowledgeResults" aria-label="文档分段预览">
                  <h4>{knowledge.preview.document.filename} · {knowledge.preview.page.total} 个片段</h4>
                  <p className="knowledgeHint">{chunkingLabel(knowledge.preview.document.chunking_strategy)}。
                    {knowledge.preview.document.chunking_strategy === "markdown_headings" && "超过 800 字的标题块会在段落处再切开，相邻两块组成一个片段。"}</p>
                  {knowledge.preview.page.items.map((chunk) => (
                    <article className="knowledgeChunk" key={chunk.id}>
                      <strong>片段 {chunk.ordinal} · 第 {chunk.start_line}–{chunk.end_line} 行</strong>
                      {chunk.section && <span>{chunk.section}</span>}<pre>{chunk.content}</pre>
                    </article>
                  ))}
                  {knowledge.preview.page.items.length < knowledge.preview.page.total && (
                    <button type="button" disabled={locked} onClick={() => void knowledge.moreChunks()}>加载更多片段</button>
                  )}
                </section>
              )}
            </>
          )}
          {deleting && (
            <div className="knowledgeDelete" role="alertdialog" aria-label="确认删除" tabIndex={-1} ref={confirmation}>
              <p>确认删除“{deleting.name}”？{deleting.kind === "base" ? "该知识库中的文档和索引也会一并移除。" : "文档及其检索索引会一并移除。"}</p>
              <div className="knowledgeActions">
                <button type="button" disabled={knowledge.busy} onClick={() => setDeleting(null)}>取消</button>
                <button type="button" disabled={knowledge.busy} onClick={async () => {
                  const done = deleting.kind === "base" ? await knowledge.removeBase(deleting.id) : await knowledge.removeDocument(deleting.id);
                  if (done) setDeleting(null);
                }}>确认删除</button>
              </div>
            </div>
          )}
        </section>
      </div>
    </dialog>
  );
}
