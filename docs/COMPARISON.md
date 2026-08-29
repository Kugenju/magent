# 框架对比：LangGraph / AutoGen / CrewAI 与 magent

> 本文仅做**公开设计定位**对比，用于说明 `magent` 的取舍；不复制任何参考项目的源码或实现细节，
> 也不构成对第三方项目的性能或质量评价。参考结论记录来源仓库与查看日期；具体版本/commit 请在复现时
> 通过 `pip show <pkg>` 或锁定 Git commit 记录，并同步更新 `benchmarks/reference_comparison.py` 中的
> `version` 字段。参考框架对比在 `benchmarks/` 中始终 `status="not_comparable"`、`ranking=None`。

- 查看日期：2026-08
- 参考仓库：
  - LangGraph — https://github.com/langchain-ai/langgraph
  - AutoGen — https://github.com/microsoft/autogen
  - CrewAI — https://github.com/crewAIInc/crewAI

## 维度对比

| 维度 | LangGraph | AutoGen | CrewAI | magent（本项目） |
|------|-----------|---------|--------|------------------|
| Agent 抽象 | `StateGraph` + 节点函数/Runnable | `ConversableAgent`/小组对话 | `Agent`+`Task`+`Crew` | `BaseAgent` 协议 + 类型化 `State`/`AgentResult` |
| 状态模型 | TypedDict/状态累加 | 对话消息历史 | 任务上下文/共享 | 显式 `State` 与 `merge_updates`（带校验） |
| 图/工作流 | 显式有向图、条件边、持久化 | 会话编排、群聊/顺序 | 角色化流程 | 条件路由 DAG、fan-out/fan-in、reducer |
| 并发 | 托管运行时（服务端） | 组内并发/事件 | 顺序/轻并发 | 进程内有界 `asyncio` 调度、fan-out/fan-in |
| Checkpoint | 内建（服务端存储） | 依赖扩展 | 依赖扩展 | 可选 SQLite Checkpoint + 稳定 execution key |
| 重试/超时/取消 | 运行时层 | 依赖扩展 | 依赖扩展 | 节点级超时/有界重试/调用方取消/错误分类 |
| 工具/LLM 扩展 | Tool/Model 集成丰富 | 工具+代码执行 | 工具+LLM | Tool Registry + 可插拔 Provider + Middleware |
| 可观测性 | 服务端 tracing/平台 | 依赖扩展 | 依赖扩展 | 只读 `Trace`/`Span`/`RunSummary`，可关闭、不反向影响执行 |
| 生态定位 | LangChain 生态、生产服务 | 研究/企业对话 | 角色化 Agent 产品 | 最小可复用内核 + 下游示例（VulnTell） |

## 取舍与借鉴

- **借鉴（设计理念，非实现）**：有向图 + 条件路由、显式状态合并、节点级重试/超时、Checkpoint 恢复、
  工具/模型解耦。这些是该领域的通用实践，magent 以最小化、可复现、离线优先的方式重新实现。
- **未采用**：服务端 tracing 平台、分布式运行时、对话/群聊编排、代码执行与远程工具、生产 Web 看板。
  这些超出阶段 1–9 的发布范围（见 `docs/PHASE9.md` 非目标），如确需应独立范围评审，不阻塞核心发布。
- **不复制**：本文不引用任何参考项目的源码片段；对比仅基于公开文档与仓库定位。

## 不可比边界

- 参考框架面向不同部署形态（多为服务端/分布式），与 magent 的进程内离线内核不在同一基准；
- 不输出跨框架排名，也不把小样本本地评测写成性能结论；
- 第三方名称、URL 与版本仅作归属与背景说明，不构成项目背书。
