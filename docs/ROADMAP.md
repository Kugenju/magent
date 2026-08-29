# 自研多智能体框架实现路线图与验收标准

> 每个阶段都必须产出可运行代码、测试和文档。VulnTell 是贯穿式示例应用，用于验证框架能力，不应成为框架核心的业务耦合。

## 当前进度

截至当前工作区检查：

- 阶段 0：项目骨架、`pyproject.toml`、README、测试配置和参考项目对比材料已完成。
- 阶段 1：核心执行内核已完成，Producer/Consumer 离线示例可运行。
- 阶段 2：Graph、条件路由、拓扑校验和顺序 Graph 执行已完成。
- 阶段 3：fan-out/fan-in、状态 reducer、并发执行、取消传播和内存 EventBus 已完成。
- 阶段 4：超时、显式可重试错误、指数退避、调用方取消、失败传播和结构化尝试报告已完成；
  当前全量离线测试为 103 个且全部通过，阶段 4 文档已在提交
  `f45c672 docs: document phase-4 reliability semantics` 中同步。
- 阶段 5：Checkpoint / SQLite 快照 / 顺序与并发 DAG 恢复 / 稳定 execution key / 幂等副作用已完成；
  发布门禁（checksum 读后校验、并发序号统一分配、幂等竞态原子 claim、运行状态一致性、
  版本与 frontier 可追溯）已关闭，阶段 5 已提交。当前全量离线测试为 168 个且全部通过，
  pyproject 中 `pythonpath=["src"]`、`asyncio_mode="auto"`；执行器在无 `checkpoint_store` 时保持阶段 1–4 行为不变。
- 阶段 6：工具协议（ToolSpec/ToolRegistry、输入输出 schema 校验、同步/异步适配、超时/allowlist/
  限流/脱敏、幂等副作用）、可插拔 `LLMProvider` 与确定性 `FakeProvider`、可选 OpenAI 适配器（懒加载）、
  以及可组合 Middleware（logging/rate-limit/size-limit/redaction、确定性 compose）已完成。
  核心不绑定单一 LLM SDK；无 API Key/网络时确定性 Agent 仍可运行；本阶段新增 38 个测试且全部通过。
 - 阶段 7：VulnTell 纵向示例已完成并提交（代码位于 `examples/vulntell`，文档位于 `docs/PHASE7.md`）。
   业务包离线跑通：多源采集→标准化→质量告警→去重→持久化→并发可恢复 Graph→聚合指标→报告；
   部分源失败仍可产出报告；重复运行幂等；核心不绑定业务。Phase 7 完成时全量离线测试为 211 个且全部通过。

- 阶段 8：评测、可观测性与对比实验已完成并提交（可观测性代码位于 `src/magent/observability`，
   实验代码位于 `benchmarks/`，文档位于 `docs/PHASE8.md`，实验说明位于 `benchmarks/README.md`）。
   只读 `Trace`/`Span`/`RunSummary` 可观测协议与 EventBus 接入；离线 `benchmarks/` runner 覆盖
   确定性 / 隔离安全 / 并行可靠性（重试·超时）/ Checkpoint 恢复；VulnTell 源质量评测（去重
   precision/recall/F1、跨源一致性、标准化率、可复现性、样本不足不排名）；参考框架对比记录器仅记录
    版本、不输出排名。Phase 8 新增离线测试 39 个，全量离线测试为 250 个且全部通过。

 - 阶段 9：发布、展示与工程化收口已完成本地候选发布准备。目标为可安装、可验证、可理解、可展示的 GitHub 源码仓库
   发布；不改变执行语义。交付物包括文档事实统一、框架对比 `docs/COMPARISON.md`、许可证与第三方归属、
   GitHub Actions CI、干净安装验证、安全/敏感信息审计、`CHANGELOG.md` 与发布检查清单。PyPI 正式发布与
   Web 看板不在默认交付范围内，须单独验收。

## 阶段 0 — 项目初始化与参考分析

建立 `magent` 包、依赖管理和质量基线；阅读 LangGraph、AutoGen、CrewAI 的 Agent、State、Graph、Executor、Checkpoint 和错误处理设计，形成 `COMPARISON.md`。不复制第三方源码。

验收：`pip install -e .`、`python -m pytest`、`import magent` 成功；参考分析和边界文档完成。参考项目对比文档可在发布阶段补齐，但不能伪称已经完成。

## 阶段 1 — Agent、State 与 Result 最小执行模型（已完成）

