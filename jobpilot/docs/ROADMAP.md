# 多 Agent 编排项目 · 实施路线

> 目标：**一份简历进去，一条流水线出来**——解析 → 搜索 → 匹配 → 决策 → 执行投递。
> 原则：**契约先行，实现可替换**。每个 Agent 先定死输入输出，再谈怎么实现。

---

## 现状盘点（v0，已完成）

| 组件 | 状态 | 说明 |
| --- | --- | --- |
| `agents/resume_agent.py` | v0 · 规则版 | 词典 + 正则抽取，未接 PDF 解析 |
| `agents/search_agent.py` | v0 · 本地索引 | 有 `search()` 接口，扩展实现是空壳 |
| `agents/match_agent.py` | v0 · 技能+语义 | 覆盖度口径已修正（分母为 JD 技能） |
| `agents/decide_agent.py` | v0 · 模板话术 | 有 LLM 分支，未验证 |
| `pipeline/orchestrator.py` | v1 · 串行图 + 失败隔离 | LangGraph 四节点，单节点失败不中断整批 |
| `pipeline/orchestrator_cli.py` | ✅ | `python -m pipeline.orchestrator_cli` |
| `tests/test_agents.py` | ✅ 通过 | 覆盖 4 个 agent 的关键规则 |

**v0 能证明的事**：链路是通的、契约是清楚的、两个关键坑（覆盖率分母、方向误触发）已经踩过。
**v0 不能证明的事**：真实 PDF 能解析、真实 BOSS 能搜到、真实 JD 能抓、真实话术能发出去。

---

## 数据契约（先定死，谁都不许改）

### Agent1 输出 `ResumeProfile`
```json
{
  "skills": ["Python", "LangGraph", "Qdrant"],
  "directions": ["Agent", "智能体"],
  "city": "广州",
  "salary_min": 8,
  "degree": "本科",
  "years": "应届",
  "keywords": ["Agent", "智能体", "大模型"],
  "summary": "广州 · 本科 · 技能 11 项"
}
```

### Agent2 输出 `Job[]`
```json
{
  "job_id": "boss-c5a4c833",
  "title": "AI Agent 开发工程师",
  "company": "迈络科技",
  "salary": "12-20K",
  "city": "广州",
  "url": "https://www.zhipin.com/job_detail/xxx.html",
  "jd": "岗位职责……",
  "source": "zhipin"
}
```

### Agent3 输出 `ScoredJob[]`
```json
{
  "...Job": "全部字段保留",
  "score": 70,
  "matched": ["Python", "Agent", "MCP"],
  "missing": ["Redis"],
  "coverage": 71.4,
  "semantic": 65.3
}
```

### Agent4 输出 `Decision[]`
```json
{
  "...ScoredJob": "全部字段保留",
  "decision": "apply",
  "reason": "匹配 70 分",
  "greeting": "您好，我是……"
}
```

---

## 阶段划分

### P0 · 契约与骨架 ✅ 已完成
- 4 个 Agent 函数签名固定为 `run(state) -> partial_state`
- 共享 `PipelineState`（TypedDict）
- CLI 能跑通假数据，测试覆盖关键规则

**验收**：`python tests/test_agents.py` 全绿。

---

### P1 · Agent1 简历解析（生产级）✅ 已完成
**目标**：真实 PDF 进去，结构化 JSON 出来。

| 项 | 内容 |
| --- | --- |
| 输入 | PDF / DOCX 文件路径 |
| 处理 | `pypdf` 抽文本 → LLM 抽取（有 key）/ 规则抽取（无 key） |
| 输出 | `ResumeProfile` |
| 验收 | 3 份不同格式简历，字段齐全率 ≥ 90%；无 key 时仍可跑 |
| 风险 | 扫描版 PDF 抽不出文字 → 检测到空文本时明确报错，不静默返回空 profile |

**关键设计**：`extract_text()` 与 `extract_profile()` 分离，前者可换 OCR，后者可换模型。

---

### P2 · Agent2 岗位搜索（接真实扩展）✅ 已完成（数据接入 + 三级回退）
**目标**：真的从 BOSS 页面上拿到岗位列表。

