# 阶段 5 收尾复核：真实漏洞情报采集能力

## 结论

阶段 5 收尾未完成。当前状态是“live adapter 可独立请求部分公网来源，但正式 CLI/Application 的端到端集成未通过”。因此不能进入阶段 6，也不能宣称 VulnTell 已具备真实漏洞情报生产能力。

## 复核证据（2026-08-31）

### 独立 adapter smoke

使用显式 `NVDTransport`、`CISAKEVTransport` 和 `CNVDTransport`，不写入仓库或日志：

| 来源 | 结果 |
| --- | --- |
| NVD | 成功返回 `SourcePage`，1 条真实 CVE（`CVE-2015-3246`），`has_more=true` |
| CISA KEV | 成功返回 `SourcePage`，500 条真实记录，`has_more=true`（批次分页已生效） |
| CNVD | 返回 `SourceError(transient, HTTP 521)`，响应为 JavaScript/WAF challenge，无结构化漏洞记录 |

### 正式 CLI smoke

- `python -m apps.vulntell --live --source nvd --no-llm --json --window-days 7`：进程返回 0，但报告为 `nvd=failed`；step message 为 `collect nvd failed: 'NVDAdapter' object has no attribute 'fetch'`。这是部分失败降级，不代表采集成功。
- `python -m apps.vulntell --live --source cisa_kev ...`：进程返回 0，报告仍是 fixture 的 `nvd/cnvd` 两来源；当前 Graph 只定义 NVD/CNVD 节点，CISA adapter 未进入 pipeline。
- `python -m apps.vulntell --live --source cnvd ...`：启动即拒绝，提示 CNVD 暂不支持 live；这是预期的合规保护，不是数据采集成功。

## 阶段门禁判定

| 门禁 | 状态 | 说明 |
| --- | --- | --- |
| adapter 单元和离线测试 | 通过 | 全量 `345 passed` |
| NVD 独立公网请求 | 通过 | 仅证明 transport/解析可用 |
| CISA 独立公网请求 | 通过 | 尚未进入正式 Graph |
| CNVD 结构化 live 数据 | 未通过 | 521/WAF challenge；需官方 API 或合规人工 fixture |
| `--live` CLI/Application 端到端 | 未通过 | NVD 接口不匹配，CISA 分支缺失 |
| 真实数据进入规范化/去重/持久化/报告 | 未通过 | 当前正式运行仍产生 fixture 报告或部分失败报告 |
| 默认离线与敏感信息边界 | 通过 | 默认命令未联网，未记录 raw payload/凭据 |

## 下一步

按 [PHASE5_CLOSEOUT_PLAN.md](PHASE5_CLOSEOUT_PLAN.md) 完成统一 `fetch_page`/`fetch` 协议、Graph 来源选择和 CISA 分支、live 窗口元数据、live pipeline contract，并将 `httpx` 声明为 live extra。CNVD 必须保留“不可用来源”状态，禁止绕过 WAF。

