"""记录本轮真正读取的 Skill；不将可用目录误报为加载结果。"""
from threading import Lock


class SkillLoads:
    def __init__(self):
        self._lock = Lock()
        self._loaded = {}

    def record(self, skill):
        with self._lock:
            self._loaded.setdefault(skill.id, {"id": skill.id, "name": skill.name, "version": skill.version})

    def snapshot(self):
        with self._lock:
            return [dict(item) for item in self._loaded.values()]