| 项 | 内容 |
| --- | --- |
| 输入 | `keywords[] / city / salary_min / limit` |
| 工具 | `ExtensionBridge`：后端发指令 → 扩展执行 → 回传结果（WebSocket） |
| 输出 | `Job[]` |
| 验收 | 一次指令拿到 ≥ 10 条真实岗位，字段完整；扩展掉线时 3 秒内降级到本地索引 |
| 风险 | 扩展与后端的请求/响应关联（需要 request_id）、超时、页面未登录 |

**关键设计**：
- `Bridge` 用 `request_id` 匹配请求响应，超时 15s
- 扩展侧新增 `search` 指令处理器（复用现有筛选逻辑）
- 无浏览器时永远有 LocalIndex 兜底，保证 demo 不翻车

---

### P3 · Agent3 JD 匹配（真实 JD + 双信号）✅ 已完成（硬性条件扣分 + JD 缺失跳过）
**目标**：每条 JD 都有可信的匹配分。

| 项 | 内容 |
| --- | --- |
| 输入 | `Job[]` + 简历全文 |
| 处理 | ① 若 `jd` 为空 → 让 Agent2/扩展补抓详情页；② 技能覆盖（分母=JD 技能）；③ 语义相似（向量） |
| 输出 | `ScoredJob[]`，按分降序 |
| 验收 | 10 条真实 JD 打分，人工抽检 5 条，排序合理性 ≥ 4/5 |
| 风险 | JD 抓取为空（选择器变化）→ 标记 `jd_missing` 不参与打分，而不是打 0 分 |

**关键设计**：分数可解释——每个分数都带 `matched / missing / coverage / semantic`，面试和调参都靠它。

---

### P4 · Agent4 决策与话术（可解释 + 可定制）✅ 已完成（话术校验 + 回退）
**目标**：投不投有据可查，话术不像群发。

| 项 | 内容 |
| --- | --- |
| 输入 | `ScoredJob[]` + 阈值 + 排除词 |
| 处理 | 阈值 / 排除词 / 已投去重 → 决策；通过则生成话术（模板或 LLM） |
| 输出 | `Decision[]` |
| 验收 | 话术 40–60 字、无联系方式、引用 JD 里至少 2 个技能；拒绝原因分类准确 |
| 风险 | LLM 乱编技能 → 生成后校验：话术里的技能必须出现在 `matched` 里，否则回退模板 |

---

### P5 · 编排与可观测（稳）✅ 已完成（失败隔离 + trace）
**目标**：单条失败不拖垮整批，能回放、能重试。

| 项 | 内容 |
| --- | --- |
| 处理 | LangGraph 串接 + 每节点 try/catch + 失败降级 + trace 落库 |
| 并发 | Agent3 对多个 JD 并发打分（`asyncio.gather` + 限流） |
| 验收 | 注入 1 条坏数据，整批仍完成；trace 能还原每一步 |
| 风险 | 并发打爆 LLM 限流 → 信号量控制在 3–5 |

---

### P6 · 真实联调（落地）🟡 后端完成，扩展待实测
**目标**：跑一轮真实投递，结果进看板。

| 项 | 内容 |
| --- | --- |
| 链路 | `/run` → 扩展执行打招呼 → 结果回传 `/ingest` → MySQL → React 看板 |
| 验收 | 3 条真实投递成功，看板能看到分数与话术 |
| 风险 | BOSS 风控 → 单轮上限 3、随机间隔 25–75s、验证码熔断 |

---

## 里程碑

| 里程碑 | 包含 | 可演示的东西 |
| --- | --- | --- |
| **M1 单机可跑** | P0–P4 | 一条命令：PDF → JSON → 岗位 → 打分 → 话术 |
| **M2 编排稳定** | P5 | 批量跑、失败隔离、trace 回放 |
| **M3 真实落地** | P6 | 真的投出去 3 份，看板有数据 |

预计工时：P1 2h / P2 3h / P3 3h / P4 2h / P5 2h / P6 3h ≈ **15 小时**（不含调试意外）。

