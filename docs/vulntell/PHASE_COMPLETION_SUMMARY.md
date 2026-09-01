# VulnTell 阶段完成汇总（截至 2026-08-31）

本文把已完成阶段的计划、结果和复核结论集中在一个入口；各 `PHASE*_PLAN.md`、
`PHASE*_REVIEW.md` 文件仍保留为可追溯的历史记录，不再单独作为当前状态来源。

## 已完成并冻结

| 阶段 | 当前结论 | 主要证据 |
| --- | --- | --- |
| 2 领域层迁移 | 已完成 | [PHASE2_RESULT.md](PHASE2_RESULT.md) |
| 3 Graph/任务层迁移 | 已完成 | [PHASE3_RESULT.md](PHASE3_RESULT.md) |
| 4 数据源契约与离线同步 | 已完成（checkpoint 为单进程边界） | [PHASE4_REVIEW.md](PHASE4_REVIEW.md) |
| COSV A、批次 C/D、SQLite E | 模块与离线测试已具备；产品链路仍在收口 | [NEXT_PHASE_IMPLEMENTATION.md](NEXT_PHASE_IMPLEMENTATION.md) |

阶段 0–4 的 fixture-first、默认离线、幂等、恢复和敏感信息边界是当前基线。
阶段 4 的跨进程持久化 checkpoint 以及正式业务存储迁移属于后续工作，不应在文档中表述为已交付。

## 尚未完成

阶段 5 的 adapter 已实现，但 live CLI/Application 端到端门禁未通过：NVD 接口适配仍有缺口，
CISA 尚未完整接入 Graph，CNVD 只能走合规人工下载导入。详见
[PHASE5_CLOSEOUT_REVIEW.md](PHASE5_CLOSEOUT_REVIEW.md) 和
[PHASEB_REAL_SMOKE_REPORT.md](PHASEB_REAL_SMOKE_REPORT.md)。

因此当前仓库可以复现离线 VulnTell 流程和独立来源 smoke，不能宣称真实数据生产 MVP，
也不应提前进入阶段 6 的产品化存储查询门禁。

## 当前执行顺序

1. 先按 [PHASE5_CLOSEOUT_PLAN.md](PHASE5_CLOSEOUT_PLAN.md) 完成 live 入口、来源分支和测试门禁；
2. 通过后再推进阶段 6 存储/查询，并替换 `storage/legacy.py`；
3. 多人采集和 COSV 批次交付遵循 [INTELLIGENCE_COLLECTION_GUIDE.md](INTELLIGENCE_COLLECTION_GUIDE.md)。

