"""解析单文件 SKILL.md；只接受文本规则，不安装脚本或启用工具。"""
import yaml
from pydantic import ValidationError

from app.errors import ServiceError
from app.models.skills import SkillImportPreview


def preview_skill(request):
    if not request.filename.lower().endswith(".md"):
        raise ServiceError("请选择 Markdown 格式的 SKILL.md 文件。", 422)
    if len(request.content.encode("utf-8")) > 128 * 1024 or "\x00" in request.content:
        raise ServiceError("文件不能超过 128 KB，且必须是有效文本。", 422)
    text = request.content.removeprefix("\ufeff").replace("\r\n", "\n")
    lines = text.split("\n")
    if lines[0].strip() != "---":
        raise ServiceError("SKILL.md 顶部需要 --- 分隔的元信息，包含 name 和 description。", 422)
    end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end is None:
        raise ServiceError("Skill 元信息缺少结束分隔符 ---。", 422)
    header = "\n".join(lines[1:end])
    if len(header) > 8192:
        raise ServiceError("Skill 元信息过长。", 422)
    try:
        if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for token in yaml.scan(header)):
            raise ValueError("不支持 YAML 锚点")
        metadata = yaml.safe_load(header)
        if not isinstance(metadata, dict):
            raise ValueError("元信息需要是键值结构")
        if any(not isinstance(key, str) for key in metadata):
            raise ValueError("元信息字段名需要是文本")
        return SkillImportPreview(
            name=metadata.get("name"), description=metadata.get("description"),
            content="\n".join(lines[end + 1:]),
            ignored_fields=sorted(key for key in metadata if key not in ("name", "description")),
        )
    except (yaml.YAMLError, ValueError, TypeError, RecursionError, ValidationError) as error:
        raise ServiceError("无法解析 Skill，请检查 name、description 和非空正文；不支持 YAML 标签对象或锚点。", 422) from error
