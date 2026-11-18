# jobpilot — BOSS 自动投递的后端大脑

浏览器里的扩展负责「点按钮、发消息」，这个服务负责所有需要持久化和判断的部分：**去重 → 打分 → 决策 → 入库 → 看板**。

```
┌──────────────┐   POST /ingest    ┌──────────────────────────────┐
│ Chrome 扩展  │ ─────────────────►│ FastAPI                       │
│ (zhipin.com) │                   │  ├─ Redis   已投去重 / 每日配额 │
└──────────────┘                   │  ├─ Qdrant  JD 相似度去重      │
                                   │  ├─ LangGraph 打分 → 决策       │
┌──────────────┐   GET /jobs       │  └─ MySQL   岗位表 + 统计       │
│ React 看板   │ ◄────────────────►│                               │
│ /ws/live 实时│                   └──────────────────────────────┘
└──────────────┘
        ▲
        │  MCP (stdio)
┌───────┴──────┐
│ Claude/Cursor│  可调用 evaluate_jd / list_jobs / get_stats
└──────────────┘
```

## 一键起（Docker）

```bash
cp .env.example .env
docker compose up -d --build
# 看板 http://127.0.0.1:8030/
```

compose 会拉起 MySQL 8.4、Redis 7、Qdrant 和 API，`.env` 里已经把这些连接串写好。

## 本地裸跑（零依赖也能跑）

```bash
pip install -r requirements.txt
python -m pipeline.cli --file data/sample_jobs.json   # 灌样例数据
python -m pipeline.api                                 # 起服务 :8030
```

不配 `DATABASE_URL` / `REDIS_URL` / `QDRANT_URL` 时会自动降级：

| 组件 | 有服务时 | 缺省降级 | 代价 |
| --- | --- | --- | --- |
| MySQL | `mysql://…` | SQLite 文件 | 单机、无并发写 |
| Redis | `redis://…` | 进程内字典 | 多实例不共享去重与配额 |
| Qdrant | `http://…:6333` | Qdrant 本地内存模式 | 重启即丢向量 |

`GET /health` 会直接告诉你当前生效的是哪套组合：

```json
{"ok":true,"db":"sqlite","cache":"memory","vectors":"qdrant","threshold":60}
```

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/ingest` | 上报一个岗位：先查 Redis 是否已投，再算 JD 相似度去重，然后过 LangGraph 决策，最后入库 |
| GET | `/jobs?limit=&decision=` | 岗位列表，可按 `apply` / `skip` 过滤 |
| GET | `/stats` | 总数、投递数、跳过数、平均分、今日已投 |
| GET | `/health` | 各后端生效情况 |
| WS | `/ws/live` | 新岗位上架实时推送，看板订阅 |

## 和扩展怎么接

扩展设置页填「**匹配结果上报地址**」= `http://127.0.0.1:8030`，之后每条投递结果都会 `POST /ingest`：

```json
{
  "job_id": "c5a4c833...",
  "title": "AI Agent 开发工程师",
  "company": "迈络科技",
  "salary": "12-20K",
  "url": "https://www.zhipin.com/job_detail/...",
  "source": "zhipin",
  "jd": "岗位职责……（前 300 字）"
}
```

上报是 **fire-and-forget**：服务没起、网络断了都不影响扩展继续投递（`catch` 后静默）。

## MCP Server

```bash
python -m pipeline.mcp_server        # stdio
```

挂在 Claude Desktop / Cursor 里：

```json
{"mcpServers": {"jobpilot": {"command": "python", "args": ["-m", "pipeline.mcp_server"], "cwd": "C:/…/jobpilot"}}}
```

暴露三个工具：`evaluate_jd(jd_text, title, company)`、`list_jobs(limit, decision)`、`get_stats()`。

## 三个设计取舍

**① 去重放在两处，不是一个**
Redis 按 `job_id` 拦「已经投过的」，Qdrant 按 JD 相似度拦「同岗换链接重发的」。
只做前者会重复打扰同一家公司，只做后者会漏掉恰好改了措辞的旧岗。

**② 打分走 LangGraph 而不是 if/else**
节点是 `parse → score → (apply|reject)`，条件边由分数决定。
好处是后面要加「按 JD 改简历」「人工确认」这类节点时，只加 node + edge，不动主流程。

**③ 幂等优先**
`/ingest` 对同一 `job_id` 重复调用返回 `duplicate: true` 且不改库，
所以扩展重试、脚本重跑、看板手动补数据都不会把统计冲歪。

## 测试

```bash
python tests/test_pipeline.py    # 去重 / 排除词 / 统计 / WS 推送
python tests/test_mcp.py         # MCP 工具可调用
```

