# VulnTell 阶段 3：Graph 与任务层迁移实施计划（已完成）

> 本计划已执行完毕。审查结论与遗留问题见 [PHASE3_REVIEW.md](PHASE3_REVIEW.md)，实施结果见 [PHASE3_RESULT.md](PHASE3_RESULT.md)。以下内容保留作为下游复盘和回滚依据。

## 1. 进入基线

阶段 0–1 已完成基线冻结与应用外壳，阶段 2 已完成领域层迁移。当前验证基线：

- `python -m pytest -q`：286 passed；
- `mypy src/magent`：通过；
- `python -m apps.vulntell --no-llm --json` 与旧入口结构化报告等价；
- `apps.vulntell.domain`、`apps.vulntell.reporting` 为真实实现；
- `examples.vulntell` 的 models/loading/normalize/dedupe/metrics/report 仅保留 re-export；
- `apps.vulntell.application` 仍依赖 `examples.vulntell.run` 和 `examples.vulntell.state`；
- `db.py`、`sources.py`、`agents.py`、`graph.py` 仍在 examples 目录；
- HTTP source adapter 仍明确禁用，阶段 3 不接入真实网络。

阶段 3 的唯一重点是迁移运行时编排，不改变领域规则、报告 schema、magent 执行语义或真实数据源范围。

## 2. 阶段目标

完成后应达到：

1. `apps.vulntell.application` 不再依赖 `examples.vulntell.run`；
2. `VulnTellState`、业务 Agent、Graph 和 run/resume 生命周期位于 `apps.vulntell.pipeline`；
3. CLI、未来 API 和定时任务都调用同一个应用服务；
4. full run、resume、replay（语义等同于当前恢复）入口统一；
5. 部分来源失败、Checkpoint、幂等、Trace 和 LLM 边界保持不变；
6. `examples.vulntell` 只承担兼容入口和短期 re-export，不承载新的编排实现。

阶段 3 不实现分页/游标、真实 HTTP、PostgreSQL、查询 API、Web 看板或分布式任务队列；这些属于后续阶段。

## 3. 目标目录

    apps/vulntell/
    ├── application.py
    ├── pipeline/
    │   ├── __init__.py
    │   ├── state.py
    │   ├── agents.py
    │   ├── graph.py
    │   └── jobs.py
    ├── sources/
    │   └── legacy.py       # 阶段 3 过渡包装，阶段 4 替换
    └── storage/
        └── legacy.py       # 阶段 3 过渡包装，阶段 6 替换

`legacy.py` 只能集中承载旧 `examples.vulntell.db/sources` 的兼容导入，不能复制业务逻辑。阶段 3 结束时应有明确的替换清单和删除时间点。

## 4. 任务拆分

### Task 3.1：依赖图和接口冻结

建立模块依赖图和迁移映射：

| 当前模块 | 阶段 3 目标 | 处理 |
| --- | --- | --- |
| examples/vulntell/state.py | apps/vulntell/pipeline/state.py | 迁移真实实现 |
| examples/vulntell/agents.py | apps/vulntell/pipeline/agents.py | 迁移真实实现并改导入 |
| examples/vulntell/graph.py | apps/vulntell/pipeline/graph.py | 迁移真实实现并改导入 |
| examples/vulntell/run.py | apps/vulntell/pipeline/jobs.py | 迁移 run/resume 编排 |
| examples/vulntell/sources.py | apps/vulntell/sources/legacy.py | 过渡 re-export |
| examples/vulntell/db.py | apps/vulntell/storage/legacy.py | 过渡 re-export |

冻结以下公开契约：`VulnTellState` 字段与 reducers、`PipelineResult`/新结果对象、`build_vulntell_graph` 参数、run/resume 退出码和 checkpoint 元数据。

验收：

- 依赖图中没有 pipeline → examples 领域模块的反向依赖；
- 新旧模块的公开符号有迁移表；
- 未经确认不得改报告 schema 或执行参数。

### Task 3.2：迁移 State

