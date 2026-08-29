# 阶段 6：工具协议、LLM Agent 与 Middleware 实施计划

> **实施状态：已完成。** 工具协议、`LLMProvider`/`FakeProvider`/可选 OpenAI 适配器、
> 以及可组合 Middleware 均已实现并通过测试（阶段 6 新增 38 个测试，全量 168 个离线测试通过，
> `mypy src/magent` 无错误）。阶段 5 发布门禁已全部关闭，阶段 6 代码、文档、示例与公共导出已提交。
> 核心在无 API Key/网络/LLM 服务时仍可运行。

## 1. 阶段定位

阶段 1～4 已建立 Agent、类型化 State、DAG 编排、并发、EventBus 和可靠性策略；阶段 5
已经实现本地 Checkpoint、恢复和幂等能力并完成发布门禁。阶段 6 在此基础上增加
“Agent 如何安全调用工具”和“如何可选接入 LLM”的扩展层，同时用 Middleware 统一实现
日志、限流、策略检查和运行前后钩子。

本阶段的目标不是把 `magent` 变成某一家模型厂商的 SDK，而是冻结最小、可替换、可测试的
扩展协议，为后续 VulnTell 数据源采集和报告生成提供基础。所有 LLM 能力必须是可选依赖；
没有 API Key、网络和 LLM 服务时，框架核心及确定性 Agent 仍必须可运行。

## 2. 当前基线审视

### 已完成

- 类型化 `BaseAgent` / `AgentResult` / `Runtime`；
- 顺序 Executor 和支持条件路由、fan-out/fan-in 的 DAG Executor；
- 显式重试、节点超时、调用方取消和失败传播；
- EventBus 旁路事件机制；
- `CheckpointStore`、SQLite 快照、顺序/并发 DAG 恢复和 `SideEffectSink`；
- 阶段 5 测试通过，当前全量测试为 168 个（含阶段 6 新增 38 个工具/LLM/Middleware 测试）。

### 阶段 5 必须先完成的发布门禁（已关闭）

阶段 6 的功能开发不得以“顺便修复”为名绕过以下问题（均已关闭并附测试）：

1. SQLite 读取 checkpoint 后重新计算并校验 checksum（`sqlite.py` 在 `_fill_workflow` 之后 `_verify_checksum`）；
2. 并发 Graph 的 checkpoint 序号由统一机制分配，不能出现重复序号（`graph/executor.py` 用 `seq[0]` + `asyncio.Lock`）；
3. `SideEffectSink` 对同一 execution key 的并发请求具备原子 claim/处理中语义（每键 `asyncio.Lock`）；
4. 副作用结果首次返回与重放返回的数据结构一致（统一存储/返回 `result_json`）；
5. `RunRecord.status` 与成功、失败、取消和中断状态保持一致（`update_run_status` 在首尾写 checkpoint）；
6. 恢复时的 abandoned attempt、节点版本和 frontier 可追溯且有测试覆盖（`tests/unit/test_phase5_checkpoint.py`）；
7. 阶段 1～5 的代码、文档、示例和公共导出形成一个独立提交（阶段 5 提交节奏见 `ROADMAP.md`）。

门禁关闭后，阶段 6 工具副作用已可安全接入恢复流程（通过 `SideEffectSink` 幂等）。

## 3. 阶段目标

完成后，框架应提供：

1. 统一的 Tool 描述、注册、输入校验、执行和输出校验协议；
2. 同步工具与异步工具的统一调用方式，并避免同步阻塞事件循环；
3. 工具超时、取消、错误分类、白名单和基础限流能力；
4. 可替换的 `LLMProvider` 接口、确定性 Fake Provider 和至少一个可选适配器；
5. LLM 请求/响应的结构化模型、token/耗时元数据和敏感信息脱敏；
6. Agent/Tool Middleware 的确定性组合、执行顺序和异常传播语义；
7. 工具调用与阶段 4、阶段 5 的重试、Checkpoint 和幂等边界衔接清楚；
8. VulnTell 可以在后续阶段通过插件使用这些协议，而不修改 `magent` 核心执行逻辑。

## 4. 范围与非目标

### 4.1 本阶段包含

- `magent.tools`：ToolSpec、ToolRegistry、ToolContext、ToolResult、ToolError；
- 输入/输出 schema 校验和可序列化工具结果；
- 同步函数、异步函数和受控线程池适配；
- 工具级 timeout、取消传播、限流和白名单；
- `magent.llm`：消息、请求、响应、Provider 协议和 Fake Provider；
- 一个单独的可选 Provider adapter，依赖和导入不能污染核心包；
- `magent.middleware`：Agent/Tool middleware protocol、组合器和最小内置中间件；
- EventBus 事件和 ExecutionReport 的工具/LLM 调用摘要；
- 离线 fixture、契约测试、示例和 API 文档。

