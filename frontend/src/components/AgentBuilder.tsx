import { useEffect, useRef, useState } from "react";
import {
  buildLabels, fetchBuild, fetchBuilds, fetchBuildRuntime, fetchPackages, publishBuild, reviseBuild, startBuild, working,
  type Build, type BuildRuntime, type BuildSummary, type CapabilityPackage,
} from "../api/builds";
import type { AgentInfo } from "../types";
import { MarkdownContent } from "./MarkdownContent";
import "./AgentBuilder.css";

export function AgentBuilder({ onClose, onManual, onCreated }: {
  onClose: () => void; onManual: () => void; onCreated: (agent: AgentInfo) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [build, setBuild] = useState<Build | null>(null);
  const [recent, setRecent] = useState<BuildSummary[]>([]);
  const [packages, setPackages] = useState<CapabilityPackage[]>([]);
  const [runtime, setRuntime] = useState<BuildRuntime | null>(null);
  const [base, setBase] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const mutation = useRef(false);
  const requests = useRef(new Set<AbortController>());
  const startId = useRef(crypto.randomUUID());
  const log = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    const controller = new AbortController();
    void Promise.all([fetchBuilds(controller.signal), fetchPackages(controller.signal), fetchBuildRuntime(controller.signal)])
      .then(([builds, list, status]) => { setRecent(builds); setPackages(list); setRuntime(status); })
      .catch((caught) => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "读取失败。"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    const active = requests.current;
    return () => { controller.abort(); active.forEach((item) => item.abort()); element?.close(); };
  }, []);

  useEffect(() => {
    if (!build || !working(build.status)) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const id = build.id;
    async function poll() {
      try {
        const updated = await fetchBuild(id, controller.signal);
        if (controller.signal.aborted) return;
        setBuild(updated);
        setError("");
        if (!working(updated.status)) {
          setRecent((current) => current.map((item) => item.id === updated.id ? { id: updated.id, name: updated.plan?.name || item.name, status: updated.status } : item));
          return;
        }
      } catch (caught) {
        if (controller.signal.aborted) return;
        setError(caught instanceof Error ? caught.message : "读取进度失败，将自动重试。");
      }
      timer = setTimeout(() => { void poll(); }, 2000);
    }
    timer = setTimeout(() => { void poll(); }, 1200);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [build?.id, build?.status]);

  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight, behavior: "smooth" }); }, [build?.history.length, build?.status]);

  async function action(callback: (signal: AbortSignal) => Promise<void>) {
    if (mutation.current) return;
    mutation.current = true; setPending(true); setError("");
    const controller = new AbortController(); requests.current.add(controller);
    try { await callback(controller.signal); }
    catch (caught) { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "操作失败，请重试。"); }
    finally { requests.current.delete(controller); mutation.current = false; if (!controller.signal.aborted) setPending(false); }
  }

  const inProgress = working(build?.status);
  const canEdit = !build || (!inProgress && build.status !== "published");
  return <dialog className="agentEditor agentBuilder" ref={dialog} aria-labelledby="builderTitle"
    onCancel={(event) => { event.preventDefault(); if (!pending) onClose(); }}>
    <header className="builderHeader">
      <div><span className="builderEyebrow">WORKBENCH · 构建助手</span><h2 id="builderTitle">描述需求，创建你的 Agent</h2>
        <p className="agentEditorHint">一起明确规则，编写可复用方法，测试通过后再创建。</p></div>
      <button type="button" disabled={pending} onClick={onClose} aria-label="关闭构建助手">关闭</button>
    </header>
    <div className="builderToolbar">
      <label>构建记录<select aria-label="打开构建记录" disabled={pending || loading} value={build?.id || ""}
        onChange={(event) => { const id = event.target.value; if (!id) { setBuild(null); setMessage(""); startId.current = crypto.randomUUID(); return; }
          void action(async (signal) => { const selected = await fetchBuild(id, signal); if (!signal.aborted) { setBuild(selected); setMessage(""); } }); }}>
        <option value="">新的构建</option>{recent.map((item) => <option key={item.id} value={item.id}>{item.id === build?.id ? build.plan?.name || item.name : item.name} · {buildLabels[item.id === build?.id ? build.status : item.status]}</option>)}
        {build && !recent.some((item) => item.id === build.id) && <option value={build.id}>{build.plan?.name || "当前构建"}</option>}
      </select></label>
      <button type="button" disabled={pending} onClick={onManual}>高级手动配置</button>
    </div>
    <div className="builderBody">
      <section className="builderConversation" aria-label="与构建助手讨论需求">
        <div className="builderLog" ref={log}>
          {!build ? <div className="builderIntro"><span className="builderSpark">✦</span><h3>把重复工作，变成一个 Agent</h3>
            <p>说清楚输入是什么、要遵循哪些规则、希望得到什么结果。构建助手会提出问题，并编写实际执行的方法。</p>
            <button type="button" onClick={() => setMessage("创建一个销售汇总 Agent：我提供 JSON 订单数组，每条包含 category 和 amount。按 category 汇总金额，保留两位小数，返回各分类汇总与总额；空数组返回零。")}>试试：按类别汇总订单</button>
            <p className="builderScope">当前支持文本、CSV 和 JSON 数据处理。需要文件或外部系统连接时，可使用高级手动配置。</p>
          </div> : <>
            {build.history.map((item, index) => <article className={`builderBubble ${item.role}`} key={index}>
              <span>{item.role === "user" ? "你" : "构建助手"}</span><MarkdownContent>{item.content}</MarkdownContent>
            </article>)}
            {inProgress && <p className="builderProgress" role="status"><span className="builderPulse" />{buildLabels[build.status]}…<small>关闭窗口后仍会继续，可从构建记录返回。</small></p>}
            {build.error && <p className="agentEditorError" role="alert">{build.error}</p>}
          </>}
        </div>
        {canEdit ? <form className="builderComposer" onSubmit={(event) => {
          event.preventDefault(); if (!message.trim() || inProgress) return;
          void action(async (signal) => {
            const updated = build ? await reviseBuild(build, message.trim(), signal)
              : await startBuild(startId.current, message.trim(), base || null, signal);
            if (!signal.aborted) { setBuild(updated); setMessage(""); setRecent(await fetchBuilds(signal)); }
          });
        }}>
          {!build && packages.length > 0 && <label className="builderBase">起点<select aria-label="构建起点" value={base} disabled={pending} onChange={(event) => { setBase(event.target.value); startId.current = crypto.randomUUID(); }}>
            <option value="">从零创建</option>{packages.map((item) => <option key={item.id} value={item.id}>基于 {item.name} · v{item.version} 创建新版本</option>)}
          </select></label>}
          <textarea autoFocus aria-label="描述 Agent 需求" maxLength={8000} rows={4} disabled={pending || loading}
            placeholder={build ? "回答问题，或补充你希望调整的规则…" : "例如：我每周会收到订单 CSV，希望按地区汇总销售额，找出退款和异常记录…"}
            value={message} onChange={(event) => { setMessage(event.target.value); if (!build) startId.current = crypto.randomUUID(); }} />
          <div><small>{runtime?.available ? "方法在独立环境测试，不自动读取本机文件。" : loading ? "正在检查执行环境…" : runtime?.message || "执行环境状态读取失败，请关闭后重试。"}</small>
            <button type="submit" className="primaryButton" disabled={pending || loading || !runtime?.available || !message.trim()}>{pending ? "正在提交…" : build ? "提交调整" : "开始构建"}</button></div>
        </form> : build?.status === "published" ? <div className="builderPublished">Agent 已保存，原有版本仍然可用。<button type="button" className="primaryButton" disabled={pending} onClick={() => { if (build.published_agent) { onCreated(build.published_agent); onClose(); } }}>切换并使用</button></div> : null}
      </section>
      <aside className="builderPreview" aria-label="Agent 方案与测试结果">
        <span className="builderEyebrow">生成的能力</span>
        {build?.plan?.tools.length ? <>
          <h3>{build.plan.name}</h3><p>{build.plan.description}</p>
          <span className={`builderBadge ${build.status === "ready" || build.status === "published" ? "passed" : ""}`}>{buildLabels[build.status]}</span>
          {build.plan.tools.map((tool) => <div className="builderMethod" key={tool.name}><strong>{tool.name}</strong><p>{tool.description}</p>
            <details><summary>查看实现与输入输出</summary><MarkdownContent>{`\`\`\`python\n${tool.code}\n\`\`\`\n\n**输入**\n\`\`\`json\n${JSON.stringify(tool.input_schema, null, 2)}\n\`\`\`\n\n**输出**\n\`\`\`json\n${JSON.stringify(tool.output_schema, null, 2)}\n\`\`\``}</MarkdownContent></details>
          </div>)}
          {build.tests.length > 0 && <section className="builderTests"><h4>实际测试 · {build.tests.filter((test) => test.passed).length}/{build.tests.length} 通过</h4>
            <ul>{build.tests.map((test, index) => <li key={index}><span aria-label={test.passed ? "通过" : "失败"}>{test.passed ? "✓" : "!"}</span><div>{test.name}<small>{test.method}{test.error ? ` · ${test.error}` : ""}</small></div></li>)}</ul></section>}
          <details className="builderPrompt"><summary>Agent 工作规则</summary><MarkdownContent>{build.plan.system_prompt}</MarkdownContent></details>
          <p className="builderVersion">创建为独立能力包 v{build.base_version + 1}。旧 Agent 固定使用原版本。</p>
        </> : <div className="builderEmpty"><p>明确需求后，这里会展示：</p><ol><li>Agent 的职责和工作规则</li><li>现场编写的方法</li><li>实际运行的测试结果</li></ol><small>测试通过后，由你决定是否创建。</small></div>}
      </aside>
    </div>
    <footer className="builderFooter"><span>{build ? buildLabels[build.status] : "从需求开始，逐步明确能力"}</span>
      {build?.status === "ready" && <button type="button" className="primaryButton" disabled={pending} onClick={() => {
        void action(async (signal) => { const agent = await publishBuild(build, signal); if (!signal.aborted) { onCreated(agent); onClose(); } });
      }}>{pending ? "正在保存…" : "创建并使用"}</button>}
    </footer>
    {error && <p className="agentEditorError" role="alert">{error}</p>}
  </dialog>;
}
