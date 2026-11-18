# jobgraph — 用 LangGraph 编排求职决策流程

把「一份 JD 值不值得投」拆成一张可回放的状态图：解析 → 抽技能 → 打分 → 条件分支 → 生成话术 / 拒绝。

这是 BOSS 自动投递项目里「匹配打分」环节的重构：原来是一个 400 行的 `if/else` 函数，现在拆成 5 个节点和 1 条条件边，每个节点都能单独测试、单独替换。

## 为什么用 LangGraph，而不是继续写 if/else

| | 手写状态机 | LangGraph |
| --- | --- | --- |
| 分支逻辑 | 嵌在函数里的 `if score < threshold` | `add_conditional_edges` 声明式表达 |
| 中间结果 | 局部变量，出问题只能加 print | State 全量落盘，按 `thread_id` 回放 |
| 新增一步（如「按 JD 改简历」） | 改函数、改调用链 | 加一个 node + 一条 edge |
| 单测 | 只能测整个函数 | 每个 node 单独测 |
| 中断恢复 | 自己写序列化 | `MemorySaver` checkpoint 自带 |

## 图结构

```
        START
          │
      parse_jd           拆「岗位职责 / 任职要求」，清噪音行
          │
   extract_skills        用同义词组在 JD 里找技能关键词
          │
        score            技能覆盖度打分（核心 ×3，加分 ×1）
          │
   ┌──────┴───────┐
   │  score ≥ 阈值 │
   ▼              ▼
draft_greeting   reject
（按命中技能      （写清拒绝原因：
 拼打招呼语）      排除词 / 分数不足）
   │              │
  END            END
```

## State 设计

```python
class JobState(TypedDict):
    # 输入
    title, company, salary, jd_text, threshold, profile
    # 中间
    sections, jd_skills, matched, missing, banned, score
    # 输出
    decision, reason, greeting
    # 可观测
    trace: list[str]      # 每个节点追加一行，便于回放
```

## 运行

```bash
pip install -r requirements.txt

# 批量评估 sample_jds.json，输出 CSV
python -m jobgraph.cli --threshold 60

# 打印每个节点的轨迹
python -m jobgraph.cli --verbose

# 回归测试
python tests/test_graph.py
```

输出示例：

```
=== AI Agent 开发工程师 ===
   parse_jd: 职责 141 字 / 要求 93 字
   extract_skills: JD 命中技能 ['Python', 'Agent', 'LLM', 'LangGraph', 'RAG', 'Qdrant', 'Docker']
   score: 17/25 权重 → 68 分
   draft_greeting: 已生成（129 字）
   决策：apply（匹配 68 分，高于阈值）

共评估 5 个岗位，投递 1 个，跳过 4 个
```

## 三个踩过的坑（面试可以讲）

**① 排除词误伤**
排除词一开始扫全文，结果「AI Agent 开发工程师」的 JD 正文里有「负责后端开发」，被 `后端` 判成 0 分。改成只匹配**岗位标题**，因为岗位类型由标题决定，正文里的技术词不代表岗位性质。

**② 中文同义词**
JD 写「大模型」不会命中 `LLM`，写「智能体」不会命中 `Agent`。技能组用竖线分隔同义词（`LLM|大模型|大语言模型`），否则分数系统性偏低。

**③ 抓不到 JD 时不能当 0 分**
上游抓取失败时 `jd_text` 为空，若按 0 分处理会把整轮岗位全部拒掉。正确做法是标记 `jd-empty` 并跳过打分，让这轮继续跑。

## 可扩展点

- `draft_greeting` 换成 LLM 节点：把节点函数替换即可，图结构不变
- 加 `rewrite_resume` 节点：接在 `draft_greeting` 之后，按 JD 改写项目描述
- 加 `human_approval` 节点：`interrupt_before=["draft_greeting"]`，人工确认后再发
- 换 `SqliteSaver`：把 MemorySaver 换成持久化 checkpointer，支持跨进程恢复
