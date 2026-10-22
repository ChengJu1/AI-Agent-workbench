"""记录本轮真正读取的 Skill；不将可用目录误报为加载结果。"""
from threading import Lock

from app.config import DEFAULT_SKILL_READ_BUDGET_CHARS
from app.errors import ServiceError


class SkillLoads:
    def __init__(self, budget_chars=DEFAULT_SKILL_READ_BUDGET_CHARS):
        if type(budget_chars) is not int or budget_chars < 1:
            raise ValueError("Skill 正文读取预算必须为正整数")
        self._lock = Lock()
        self._loaded = {}
        self._budget_chars = budget_chars
        self._used_chars = 0

    def record(self, skill, before_record=None):
        with self._lock:
            size = len(skill.content)
            if self._used_chars + size > self._budget_chars:
                raise ServiceError(
                    f"本轮 Skill 正文读取预算不足：剩余 {self._budget_chars - self._used_chars} 字符，"
                    f"此 Skill 需要 {size} 字符。请优先处理已读取的规则，或下一轮再读取；正文未截断。", 422,
                )
            if before_record is not None:
                before_record()
            # 重复返回全文同样占用上下文，因此每次成功读取都计入预算，引用只记一次。
            self._used_chars += size
            self._loaded.setdefault(skill.id, {"id": skill.id, "name": skill.name, "version": skill.version})
            return {"limit_chars": self._budget_chars, "used_chars": self._used_chars,
                    "remaining_chars": self._budget_chars - self._used_chars}

    def snapshot(self):
        with self._lock:
            return [dict(item) for item in self._loaded.values()]
