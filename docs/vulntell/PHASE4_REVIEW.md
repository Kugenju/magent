# VulnTell 阶段 4 审查记录

## 结论

阶段 4 已完成。协议、分页 fixture、错误分类、同步状态和离线测试均已补齐；随后阶段 5 adapter 开发暴露出的 live 集成问题不回溯改变阶段 4 的离线契约。阶段 5 的公网和端到端能力另见 [PHASE5_REVIEW.md](PHASE5_REVIEW.md)。

## 已完成项

- `apps.vulntell.sources.protocol` 提供不可变、可序列化的请求、页面和记录对象，并生成稳定请求指纹；
- `sources.errors` 提供错误分类、重试提示和基本脱敏；
- `PagedFixtureSource`/`FaultyPagedSource` 支持分页、故障注入、空结果和坏记录标记；
- `domain.models` 增加 `SyncRun`、页 checkpoint 和错误摘要值对象；
- `pipeline.sync` 提供 run/resume/cancel 服务，并完成状态统计、重试游标、重复页检测和 checkpoint 幂等；
- 默认 VulnTell CLI 仍 fixture-first、离线，未接入真实 HTTP；
- `python -m pytest -q` 当前为 296 passed，`mypy src/magent` 无类型错误。

## 当时发现的问题及处理结果

1. 专门的 `tests/unit/test_sources.py`、`tests/unit/test_sync.py` 已补齐；
2. 正常分页的 `total_pages`、重试同页和重复页 execution key 已修正并有测试；
3. 阶段 4 仍保留单进程 checkpoint 实现边界，跨进程持久化将在阶段 6 存储层完成；
4. `sources.legacy` 继续作为兼容层，live adapter 已迁移到正式模块。

## 门禁判定

| 门禁 | 结果 |
| --- | --- |
| 协议 round-trip 与输入校验 | 通过 |
| 分页 fixture 与错误分类 | 通过 |
| 正常同步状态为 succeeded | 通过 |
| 中断后游标恢复且不重放已提交页 | 通过（单进程边界） |
| 跨进程 checkpoint/幂等 | 延后至阶段 6 存储层 |
| 默认离线与安全脱敏 | 通过现有 CLI/框架测试 |
| 真实 HTTP adapter | 未开始 |

## 处理原则

在阶段 4 收尾前禁止接入生产 HTTP、API 或新存储。若修复需要修改 `magent`，先提交业务无关最小复现和独立框架变更，不在 VulnTell 迁移提交中混改。
