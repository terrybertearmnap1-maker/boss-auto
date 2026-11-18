# boss-auto · 求职多 Agent 编排 + BOSS 自动投递

一个**简历驱动**的求职自动化系统：上传简历 PDF，系统解析出技能画像，自动搜索岗位、抓取 JD、打分，按分数决定是否打招呼，并为每个岗位生成不同的开场话术。

> ⚠️ **免责声明**：自动投递可能违反 BOSS 直聘用户协议，存在限流或封号风险；请自行评估后果，建议控制频率、小批量使用。本项目仅用于学习与个人求职效率研究。

## 它解决什么问题

投递简历的重复劳动有三块：**筛选岗位、判断匹配度、写开场白**。这三件事都可以用简历本身作为输入来自动化——难点不在"能不能点按钮"，而在"点得准不准、会不会投错、被拒时知不知道为什么"。

项目就是围绕这三点设计的：每一步的产出都结构化、可查看、可回放。

## 架构

```
简历 PDF
   │
   ▼
┌──────────┐  profile   ┌──────────┐  岗位列表   ┌──────────┐
│ Agent1   │ ─────────► │ Agent2   │ ─────────► │ Agent3   │
│ 简历解析  │            │ 岗位搜索  │            │ JD 匹配   │
└──────────┘            └──────────┘            └──────────┘
     │ 解析失败即终止                                   │ 分数
     ▼                                                ▼
    END                                     ┌──────────┐
                                            │ Agent4   │
                                            │ 决策+话术 │
                                            └──────────┘
                                                  │ 指令
                                                  ▼
                                        ┌──────────────────┐
                                        │ 浏览器扩展（MV3） │
                                        │ 点沟通 → 发话术   │
                                        └──────────────────┘
```

四个 Agent 用 LangGraph `StateGraph` 串联，按「数据形态变化」切分边界：文本 → 画像 → 岗位 → 分数 → 决策。每段都能单独测试和替换。

### 四个 Agent 的职责

| Agent | 输入 | 输出 | 关键设计 |
| --- | --- | --- | --- |
| **A1 简历解析** | PDF/DOCX/TXT/MD | `{skills, directions, city, salary_min, degree, school, keywords}` | 76 条技能词典 + 英文词边界匹配，避免 `Go` 命中 `Google`；输入过短直接报错而非编造画像 |
| **A2 岗位搜索** | 关键词 + 城市 + 薪资 | 岗位列表（含 JD） | 三级数据源（浏览器批次 / 历史真实岗位 / 本地索引）；关键词粗筛不足时放宽到「城市+薪资」补量 |
| **A3 JD 匹配** | 岗位 + 简历 | `{score, matched, missing, penalty}` | `0.7×技能覆盖 + 0.3×语义 − 硬性条件扣分`；覆盖度分母取 **JD 要求的技能**；JD 缺失时标记待补抓而不是打 0 分 |
| **A4 决策话术** | 打分结果 | `{decision, reason, greeting}` | 阈值 + 标题排除词 + 去重三道关；话术按「JD 技术栈 → 项目细节 → 邀请」三段生成，且必须引用真实技能 |

## 关键实现细节

**反爬：薪资数字是私有区字符**
BOSS 把薪资里的数字渲染成 Unicode 私有区字符（`U+E031`→0 … `U+E03A`→9），配合自定义字体显示。不还原的话抓到的薪资永远为空。扩展里做了映射还原。

**为什么用浏览器扩展而不是 CDP**
Playwright / puppeteer 会留下 `navigator.webdriver` 等指纹，BOSS 能识别并跳转登录页。扩展运行在真实浏览器环境里，没有这类痕迹。

**指令队列：决策与执行解耦**
后端算出该投什么、说什么，排进队列；扩展每 6 秒轮询取走并执行，两条之间强制间隔 25–45 秒。这样"决策"可以离线跑、可以复用，执行侧只管点按钮。

**防止把自己写的数据当输入**
流水线回写结果时不能覆盖岗位的 `source=zhipin` 标记，否则真实岗位写一次就变成"流水线产物"，之后再也不会被搜到。

## 快速开始

### 后端

```bash
cd jobpilot
pip install -r requirements.txt
python -m uvicorn pipeline.api:app --host 127.0.0.1 --port 8030
```

打开 <http://127.0.0.1:8030> ，上传简历 PDF，点「用这份简历跑一轮」。

### 浏览器扩展

1. Chrome 打开 `chrome://extensions` → 开启开发者模式 → 加载 `extension/` 目录
2. 点扩展图标进设置页，填「匹配结果上报地址」：`http://127.0.0.1:8030`
3. 打开 <https://www.zhipin.com/web/geek/jobs?bossauto=1>

### 配置 LLM 话术（可选）

不配置时用模板话术；配置后按 JD 逐条生成：

```bash
# jobpilot/.env
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=sk-xxxx
OPENAI_MODEL=deepseek-chat
```

`.env` 已在 `.gitignore` 中，不会被提交。

## 测试

```bash
cd jobpilot
python tests/test_p1_resume.py        # 简历解析
python tests/test_agent2_search.py    # 两段式搜索
python tests/test_p3_match.py         # 打分与扣分
python tests/test_p6_commands.py      # 指令队列
python tests/test_agents.py           # 四段流水线
python tests/test_p5_resilience.py    # 故障隔离
```

## 目录结构

```
boss-auto/
├── jobpilot/          # 后端：Agent 流水线、API、看板、MCP Server
│   ├── agents/        # 四个 Agent
│   ├── pipeline/      # 编排、数据库、缓存、指令队列、API
│   ├── web/           # 看板（无构建，CDN React）
│   └── tests/         # 8 套回归测试
├── extension/         # Chrome MV3 扩展：筛选、打分、发送、指令执行
├── jobgraph/          # LangGraph 决策原型
├── agentchat/         # FastAPI + WebSocket 流式对话 demo
└── 使用手册.md
```

## 已知限制

- 扩展轮询指令需要**保持一个 BOSS 标签页打开**（轮询器在 content script 里）
- 语义相似度用的是哈希向量，只能捕捉词面相近，不懂同义改写
- 单进程 SQLite，适合个人使用；高并发需要 PostgreSQL
- 扫描版 PDF 不支持（没有 OCR）
- LLM 话术有硬校验：提到简历里没有的技术会整句回退模板
