# 自研多智能体框架与 VulnTell 示例应用

> 项目定位：实现一个可复用、可测试、可恢复的轻量多智能体执行框架，并使用公开漏洞情报项目 VulnTell 验证框架能力。

## 1. 项目定位

| 维度 | 说明 |
|------|------|
| **核心目标** | 自研 Agent、类型化状态、图编排、并发执行、错误处理、Checkpoint 和可观测能力。 |
| **示例应用** | 使用该框架实现 VulnTell：采集、标准化、聚合和评估公开漏洞情报。 |
| **参考项目** | LangGraph、AutoGen、CrewAI 等仅用于学习设计思路、建立功能对比和测试基线，不直接复制其实现。 |
| **技术栈** | Python 3.11+、asyncio、Pydantic、httpx、SQLite、pytest。LLM 和 Web 看板属于可选扩展。 |
| **项目价值** | 通过真实业务场景验证框架的状态流转、并发、恢复、可观测和插件扩展能力。 |

框架与业务保持边界：漏洞模型、数据源适配器和情报指标属于 `examples/vulntell`，不能反向污染 `magent` 核心。

## 2. 范围边界

### 框架核心包含

- Agent 生命周期和结构化执行结果
- 类型化共享状态
- 有向执行图、顺序节点、并行节点和条件路由
- 异步执行、超时、取消、重试和错误传播
- 状态快照、Checkpoint、恢复和幂等执行
- 可插拔的消息/事件机制
- 日志、执行轨迹和基础指标
- Agent、工具、存储和中间件扩展接口

### 首版不包含

- 通用自主规划算法
- 分布式多机调度
- 复杂消息队列或工作流集群
- 自动执行漏洞利用、PoC、资产探测或扫描
- 让 LLM 决定评分结果

首版重点是可靠的本地单进程框架。只有本地执行语义稳定后，才考虑分布式或更复杂的自主规划能力。

## 3. 总体架构

```text
┌────────────────────────────────────────────────────────────┐
│                         magent 框架                         │
│ Agent Contract │ Typed State │ Graph │ Executor │ Runtime   │
│ Retry/Timeout  │ Checkpoint  │ Event │ Middleware │ Trace   │
└──────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│                 examples/vulntell 示例应用                  │
│ Source Agents │ Normalize │ Persist │ Aggregate │ Evaluate   │
│                                              │              │
│                                         Report Agent        │
└──────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
                    NVD / CNVD / CISA KEV / SQLite
```

框架层只处理“如何执行 Agent”，业务层负责“处理什么数据”。

## 4. 核心执行模型

### 4.1 Agent

Agent 是可被框架调度的执行单元，不要求必须使用 LLM。规则型、工具型和 LLM Agent 都应实现统一执行协议。

```python
class Agent(Protocol):
    name: str

    async def run(self, state: State, runtime: Runtime) -> AgentResult:
        ...
```

`AgentResult` 应结构化表达：状态更新、事件或消息、下一步路由、成功/失败/跳过状态、错误信息和执行元数据。Agent 不应直接依赖具体业务数据库，也不应随意修改全局状态。

### 4.2 Typed State

使用 Pydantic 或其他明确 schema 定义运行状态，禁止把 Blackboard 设计成无约束共享字典。状态更新必须经过框架校验和合并，以便处理并行写入、审计、序列化和恢复。

至少需要定义：字段及类型、读写约束、并行合并策略、状态版本号和快照格式。

### 4.3 Graph 和 Executor

执行图至少支持：

```text
A → B → C                 顺序执行
A ──┬→ B ──┐
    └→ C ──┴→ D           并行与汇合
A → 条件判断 → B / C      条件路由
```

Executor 负责调度和生命周期；Graph 只描述拓扑和路由规则。两者不能混为包含大量业务判断的 Orchestrator。

### 4.4 Runtime 和可靠性策略

`Runtime` 提供一次运行所需的基础能力：`run_id`、节点 ID、尝试次数、超时与取消信号、重试策略、并发限制、日志/指标/trace、工具上下文和 Checkpoint 存储。

节点失败时的行为必须明确：终止、重试、跳过、降级或人工审核，不能依赖未定义的默认行为。

### 4.5 Checkpoint 与幂等性

Checkpoint 是执行状态的持久化提交记录，不是 EventBus 的日志缓存。节点执行前保存输入快照，
节点成功后把“合并后的状态、路由结果和下一执行 frontier”以一个事务提交；只有成功提交的节点
才算完成。进程在节点执行中断时，结果视为未知，恢复时从该节点输入快照重新执行。

恢复协议必须保存 `run_id`、workflow/graph version、node ID/version、state schema hash、
单调 checkpoint 序号、尝试历史、条件路由和并发 join 所需的父节点提交信息。顺序图和并发 DAG
均不得依赖任务完成顺序恢复状态；reducer 按声明顺序重放。版本、schema、checksum 或 frontier
无法验证时应明确拒绝恢复，不进行隐式迁移或猜测。

外部副作用节点使用不包含 `attempt` 的稳定执行键（例如
`run_id + node_id + node_version + canonical(input_state)`）。这只能让具备幂等协议或唯一键的
副作用安全重试；对不受框架控制的 API、消息和文件系统，系统最多提供 at-least-once，不能由
Checkpoint 单独保证 exactly-once。详细字段、SQLite 表和验收要求见 [`PHASE5.md`](F:/personal/tool/muti-agent/docs/PHASE5.md)。

### 4.6 Tools、LLM 与 Middleware 扩展

