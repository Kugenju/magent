# 八来源两年采集审计

采集窗口：UTC `2024-09-10T00:00:00Z` 至 `2026-09-15T00:00:00Z`，半开区间。

## 当前状态

| 来源 | 记录数 | 页数 | 状态 | 说明 |
|---|---:|---:|---|---|
| NVD | 141,198 | 708 | 完成 | 使用官方年度 bulk feed |
| CISA KEV | 538 | 4 | 完成 | 已利用漏洞目录，不能与全量库直接比较规模 |
| Red Hat | 23,234 | 24 | 完成 | 原先 1,000 条是单页上限；已启用 `page` 续采 |
| Ubuntu | 1,059 | 53 | 完成 | 使用 `offset/limit` 分页，起始 offset 记录在采集脚本 |
| OSV | 242,951 | 2,431 | 完成 | 使用官方生态 bulk 快照 |
| Debian | 4,004 | 1 | 完成 | `data/json` 是原子快照，不做伪分页 |
| MSRC | 0 | — | 受限 | 公告索引可访问，但 CVRF 批量端点在当前网络下超时 |
| GitHub Advisory | 0 | — | 受限 | 公共 API 对当前出口 IP 返回 HTTP 403 rate limit |

## Red Hat 限制核验

对同一窗口请求 Red Hat `cve.json`：

- 第 1 页返回 1,000 条；
- 第 2 页仍返回 1,000 条；
- 使用 `page=1..24` 续采，最终得到 23,234 条；
- 第 24 页不足 1,000 条，manifest 标记 `collection_complete=true`、`truncated=false`。

因此，旧批次的 1,000 条不能作为 Red Hat 两年规模，应废弃并使用新批次。

## 可复现实验

```powershell
$env:PYTHONPATH='.'
python tools/collect_live_2y.py --sources redhat
python tools/collect_live_2y.py --sources debian
python tools/collect_live_2y.py --sources osv
```

MSRC 和 GitHub 在没有更稳定的网络出口、API token 或离线镜像前，只能作为“采集受限”来源报告，不能填充为零记录。
