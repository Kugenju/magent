# VulnTell 阶段 3 审查记录

## 结论

阶段 3（Graph 与任务层迁移）已完成，可进入阶段 4“数据源契约与增量模型”。当前不建议直接接入真实 HTTP；应先冻结分页、游标、同步运行和错误分类契约。

## 已完成项

- `apps.vulntell.pipeline` 已包含 State、业务 Agent、Graph 和任务 Runner；
- `apps.vulntell.application` 直接依赖 `pipeline.jobs`，不再依赖 `examples.vulntell.run/state/agents/graph`；
- `examples.vulntell` 的对应模块仅保留兼容 re-export；数据源和存储仍通过 `legacy.py` 过渡；
- full run、resume、部分来源失败、幂等、资源关闭和无网络行为已有 contract 覆盖；
- 新旧 CLI 输出结构化等价；领域层和报告层未反向依赖 examples 或 magent 编排实现；
- `python -m pytest -q`：296 passed；`mypy src/magent`：通过；Markdown 链接检查：0 个断链。

## 尚未完成与技术债

1. `apps.vulntell.sources.legacy` 仍转发到 `examples.vulntell.sources`，没有分页/游标/增量协议；
2. `apps.vulntell.storage.legacy` 仍转发到 `examples.vulntell.db`，存储迁移属于阶段 6；
3. `HttpSourceAdapter` 仍是显式禁用接口，尚未实现限速、超时、重试和凭据策略；
4. 当前状态只表达一次 fixture 运行，尚未持久化 `SyncRun`、游标和批次边界；
5. 真实来源许可、字段映射和大响应/坏记录隔离尚未完成；
6. `PHASE2_PLAN.md`、`NEXT_STAGE.md` 等历史入口曾滞后，已在本次审查中同步为阶段 4。

## 阶段门禁判定

| 门禁 | 结果 | 证据 |
| --- | --- | --- |
| 新旧入口等价 | 通过 | `test_entrypoint_compat.py`、pipeline migration contract |
| State/checkpoint/resume 稳定 | 通过 | `test_pipeline_migration.py`、baseline fixtures |
| 部分失败与幂等 | 通过 | baseline 与 migration contract |
| 默认离线、无凭据 | 通过 | 无网络 contract、CLI smoke |
| 数据源增量契约 | 未开始 | 进入阶段 4 |
| 真实 HTTP 来源 | 未开始 | 明确禁止提前接入 |

## 下一步决策

阶段 4 只做协议、fixture 和可恢复同步骨架；完成其验收后，才允许阶段 5 开发 NVD/CNVD/CISA KEV live adapter。阶段 4/5 中发现的通用执行问题，必须先用业务无关最小复现验证，再决定是否修改 `magent`。