详细方案见 [`PHASE1.md`](docs/PHASE1.md)。阶段 1 建立单进程、单流程、确定性的最小内核：Agent、类型化状态更新、结构化结果、Runtime、顺序执行器和执行报告。

## 阶段 2 — Graph 与顺序、条件执行（已完成）

详细方案见 [`PHASE2.md`](docs/PHASE2.md)。阶段 2 支持节点注册、无条件边、条件路由、拓扑校验和单路径顺序 Graph 执行；不包含并发、重试、Checkpoint、EventBus 或 VulnTell。

## 阶段 3 — 并发执行与 EventBus（已完成）

详细方案见 [`PHASE3.md`](docs/PHASE3.md)。阶段 3 已实现无依赖节点并行、fan-out/fan-in、并发限制、显式 reducer、失败取消传播和内存 EventBus，并已由阶段 4 回归测试覆盖。

## 阶段 4 — 超时、重试、取消与错误策略（已完成）

详细方案见 [`PHASE4.md`](docs/PHASE4.md)。本阶段为 Agent 调用建立显式可靠性策略：节点超时、可重试错误分类、指数退避、调用方取消、失败传播和结构化尝试记录。阶段 3 已有的兄弟分支取消语义必须与本阶段的调用方取消区分。

## 阶段 5 — Checkpoint、恢复与幂等（已完成）

详细实施计划见 [`PHASE5.md`](docs/PHASE5.md)。本阶段实现 `CheckpointStore`、SQLite 快照、运行/图/节点版本、顺序与并发 DAG 恢复、
稳定 execution key 和幂等记录，发布门禁已关闭。

本阶段只保证框架状态提交的原子性，以及接入幂等协议后的安全重试；任意外部 API 或数据库的
exactly-once 不属于单独 checkpoint 能力。

## 阶段 6 — 工具、LLM Agent 与 Middleware 扩展（已完成）

详细实施计划见 [`PHASE6.md`](docs/PHASE6.md)。已完成 ToolSpec/ToolRegistry、
输入输出 schema 校验、同步/异步适配、超时取消、allowlist、限流与脱敏；随后实现可选 `LLMProvider`、
确定性 Fake Provider 和 Middleware 组合协议。验收重点是：核心不绑定单一 LLM SDK；无 API Key/网络时
确定性 Agent 仍可运行；工具与 LLM 输出经过 schema 和权限校验；重试、Checkpoint 和幂等语义不被扩展层复制或破坏。

## 阶段 7 — VulnTell 纵向示例（已完成）

详细实施计划见 [`PHASE7.md`](docs/PHASE7.md)。本阶段使用现有框架实现 NVD/CNVD 等数据源 Agent、标准化、持久化、聚合、指标计算和报告。论文材料作为业务设计和离线 fixture 参考，不放入框架核心。验收：fixture 离线跑通、部分源失败可生成报告、重复运行幂等、业务不修改 `magent` 执行逻辑。阶段 7 已提交，新增 43 个离线测试（模型/标准化/去重/指标/持久化/Graph 端到端/恢复/部分失败/LLM 边界/安全），全量 211 个测试通过。

## 阶段 8 — 评测、可观测性与对比实验（已完成）

实施计划和结果见 [`PHASE8.md`](docs/PHASE8.md) 与
[`benchmarks/README.md`](benchmarks/README.md)。本阶段已建立统一的
Trace/Span/RunSummary、离线实验 runner、VulnTell 质量评测和参考框架不可比记录；性能数字只对
声明的环境、版本、数据集和场景负责，样本不足时不进行排名。

## 阶段 9 — 发布、展示与工程化收口（候选发布已准备）

详细实施计划见 [`PHASE9.md`](docs/PHASE9.md)。本阶段已完善 README/API/DESIGN、参考项目对比、
许可证与第三方归属、干净安装说明、CI、离线示例和发布检查清单。当前仅剩远程 CI 验证、维护者
确认和正式 tag/release；验收重点是：
新用户可按 README 完成离线运行；CI 在声明的 Python 版本上通过；仓库不包含密钥、敏感日志、
临时数据库或未授权数据。Web 看板和 PyPI 发布不作为默认前置条件。

## 建议提交节奏

```text
init → agent-state → graph → concurrency-events → reliability
→ checkpoint/recovery → phase5-release-gate → tools/llm/middleware → vulntell-example → evaluation-observability → release-engineering → release
```
