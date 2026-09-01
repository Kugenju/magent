# VulnTell 阶段 4：数据源契约与增量模型实施计划（已完成，历史记录）

> 当前实现审查见 [PHASE4_REVIEW.md](PHASE4_REVIEW.md)。协议代码已提交，但在专门测试和持久化恢复门禁通过前，不得进入真实数据源开发。

## 目标与范围

本阶段把当前 fixture-only `SourceAdapter.fetch()` 演进为可分页、可恢复、可审计的同步协议，为阶段 5 的真实来源接入提供稳定边界。阶段 4 不实现 NVD/CNVD/CISA KEV 的真实 HTTP 请求，不迁移存储实现，不增加 API/Web/任务队列，也不改变 `magent` 的执行语义。

完成后应能在完全离线环境中模拟完整同步生命周期：创建同步运行、按游标读取页面、批次 checkpoint、处理中断并恢复、识别重复页、分类错误并产生可审计结果。

## 目标目录与依赖方向

```text
apps/vulntell/sources/
├── __init__.py          # 稳定公开导出
├── protocol.py          # SourceRequest/Page/Cursor/Error 契约
├── fixtures.py          # 分页 fixture adapter 与故障注入
└── errors.py            # 错误分类与 retry hint
apps/vulntell/pipeline/
└── sync.py              # SyncRun、批次边界、resume 编排
apps/vulntell/domain/
└── models.py            # 仅在必要时增加可序列化同步值对象
```

依赖必须单向：`pipeline.sync → sources.protocol/fixtures → domain`；数据源不得导入 `examples.vulntell`、Graph 实现或全局连接。阶段 4 仍可暂时由 `sources/legacy.py` 提供旧 `SourceAdapter` 兼容导出，但新代码不得依赖 legacy。

## 任务拆分

### 4.1 冻结请求、页面和游标协议

定义不可变、可 JSON 序列化的 `SourceRequest`（source、dataset、时间窗口、page_size、cursor、filters）、`SourcePage`（records、next_cursor、has_more、page_index、source、observed_at）和 `SyncCursor`。规定游标 opaque、大小上限、窗口边界（含/不含）、排序稳定性及 `request_fingerprint`。

验收：协议 round-trip、缺字段/超限/非法游标校验；相同请求指纹稳定；文档给出版本和兼容策略。

### 4.2 定义同步运行与批次状态

实现 `SyncRun`/`SyncRunStatus`（pending/running/partial/succeeded/failed/cancelled）、开始/结束时间、最后成功游标、页数、记录数、错误摘要和 `source_version`。状态必须适合 checkpoint，不保存连接、响应正文或凭据。为批次生成稳定 execution key：`sync:{run_id}:{source}:{page_index}:{request_fingerprint}`。

验收：中断后可从最后成功页恢复；重复恢复不重复提交批次；状态转换非法时明确报错。

### 4.3 构建可控的分页 Fixture Adapter

将现有 JSON fixture 包装为 `PagedFixtureSource`，支持固定 page size、空页、重复页、乱序（应被拒绝或规范化）、游标失效、单条坏记录、指定页超时/限流/权限错误和中断注入。默认 adapter 仍为离线且不创建 socket。

验收：每种场景均有可重复测试；重复页由 page fingerprint 去重；坏记录隔离并计入质量问题，不丢弃整页。

### 4.4 错误分类与重试提示

定义 `SourceErrorKind`：`rate_limited`、`timeout`、`transient`、`invalid_response`、`auth`、`forbidden`、`not_found`、`permanent`、`cancelled`。错误对象包含 source、可安全展示的 message、retryable、retry_after、http_status（若有）和 correlation id；禁止保留 Authorization、完整 URL query 或 raw body。仅输出 retry hint，由现有执行器策略消费，不在 adapter 内自行循环重试。

验收：分类决策表和边界测试齐全；429/超时可重试，其余按契约处理；敏感字段脱敏测试通过。

### 4.5 实现同步编排与 checkpoint 接口

新增 `SyncRunner`（或等价服务）负责创建/恢复 `SyncRun`、循环 `fetch_page`、在“页面验证→规范化→持久化成功”后提交游标 checkpoint，并在失败/取消时保存最后安全边界。与现有 `VulnTellJobRunner` 组合，但不把分页循环塞入业务 Agent。批次提交必须幂等，恢复只重放未确认页面。

验收：正常、空结果、部分失败、中断恢复、取消和重复运行均有 contract；恢复后的记录、游标和统计与无中断运行一致。

### 4.6 兼容层与文档

保留旧 `SourceAdapter.fetch()` 的 fixture 行为至少一个兼容周期；在 `sources/legacy.py` 标注替换条件和删除版本。更新 `FINAL_DESIGN.md`、`ROADMAP.md`、`README.md`、配置说明和数据许可清单；补充阶段 5 live adapter 的前置门禁。

## 测试与质量门禁

下游 agent 每个任务均需提供 unit + contract 测试。阶段完成前必须通过：

```text
python -m pytest -q tests/contract/vulntell tests/unit
python -m pytest -q
mypy src/magent
python -m apps.vulntell --no-llm --json
git diff --check
```

额外门禁：默认 CLI 无网络；游标/SyncRun schema hash 稳定；相同窗口连续同步结果一致；trace、日志、checkpoint、错误和 prompt 不含 raw payload/凭据；`magent` 无业务导入或语义变更。

## 推荐执行顺序与交付物

1. 4.1（协议）→ 4.2（SyncRun 值对象）→ 4.3（fixture）；
2. 4.4（错误分类）→ 4.5（SyncRunner 与 checkpoint）；
3. 4.6（兼容、文档、门禁审查）。

每个任务提交说明范围、文件变更、schema/checkpoint 影响、测试命令与结果、与阶段 3 baseline 的 diff、遗留风险。阶段 4 通过后，才建立阶段 5 live adapter 的独立计划。

## 风险与回滚

- 游标语义不清：先冻结窗口/排序/指纹，再写 adapter；任何变更提升 protocol version 并拒绝旧 checkpoint；
- 重复页或乱序导致重复写入：使用 page fingerprint + 稳定 execution key，保留审计计数；
- 错误信息泄密：集中 scrubber，禁止序列化异常对象和 raw response；
- 分页循环破坏执行器恢复：同步批次作为明确节点/side effect，先写 contract 再实现；
- 若无法在不改 `magent` 的情况下表达需求，暂停本阶段并提交业务无关最小复现与单独框架变更提案。