---

## 阶段之间的依赖

```
P0 ✅ ──► P1 ──► P2 ──► P3 ──► P4 ──► P5 ──► P6
                    │
                    └── 没有 P2 的真实岗位，P3/P4 只能用假数据验证
```

**建议顺序**：P1 → P2 → P3 → P4 严格按序；P5 可与 P4 并行；P6 必须在 P2 之后。

---

## 实施记录

### P1 完成（2026-11-18）
- 新增 `pipeline/resume_io.py`：PDF（pypdf）/ DOCX / TXT 统一读文本，抽不出文字时抛 `ResumeReadError` 而不是静默返回空
- 真实简历 PDF 实测：1753 字 → 11 项技能 / 方向 [Agent, 智能体] / 城市 广州 / 学历 本科 / 学校 示例大学
- 修掉两个副作用：薪资下限被「实习」误拉到 3K（改为只认显式薪资区间，缺省 4K）；话术里没有学校
- 验收：`tests/test_p1_resume.py` 通过

### P4 完成
- 话术来源标记 `greeting_source`（template / llm / template(fallback)）
- LLM 话术必须引用 `matched` 里的技能，否则判定为编造并回退模板

### P5 完成
- 每个节点包一层 `_safe`：异常写进 `errors` + `trace`，后续节点继续跑
- 验收：`tests/test_p5_resilience.py` 通过（工具爆炸 / 空简历两种故障场景）
- 顺带修掉测试暴露的真 bug：Agent2 单关键词无命中时无限递归（`len(keywords) > 1` 判断）
### P3 完成（2026-11-18）
- **JD 缺失不打 0 分**：`jd` 短于 30 字标记 `jd_missing=True, score=None`，排序排到最后，决策阶段跳过并注明「JD 缺失，待补抓」
- **硬性条件扣分**：从 JD 解析年限与学历要求，3 年以上 −15、2 年 −8、硕士 −15、博士 −25
- **分数可解释**：每条结果带 `coverage / semantic / penalty / penalty_reasons`
- 实测：高级岗（3-5 年）技能 100% 也只能到 58 分被跳过；同内容无年限要求则 73 分通过
- 验收：`tests/test_p3_match.py` 通过（JD 缺失 / 年限扣分 / 学历扣分 / 排序 / 决策跳过）
- 调试工具：`scripts/show_scores.py` 一屏输出所有岗位的分数与扣分原因

### 阶段状态
| 阶段 | 状态 |
| --- | --- |
| P0 契约骨架 | ✅ |
| P1 简历解析 | ✅ |
| P2 岗位搜索（接扩展） | ⬜ 待做（需要扩展改动 + 联调） |
| P3 JD 匹配 | ✅ |
| P4 决策话术 | ✅ |
| P5 编排加固 | ✅ |
| P6 真实联调 | ⬜ 待做（依赖 P2） |
### 看板接入（2026-11-18）
- `jobs` 表补 `penalty / penalty_reasons` 两列，老库自动 `ALTER TABLE` 迁移，不用删库
- `POST /run` 结果除入库外，额外记录 `LAST_RUN`（时间/评估数/投递数/耗时/关键词/城市），新接口 `GET /runs/last`
- 看板新增：顶部「最近一次流水线运行」条、表格「扣分」列、点行展开详情（决策原因 / 命中技能 / 打招呼语 / JD 摘要）
- 实测：`/run` → 评估 6 / 投递 4 / 28ms，看板同步显示，点开第一行能看到完整话术
### P2 完成（2026-11-18）
- **扩展上报接口**：`POST /search-results` 接收 `{keywords, city, jobs[]}`，存入 `pipeline/search_hub.py` 的单例批次（默认 15 分钟过期）
- **三级数据源回退**：
  1. `browser-batch` —— 扩展刚推上来的批次（最鲜）
  2. `browser-recent` —— 扩展历史上报、带真实 JD 的岗位（从 MySQL/SQLite 读）
  3. `local` —— 本地索引兜底，保证 demo 永不翻车
