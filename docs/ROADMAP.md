# 自研多智能体框架实现路线图与验收标准

> 每个阶段都必须产出可运行代码、测试和文档。VulnTell 是贯穿式示例应用，用于验证框架能力，不应成为框架核心的业务耦合。

## 当前进度

截至当前工作区检查：

- 阶段 0：项目骨架、`pyproject.toml`、README 和测试配置已完成；参考项目对比文档仍需补齐。
- 阶段 1：核心执行内核已完成，Producer/Consumer 离线示例可运行。
- 阶段 2：Graph、条件路由、拓扑校验和顺序 Graph 执行已完成。
- 阶段 3：fan-out/fan-in、状态 reducer、并发执行、取消传播和内存 EventBus 已完成。
- 阶段 4：超时、显式可重试错误、指数退避、调用方取消、失败传播和结构化尝试报告已完成；
  当前全量离线测试为 103 个且全部通过，阶段 4 文档已在提交
  `f45c672 docs: document phase-4 reliability semantics` 中同步。
- 阶段 5：Checkpoint / SQLite 快照 / 顺序与并发 DAG 恢复 / 稳定 execution key / 幂等副作用已实现；
  当前全量离线测试为 125 个且全部通过，执行器在无 `checkpoint_store` 时保持阶段 1–4 行为不变。
  但阶段 5 改动仍在工作区，需先完成 checksum、并发序号、幂等竞态和运行状态等发布门禁。
- 下一阶段：阶段 6 工具、LLM Agent 与 Middleware 扩展（以阶段 5 发布门禁关闭为前置条件）。

## 阶段 0 — 项目初始化与参考分析

建立 `magent` 包、依赖管理和质量基线；阅读 LangGraph、AutoGen、CrewAI 的 Agent、State、Graph、Executor、Checkpoint 和错误处理设计，形成 `COMPARISON.md`。不复制第三方源码。

验收：`pip install -e .`、`python -m pytest`、`import magent` 成功；参考分析和边界文档完成。参考项目对比文档可在发布阶段补齐，但不能伪称已经完成。

## 阶段 1 — Agent、State 与 Result 最小执行模型（已完成）

详细方案见 [`PHASE1.md`](F:/personal/tool/muti-agent/docs/PHASE1.md)。阶段 1 建立单进程、单流程、确定性的最小内核：Agent、类型化状态更新、结构化结果、Runtime、顺序执行器和执行报告。

## 阶段 2 — Graph 与顺序、条件执行（已完成）

详细方案见 [`PHASE2.md`](F:/personal/tool/muti-agent/docs/PHASE2.md)。阶段 2 支持节点注册、无条件边、条件路由、拓扑校验和单路径顺序 Graph 执行；不包含并发、重试、Checkpoint、EventBus 或 VulnTell。

## 阶段 3 — 并发执行与 EventBus（已完成）

详细方案见 [`PHASE3.md`](F:/personal/tool/muti-agent/docs/PHASE3.md)。阶段 3 已实现无依赖节点并行、fan-out/fan-in、并发限制、显式 reducer、失败取消传播和内存 EventBus，并已由阶段 4 回归测试覆盖。

## 阶段 4 — 超时、重试、取消与错误策略（已完成）

详细方案见 [`PHASE4.md`](F:/personal/tool/muti-agent/docs/PHASE4.md)。本阶段为 Agent 调用建立显式可靠性策略：节点超时、可重试错误分类、指数退避、调用方取消、失败传播和结构化尝试记录。阶段 3 已有的兄弟分支取消语义必须与本阶段的调用方取消区分。

## 阶段 5 — Checkpoint、恢复与幂等（功能完成，待发布门禁）

详细实施计划见 [`PHASE5.md`](F:/personal/tool/muti-agent/docs/PHASE5.md)。本阶段实现 `CheckpointStore`、SQLite 快照、运行/图/节点版本、顺序与并发 DAG 恢复、
稳定 execution key 和幂等记录。当前功能已实现，但发布前仍需验证 checkpoint checksum 读取校验、
并发序号分配、同一幂等键的并发 claim、运行状态更新和恢复记录完整性。阶段 5 的具体门禁见
[`PHASE5.md`](F:/personal/tool/muti-agent/docs/PHASE5.md) 第 12 节。

本阶段只保证框架状态提交的原子性，以及接入幂等协议后的安全重试；任意外部 API 或数据库的
exactly-once 不属于单独 checkpoint 能力。

## 阶段 6 — 工具、LLM Agent 与 Middleware 扩展（下一阶段）

详细实施计划见 [`PHASE6.md`](F:/personal/tool/muti-agent/docs/PHASE6.md)。先完成阶段 5 发布门禁，
再实现 ToolSpec/ToolRegistry、输入输出 schema 校验、同步/异步适配、超时取消、allowlist、
限流与脱敏；随后实现可选 `LLMProvider`、Fake Provider 和 Middleware 组合协议。验收重点是：
核心不绑定单一 LLM SDK；无 API Key/网络时确定性 Agent 仍可运行；工具与 LLM 输出经过 schema
和权限校验；重试、Checkpoint 和幂等语义不被扩展层复制或破坏。

## 阶段 7 — VulnTell 纵向示例

使用自研框架实现 NVD/CNVD 等数据源 Agent、标准化、持久化、聚合、指标计算和报告。论文材料作为业务设计和离线 fixture 参考，不放入框架核心。验收：fixture 离线跑通、部分源失败可生成报告、重复运行幂等、业务不修改 `magent` 执行逻辑。

## 阶段 8 — 评测、可观测性与对比实验

记录 trace、耗时、重试、失败、资源消耗和恢复结果；对比串行基线，并评估漏洞去重、标准化和指标计算质量。验收：实验可离线重放，评分记录数据集、窗口、样本数和版本，样本不足不强行排名。

## 阶段 9 — 发布与展示

完善 README、API 文档、示例配置、CI、许可证说明和可选 Web 看板。验收：新用户可按 README 完成离线运行；CI 在干净环境通过；不包含密钥、敏感日志或未授权数据。

## 建议提交节奏

```text
init → agent-state → graph → concurrency-events → reliability
→ checkpoint/recovery → phase5-release-gate → tools/llm/middleware → vulntell-example → benchmarks → release
```
