"""笔记 MCP 的版本化来源协议：工具返回引用链接，运行时保存同一原文快照。"""
import json

from app.services.knowledge_evidence import KnowledgeEvidence


SCHEMA = "workbench.notes.v1"
NOTE_ACTIONS = {"list_note_collections", "list_notes", "search_notes", "read_note"}


def notes_servers(agent):
    return {tool.name for tool in agent.tools if getattr(tool, "type", None) == "mcp"
            and NOTE_ACTIONS.intersection(tool.actions)}


def annotate_notes_result(action, result):
    evidence = KnowledgeEvidence()
    if action == "search_notes":
        for group in result["collections"]:
            annotated = evidence.record({"query": result["query"], "channel": "notes_mcp",
                "knowledge_base_id": group["collection_id"], "knowledge_base_name": group["collection_name"],
                "matches": group["matches"]})
            group["matches"] = annotated["matches"]
        # 没有开放分类时，同样记录一次成功但无匹配的查询。
        if not result["collections"]:
            evidence.record({"query": result["query"], "channel": "notes_mcp",
                "knowledge_base_id": "none", "knowledge_base_name": "笔记", "matches": []})
    elif action == "read_note":
        matches = [{"document_id": result["document_id"], "document_version": result["document_version"],
                    "filename": result["filename"], "section": "原文读取", "start_offset": result["offset"],
                    "end_offset": result["offset"] + len(result["content"]),
                    "start_line": result["start_line"], "end_line": result["end_line"],
                    "content": result["content"]}] if result["content"] else []
        annotated = evidence.record({"query": f"读取：{result['filename']}", "channel": "notes_mcp",
            "knowledge_base_id": result["collection_id"], "knowledge_base_name": result["collection_name"],
            "matches": matches})
        if annotated["matches"]:
            result.update({key: annotated["matches"][0][key] for key in ("citation_id", "citation_link")})
    else:
        return result
    return {**result, "schema": SCHEMA, "evidence": evidence.snapshot()[1]}


class NotesEvidenceTracker:
    def __init__(self, evidence, servers):
        self.evidence = evidence
        self.servers = servers

    def capture(self, call, content, failed):
        if call["tool_name"] not in self.servers or call["action"] not in NOTE_ACTIONS:
            return
        self.evidence.record_notes_call()
        if failed:
            self.evidence.record_failure()
            return
        if call["action"] not in {"search_notes", "read_note"}:
            return
        try:
            if isinstance(content, list):
                texts = [part["text"] for part in content if isinstance(part, dict) and part.get("type") == "text"]
                if len(texts) != 1:
                    raise ValueError("笔记工具应返回一个 JSON 结果")
                content = texts[0]
            if not isinstance(content, str) or len(content) > 4_000_000:
                raise ValueError("笔记结果格式无效或过大")
            payload = json.loads(content)
            if payload.get("schema") != SCHEMA:
                raise ValueError("笔记来源协议版本不匹配")
            self.evidence.merge_notes(payload["evidence"])
        except (ValueError, TypeError, KeyError, AttributeError):
            # 不能从回答文字猜测引用；不完整或旧版结果不升级成已核验来源。
            self.evidence.record_failure()
