"""读取和检索本地制度；缓存未变化的文件，避免每次工具调用重复解析。"""
from pathlib import Path

from app.config import BACKEND_DIRECTORY

class PolicyStore:
    def __init__(self, policies_directory=None):
        if policies_directory is None:
            policies_directory = BACKEND_DIRECTORY / "data" / "policies"
        self._policies_directory = Path(policies_directory).resolve()
        self._cached_signature = None
        self._cached_policies = []

    # 列出符合条件的md文件
    def _list_policy_files(self):
        if not self._policies_directory.is_dir():
            raise FileNotFoundError(f"路径有错误: {self._policies_directory}")

        file_list = sorted(self._policies_directory.glob("*.md"))
        if not file_list:
            raise RuntimeError(f"文件目录下没有规则文件，文件目录为{self._policies_directory}")
        return file_list

    # 把文件读取出来
    def _read_policy_file(self, policy_path):
        path = Path(policy_path).resolve()
        if self._policies_directory not in path.parents:
            raise ValueError (f"您提供的目录{path}不在制度文件中")

        if not path.is_file():
            raise FileNotFoundError (f"请输入有效的文件地址，当前输入文件地址为{policy_path}")

        if path.suffix.lower( ) != ".md":
            raise ValueError ("读取到的文件不是md文件")

        content = path.read_text(encoding="utf-8").strip()

        if not content:
            raise ValueError (f"制度文件为空")

        return content

    #解析读取到的text
    def _parse_policy_file(self, policy_path):
        content = self._read_policy_file(policy_path)
        lines = content.splitlines()
        title = None
        policy_id = None
        keywords = []
        for raw_line in lines:
            line = raw_line.strip()
            # 解析title
            if title is None and line.startswith("# "):
                title = line.removeprefix("# ").strip()
            # 解析id
            if policy_id is None and line.startswith("- 制度ID:"):
                policy_id = line.removeprefix("- 制度ID:").strip()
            # 解析关键词
            if line.startswith("- 关键词:"):
                keywords_text = line.removeprefix("- 关键词:").strip()
                keywords_parts = keywords_text.split("、")

                for keyword in keywords_parts:
                    clean_keyword = keyword.strip()
                    if  clean_keyword:
                        keywords.append(clean_keyword)

        if not title:
            raise ValueError (f"md文件缺少title")
        if not policy_id:
            raise ValueError("缺少制度id")
        if not keywords:
            raise ValueError("缺少关键词描述")

        result = {"title": title,
                  "policy_id": policy_id,
                  "keywords": keywords,
                  "source": Path(policy_path).name,
                  "content": content
                  }
        return result

    # 把解析出来的policy放入到列表中
    def _load_policies(self):
        policy_files = self._list_policy_files()
        signature = []
        for policy_file in policy_files:
            resolved_path = policy_file.resolve()
            if self._policies_directory not in resolved_path.parents:
                raise ValueError("制度文件超出允许的目录")
            stat = resolved_path.stat()
            signature.append((str(resolved_path), stat.st_mtime_ns, stat.st_size))
        if signature == self._cached_signature:
            return self._cached_policies

        policies = []
        seen_policy_ids = set()
        for policy_file in policy_files:
            policy = self._parse_policy_file(policy_file)
            policy_id = policy["policy_id"]
            if policy_id in seen_policy_ids:
                raise ValueError(f"policyid重复，当前id为{policy_id}")
            seen_policy_ids.add(policy_id)
            policies.append(policy)

        self._cached_signature = signature
        self._cached_policies = policies
        return policies

    # 匹配提示词
    def search_policy(self, query):
        if not isinstance(query, str):
            raise ValueError("输入不是字符串类型")
        query_clean = query.strip().lower()
        if not query_clean:
            raise ValueError("返回的查询提示词为空")
        policies = self._load_policies()
        matches = []

        for policy in policies:
            tmp_matches = []
            for keyword in policy["keywords"]:
                if keyword.lower() in query_clean:
                    tmp_matches.append(keyword)
            if tmp_matches:
                match = {
                    "policy_id": policy["policy_id"],
                    "title": policy["title"],
                    "source": policy["source"],
                    "matched_keywords": tmp_matches
                }
                matches.append(match)

        if not matches:
            result = {
                "status": "success",
                "matches": [],
                "message": "没有找到相关制度"
            }
            return result

        result = {
            "status": "success",
            "matches": matches,
            "message": f"找到{len(matches)}条制度"
        }
        return result

    # 获取匹配文件细节
    def get_policy_detail(self, policy_id):
        if not isinstance(policy_id, str):
            raise ValueError("制度 ID 必须是字符串")
        if not policy_id.lower().strip():
            raise ValueError("制度ID不能为空")
        all_policies = self._load_policies()
        for policy in all_policies:
            if policy["policy_id"].lower().strip() == policy_id.lower().strip():
                return policy
        raise ValueError("制度ID不存在")
