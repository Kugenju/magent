# 使用 VulnTell 采集与交付情报源数据

本文给采集人员一套可复现的交付约定。采集者可以在不同机器、不同时间窗口独立工作，
不共享运行时 SQLite；合并人员只接收 COSV 批次目录。

## 交付目录与文件

每个批次交付到约定的共享目录（推荐 `deliveries/<collector_id>/<source>/<batch_id>/`，
也可以是对象存储中同样的目录层级）：

```text
deliveries/
└── <collector_id>/<source>/<batch_id>/
    ├── records.cosv.jsonl   # 一行一个 COSVDocument
    ├── manifest.json         # 来源、窗口、版本、数量、SHA-256、许可证
    └── quality.json          # 丢弃记录、字段问题和结构化错误
```

`records.cosv.jsonl`、`manifest.json` 和 `quality.json` 是唯一需要交付的文件。API key、Cookie、
Authorization、HTML/WAF challenge 和完整 raw response 不得写入其中；原始响应如确有合规留存要求，
应放在受控的、与批次目录分离的归档区，并只在 manifest 中记录引用或哈希。

## 采集步骤

1. 选择已登记来源和合法 API/feed；CNVD 无稳定公开 API 时，操作员在官方页面完成验证后下载
   UTF-8 CSV/JSON，再使用 `CNVDManualFileSource` 本地导入，禁止绕过 WAF。
2. 固定 UTC 半开窗口 `[window_start, window_end)`、`dataset_version` 和 `page_size`，保留来源版本/hash。
3. 使用 `apps.vulntell.batch.collect_adapter()` 将 adapter 的 `SourcePage` 转换为 COSV 批次：

```python
import asyncio
from datetime import datetime, timezone, timedelta
from apps.vulntell.batch import collect_adapter
from apps.vulntell.sources import NVDAdapter, NVDConfig
from apps.vulntell.sources.nvd import NVDTransport
from apps.vulntell.sources.protocol import SourceRequest

end = datetime.now(timezone.utc)
request = SourceRequest(
    source="nvd", dataset_id="nvd-cve", dataset_version="2.0",
    window_start=end - timedelta(days=7), window_end=end, page_size=100,
)
manifest, documents = asyncio.run(
    collect_adapter(NVDAdapter(config=NVDConfig(), transport=NVDTransport()), request,
                    "deliveries/alice/nvd/batch-20260831")
)
print(manifest.batch_id, len(documents))
```

采集函数最多写入 100 条记录，先规范化、映射并校验 COSV schema 再序列化；失败页应重试/恢复后再交付，
不要手工修改 JSONL。adapter 必须使用显式 HTTP transport（例如 `NVDTransport`），默认构造不会联网。
窗口过滤在 adapter 层完成，窗口内不足 100 条时按实际数量交付，不得用重复记录补齐。
人工 CNVD 文件可将 `CNVDManualFileSource(CNVDManualConfig(path=...))` 作为 adapter 传入同一函数。

## 验证、导入与合并

合并人员收到目录后，在无网络环境执行：

```python
from apps.vulntell.batch import validate_batch_directory, import_batch, merge_batches

ok, errors = validate_batch_directory("deliveries/alice/nvd/batch-20260831")
if not ok:
    raise SystemExit(errors)
import_batch("deliveries/alice/nvd/batch-20260831", "received")
merge_batches(
    ["received/batch-a", "received/batch-b"],
    "merged/2026-08-31",
)
```

`validate_batch_directory` 会检查 manifest、文件 SHA-256 和 COSV schema；`collect_adapter` 在写出前也会
拒绝 schema 不合格文档。`import_batch` 按 batch_id
原子导入且重复导入幂等；`merge_batches` 覆盖写入 `merged.cosv.jsonl` 并生成 `merge_report.json`。
合并结果按 CVE、来源优先级和稳定排序去重，无法关联的来源 ID 保留为 pending；冲突、拒绝和重复数量
以合并报告为准。采集者 ID 不是漏洞实体主键。

当前正式 CLI 尚未提供完整 `collect/validate-batch/merge` 子命令，因此请使用上述 Python API；
相关命令只有在阶段 5 收尾门禁通过后才可作为稳定接口对外承诺。
