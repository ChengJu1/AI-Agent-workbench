import { useEffect, useRef, useState } from "react";
import { fetchEvaluationSuite } from "../api/knowledge";
import { downloadEvaluationJson, MAX_SUITE_BYTES, parseRetrievalSuite, percentage } from "../lib/retrievalEvaluation";
import type { RetrievalReport, RetrievalSuite } from "../types";
import { chunkingLabel, milliseconds, retrievalFeedback } from "../lib/knowledge";
import "./KnowledgeEvaluation.css";

type Props = {
  busy: boolean;
  operation: string;
  documentRevision: string;
  onRun: (suite: RetrievalSuite) => Promise<RetrievalReport | undefined>;
};

const categories = { keyword: "关键词", question: "问句", paraphrase: "同义词挑战", negative: "空结果" };
const statuses = { passed: "通过", failed: "失败", not_applicable: "不适用" };

export function KnowledgeEvaluation({ busy, operation, documentRevision, onRun }: Props) {
  const [suite, setSuite] = useState<RetrievalSuite | null>(null);
  const [report, setReport] = useState<RetrievalReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [filter, setFilter] = useState<"all" | "attention">("attention");
  const alive = useRef(true);
  const importGeneration = useRef(0);
  const submitting = useRef(false);
  const disabled = busy || loading || importing;

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; importGeneration.current += 1; };
  }, []);
  useEffect(() => { setReport(null); }, [documentRevision]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void fetchEvaluationSuite(controller.signal).then((result) => {
      if (!controller.signal.aborted) { setSuite(result); setReport(null); }
    }).catch((error) => {
      if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "题集读取失败。");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt]);

  const visibleResults = report?.results.filter((result) => filter === "all" || result.status !== "passed") ?? [];

  return <details className="knowledgeEvaluation">
    <summary>批量检索评估</summary>
    <p className="knowledgeHint">用已知问题检查目标文档、关键原文和来源位置。只运行本地检索，不调用模型，也不给回答自动判对错。</p>
    {loading && <p role="status">正在读取示例题集…</p>}
    {error && <p className="knowledgeError" role="alert">{error}</p>}
    {suite && <>
      <h4>{suite.name} · {suite.cases.length} 题</h4>
      <p className="knowledgeHint">{suite.description}</p>
      <div className="evaluationControls">
        <label>每题返回条数<select value={suite.limit} disabled={disabled} onChange={(event) => {
          setSuite({ ...suite, limit: Number(event.target.value) }); setReport(null);
        }}>{[1, 3, 5, 10, 20].map((limit) => <option key={limit} value={limit}>{limit}</option>)}</select></label>
        <button type="button" disabled={disabled} onClick={async () => {
          if (submitting.current) return;
          submitting.current = true;
          setError("");
          setReport(null);
          try {
            const result = await onRun(suite);
            if (alive.current && result) {
              setReport(result);
              setFilter(result.summary.failed || result.summary.not_applicable ? "attention" : "all");
            }
          } finally { submitting.current = false; }
        }}>{operation === "evaluating" ? "正在评估…" : "运行评估"}</button>
        <button type="button" disabled={disabled} onClick={() => downloadEvaluationJson("retrieval-suite.json", suite)}>导出题集</button>
      </div>
    </>}
    <div className="evaluationControls">
      <label className="evaluationImport">导入自己的题集（JSON，最大 100 KB）
        <input type="file" accept=".json,application/json" disabled={disabled} onChange={async (event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (!file) return;
          const generation = ++importGeneration.current;
          setImporting(true);
          setError("");
          try {
            if (file.size > MAX_SUITE_BYTES) throw new Error("题集文件不能超过 100 KB。");
            const result = parseRetrievalSuite(await file.text());
            if (alive.current && generation === importGeneration.current) { setSuite(result); setReport(null); }
          } catch (error) {
            if (alive.current && generation === importGeneration.current) setError(error instanceof Error ? error.message : "导入失败。");
          } finally { if (alive.current && generation === importGeneration.current) setImporting(false); }
        }} />
      </label>
      <button type="button" disabled={disabled} onClick={() => { importGeneration.current += 1; setAttempt((value) => value + 1); }}>重新读取示例题集</button>
    </div>
    {report && <section className="evaluationReport" aria-label="检索评估报告" aria-live="polite">
      <h4>通过 {report.summary.passed} / {report.summary.evaluated} 道有效题</h4>
      <p className="knowledgeHint">{new Date(report.created_at).toLocaleString()} · {report.knowledge_base_name} · 关键词 + BM25</p>
      <p className="knowledgeHint">本轮评估 {milliseconds(report.elapsed_ms)} · 单题检索平均 {milliseconds(report.average_retrieval_ms)}（含去重，不含网络与模型耗时）</p>
      <p className="knowledgeHint">按原文位置合并重叠结果 · 候选数为返回上限的 {report.candidate_multiplier} 倍 · 合并扩展上限 {report.max_merged_characters} 字符，已有长片段不截断</p>
      <p className="knowledgeHint">分段策略：{report.chunk_unit === "heading_blocks" ? chunkingLabel("markdown_headings")
        : report.chunk_unit === "characters" ? chunkingLabel("characters")
          : report.chunk_unit === "mixed" ? "按文档分别使用标题块或字符分段，详见本次文档版本" : "暂无文档"}</p>
      {report.summary.not_applicable > 0 && <p className="evaluationWarning">有 {report.summary.not_applicable} 题不适用（缺少文档或预期原文已变化），评估不完整。下列比例只统计 {report.summary.evaluated} 道有效题。</p>}
      <div className="evaluationMetrics">
        <div><span>有效题通过率</span><strong>{percentage(report.summary.pass_rate)}</strong><small>{report.summary.passed} / {report.summary.evaluated}</small></div>
        <div><span>正例首条命中</span><strong>{percentage(report.summary.top1_hit_rate)}</strong><small>{report.summary.top1_hits} / {report.summary.positive_evaluated}</small></div>
        <div><span>正例前 {report.suite.limit} 条命中</span><strong>{percentage(report.summary.top_k_hit_rate)}</strong><small>{report.summary.top_k_hits} / {report.summary.positive_evaluated}</small></div>
        <div><span>空结果判断正确</span><strong>{percentage(report.summary.negative_accuracy)}</strong><small>{report.summary.negative_correct} / {report.summary.negative_evaluated}</small></div>
      </div>
      <p className="knowledgeHint">正例需要在同一片段中命中指定文件和全部关键原文；空结果题必须返回零片段。报告对应运行时文档版本，资料变化后请重新评估。</p>
      <div className="evaluationControls">
        <label>显示题目<select value={filter} onChange={(event) => setFilter(event.target.value as "all" | "attention")}>
          <option value="attention">失败与不适用</option><option value="all">全部题目</option>
        </select></label>
        <button type="button" onClick={() => downloadEvaluationJson("retrieval-report.json", report)}>导出报告</button>
      </div>
      {!visibleResults.length && <p>当前筛选下没有题目。</p>}
      <div className="evaluationCases">{visibleResults.map((result) => <details className={`evaluationCase ${result.status}`} key={result.case.id}>
        <summary><span>{statuses[result.status]}</span> {result.case.query} <small>{categories[result.case.expect_no_match ? "negative" : result.case.category]}</small></summary>
        <p>{result.reason}</p>
        <p className="knowledgeHint">题目：{result.case.id} · 来源位置：{result.matches.length ? result.source_positions_valid ? "一致" : "不一致" : "无返回片段"}</p>
        <p className="knowledgeHint">{retrievalFeedback(result.diagnostics, result.matches.length)}</p>
        <p>预期：{result.case.expect_no_match ? "没有匹配片段" : `${result.case.expected_filename}；${result.case.expected_texts.join(" / ")}`}</p>
        {result.matches.map((match, index) => <article className="knowledgeChunk" key={match.id}>
          <strong>第 {index + 1} 条 · {match.filename} · v{match.document_version} · 第 {match.start_line}–{match.end_line} 行</strong>
          {match.source_chunk_ids.length > 1 && <span>已合并 {match.source_chunk_ids.length} 个命中片段</span>}
          <pre>{match.content}</pre>
        </article>)}
      </details>)}</div>
      <details className="evaluationDocuments"><summary>本次文档版本（{report.documents.length}）</summary>
        <ul>{report.documents.map((document) => <li key={document.id}>{document.filename} · v{document.version} · {chunkingLabel(document.chunking_strategy)}</li>)}</ul>
      </details>
    </section>}
  </details>;
}
