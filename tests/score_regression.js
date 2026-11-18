// 打分逻辑回归：用真实风格的 JD 文本验证分数是否合理
const core = ['Python', 'Agent|智能体', 'LLM|大模型', 'RAG|检索增强|知识库', 'LangChain|LangGraph', 'Prompt|提示词'];
const bonus = ['FastAPI', 'Docker', 'SQL', '向量数据库|向量检索', '工具调用|Function Calling', 'MCP', '微调|Fine-tune', '多模态'];
const exclude = ['java', '后端', '服务端', '产品经理', '销售', '客服', '运营', '标注', '训练师'];

function scoreJd(text) {
  const banned = exclude.find((w) => text.includes(w));
  if (banned) return { score: 0, banned, hits: [] };
  const items = [
    ...core.map((w) => ({ w, weight: 3 })),
    ...bonus.map((w) => ({ w, weight: 1 })),
  ];
  const total = items.reduce((s, i) => s + i.weight, 0);
  let got = 0;
  const hits = [];
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  for (const it of items) {
    const parts = String(it.w).split('|').map((s) => s.trim()).filter(Boolean);
    if (parts.some((p) => new RegExp(esc(p), 'i').test(text))) { got += it.weight; hits.push(it.w.split('|')[0]); }
  }
  return { score: Math.round((got / total) * 100), hits };
}

const cases = {
  '高匹配-AI Agent 开发': `
    岗位职责：负责 AI Agent 智能体应用的开发，基于 LangChain 搭建工作流，
    实现 RAG 检索与知识库问答，设计 Prompt 提示词模板，接入工具调用；
    要求熟悉 Python，了解大模型 LLM 应用开发，有向量数据库使用经验。`,
  '中匹配-AI应用开发（偏业务）': `
    负责公司 AI 应用产品的落地，使用大模型能力做业务场景封装，
    需要 Python 基础，了解智能体概念，能配合产品完成需求；
    加分项：熟悉 Docker 部署。`,
  '低匹配-AI训练师': `
    负责大模型训练数据标注质量管理，制定标注规范，培训标注团队，
    统计标注效率，输出质量报告。要求细心、有责任心。`,
  '排除-java后端': `
    负责 Java 后端服务开发，参与 Agent 平台的服务端建设，熟悉 Spring Boot。`,
  '中低-数据分析': `
    负责业务数据分析，编写 SQL 提取数据，制作可视化看板，输出分析报告。`,
};

for (const [name, text] of Object.entries(cases)) {
  const r = scoreJd(text);
  console.log(`${String(r.score).padStart(3)} 分 | ${name}${r.banned ? ' [排除:' + r.banned + ']' : ''} | 命中 ${r.hits.length}: ${r.hits.join(',')}`);
}
