"""只构造用途目录；目录过大时由搜索工具分页返回，不扩充系统提示。"""
import json


CATALOG_MAX_CHARS = 12000


def catalog_entry(skill):
    return {"skill_id": skill.id, "name": skill.name, "description": skill.description, "version": skill.version}


def inline_catalog(skills):
    entries = []
    size = 2
    for skill in skills:
        entry = catalog_entry(skill)
        size += len(json.dumps(entry, ensure_ascii=False)) + (2 if entries else 0)
        if size > CATALOG_MAX_CHARS:
            return None
        entries.append(entry)
    return json.dumps(entries, ensure_ascii=False)