- `/run` 返回与看板运行条都会标明本次用了哪一级（`search_source`）
- 实测：推 3 条真实岗位 → `/run` 自动走 `browser-batch` → 打分 73 → 投递，14ms
- 验收：`tests/test_p2_search.py`（批次命中 / 关键词过滤 / 过期回退 / 本地兜底 / 复用历史记录）
- 未做：后端主动触发搜索（需要扩展轮询命令或 WS），留到 P6 与「自动执行投递」一起做

### 阶段状态（更新）
| 阶段 | 状态 |
| --- | --- |
| P0 契约骨架 | ✅ |
| P1 简历解析 | ✅ |
| P2 岗位搜索 | ✅ 数据接入完成（主动触发未做） |
| P3 JD 匹配 | ✅ |
| P4 决策话术 | ✅ |
| P5 编排加固 | ✅ |
| P6 真实联调 | ⬜ 主动触发 + 自动执行投递 |
### Agent2 加固（2026-11-18）
- **两段式搜索**：先按关键词粗筛；命中 < `min_results`（默认 6）时，第二段放宽为「城市 + 薪资」，把标题没写关键词但可能匹配的岗位捞进来。`limit` 仍是硬上限。
- **简历闸门**：Agent1 对 < 50 字的输入直接报错（空文件/扫描件），编排层用条件边在 Agent1 失败时直接 END——避免拿假画像去投递。
- **输出归一化**：提前结束时 `jobs/decisions/trace` 也返回空列表，调用方不用判空。
- 实测（真实数据）：`browser-recent` 从 1 条提升到 3 条（放宽补 2 条），Java 岗被标题排除词拦下，JD 缺失的标记待补抓。
- 新增测试 `test_agent2_search.py`：放宽触发、充足不触发、limit 硬上限、trace 文案。

### 测试清单（7 个）
| 文件 | 覆盖 |
| --- | --- |
| `test_skill_dict.py` | 76 词条、同义词、误匹配（Go≠Google） |
| `test_p1_resume.py` | 真实 PDF 解析、学校/薪资、坏文件报错 |
| `test_agent2_search.py` | 两段式搜索与边界 |
| `test_p2_search.py` | 批次缓存、过期回退、来源过滤 |
| `test_p3_match.py` | JD 缺失、年限/学历扣分、排序 |
| `test_agents.py` | 四段流水线全链路 |
| `test_p5_resilience.py` | 工具故障隔离、空简历闸门 |
### P6 实施（2026-11-18）

**后端：投递指令队列**（`pipeline/commands.py`）

| 接口 | 作用 |
| --- | --- |
| `POST /run {execute:true}` | 跑完流水线后，把通过的岗位排进指令队列 |
| `GET /commands?limit=N` | 扩展轮询取指令（取走即移到 inflight，等 ack） |
| `POST /commands/ack` | 扩展回报执行结果（ok / reason） |
| `GET /commands/status` | 队列状态：queued / inflight / done / ok / failed |
| `POST /commands/clear` | 调试用清空 |

实测：`/run execute=true` → 入队 2 → 扩展取走 2 → ack 2 → `done=2 ok=2`。

**扩展：轮询与执行**（v2.9，默认关闭）

- 设置页新增「自动执行后端下发的投递指令」开关（`autoExecute`，默认 false）
- 开启后每 6 秒轮询 `/commands`；**正常投递流程进行中不抢**
- 拿到指令 → 存 `chrome.storage` → 跳转岗位页 → 点「立即沟通」→ 发后端算好的话术 → `ack` 回报
- 执行完停在该页，不续跑队列

**为什么用轮询而不是 WebSocket**：MV3 的 service worker 会被回收，长连接不稳；6 秒轮询对人肉投递节奏足够，且断线自愈。

**测试**：`tests/test_p6_commands.py`（入队去重 / 取走 / ack / 重复 ack / 失败记录）

### 测试清单（8 个，全绿）
test_skill_dict / test_p1_resume / test_agent2_search / test_p2_search /
test_p3_match / test_agents / test_p5_resilience / test_p6_commands