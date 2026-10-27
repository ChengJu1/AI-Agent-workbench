"""按来源区间合并重叠命中；保留最高相关性位置，不改写原文。"""
import math

from app.services.document_indexing import lexical_tokens

CANDIDATE_MULTIPLIER = 3
RRF_K = 60
# 相关度判断：重排序模型只给融合去重后的前 3 组打分，不改变顺序；
# 最高分低于下限时整次结果标记为“可能不相关”，结果照常返回，由 Agent 核对。
# 取值依据见 docs/knowledge-base.md 的“相关度判断”。
RELEVANCE_GROUPS = 3
RELEVANCE_FLOOR = 0.02
# 打分只看每组中最可能含答案的一段，返回给 Agent 的仍是整组原文。
RELEVANCE_WINDOW_CHARS = 500
MAX_MERGED_CHARACTERS = 4000
RETRIEVAL_POLICY = "overlap_merge_v1"


def _overlaps(left, right):
    return (left["document_id"] == right["document_id"]
            and left["document_version"] == right["document_version"]
            and max(left["start_offset"], right["start_offset"]) < min(left["end_offset"], right["end_offset"]))


def _merge(parts, representative):
    ordered = sorted(parts, key=lambda part: (part["start_offset"], part["end_offset"]))
    content = ordered[0]["content"]
    end = ordered[0]["end_offset"]
    last = ordered[0]
    for part in ordered[1:]:
        if part["end_offset"] > end:
            content += part["content"][end - part["start_offset"]:]
            end = part["end_offset"]
            last = part
    sections = dict.fromkeys(section for part in ordered for section in part["section"].split(" → ") if section)
    return {
        **representative, "content": content, "start_offset": ordered[0]["start_offset"], "end_offset": end,
        "start_line": ordered[0]["start_line"], "end_line": last["end_line"],
        "section": " → ".join(sections)[:200],
        "source_chunk_ids": sorted({chunk_id for part in parts for chunk_id in part["source_chunk_ids"]}),
    }


def fuse_rankings(keyword, vector=(), k=RRF_K):
    """倒数排名融合（RRF）：按两路的名次而不是分数合并，关键词和向量的分数不需要可比。
    每行附上 ranking，记录它在各路的名次、原始分数和融合得分。"""
    rows = {}
    for channel, score_key, ranking in (("keyword", "keyword_score", keyword), ("vector", "similarity", vector)):
        for rank, row in enumerate(ranking, 1):
            entry = rows.setdefault(row["id"], {**row, "ranking": {"keyword_rank": None, "keyword_score": None,
                                                                    "vector_rank": None, "similarity": None, "rrf_score": 0.0}})
            entry["ranking"][channel + "_rank"] = rank
            score = row.get(score_key)
            entry["ranking"]["keyword_score" if channel == "keyword" else "similarity"] = None if score is None else round(score, 4)
            entry["ranking"]["rrf_score"] += 1 / (k + rank)
    for entry in rows.values():
        entry.pop("keyword_score", None), entry.pop("similarity", None)
        entry["ranking"]["rrf_score"] = round(entry["ranking"]["rrf_score"], 6)
    return sorted(rows.values(), key=lambda row: (-row["ranking"]["rrf_score"], row["id"]))


def relevance_window(query, section, content, size=RELEVANCE_WINDOW_CHARS):
    """从一组原文中挑出送去打分的一段：每行开头起一个窗口，按查询词的组内 IDF 求和取最高。

    不计词频和长度归一化：评估中它们会偏向常见词反复出现的段落，把负例的分数抬过下限。
    同分时取中间那个，让命中的词前后都留有上下文；一个词都没命中时取开头。
    """
    if len(content) <= size:
        return f"{section}\n{content}"
    starts = [0] + [index + 1 for index, char in enumerate(content[:-1]) if char == "\n"]
    windows = list(dict.fromkeys(content[start:start + size] for start in starts))
    lowered = [window.lower() for window in windows]
    terms = set(lexical_tokens(query))
    frequency = {term: sum(term in window for window in lowered) for term in terms}
    weight = {term: math.log((len(windows) - count + 0.5) / (count + 0.5) + 1)
              for term, count in frequency.items() if count}
    scores = [sum(value for term, value in weight.items() if term in window) for window in lowered]
    best = max(scores)
    if best <= 0:
        return f"{section}\n{content[:size]}"
    tied = [index for index, score in enumerate(scores) if score == best]
    return f"{section}\n{windows[tied[len(tied) // 2]]}"


def assess_relevance(groups, scores, floor=RELEVANCE_FLOOR):
    """把相关度写入前几组的排序明细；返回 (新的组列表, 最高相关度, 是否低于下限)。"""
    head = [{**group, "ranking": {**group["ranking"], "rerank_score": round(score, 4)}}
            for group, score in zip(groups, scores)]
    best = max(scores, default=None)
    return head + groups[len(head):], best, best is not None and best < floor


def deduplicate_matches(candidates, max_characters=MAX_MERGED_CHARACTERS):
    # 输入按 BM25 排名排序；输出组保留其中最佳命中的排名和代表 id。
    groups = []
    skipped = 0
    for candidate in candidates:
        candidate = {**candidate, "source_chunk_ids": [candidate["id"]]}
        overlapping = [index for index, group in enumerate(groups) if _overlaps(candidate, group)]
        if not overlapping:
            groups.append(candidate)
            continue
        parts = [groups[index] for index in overlapping] + [candidate]
        start = min(part["start_offset"] for part in parts)
        end = max(part["end_offset"] for part in parts)
        # 单个已有长片段不截断，但不让相邻命中无限串联为整篇文档。
        if end - start > max_characters:
            skipped += 1
            continue
        first = overlapping[0]
        groups[first] = _merge(parts, groups[first])
        for index in reversed(overlapping[1:]):
            del groups[index]
    return groups, skipped
