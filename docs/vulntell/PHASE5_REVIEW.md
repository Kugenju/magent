# VulnTell 阶段 5 审查记录：真实数据源可用性

## 审查日期与结论

审查日期：2026-08-31。

阶段 5 的三个 adapter 代码和离线单元测试已提交，但阶段验收尚未闭环，不能标记为“真实数据 MVP 完成”。独立 adapter 已能访问部分公网来源；VulnTell 应用服务和 CLI 尚未把 live adapter 接入完整 Graph，因此当前工具整体仍不能端到端运行一次真实情报采集并生成持久化报告。

## 已完成项

- `NVDAdapter`、`CISAKEVAdapter`、`CNVDAdapter` 位于 `apps/vulntell/sources/`；
- 三个 adapter 均使用依赖注入 transport，默认构造不联网；
- 429、408、5xx、401、403、404 和解析/网络异常可映射为 `SourceError`；
- NVD 支持 `startIndex/resultsPerPage`，CISA KEV 支持 catalog 版本，CNVD 支持分页参数和中文字段映射；
- 离线全量测试：`345 passed`；`mypy src/magent` 通过；
- `python -m apps.vulntell --no-llm --json` 仍保持 fixture-first、无网络。

## 真实网络 smoke 结果

在不提供 API key、只请求一页或一个 catalog 的受控测试中：

| 来源 | 结果 | 证据与限制 |
| --- | --- | --- |
| NVD | 部分通过 | 7 天窗口、`page_size=1` 返回 `SourcePage`，包含真实 CVE 记录；使用 10 年窗口并附带 `cveId` 返回 HTTP 404，说明未处理 NVD 的日期窗口限制，不能据此进行任意历史查询 |
| CISA KEV | 通过 adapter smoke | 返回真实 catalog，1685 条记录，`has_more=False`；当前一次性加载整个 catalog，未按 `page_size` 分页，内存/增量语义仍需收尾 |
| CNVD | 未通过 | 官方 endpoint 返回 HTTP 521 和 JavaScript 反爬挑战，未获得结构化漏洞记录；当前实现不能把该响应转换为情报 |

测试只验证了网络可达性和最小解析，不把公网响应写入仓库、fixture、trace 或日志。

## 端到端工具能力判定

当前 `python -m apps.vulntell --help` 没有 `--live`、`--source` 或 endpoint 配置；`VulnTellConfig` 的已知来源也不包含 `cisa_kev`，`VulnTellJobRunner/Graph` 固定使用 fixture/legacy adapter。因此：

- 可以通过 Python 直接调用 NVD/CISA adapter 获取真实记录；
- 不能通过正式 CLI/Application 选择 live 来源并将其送入现有规范化、去重、持久化、评估和报告流程；
- 不能宣称三来源真实采集可用，CNVD 还需要官方接口/下载渠道或明确的人工 fixture 方案；
- `httpx` 未列入项目运行时依赖，干净安装环境无法保证 live transport 可用。

## 阶段 5 门禁

| 门禁 | 状态 |
| --- | --- |
| 三个 adapter 单元/离线 contract | 通过 |
| NVD、CISA 公网最小 smoke | 部分通过 |
| CNVD 公网结构化采集 | 未通过 |
| CLI/Application live 入口 | 未实现 |
| 三来源进入同一 pipeline 并生成报告 | 未实现 |
| 默认离线、无凭据运行 | 通过 |
| NVD 窗口分片、CISA 增量/分页 | 未通过或不完整 |

## 审查结论

阶段 5 定性为“adapter 实现完成、产品集成和来源可用性收尾中”。下一步不是直接进入存储查询阶段，而是完成 live 入口、NVD 窗口分片、CISA 增量边界和 CNVD 可行性决策。具体任务见 [PHASE5_CLOSEOUT_PLAN.md](PHASE5_CLOSEOUT_PLAN.md)。

