import { useEffect, useState } from "react";
import { addCodeProject, fetchCodeProjects, removeCodeProject, type CodeProject } from "../api/platform";

// Bindings save immediately; the Agent can only read them once the "code" capability is saved too.
export function CodeProjects({ agentId }: { agentId: string }) {
  const [projects, setProjects] = useState<CodeProject[]>([]);
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
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
    <form onSubmit={(event) => { event.preventDefault(); const value = path.trim(); if (!value) return; void run(async () => {
      const added = await addCodeProject(agentId, value);
      setProjects((items) => [...items, added]); setPath("");
      setMessage(`已绑定 ${added.name}：${added.file_count} 个可读文件${added.files_truncated ? "（超过上限，只显示前 20000 个）" : ""}。`);
    }); }}>
      <input value={path} disabled={busy || projects.length >= 3} placeholder="/Users/you/projects/my-app" aria-label="项目目录路径" onChange={(event) => setPath(event.target.value)} />
      <button disabled={busy || !path.trim() || projects.length >= 3}>{busy ? "处理中…" : "绑定"}</button>
    </form>
    <small>只读：Agent 不能修改或运行代码；遵守 .gitignore，.env、私钥等文件不可见，代码中的密钥会被遮盖。</small>
    {message && <small role="status">{message}</small>}
    {error && <p className="agentEditorError" role="alert">{error}</p>}
  </fieldset>;
}