## 已知限制

- 扩展上报的 `jd` 只有前 300 字（完整 JD 留在扩展本地日志里），相似度去重精度受此影响
- 打分基于技能词表覆盖度，不理解语义；接真实 embedding + rerank 会更准
- 单进程 uvicorn；要横向扩展需要把 WS 广播换成 Redis Pub/Sub

## 四段式多 Agent 流水线（主线）

`pipeline/orchestrator.py` 用 LangGraph 把四个各司其职的 Agent 串成一条链：

```
简历文本
   │
   ▼
Agent1 简历解析 ──► {skills, directions, city, salary_min, degree, keywords}  (JSON)
   │
   ▼
Agent2 岗位搜索 ──► [岗位…]       工具：浏览器扩展 / 本地索引（同一接口）
   │
   ▼
Agent3 JD 匹配 ──► [{score, matched, missing, jd}…]
   │                 score = 0.7 × 技能覆盖 + 0.3 × 语义相似
   ▼
Agent4 决策话术 ──► [{decision, reason, greeting}…]
```

跑一次：

```bash
python -m pipeline.orchestrator_cli --resume data/resume_sample.txt --limit 10
```

实测输出（样例简历 + 10 条本地岗位）：

```
Agent1 简历解析：技能 11 项 / 方向 ['Agent','智能体'] / 关键词 ['Agent','智能体','LangChain','MCP'] / 城市 广州
Agent2 岗位搜索：命中 5 个岗位
Agent3 JD 匹配：
   · 智能体平台研发工程师 → 89 分（技能 100% + 语义 62.0）
   · AI Agent 开发工程师 → 70 分（技能 71.4% + 语义 65.3）
   · AI 应用开发工程师 → 68 分 / 大模型应用工程师 → 60 分 / 销售支持方向 → 49 分
Agent4 决策：投递 4 / 跳过 1
```

### 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/resume` | 只跑 Agent1，返回结构化画像与关键词 |
| POST | `/run` | 跑完整四段流水线，通过的岗位直接入库 |

```bash
curl -s -X POST http://127.0.0.1:8030/run \
  -H "Content-Type: application/json" \
  -d '{"text": "<简历全文>", "threshold": 60, "limit": 10}'
```

### 三个踩过的坑

1. **覆盖率的分母错了**：一开始用「我的技能全集」做分母，导致只要求 5 项技能的 JD 也拿不到高分；改成「JD 要求的技能」做分母才对。
2. **方向识别被误触发**：词典里用 `SQL` 当「数据分析」的触发词，结果 `MySQL` 命中了它，简历被识别成「数据分析 + 前端」方向。触发词必须足够重（改成 `数据分析`/`前端开发`）。
3. **城市过滤误杀**：一开始拿城市去匹配 JD 全文，JD 里不写城市就全被过滤；改成岗位记录自带 `city` 字段，缺失时不参与过滤。
### 数据来源优先级（P2）

`/run` 会自动挑数据源，并在响应与看板里标明 `search_source`：

| 优先级 | source | 含义 |
| --- | --- | --- |
| 1 | `browser-batch` | 扩展刚通过 `POST /search-results` 推上来的批次（15 分钟内有效） |
| 2 | `browser-recent` | 扩展历史上报过、带真实 JD 的岗位（从库里读） |
| 3 | `local` | 本地索引兜底，保证没有浏览器也能演示 |

扩展侧只需一个 HTTP 调用：

```bash
curl -X POST http://127.0.0.1:8030/search-results \
  -H "Content-Type: application/json" \
  -d '{"keywords":["Agent"],"city":"广州","jobs":[{"job_id":"x","title":"...","jd":"..."}]}'
```
## 仓库卫生（上传 GitHub 前必看）

这个仓库**只放代码，不放个人资料**。已做过的清理：

| 内容 | 处理 |
| --- | --- |
| `data/resume_sample.txt` | 换成虚构人物（李知远 / 示例大学 / 138-0000-0000），结构与真实简历一致 |
| 测试与脚本 | 不再引用任何真实简历文件；PDF 解析测试改为读环境变量 `RESUME_PDF`，默认跳过 |
| 演示数据库 `*.db` | 已删除，且写进 `.gitignore`（运行时会自动重建） |
| 个人目录 | `private/`（简历生成脚本）、`resume/`（简历成品）均在 `.gitignore` 中 |

上传前自查：

```bash
git status --ignored | grep -E "resume|private|\.db"   # 确认这些被忽略
```

**如果已经提交过**：仅删除文件不够，需要改写历史（`git filter-repo` 或 BFG），否则旧提交里仍能翻到。最省事的做法是**删库重建**——反正才刚开始。