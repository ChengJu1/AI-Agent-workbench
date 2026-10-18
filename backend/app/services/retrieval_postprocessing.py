"""按来源区间合并重叠命中；保留最高相关性位置，不改写原文。"""

CANDIDATE_MULTIPLIER = 3
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
