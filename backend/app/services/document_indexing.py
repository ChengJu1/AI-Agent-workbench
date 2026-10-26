"""把 UTF-8 文档分段，保留来源位置；建立中文双字词及英文词的关键词索引。"""
import re
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import PurePosixPath

from markdown_it import MarkdownIt


CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
INDEXING_VERSION = "md-heading-overlap-v2"
MARKDOWN_STRATEGY = "markdown_headings"
CHARACTER_STRATEGY = "characters"
SEPARATORS = ("\n\n", "\n", "。", "！", "？", ". ")
WORD_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]+")


def lexical_tokens(text, include_characters=False):
    tokens = []
    for match in WORD_PATTERN.finditer(text.lower()):
        word = match.group()
        if "\u3400" <= word[0] <= "\u9fff":
            if include_characters or len(word) == 1:
                tokens.extend(word)
            tokens.extend(word[index:index + 2] for index in range(len(word) - 1))
        else:
            tokens.append(word)
    return tokens


def search_expression(query):
    terms = list(dict.fromkeys(lexical_tokens(query)))[:40]
    return " OR ".join(f'"{term}"' for term in terms)


@dataclass(frozen=True)
class DocumentIndex:
    chunks: list[dict]
    strategy: str


def _chunk(text, start, end, newlines, ordinal, section):
    raw = text[start:end]
    content = raw.strip()
    if not content:
        return None
    content_start = start + len(raw) - len(raw.lstrip())
    content_end = content_start + len(content)
    return {
        "ordinal": ordinal, "content": content, "section": section[:200],
        "start_offset": content_start, "end_offset": content_end,
        "start_line": bisect_right(newlines, content_start) + 1,
        "end_line": bisect_right(newlines, content_end - 1) + 1,
        "tokens": " ".join(lexical_tokens(content, include_characters=True)),
    }


def _markdown_headings(text, line_starts):
    # 首部 YAML 元数据保留为前言，但不把其中的 --- 识别成 Setext 标题。
    lines = text.split("\n")
    parsed_text = text
    if lines and lines[0].strip() == "---":
        for end in range(1, len(lines)):
            if lines[end].strip() in ("---", "..."):
                parsed_text = "\n" * (end + 1) + "\n".join(lines[end + 1:])
                break
    tokens = MarkdownIt("commonmark").enable("table").parse(parsed_text)
    headings = []
    stack = []
    for index, token in enumerate(tokens):
        # 嵌套在引用、列表或代码中的内容不作为文档的标题边界。
        if token.type != "heading_open" or token.level != 0 or token.map is None:
            continue
        level = int(token.tag[1:])
        title = tokens[index + 1].content.strip()[:200] or "（空标题）"
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        headings.append((line_starts[token.map[0]], " / ".join(item[1] for item in stack)[:200]))
    return headings


def _split_characters(text, chunk_size, overlap, newlines):
    if chunk_size < 2 or overlap < 0 or overlap >= chunk_size // 2:
        raise ValueError("分段长度和重叠长度不正确")
    headings = list(re.finditer(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.MULTILINE))
    heading_offsets = [heading.start() for heading in headings]
    heading_sections = [heading.group(1).strip()[:200] for heading in headings]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            for separator in SEPARATORS:
                boundary = text.rfind(separator, start + chunk_size // 2, end)
                if boundary >= 0:
                    end = boundary + len(separator)
                    break
        raw = text[start:end]
        content_start = start + len(raw) - len(raw.lstrip())
        heading_index = bisect_right(heading_offsets, content_start) - 1
        section = heading_sections[heading_index] if heading_index >= 0 else ""
        chunk = _chunk(text, start, end, newlines, len(chunks) + 1, section)
        if chunk is not None:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _piece_starts(text, start, end, size):
    """Split one long heading block at paragraph or sentence ends, so no piece exceeds size."""
    starts = [start]
    while end - starts[-1] > size:
        current = starts[-1]
        cut = current + size
        for separator in SEPARATORS:
            boundary = text.rfind(separator, current + size // 2, current + size)
            if boundary >= 0:
                cut = boundary + len(separator)
                break
        starts.append(cut)
    return starts


def index_document(text, filename="document.md", chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    newlines = [match.start() for match in re.finditer("\n", text)]
    if PurePosixPath(filename).suffix.lower() in (".md", ".markdown"):
        headings = _markdown_headings(text, [0] + [position + 1 for position in newlines])
        if headings:
            blocks = list(headings)
            if text[:headings[0][0]].strip():
                blocks.insert(0, (0, "前言"))
            # 超长的标题块按段落再切开，两块相邻组合后也不超过 2 × chunk_size。
            blocks = [(offset, title) for index, (start, title) in enumerate(blocks)
                      for offset in _piece_starts(text, start, blocks[index + 1][0] if index + 1 < len(blocks) else len(text), chunk_size)]
            chunks = []
            # A+B、B+C、C+D：每次前进一步，重叠完整的一个标题块。
            for index in range(max(1, len(blocks) - 1)):
                end = blocks[index + 2][0] if index + 2 < len(blocks) else len(text)
                section = " → ".join(dict.fromkeys(block[1] for block in blocks[index:index + 2]))
                chunk = _chunk(text, blocks[index][0], end, newlines, len(chunks) + 1, section)
                if chunk is not None:
                    chunks.append(chunk)
            return DocumentIndex(chunks, MARKDOWN_STRATEGY)
    return DocumentIndex(_split_characters(text, chunk_size, overlap, newlines), CHARACTER_STRATEGY)


def split_document(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP, *, filename="document.md"):
    return index_document(text, filename, chunk_size, overlap).chunks