工具、LLM Provider 和 Middleware 属于框架扩展层，不改变 Executor 的状态合并、重试、
Checkpoint 和取消主语义。工具必须经过 Registry、输入/输出 schema 和 allowlist；同步工具不能
阻塞事件循环；LLM 只通过可替换 Provider 协议接入，核心不绑定厂商 SDK；middleware 只包装
调用生命周期，不能复制一套 retry 或直接修改 State。阶段 6 的实施边界和验收标准见
[`PHASE6.md`](F:/personal/tool/muti-agent/docs/PHASE6.md)。

### 4.7 EventBus

EventBus 是可插拔通信组件，不应成为所有状态交换的默认方式。应区分 Command、Event、Result 和 Error。首版需要明确消息顺序、异常处理、重复消费、取消订阅和队列容量；复杂持久化消息队列不属于首版范围。

## 5. VulnTell 示例应用

### 5.1 业务流程

```text
NVD Agent ─────┐
               ├→ Normalize → Persist → Aggregate → Evaluate → Report
CNVD Agent ────┘
```

VulnTell 用于验证多源 Agent 并行执行、状态合并、部分失败、SQLite 幂等写入和固定数据集评测。CISA KEV 等专用源可在后续扩展。

### 5.2 数据模型

标准漏洞实体与来源观察记录分离：

```text
CanonicalVulnerability   标准化后的漏洞实体
SourceObservation        某来源对漏洞的观察记录
MetricSnapshot            某时间窗口内的指标结果
```

`SourceObservation` 至少保存：`source`、`source_record_id`、`cve_id`、`published_at`、`modified_at`、`source_added_at`、`observed_at`、`raw_payload`、`normalized_fields`、`parser_version`。

时间统一使用带时区的 UTC 时间。CVSS 保存版本、向量和分数；引用保存 URL、类型和验证状态。

### 5.3 情报源质量评估

评分采用确定性规则，LLM 只能解释评分，不能修改评分结果。综合评分是派生结果，不是与基础指标并列的独立维度。

| 维度 | 建议定义 |
|------|----------|
| 数据量 | 时间窗口内新增记录数、唯一漏洞数和更新记录数 |
| 时效性 | 参考时间点到源记录时间的相对延迟 |
| 完整性 | 标准字段的加权覆盖率，并区分存在率与有效率 |
| 维护性 | 更新频率、更新间隔分布和持续维护比例 |
| 可验证性 | 有效引用率、权威来源占比和关键字段可回溯率 |
| 相关性 | 对指定技术栈、行业或任务画像的匹配程度 |
| 相对独立性 | 当前观测范围内的首次观察比例，不等同于真实原创率 |

CISA KEV 属于已利用漏洞目录，不与 NVD 按相同覆盖率直接排名。不同来源应使用匹配其职责的指标。

### 5.4 论文材料的复用原则

论文中的 COSV 风格字段、时间窗口、TTI、完整性、维护性、可验证性、相关性和相对独立性分析，可以作为 VulnTell 业务层的设计和 fixture 来源。

论文历史数据只能作为基线或离线测试材料，不能直接当作当前系统结论。每次评估都必须记录数据集、时间窗口、采集时间、解析器版本和指标版本。

## 6. 评测体系

### 框架评测

- Agent 调度和路由正确率
- 顺序与并行执行耗时
- 失败重试成功率
- 超时取消是否生效
- Checkpoint 恢复成功率
- 状态合并正确率
- 重复运行的幂等性
- 与简单串行基线的性能对比

### 业务评测

- CVE 去重准确率
- 字段标准化完整率
- 跨源字段一致性
- 固定样本覆盖率
- 报告生成完整性

普通测试使用本地 fixture 和 mock，真实网络 smoke test 单独运行并设置超时、限速和重试。

## 7. 安全与合规

外部漏洞描述可能包含 Prompt Injection；远程 URL 抓取可能引入 SSRF；工具插件可能产生任意副作用；API Key 和敏感日志不得进入代码。首版不自动抓取引用链接、不执行外部代码，并对工具调用设置白名单和超时。

## 8. 目录结构

```text
muti-agent/
├── pyproject.toml
├── README.md
├── docs/
│   ├── DESIGN.md
│   ├── ROADMAP.md
│   ├── PHASE1.md
│   ├── PHASE2.md
│   ├── PHASE3.md
│   ├── PHASE4.md
│   ├── PHASE5.md
│   ├── API.md
│   ├── COMPARISON.md
│   └── BENCHMARKS.md
├── src/magent/
│   ├── core/
│   │   ├── agent.py
│   │   ├── state.py
│   │   ├── result.py
│   │   ├── runtime.py
│   │   ├── executor.py
│   │   ├── errors.py
│   │   └── events.py
│   ├── graph/
│   ├── checkpoint/
│   ├── tools/
│   ├── llm/
│   ├── middleware/
│   └── observability/
├── examples/vulntell/
│   ├── models/
│   ├── sources/
│   ├── agents/
│   ├── evaluation/
│   └── cli.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── contract/
├── benchmarks/
└── fixtures/
```

## 9. GitHub 策略

个人仓库以自研框架为主体，在 README 和 `docs/COMPARISON.md` 中说明 LangGraph、AutoGen 等参考项目。研究 LangGraph 源码时可单独 Fork 或保留上游远程仓库，但不要复制上游源码到本项目；应记录参考 commit，遵守许可证要求，并将自己的实现、测试和实验结果放在个人仓库中。
