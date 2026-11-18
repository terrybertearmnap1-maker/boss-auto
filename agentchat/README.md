# agentchat — 流式 Agent 对话服务

FastAPI + WebSocket + Redis + Qdrant + React 的一个最小可用 Agent 应用：知识库检索 → 工具调用 → 流式回答。

**clone 下来就能跑**：没装 Redis、没配 Qdrant、没有大模型 API Key 也能启动，会自动降级并在 `/health` 里说明当前用的是哪套后端。

## 架构

```
浏览器 (React)                FastAPI                    依赖（可降级）
   │                            │
   │  WS /ws/chat               │
   ├───────────────────────────►│  receive_json
   │                            │
   │                            ├─► ChatAgent.stream()
   │                            │      ├─ 检索   → Qdrant（无则内存）
   │                            │      ├─ 重排   → 向量分 + 词面重合度
   │                            │      ├─ 工具   → 命中关键词则执行
   │                            │      ├─ 记忆   → Redis（无则内存）
   │                            │      └─ 生成   → OpenAI 兼容 / Mock
   │  {"type":"status"}         │
   │  {"type":"sources"}        │
   │  {"type":"tool"}           │
   │  {"type":"token", ...} ◄───┤  逐 token 推送
   │  {"type":"done"}           │
   │◄───────────────────────────┤
```

## 启动

```bash
pip install -r requirements.txt
uvicorn backend.app:app --reload --port 8000
# 打开 http://127.0.0.1:8000
```

可选环境变量：

| 变量 | 作用 | 缺省行为 |
| --- | --- | --- |
| `REDIS_URL` | 会话记忆 | 降级为进程内字典 |
| `QDRANT_URL` | 向量库服务端地址 | 用 qdrant 本地内存模式 |
| `OPENAI_BASE_URL` / `OPENAI_API_KEY` | 真实模型 | 用 MockLLM 流式输出 |

`GET /health` 返回当前实际使用的后端：

```json
{"ok": true, "vector": "qdrant", "memory": "memory", "llm": "mock", "docs": 6}
```

## WebSocket 协议

客户端：

```json
{"type": "user", "text": "LangGraph 的条件边怎么用？", "conv_id": "conv-abc"}
```

服务端事件流：

| type | 含义 |
| --- | --- |
| `status` | 阶段（retrieving） |
| `sources` | 命中的文档与分数，前端展示引用来源 |
| `tool` | 调用了哪个工具、返回什么 |
| `token` | 增量文本 |
| `done` | 结束，带字数与耗时 |
| `error` | 出错 |

## 三处值得讲的设计

**① 流式是真的流式**
生成器是同步阻塞的（MockLLM 每个字符 sleep 8ms）。直接 `for` 循环会卡住事件循环；而先 `list(gen)` 再发又等于攒完才推、没有流式效果。做法是把生成器丢进线程池，用 `asyncio.Queue` + `loop.call_soon_threadsafe` 把每个事件转回事件循环，生产一个推一个。

**② 降级是设计的一部分**
Redis / Qdrant / 大模型三处依赖都有「连不上就换实现」的路径，接口一致。好处是演示环境零配置可跑；代价是降级后不具备跨进程共享与持久化，README 里写明白，避免误用到生产。

**③ 纯向量召回不够，要加一层重排**
embedding 用的是字符 n-gram 哈希（零依赖、离线可跑），但长文档的噪声会把排序带偏——问「LangGraph 条件边」时，先召回的是 Qdrant 文档。加了「0.6 × 向量分 + 0.4 × 词面重合度」的混合重排后，正确文档稳定排第一。这也是为什么真实场景建议用语义 embedding + rerank 模型。

## 测试

```bash
python tests/test_smoke.py
```

覆盖：健康检查、流式事件序列（status → sources → token… → done）、工具调用路由、多轮记忆、前端页面可访问。

## 已知限制

- MockLLM 只是把检索到的第一条内容复述出来，不代表真实生成质量
- 哈希向量无语义泛化能力（同义改写召回不到），生产应换真实 embedding
- 单进程 + 内存降级时，多实例部署会各存各的会话
