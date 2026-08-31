"""VulnTell 批次协议模块（阶段 C：分布式采集批次协议）。

提供：
- BatchManifest 数据模型
- 批次状态管理
- 目录/对象存储导入器
- CLI 命令：collect, validate-batch, merge

约束：
- 不共享运行时 SQLite
- collector_id 不作为漏洞实体身份
- 重复导入同一批次结果不变（幂等）
- 篡改文件会因 hash 不匹配拒绝
"""

from apps.vulntell.batch.manifest import (
    BatchManifest,
    BatchStatus,
    create_batch_manifest,
    validate_manifest,
)
from apps.vulntell.batch.importer import (
    import_batch,
    validate_batch_directory,
)
from apps.vulntell.batch.merger import merge_batches

__all__ = [
    "BatchManifest",
    "BatchStatus",
    "create_batch_manifest",
    "validate_manifest",
    "import_batch",
    "validate_batch_directory",
    "merge_batches",
]