将 `VulnTellState` 迁移到 `apps.vulntell.pipeline.state`。

要求：

- 字段、默认值、Pydantic 序列化和 reducers 完全一致；
- State 只包含可 checkpoint 的 dict/list/标量；
- 不把数据库连接、adapter、provider 或 logger 放进 State；
- 保持 source_status、failed_sources、metrics、report 语义；
- 增加 state schema hash 回归断言。

验收：

- state round-trip 测试通过；
- 与阶段 0 baseline 的状态/报告一致；
- checkpoint 写入和恢复成功；
- 并发 join 的 reducer 顺序不变。

### Task 3.3：迁移业务 Agent

将 Collect、Normalize、Dedupe、Persist、Evaluate、Report Agent 迁移到 `pipeline/agents.py\)。

依赖必须通过构造函数注入：

- SourceAdapter；
- repository/store；
- ToolRegistry/SideEffectSink；
- LLM Provider；
- 运行配置。

要求：

- Agent 只通过 AgentResult 提议状态更新；
- 采集失败继续使用部分失败降级；
- Persist 仍通过工具 allowlist 和 SideEffectSink；
- Evaluate 使用确定性规则；
- Report 的 LLM 只写 explanation，不改指标；
- 不在 Agent 内部读取环境变量、系统时间或创建全局连接。

验收：

- 每个 Agent 有独立 unit tests；
- flaky、超时、取消和 provider 失败行为与原实现一致；
- 无业务 Agent 导入 `examples.vulntell` 领域模块；
- raw payload 不进入 trace、日志和 LLM prompt。

### Task 3.4：迁移 Graph

将 GraphBuilder 构建逻辑迁移到 `pipeline/graph.py\)。

目标拓扑保持：

    dispatch
      ├── collect_nvd → normalize_nvd ┐
      └── collect_cnvd → normalize_cnvd ├→ dedupe → persist → evaluate → report → END

要求：

- 节点名、边、join、并发度和 reducer 语义保持；
- Graph 构建函数接收依赖，不隐式读取全局路径；
- checkpoint 的 workflow/node version 保持兼容；
- 失败来源仍能继续到评估和报告；
- 不在 Graph 中加入业务之外的调度判断。

验收：

- graph validation、并发、join、部分失败、恢复和幂等测试通过；
- 新 Graph 与旧 Graph 的报告逐字段等价；
- 节点调用顺序和 checkpoint frontier 可审计。

### Task 3.5：迁移任务生命周期

将 `examples.vulntell.run.run_vulntell` 迁移为 `apps.vulntell.pipeline.jobs.run_vulntell` 或 `VulnTellJobRunner`。

建议接口：

    class VulnTellJobRunner:
        async def run(self) -> VulnTellRunResult: ...
        async def resume(self, run_id: str) -> VulnTellRunResult: ...

职责：

1. 加载 dataset metadata；
2. 组装 store、checkpoint store、sink、provider 和 adapters；
3. 构建并运行 GraphExecutor；
4. 转换结构化结果；
5. 关闭资源并报告清理错误。

要求：

- `application.py` 只依赖 jobs 和 domain/reporting；
- full/resume 使用同一 runner；
- 资源关闭使用 `try/finally`；
- checkpoint、run_id、workflow_version 和 provider 配置显式传递；
- 失败时保留 ExecutionReport，不吞掉原始错误。

验收：

- `apps.vulntell.application` 不再导入 `examples.vulntell.run/state/graph/agents`；
- CLI 与应用服务使用同一 runner；
- full、resume、故障注入和 trace contract tests 通过；
- 应用生命周期异常时数据库和 checkpoint 连接均关闭。

### Task 3.6：更新旧入口和兼容层

`examples.vulntell.__main__` 继续只转发到 `apps.vulntell`。

对于旧的 `examples.vulntell.state/agents/graph/run`：

- 若外部测试或 benchmark 仍依赖，保留明确 re-export；
- re-export 文件不得保留第二份实现；
- docstring 标注弃用和预计移除版本；
- 新测试全部改用 `apps.vulntell.pipeline`；
- 阶段 3 完成后不得新增 examples 导入。

