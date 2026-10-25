import { useEffect, useState } from "react";
import { addCodeProject, browseDirectories, fetchCodeProjects, removeCodeProject, type CodeProject, type LocalDirectory } from "../api/platform";

// Bindings save immediately; the Agent can only read them once the "code" capability is saved too.
export function CodeProjects({ agentId }: { agentId: string }) {
  const [projects, setProjects] = useState<CodeProject[]>([]);
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [browsing, setBrowsing] = useState<LocalDirectory | null>(null);
  const bind = (target: string) => run(async () => {
    const added = await addCodeProject(agentId, target);
    setProjects((items) => [...items, added]); setPath(""); setBrowsing(null);
    setMessage(`已绑定 ${added.name}：${added.file_count} 个可读文件${added.files_truncated ? "（超过上限，只显示前 20000 个）" : ""}。`);
  });
  const open = (target?: string) => { setError(""); void browseDirectories(target).then(setBrowsing).catch((caught) => setError(caught instanceof Error ? caught.message : "无法读取目录。")); };
  useEffect(() => {
    const controller = new AbortController();
    void fetchCodeProjects(agentId, controller.signal).then((result) => { if (!controller.signal.aborted) setProjects(result.projects); })
      .catch((caught) => { if (!controller.signal.aborted) setError(caught.message); });
    return () => controller.abort();
  }, [agentId]);
  const run = async (task: () => Promise<void>) => {
    setBusy(true); setError(""); setMessage("");
    try { await task(); } catch (caught) { setError(caught instanceof Error ? caught.message : "操作失败。"); } finally { setBusy(false); }
  };
  return <fieldset className="capabilityPicker codeProjects">
    <legend>项目代码 · 绑定的目录（最多 3 个）</legend>
    {projects.length === 0 && <small>还没有绑定项目。填写后端所在电脑上项目目录的完整路径。</small>}
    <ul>{projects.map((project) => <li key={project.id}>
      <span><strong>{project.name}</strong>{project.git && <em>git</em>}{!project.available && <em className="codeMissing">目录不可用</em>}<small>{project.root}</small></span>
      <button disabled={busy} onClick={() => void run(async () => { await removeCodeProject(agentId, project.id); setProjects((items) => items.filter((item) => item.id !== project.id)); })}>移除</button>
    </li>)}</ul>
    <form onSubmit={(event) => { event.preventDefault(); const value = path.trim(); if (value) void bind(value); }}>
      <input value={path} disabled={busy || projects.length >= 3} placeholder="/Users/you/projects/my-app" aria-label="项目目录路径" onChange={(event) => setPath(event.target.value)} />
      <button type="button" disabled={busy || projects.length >= 3} onClick={() => browsing ? setBrowsing(null) : open(path.trim() || undefined)}>{browsing ? "收起" : "浏览…"}</button>
      <button disabled={busy || !path.trim() || projects.length >= 3}>{busy ? "处理中…" : "绑定"}</button>
    </form>
    {browsing && <div className="codeBrowser">
      <div className="codeBrowserBar">
        <button type="button" disabled={!browsing.parent} onClick={() => browsing.parent && open(browsing.parent)} aria-label="上一级">↑</button>
        <code title={browsing.path}>{browsing.path}</code>
        <button type="button" className="primaryButton" disabled={busy} onClick={() => void bind(browsing.path)}>绑定此目录</button>
      </div>
      <ul>{browsing.directories.map((entry) => <li key={entry.path}>
        <button type="button" onClick={() => open(entry.path)} onDoubleClick={() => void bind(entry.path)}>📁 {entry.name}{entry.git && <em>git</em>}</button>
      </li>)}</ul>
      {browsing.directories.length === 0 && <small>没有子目录。</small>}
      {browsing.truncated && <small>子目录太多，只显示前 500 个。</small>}
    </div>}
    <small>只读：Agent 不能修改或运行代码；遵守 .gitignore，.env、私钥等文件不可见，代码中的密钥会被遮盖。</small>
    {message && <small role="status">{message}</small>}
    {error && <p className="agentEditorError" role="alert">{error}</p>}
  </fieldset>;
}
