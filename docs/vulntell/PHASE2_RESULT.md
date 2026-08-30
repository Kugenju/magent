# VulnTell 阶段 2 完成记录

> 依据 `PHASE2_PLAN.md` 实施领域层迁移。本文件记录迁移差异、弃用策略与回滚方式。阶段 2 已完成；阶段 3（运行时编排迁移）也已完成，见 [PHASE3_RESULT.md](PHASE3_RESULT.md)。

## 1. 迁移映射

| 旧模块 (examples/vulntell) | 新模块 (apps/vulntell) | 类型 |
| --- | --- | --- |
| models.py | domain/models.py | 领域模型（逐字段、类型、默认值、序列化不变） |
| loading.py | domain/schemas.py | 数据集 / fixture 加载 |
| normalize.py | domain/normalize.py | 纯标准化规则 |
| dedupe.py | domain/dedupe.py | 纯去重 / 聚合规则 |
| metrics.py | domain/metrics.py | 纯指标计算 |
| report.py | reporting/report.py + reporting/exporters.py | 报告组装 / 导出 |
| fixtures/ | apps/vulntell/fixtures/ | 应用数据（内容与原 fixture 逐字节一致） |
| — | domain/policies.py | 新增：跨源优先级、相关性画像、最小样本、必需字段、校验正则 |

`state.py` / `agents.py` / `graph.py` / `run.py` 已在**阶段 3** 迁移为 `apps.vulntell.pipeline`
下的真实实现；`examples/vulntell/{state,agents,graph,run}.py` 现为转发到 `apps.vulntell.pipeline`
的薄壳。`db.py` / `sources.py` 仍保留在 `examples/vulntell`（阶段 6 / 阶段 4 再迁移），并由
`apps.vulntell/storage/legacy.py` 与 `apps.vulntell/sources/legacy.py` 集中 re-export，不复制逻辑。

## 2. 导入方向

```
apps.vulntell.application
    → apps.vulntell.pipeline.jobs.VulnTellJobRunner   (阶段 3 起唯一编排入口)
    → apps.vulntell.pipeline.{state,agents,graph}       (真实实现)
    → apps.vulntell.storage.legacy / sources.legacy      (阶段 3/4/6 过渡包装)

apps.vulntell.pipeline
    → apps.vulntell.domain / apps.vulntell.reporting      (真实实现)
    → examples.vulntell.db / examples.vulntell.sources     (仅经 legacy 包装，阶段 3 不复制逻辑)

apps.vulntell.domain / reporting
    → 仅依赖 pydantic 与 magent.checkpoint.models 的纯工具函数
    → 不导入 examples、不导入 magent 运行时 / 编排
```

约束已满足：`apps.vulntell.domain` 不导入 `examples`；`src/magent` 无 VulnTell import。

## 3. 兼容与弃用策略

旧领域模块（`examples/vulntell/{models,loading,normalize,dedupe,metrics,report}.py`）
改为**明确的 re-export 转发**到 `apps.vulntell.domain` / `reporting`，并标注弃用说明：
- 真实实现只有一份，位于 `apps`；旧模块不再包含业务代码；
- 既有 `from examples.vulntell... import ...` 的外部调用（tests、benchmarks）继续可用；
- 阶段 3 完成、Graph/任务层迁移后，再移除这些 re-export 并进入弃用周期。

## 4. 与阶段 0 基线差异

无 schema / 报告 / checkpoint / 公开入口变更。默认、无 LLM、单源失败、resume、trace
场景与 `tests/contract/vulntell/baselines/` 冻结基线逐字段一致（contract tests 覆盖）。
fixture 改为从 `apps.vulntell.fixtures` 解析（路径与当前工作目录无关），内容为原 fixture
的逐字节副本，因此行为等价。

## 5. 回滚方式

- 若阶段 2 引入回归：保留的 `examples` re-export 可立即切回 `examples.vulntell` 旧模块
  （git 历史中仍可用）；新代码与旧代码通过同一份 `apps.vulntell.domain` 实现，不存在
  双份逻辑，回滚不会造成结果漂移。
- 验证命令：`python -m pytest -q tests/contract/vulntell tests/unit`、`mypy src/magent`、
  `python -m apps.vulntell --no-llm --json` 与 `python -m examples.vulntell --no-llm --json`
  输出应逐字段一致。

## 6. 后续阶段

阶段 2 与阶段 3 均已完成。阶段 4（数据源迁移至 `apps.vulntell.sources`）与阶段 6
（存储迁移至 `apps.vulntell.storage`）将替换当前 legacy 过渡包装，届时移除
`examples/vulntell/{db,sources}.py` 与 legacy 转发。具体任务、依赖和验收标准见
[PHASE3_PLAN.md](PHASE3_PLAN.md) 与 [PHASE3_RESULT.md](PHASE3_RESULT.md)。