验收：

- 新旧 CLI 输出等价；
- 旧 import 在兼容周期内可用；
- 静态扫描显示新业务实现均位于 apps；
- 删除兼容层时有回滚提交和迁移说明。

### Task 3.7：迁移测试和文档

新增 `tests/contract/vulntell/test_pipeline_migration.py`，至少覆盖：

    test_pipeline_modules_import_without_examples_domain
    test_state_schema_and_reducers_are_stable
    test_graph_report_matches_baseline
    test_partial_failure_matches_baseline
    test_resume_is_idempotent
    test_application_closes_resources
    test_new_pipeline_has_no_network_side_effect
    test_old_entrypoint_remains_compatible

同步更新：

- `docs/vulntell/PHASE2_RESULT.md`：阶段 3 开始/完成状态；
- `docs/vulntell/ROADMAP.md`：阶段 2 已完成、阶段 3 进行中；
- `docs/vulntell/FINAL_DESIGN.md`：pipeline 目录和依赖方向；
- README/API 中的示例入口；
- 弃用和回滚说明。

## 5. 阶段 3 验收标准

必须全部满足：

1. `apps.vulntell.pipeline` 可独立导入；
2. `application.py` 不依赖 `examples.vulntell.run/state/agents/graph`；
3. State、Agent、Graph、run/resume 全部使用 apps 真实实现；
4. 默认、无 LLM、单源失败、resume、trace 与阶段 0 baseline 逐字段等价；
5. 重复运行不新增 observation、canonical、metric 或 side effect；
6. 中断后只重放未提交节点，已提交节点不重复执行；
7. CLI/API（若已有实验入口）共享应用 runner；
8. 默认运行不访问网络，不需要 key，不执行外部命令；
9. trace、日志、checkpoint 和报告不包含 raw payload 或凭据；
10. 所有新增通用问题都有业务无关的最小复现，否则不得修改 magent；
11. 旧入口兼容策略、删除时间点和回滚方式有文档；
12. 全量测试、类型检查、离线 CLI 和链接检查通过。

建议命令：

    python -m pytest -q tests/contract/vulntell tests/unit
    python -m pytest -q
    mypy src/magent
    python -m apps.vulntell --no-llm --json
    python -m examples.vulntell --no-llm --json
    git diff --check

## 6. 风险和控制

| 风险 | 控制 |
| --- | --- |
| State schema/hash 改变导致 checkpoint 不兼容 | 迁移前后做 hash 和 resume contract test |
| Agent 导入循环 | 采用 pipeline → domain/sources/storage 的单向依赖 |
| 运行资源泄漏 | runner 统一 try/finally，并增加异常路径测试 |
| 旧入口和新入口逻辑分叉 | 旧目录只 re-export，不保留编排代码 |
| 过渡 wrapper 长期残留 | 每个 wrapper 标明替换阶段和删除条件 |
| 为解决迁移问题修改 magent | 先用业务无关最小复现，另开框架任务 |
| 过早引入真实网络 | 阶段 3 明确禁止，阶段 4 先冻结契约 |

## 7. 阶段 3 完成后的下一步

阶段 3 通过后进入阶段 4：数据源契约与增量模型。

阶段 4 首先定义 SourceRequest、SourcePage、游标、SyncRun、错误分类和分页 fixture，再实现 NVD/CNVD/CISA KEV 的真实 adapter。未完成这些契约前，不允许直接在生产代码中接入 HTTP。

## 8. 下游 agent 交付格式

每个 Task 提交时必须说明：

1. Task 编号、范围和未包含内容；
2. 新增、迁移、删除和 re-export 文件；
3. 导入依赖方向；
4. State/schema/checkpoint 是否变化；
5. contract/unit/integration 测试命令和结果；
6. 与 baseline 的结构化 diff；
7. 资源关闭、错误处理和安全检查结果；
8. 遗留 wrapper、风险和下一 Task 依赖。