### 4.2 本阶段不包含

- 自动规划、循环 Agent、自主修改 Graph 或多 Agent 社交协议；
- 绑定 OpenAI、Anthropic 或其他厂商的核心数据模型；
- 在测试中访问真实模型、网络、漏洞源或生产数据库；
- 自动执行命令行、任意 Python 代码、任意 URL 抓取或漏洞利用；
- 把 LLM 输出直接当作可信状态更新或评分结果；
- 分布式 Tool Registry、远程沙箱、密钥管理平台和多租户隔离；
- 在本阶段实现 VulnTell 业务 Agent。

## 5. 核心协议设计

### 5.1 Tool 协议

建议提供如下最小领域模型，具体字段可在 Task 0 冻结：

```python
class ToolSpec:
    name: str
    version: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    side_effect: bool = False
    idempotent: bool = False

class Tool(Protocol):
    spec: ToolSpec
    async def invoke(self, arguments: BaseModel, context: ToolContext) -> ToolResult: ...

class ToolRegistry:
    def register(self, tool: Tool) -> None: ...
    def get(self, name: str, version: str | None = None) -> Tool: ...
    async def invoke(self, name: str, arguments: dict, context: ToolContext) -> ToolResult: ...
```

约束：

- 工具名和版本在注册时校验，重复注册不能静默覆盖；
- 原始字典先通过 `input_model` 校验，再传给工具；工具返回值必须通过 `output_model` 校验；
- `ToolResult` 只允许结构化数据、状态和脱敏元数据，不把任意异常正文直接放入 State；
- 同步函数通过 `asyncio.to_thread` 或受控 executor 执行，不能在事件循环中直接阻塞；
- 线程任务收到取消时，要记录“调用已取消但底层同步函数可能仍在运行”的事实，不能虚假宣称已终止；
- 工具本身不直接修改框架 State，必须返回结果，由 Agent 决定如何形成 `AgentResult`；
- 工具 schema、版本和副作用属性应进入 checkpoint/trace 元数据，便于恢复兼容检查。

### 5.2 ToolContext 与安全策略

`ToolContext` 只暴露必要的 `run_id`、`node_id`、工具版本、取消信号、日志器、Checkpoint
存储和幂等能力。不得把任意 executor 内部对象或数据库连接暴露给工具。

Registry 或 Middleware 至少提供：

- 显式工具 allowlist，默认拒绝未登记工具；
- 每个工具的最大输入/输出大小；
- 每次调用的 timeout 和并发/速率限制；
- 参数和结果日志脱敏；
- `side_effect=True` 时要求显式声明幂等策略；
- 禁止 shell、动态导入和任意代码执行工具进入默认示例。

对于 URL、文件和命令类工具，本阶段只定义策略接口和拒绝默认值，不为了演示而放开 SSRF、
任意路径或任意命令执行。

### 5.3 LLM Provider 协议

核心只依赖抽象消息和结构化响应：

```python
class LLMProvider(Protocol):
    name: str
    version: str
    async def complete(self, request: LLMRequest, context: LLMContext) -> LLMResponse: ...

class LLMRequest:
    messages: list[ChatMessage]
    model: str
    temperature: float = 0.0
    tools: list[ToolSpec] = []
    response_schema: type[BaseModel] | None = None

class LLMResponse:
    message: ChatMessage
    finish_reason: str
    usage: Usage | None
    raw_metadata: dict
```

要求：

- Provider 只返回结构化 `LLMResponse`，不能让厂商 SDK 类型穿透 `magent` 核心；
- Provider 异常映射为统一错误码，并区分限流、临时故障、认证失败、参数错误和内容拒绝；
- `response_schema` 存在时，模型输出必须经过校验，失败不得直接写入 State；
- 默认温度和 Fake Provider 结果必须确定性，便于离线重放；
- 记录 provider/model/version，但不记录 API Key、完整 Authorization header 或未脱敏 prompt；
- LLM 输出中的工具名和参数必须再次经过 Registry allowlist 与 schema 校验；
- 外部文本只能视为不可信输入，不能让其改变系统工具策略或执行权限。

至少实现一个 Fake Provider；真实厂商 adapter 放在可选依赖或独立模块中，核心安装不应因其缺失
而失败。

### 5.4 Middleware 协议

Middleware 应围绕一次 Agent/Tool/LLM 调用，不复制 Executor 的调度、重试和 checkpoint：

