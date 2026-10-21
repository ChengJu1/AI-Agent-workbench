// Job-search kit manifest: plain data the core capability list and Agent templates read without loading the kit.
export const JOB_SEARCH_MANIFEST = {
  capability: "applications",
  name: "投递台账",
  description: "记录岗位、截止日期和进展；只读读取网申表单，按你审阅过的资料生成可逐项复制的资料包。不会替你填写或提交。",
  template: {
    id: "applications", name: "秋招投递助手", capabilities: ["applications", "files", "browser", "web"],
    description: "管理投递台账，读网申表单生成资料包，按岗位准备简历和面试。",
    hint: "投递台账 + 文件 + 浏览器 + 联网",
    prompt: "你是秋招投递助手。帮用户把岗位记进台账、读取网申表单生成资料包、按岗位描述定制简历和准备面试。只使用用户审阅过的资料，资料里没有的不要编造。你不替用户填写或提交网申，只准备和记录。",
  },
} as const;
