# 阶段 B 真实采集验收记录

执行时间：2026-08-31（受控公网 smoke，单页 `page_size=100`，超时 15 秒）。

复核命令：`python -m pytest -q tests/unit/test_cosv.py tests/unit/test_batch.py tests/unit/test_storage.py`（52 passed）。

## 结果（复测）

| 来源 | 结果 | 记录数 | 说明 |
|---|---|---:|---|
| NVD | 真实闭环通过 | 100 | 真实单页 100 条，已生成 100 条 COSV、manifest，并通过 `validate_batch_directory` |
| CISA KEV | 真实闭环通过 | 100 | 从真实 catalog 抽取前 100 条，已生成 100 条 COSV、manifest，并通过 `validate_batch_directory` |
| MSRC | 可访问但空页 | 0 | 需要确认 API 查询参数和数据窗口 |
| CNVD | 不可用 | - | HTTP 521/WAF，保留人工下载导入路径 |
| OSV、GitHub Advisory、EUVD、JVN、Red Hat、Ubuntu、Debian、CERT/CC、Cisco、Fortinet、Palo Alto、Exploit-DB | 未通过 | - | 返回结构化 SourceError 或超时，尚未满足真实 100 条验收 |

## 2026-09-10 当前批次复核

在修正 live adapter 的实际公开端点、响应格式和标准字段映射后，使用 UTC 半开窗口
`[2026-08-11T03:00:27Z, 2026-09-10T03:00:27Z)` 重新采集。所有批次均经过
`collect_adapter` 的标准化、COSV schema 校验、manifest 哈希校验和唯一 ID 检查。

| 来源 | COSV 记录 | 批次校验 | 质量说明 |
|---|---:|---|---|
| NVD | 100 | 通过 | 达到采集器单批上限；保留 CVE、描述、时间和 CVSS |
| CISA KEV | 38 | 通过 | 窗口内实际新增/加入记录；未用全目录数量冒充窗口数据 |
| Red Hat | 100 | 通过 | 公共 CVE feed；按 `public_date` 窗口过滤 |
| Ubuntu | 10 | 通过 | `cves.json` 窗口内实际返回数量 |
| Microsoft MSRC | 100 | 通过 | 跟随近期 CVRF XML bulletin，按 release date 过滤并按 CVE 输出 |
| OSV | 3 | 通过 | 对指定 PyPI 包 querybatch，按 modified/published 过滤 |

批次摘要保存在本地生成目录 `deliveries/live-final-3/collection-summary.json`，不作为
仓库交付物；其中 `records.cosv.jsonl`、完整质量日志和原始响应均不提交。质量报告中的
告警是来源字段缺失（例如部分来源没有 CVSS 或 source-added 时间），不是 COSV schema
失败，也没有用默认值伪造这些字段。

## COSV 结论

NVD 和 CISA KEV 已完成“真实采集 100 条 → COSV JSONL → manifest → validate-batch”的闭环。尚未完成双人批次 merge 和其余来源的真实 100 条验收，因此阶段 B **仍未通过**。

不得将 SourcePage 记录数视为 COSV 合规：当前 adapter 输出仍是 SourceRecord，必须经过 `observation_to_cosv` 和 schema 校验。

## 复核结论

阶段 B 仍未通过。当前已有 6/17 个来源完成真实 COSV 批次闭环，但只有 NVD、Red Hat、
MSRC 达到单批 100 条；CISA KEV、Ubuntu、OSV 的窗口内实际数量低于 100。距离文档要求的
“至少 10 个来源各真实采集 100 条”仍有明显差距，单元测试通过不改变该结论。

## 后续阻塞项

1. 为其余来源核对官方 endpoint、认证、查询参数及许可；
2. 为真实采集增加稳定的可重复入口，输出脱敏统计而不是原始响应；
3. 对能获取 100 条的来源生成批次并执行 `validate-batch`、`merge`；
4. 对窗口内不足 100 条的来源记录“实际数量”，不得补造或重复填充；
5. CNVD 只能使用官方人工下载文件，不得绕过 WAF。
