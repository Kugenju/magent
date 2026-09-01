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

## COSV 结论

NVD 和 CISA KEV 已完成“真实采集 100 条 → COSV JSONL → manifest → validate-batch”的闭环。尚未完成双人批次 merge 和其余来源的真实 100 条验收，因此阶段 B **仍未通过**。

不得将 SourcePage 记录数视为 COSV 合规：当前 adapter 输出仍是 SourceRecord，必须经过 `observation_to_cosv` 和 schema 校验。

## 复核结论

阶段 B 仍未通过。当前满足真实 COSV 批次闭环的来源为 2/17（NVD、CISA KEV），距离文档要求的“至少 10 个来源各真实采集 100 条”还差 8 个。单元测试通过不改变该结论。

## 后续阻塞项

1. 修复 live pipeline 的 `fetch_page` 接口、窗口和 dataset metadata 传递；
2. 为每个来源核对官方 endpoint、认证、查询参数及许可；
3. 增加真实 smoke 可重复脚本，输出脱敏统计而不是原始响应；
4. 对能获取 100 条的来源生成批次并执行 `validate-batch`、`merge`；
5. CNVD 只能使用官方人工下载文件，不得绕过 WAF。
