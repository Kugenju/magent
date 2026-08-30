# VulnTell 阶段 3 完成记录

> 依据 `PHASE3_PLAN.md` 实施运行时编排迁移。本文件记录迁移差异、弃用策略与回滚方式。
> 阶段 3 已完成：业务编排（State / Agent / Graph / 任务生命周期）已从 `examples.vulntell`
> 迁移到 `apps.vulntell.pipeline`，`apps.vulntell.application` 不再依赖 `examples.vulntell.run`。

## 1. 迁移映射

| 旧模块 (examples/vulntell) | 新模块 (apps/vulntell) | 类型 |
| --- | --- | --- |
| state.py | pipeline/state.py | 业务执行 State（语义、reducers 不变） |
| agents.py | pipeline/agents.py | 业务 Agent（采集/标准化/去重/持久化/评估/报告） |
| graph.py | pipeline/graph.py | Graph 组装（拓扑、节点名不变） |
| run.py | pipeline/jobs.py | `run_vulntell` + `VulnTellJobRunner`（run/resume） |
| — | pipeline/__init__.py | 统一导出编排实现 |
| — | sources/legacy.py | 仅 re-export `examples.vulntell.sources`（阶段 4 替换） |
| — | storage/legacy.py | 仅 re-export `examples.vulntell.db`（阶段 6 替换） |

`db.py` / `sources.py` 按计划保留在 `examples/vulntell`（阶段 6 / 阶段 4 再迁移），由 legacy
过渡包装集中引用，**未复制任何业务逻辑**。`examples/vulntell/{state,agents,graph,run}.py`
现为转发到 `apps.vulntell.pipeline` 的薄壳，不含业务代码。

## 2. 导入方向（阶段 3 后）

```
apps.vulntell.application / examples.vulntell.__main__
    → apps.vulntell.pipeline.jobs.VulnTellJobRunner   (唯一编排入口)
    → apps.vulntell.pipeline.{state,agents,graph}      (真实实现)

apps.vulntell.pipeline
    → apps.vulntell.domain / apps.vulntell.reporting    (真实实现)
    → apps.vulntell.sources.legacy / storage.legacy     (阶段 3/4/6 过渡)
        → examples.vulntell.sources / examples.vulntell.db  (仅经 legacy，不复制逻辑)

examples.vulntell.{state,agents,graph,run}
    → apps.vulntell.pipeline.*   (薄壳转发，单一实现)
```

约束已满足：
- `apps.vulntell.pipeline` 与 `apps.vulntell.application` 不 import `examples.vulntell.{run,state,agents,graph}`；
- `apps.vulntell.domain` / `reporting` 不导入 `examples`、不导入 `magent` 运行时 / 编排；
- `legacy.py` 仅承载兼容导入，未复制 `db` / `sources` 逻辑。

## 3. 行为与边界（未变）

- 确定性结果、部分失败语义、checkpoint / resume / 幂等、trace、LLM 边界与阶段 0 冻结基线一致；
- HTTP source adapter 在阶段 3 仍明确禁用，默认运行不发起任何网络连接（contract 测试屏蔽 socket 验证）；
- `magent` 的执行语义（fail_fast、reducer 合并、side-effect 幂等）未改动。

## 4. 兼容与弃用策略

- 旧模块 `examples/vulntell/{state,agents,graph,run}.py` 改为明确的 re-export 转发，并标注
  “阶段 3 已迁移”说明；既有 `from examples.vulntell... import ...` 的外部调用（tests、benchmarks）
  继续可用，且现在指向 `apps` 的同一份实现。
- `run_vulntell` 的调用形态（关键字参数、返回结构）保持不变，contract 测试直接复用。
- 阶段 4 / 6 完成、正式实现替换 legacy 后，再移除 `examples/vulntell/{db,sources}.py` 与 legacy 转发。

## 5. 与阶段 0 基线差异

无 schema / 报告 / checkpoint / 公开入口变更。默认、无 LLM、单源失败、resume、trace 场景与
`tests/contract/vulntell/baselines/` 冻结基线逐字段一致。新增
`tests/contract/vulntell/test_pipeline_migration.py`（10 个测试）覆盖：apps 不依赖旧运行时模块、
State schema / reducers 稳定、报告等价于基线、部分失败等价于基线、resume 幂等、应用关闭资源、
无网络副作用、旧入口为转发且与 apps 入口等价。

## 6. 验证命令

```
python -m pytest -q            # 296 passed（含 10 个阶段 3 contract 测试）
python -m mypy src/magent      # Success
python -m apps.vulntell --no-llm --json
python -m examples.vulntell --no-llm --json   # 两份入口输出逐字段一致
```

## 7. 后续阶段

阶段 4：将 `examples.vulntell.sources` 迁移至 `apps.vulntell.sources`，替换 `sources/legacy.py`，
并接入/禁用真实数据源（HTTP adapter）。
阶段 6：将 `examples.vulntell.db` 迁移至 `apps.vulntell.storage`，替换 `storage/legacy.py`，
并强化幂等回放与事务语义。
