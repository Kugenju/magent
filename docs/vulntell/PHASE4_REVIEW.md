# VulnTell 阶段 4 审查记录

## 结论

阶段 4 的协议层已经提交，但尚未满足“可进入真实数据源”的完成门禁。`SourceRequest`、`SourcePage`、`SourceError`、`SyncRun` 和分页 fixture 已具备；同步 runner 仍需修正状态统计、错误重试游标、重复页检测和持久化 checkpoint，并补齐专门的 contract/unit 测试。下一阶段先完成阶段 4 收尾，再以 NVD 为首个真实 adapter。

## 已完成项

- `apps.vulntell.sources.protocol` 提供不可变、可序列化的请求、页面和记录对象，并生成稳定请求指纹；
- `sources.errors` 提供错误分类、重试提示和基本脱敏；
- `PagedFixtureSource`/`FaultyPagedSource` 支持分页、故障注入、空结果和坏记录标记；
- `domain.models` 增加 `SyncRun`、页 checkpoint 和错误摘要值对象；
- `pipeline.sync` 提供 run/resume/cancel 服务骨架；
- 默认 VulnTell CLI 仍 fixture-first、离线，未接入真实 HTTP；
- `python -m pytest -q` 当前为 296 passed，`mypy src/magent` 无类型错误。

## 阻塞项与证据

1. 当前仓库没有 `tests/unit/test_sources.py`、`tests/unit/test_sync.py` 或阶段 4 contract 测试，路线图中引用的测试路径不存在；
2. `SyncRunner` 正常跑完 3 页后返回 `partial`，因为 `total_pages` 未从页面流更新（可用 6 条记录、page size 2 的最小复现验证）；
3. 可重试错误处理把游标重置为 `None` 并递增页码，可能重新抓取第一页、跳过目标页或造成错误统计；
4. 重复页校验以 page fingerprint 查询 execution-key 字典，键空间不一致，重复页不会按预期被识别；
5. checkpoint 目前主要保存在 runner 内存，`checkpoint_store` 参数未形成跨进程可恢复的持久化契约；
6. `SyncRun` 的完成时间、错误摘要合并和失败状态转换尚未形成端到端验收；
7. `apps.vulntell.sources.legacy` 与旧 `examples` 适配器并存，live adapter 前必须明确切换和兼容策略。

## 门禁判定

| 门禁 | 结果 |
| --- | --- |
| 协议 round-trip 与输入校验 | 部分完成，需测试固化 |
| 分页 fixture 与错误分类 | 实现存在，需完整场景测试 |
| 正常同步状态为 succeeded | 未通过 |
| 中断后游标恢复且不重放已提交页 | 未通过 |
| 跨进程 checkpoint/幂等 | 未通过 |
| 默认离线与安全脱敏 | 通过现有 CLI/框架测试 |
| 真实 HTTP adapter | 未开始 |

## 处理原则

在阶段 4 收尾前禁止接入生产 HTTP、API 或新存储。若修复需要修改 `magent`，先提交业务无关最小复现和独立框架变更，不在 VulnTell 迁移提交中混改。