```python
class Middleware(Protocol):
    async def before(self, request: Invocation) -> Invocation: ...
    async def after(self, request: Invocation, response: Any) -> Any: ...
    async def on_error(self, request: Invocation, error: BaseException) -> Any: ...
```

第一版内置：

- 结构化调用日志/指标 middleware；
- 工具 allowlist middleware；
- 工具速率限制 middleware；
- 输入输出大小限制 middleware；
- 脱敏 middleware。

组合语义必须固定并测试：before 按注册顺序执行，after 按逆序执行；异常默认向上抛出，只有
显式 middleware 才能转换错误；middleware 不得静默修改状态；同一 middleware 不得因重试被
错误地注册多次。`run_node` 仍是节点级 timeout/retry 的唯一来源。

## 6. 与现有框架的衔接

### 阶段 4 可靠性

- Tool/LLM 的临时网络、429/5xx 和明确 transient 错误映射为 `RetryableError`；
- 认证失败、参数校验失败、allowlist 拒绝和 schema 错误默认不可重试；
- timeout、caller cancellation 和底层同步任务未终止的状态必须进入 AttemptRecord；
- middleware 不能在内部再实现一套 retry，避免重试次数乘法膨胀。

### 阶段 5 Checkpoint 与幂等

- 工具/LLM 请求的 provider、tool version、参数 schema 和输入摘要进入兼容性元数据；
- 有副作用工具必须通过 `SideEffectSink` 或业务侧唯一键保护，不能仅依赖 `ToolSpec.idempotent=True` 的声明；
- LLM 请求默认不作为外部副作用写入 checkpoint；若缓存响应，缓存键必须包含 provider、model、版本、规范化请求和安全策略版本；
- Checkpoint 仍只由 Executor 管理，工具和 middleware 只能通过 `ToolContext` 使用受控接口；
- EventBus 的调用事件只是观测信息，恢复不能依赖事件是否送达。

### 后续 VulnTell

阶段 6 只提供通用能力。NVD/CNVD 适配、漏洞字段、请求限速策略、报告提示词和指标计算全部
放入阶段 7，并通过 fixture 验证。LLM 可以解释或生成报告，但不能直接改变确定性漏洞评分。

## 7. 推荐任务拆分

### Task 0：阶段 5 发布收尾与协议冻结（已完成）

关闭阶段 5 发布门禁，补齐 checksum、并发序号、幂等 claim、运行状态和恢复边界测试；更新
公共 API 状态。随后冻结 ToolSpec、ToolResult、Provider、Middleware 的字段和版本策略，
产出一份最小协议 fixture。本任务已完成。

### Task 1：Tool 领域模型与 Registry

实现 ToolSpec、ToolContext、ToolResult、ToolError、Registry 注册/查找/重复检测和公共导出。
先使用纯确定性工具，不接网络和外部数据库。

### Task 2：参数/结果校验与同步异步适配

实现 Pydantic 输入输出校验、同步函数线程适配、异步函数调用、取消和错误映射。补充大输入、
非法输出、同步阻塞和取消清理测试。

### Task 3：Tool 安全策略

实现 allowlist、大小限制、超时、并发/速率限制、敏感字段脱敏和副作用声明检查。默认策略
必须拒绝未登记工具、shell、任意 URL 和任意文件路径。

### Task 4：LLM 抽象与 Fake Provider

实现 ChatMessage、LLMRequest、LLMResponse、Usage、Provider 错误和 Fake Provider；覆盖结构化
输出校验、工具调用请求校验和无 API Key 离线运行。

### Task 5：可选 Provider Adapter

选择一个独立的可选适配器验证协议映射，隔离厂商 SDK、认证和原始响应。默认测试只使用 Fake
Provider；真实网络 smoke test 若需要，必须单独标记且不进入默认 CI。

### Task 6：Middleware 组合器与内置实现

实现 Agent/Tool/LLM 调用包装、顺序/逆序钩子、异常传播、日志脱敏、限流和统计。验证与
`run_node` 的 retry/timeout 不重复计数。

### Task 7：Runtime、EventBus、Checkpoint 元数据衔接

扩展 `Runtime`/`ToolContext` 的最小只读能力，发布工具/LLM 调用事件，补充版本和输入摘要；
不得把原始 prompt、密钥或完整漏洞描述无控制地写入 report/checkpoint。

### Task 8：示例、文档和阶段发布

提供完全离线的工具 Agent、Fake LLM Agent 和 middleware 示例；更新 README、`API.md`、
`DESIGN.md`、`ROADMAP.md`；执行全量测试、类型检查和依赖最小安装验证，形成阶段 6 独立提交。

