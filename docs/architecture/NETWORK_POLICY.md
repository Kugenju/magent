# 网络策略（分层版）

> 本文定义 `magent` / VulnTell 的分层网络策略，取代早期“整个项目离线优先”的硬性表述。
> 保留的部分没有丢：默认安装、默认单元/契约测试与 CI 门禁仍是离线确定性的。
> 改变的部分是：联网能力从“每次都需单独评审的例外”，升格为**显式声明、受策略约束、一等公民的产品能力**。

## 1. 背景与动机

- 后续应用（漏洞情报采集、MCP 工具接入、外部 LLM provider、API 服务）有强联网需求，网络不应再被视为例外路径。
- 项目已存在受控联网的成熟先例：VulnTell live 模式（`--live` 显式开关、endpoint allowlist、环境变量密钥、`VULNTELL_PROXY` 代理、超时/重试/错误分类）。本策略把这些既有实践提炼为全局规范，而不是新增一套机制。

## 2. 三层策略

| 层 | 位置 | 默认能力 | 联网条件 |
|----|------|----------|----------|
| **L1 框架核心** | `src/magent`（不含联网扩展模块） | 完全离线；运行时依赖仅 `pydantic` | 禁止外呼；顶层导入不得引入网络库 |
| **L2 框架联网扩展** | `src/magent/mcp/*` transport 实现等可选模块 | 构造时才连接；未使用时零网络行为 | SDK/HTTP 库懒加载（函数内 import）；外呼必须可配置超时、可取消、错误可分类、可重试；必须提供离线替身（Fake transport） |
| **L3 应用层** | `apps/*`、`tools/*`、未来 MCP server / API | 允许联网（生产路径） | 显式开关 + endpoint allowlist + 环境变量密钥 + 超时/限速/代理；默认 fixture 流程仍保持离线 |

要点：

- “离线优先”重定义为 **“默认离线”（offline by default），而不是“禁止联网”**：
  - `pip install magent` 后不装任何 extra，核心功能照常离线运行（不变）；
  - 联网能力通过 optional extras 显式装载：`mcp`（MCP 官方 Python SDK）、`net`（httpx）；
  - 应用运行时的联网一律要求显式声明（CLI 开关 / 配置 / 环境变量），禁止隐式联网。
- 安全语义不变：SSRF 防护（endpoint allowlist）、Prompt Injection 隔离、密钥只从环境变量注入且不进入序列化/trace/异常消息、工具与来源的白名单契约。

## 3. 测试与 CI 基线

工程确定性不因联网放宽而放松：

- `tests/unit`、`tests/contract` 保持**完全离线**（zero network、fake provider、fixture only），CI 门禁不变；
- 真实网络 smoke 测试**单独命名**（`tests/live/`，pytest marker `live`），默认跳过、显式启用（`-m live` 或独立 CI job），并配置超时、限速与密钥隔离；
- 一切联网能力必须同时提供离线替身：`FakeProvider`、fixture transport、`FakeMcpServer`（Phase 10 引入），测试优先在替身上完成。

## 4. 运行时开关规范（L3 与 L2 通用）

| 事项 | 规范 | 现有先例 |
|------|------|----------|
| 显式开关 | CLI flag（如 `--live`）或 config 字段；未开启时模块不得建立连接 | `VulnTellConfig.live` |
| 端点治理 | endpoint allowlist 校验 netloc；路径前缀匹配 | `_LIVE_ENDPOINTS` |
| 密钥 | 仅从环境变量读取，不序列化、不进 trace/日志/异常消息 | `NVD_API_KEY`、`GITHUB_TOKEN` |
| 超时/限速 | 每次外呼可配置超时；按错误类别（429/超时/临时故障）进入重试 | `SourceErrorKind` + `ReliabilityPolicy` |
| 代理 | 显式环境变量优先，回退系统代理 | `VULNTELL_PROXY` |
| 取消 | 外呼响应框架取消信号，不留悬挂连接 | `ToolContext.cancel_event` |

## 5. 放宽与收紧信号

- **进一步放宽**的能力（服务端监听、长连接、自动重连、生产 API）按应用阶段逐项评审，评审结论记录在对应阶段文档；
- **收紧信号**（出现任一先暂停扩展并修复）：离线基线测试破坏、恢复结果与基线不一致、密钥进入序列化路径、endpoint allowlist 被绕过、单源联网失败导致整体不可用。每个信号转化为最小可复现测试后再继续。

## 6. 影响

- README / DESIGN / CHANGELOG / PHASES 中“offline-first/no-network”的表述统一改述为“offline by default + 显式联网能力”；
- `pyproject.toml` 增加 optional extras（`mcp`、`net`），核心依赖集不变；
- `tests/unit/test_phase9_release.py` 的“顶层无网络导入”门禁语义保持有效（它守护的是核心干净，而非禁止联网能力存在）。
