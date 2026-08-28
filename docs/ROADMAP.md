# 自研多智能体框架实现路线图与验收标准

> 每个阶段都必须产出可运行代码、测试和文档。VulnTell 是贯穿式示例应用，用于验证框架能力，不应成为框架核心的业务耦合。

## 阶段 0 — 项目初始化与参考分析

建立 `magent` 包、依赖管理和质量基线；阅读 LangGraph、AutoGen、CrewAI 的 Agent、State、Graph、Executor、Checkpoint 和错误处理设计，形成 `COMPARISON.md`。不复制第三方源码。

验收：`pip install -e .`、`python -m pytest`、`import magent` 成功；参考分析和边界文档完成。

## 阶段 1 — Agent、State 与 Result 最小执行模型

详细实施方案见 [`PHASE1.md`](F:/personal/tool/muti-agent/docs/PHASE1.md)。本阶段只建立单进程、单流程、确定性的最小内核，不提前实现 Graph、并发、EventBus、Checkpoint、LLM 或 VulnTell 业务。

## 阶段 2 — Graph 与顺序、条件执行

实现节点注册、边、条件路由、图校验和顺序执行。验收：支持 A→B→C、B/C 条件分支；能够发现重复节点、无效边和孤立节点；轨迹包含节点顺序和最终状态。

## 阶段 3 — 并发执行与 EventBus

实现无依赖节点并行、并发限制、结果合并和明确的 Command/Event/Result/Error 语义。验收：并行性能相对串行基线可测量；覆盖消息顺序、异常、取消订阅和容量限制。

## 阶段 4 — 超时、重试、取消与错误策略

实现节点超时、指数退避、错误分类、取消传播和终止/跳过/降级策略。验收：临时错误按策略重试，永久错误不无限重试，超时可取消，错误信息进入报告。

## 阶段 5 — Checkpoint、恢复与幂等

实现 `CheckpointStore`、SQLite 快照、`run_id`、节点版本、恢复和外部副作用幂等。验收：进程中断后从最近成功节点恢复，不重复写入，覆盖失败和中断测试。

## 阶段 6 — 工具、LLM Agent 与 Middleware 扩展

实现工具协议、同步/异步适配、可选 LLM Provider、日志/限流 Middleware 和工具白名单。验收：核心不绑定单一 LLM SDK；无 API Key 时确定性 Agent 仍可运行；工具结果经过 schema 校验。

## 阶段 7 — VulnTell 纵向示例

使用自研框架实现 NVD/CNVD 等数据源 Agent、标准化、持久化、聚合、指标计算和报告。论文材料作为业务设计和离线 fixture 参考，不放入框架核心。验收：fixture 离线跑通、部分源失败可生成报告、重复运行幂等、业务不修改 `magent` 执行逻辑。

## 阶段 8 — 评测、可观测性与对比实验

记录 trace、耗时、重试、失败、资源消耗和恢复结果；对比串行基线，并评估漏洞去重、标准化和指标计算质量。验收：实验可离线重放，评分记录数据集、窗口、样本数和版本，样本不足不强行排名。

## 阶段 9 — 发布与展示

完善 README、API 文档、示例配置、CI、许可证说明和可选 Web 看板。验收：新用户可按 README 完成离线运行；CI 在干净环境通过；不包含密钥、敏感日志或未授权数据。

## 建议提交节奏

```text
init → agent-state → graph → concurrency-events → reliability
→ checkpoint → extensions → vulntell-example → benchmarks → release
```