## 8. 测试要求

至少新增 30 个有意义的离线测试，并保留阶段 1～5 全部回归：

### Tool

- [ ] 工具注册、重复版本、未注册查找和 allowlist 拒绝；
- [ ] 合法/非法输入和输出 schema 校验；
- [ ] 同步工具在线程中执行，事件循环不被阻塞；
- [ ] 异步工具结果、异常、超时和调用方取消；
- [ ] 429/5xx 可重试，认证/参数/schema/权限错误不可重试；
- [ ] 限流、并发上限、输入输出大小和脱敏；
- [ ] 副作用工具要求幂等策略，重复 execution key 不重复写入。

### LLM

- [ ] Fake Provider 在无 API Key、无网络时稳定返回；
- [ ] 请求参数、消息和响应 schema 校验；
- [ ] provider/model/version 进入元数据且不泄露凭据；
- [ ] provider 错误正确映射到可靠性错误分类；
- [ ] LLM 请求的工具名/参数再次经过 Registry 校验；
- [ ] 恶意文本不能改变 allowlist 或执行权限；
- [ ] 可选 adapter 缺失时核心仍可安装和导入。

### Middleware 与集成

- [ ] before 顺序、after 逆序和异常传播；
- [ ] middleware 不重复注册、不直接修改 State；
- [ ] middleware 与 retry/timeout/cancellation 的调用次数一致；
- [ ] EventBus 事件失败不改变工具结果或核心状态；
- [ ] 工具 Agent 能在顺序 Graph 和并发 Graph 中运行；
- [ ] checkpoint 恢复后工具版本不兼容会明确拒绝；
- [ ] 全量测试、类型检查、导入检查和最小依赖安装通过。

所有默认测试必须离线、无真实 API Key、无真实 LLM、无漏洞源和无生产副作用。真实网络
验证只作为显式 smoke test，不能成为阶段验收的必要条件。

## 9. 量化验收标准（已满足）

阶段 6 同时满足以下条件才算完成：

1. 阶段 5 发布门禁已关闭，阶段 5 改动已形成可追踪提交；
2. 新增离线测试不少于 30 个，阶段 1～5 原有测试全部通过；
3. Tool 输入/输出 schema 校验覆盖率达到 100%（所有公开 invoke 路径均经过校验）；
4. 未注册工具、未授权工具、越过大小限制和非法工具参数均被拒绝且有结构化错误；
5. 同步、异步工具均能执行；同步工具不直接阻塞事件循环，取消和超时有明确报告；
6. `run_node` 的重试次数、timeout 次数和 Tool/LLM middleware 统计不发生重复计数；
7. Fake Provider 在无网络和无 API Key 环境下稳定运行，LLM 核心协议不导入厂商 SDK；
8. LLM 结构化输出和工具调用参数均经过 schema/allowlist 校验，恶意文本不能提升权限；
9. 同一副作用 execution key 的并发/重放测试只产生一次受保护写入；
10. README、`DESIGN.md`、`API.md`、`ROADMAP.md` 和本文件的实现状态一致；
11. 默认安装不要求 LLM 厂商依赖，`python -m pytest -q`、类型检查和离线示例全部通过；
12. 不引入 VulnTell 业务模型，不执行漏洞利用、PoC、资产探测或未经授权的远程操作。

## 10. 完成定义（已完成）

```text
阶段 5 发布门禁关闭
        ↓
Tool 协议、Registry 和 schema 校验
        ↓
同步/异步执行、超时取消与安全策略
        ↓
LLM Provider 抽象与 Fake Provider
        ↓
Middleware 组合与可靠性衔接
        ↓
Checkpoint/EventBus 元数据和脱敏
        ↓
离线示例、测试、类型检查和文档发布
```

阶段 6 完成后，框架具备可控的工具调用和可替换 LLM 扩展能力；只有到阶段 7 才开始实现
VulnTell 的真实数据源 Agent、标准化、持久化、聚合和报告流程。

## 11. 建议提交节奏

```text
fix(phase5): close checkpoint release gates
test(phase5): add corruption and concurrent idempotency cases
design(phase6): freeze tool provider middleware contracts
feat(tools): add tool models and registry
feat(tools): add schema validation and sync async adapter
feat(tools): add allowlist timeout rate limit and redaction
feat(llm): add provider protocol and fake provider
feat(llm): add optional provider adapter
feat(middleware): add composable invocation middleware
feat(runtime): expose safe tool and llm context
test(phase6): cover offline tool llm middleware contracts
docs: document phase-6 extension semantics
```
