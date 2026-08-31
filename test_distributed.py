"""VulnTell 分布式收集与合并功能验证测试。"""

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from apps.vulntell.batch.manifest import (
    BatchManifest,
    BatchStatus,
    calculate_content_hash,
    create_batch_manifest,
    save_manifest,
    load_manifest,
    validate_manifest,
)
from apps.vulntell.batch.importer import import_batch, validate_batch_directory, list_batches
from apps.vulntell.batch.merger import merge_batches
from apps.vulntell.cosv.models import COSVDocument
from apps.vulntell.cosv.serializer import serialize_cosv_to_file, read_cosv_file
from apps.vulntell.cosv.schema import validate_cosv_file


def create_test_batch(
    base_dir: Path,
    batch_id: str,
    source: str,
    cve_ids: list[str],
    collector_id: str = "collector-1",
) -> Path:
    """创建测试批次。"""
    batch_dir = base_dir / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    # 创建 COSV 文件
    records_path = batch_dir / "records.cosv.jsonl"
    for cve_id in cve_ids:
        doc = COSVDocument(
            id=cve_id,
            modified="2024-01-01T00:00:00Z",
            summary=f"Test vulnerability from {source}: {cve_id}",
            database_specific={"source": source, "source_id": cve_id},
        )
        serialize_cosv_to_file(doc, records_path, mode="a")

    # 计算内容哈希
    file_hash = calculate_content_hash(records_path)

    # 创建 manifest
    manifest = create_batch_manifest(
        collector_id=collector_id,
        source=source,
        dataset_version="2024-01-01",
        window_start="2024-01-01T00:00:00Z",
        window_end="2024-01-02T00:00:00Z",
        record_count=len(cve_ids),
        content_hash=file_hash,
    )
    save_manifest(manifest, batch_dir)

    return batch_dir


def test_distributed_collection():
    """测试分布式收集场景。"""
    print("=" * 60)
    print("测试场景 1: 分布式收集")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 模拟两个采集者在不同目录采集
        collector1_dir = Path(tmpdir) / "collector1"
        collector2_dir = Path(tmpdir) / "collector2"
        collector1_dir.mkdir()
        collector2_dir.mkdir()

        # 采集者 1: 采集 NVD 来源
        print("\n[Collector 1] 采集 NVD 数据...")
        batch1 = create_test_batch(
            collector1_dir,
            "batch-nvd-001",
            "nvd",
            ["CVE-2024-0001", "CVE-2024-0002", "CVE-2024-0003"],
            collector_id="collector-nvd-1",
        )
        print(f"  创建批次: {batch1.name}")
        print(f"  记录数: 3")

        # 采集者 2: 采集 OSV 来源
        print("\n[Collector 2] 采集 OSV 数据...")
        batch2 = create_test_batch(
            collector2_dir,
            "batch-osv-001",
            "osv",
            ["CVE-2024-0002", "CVE-2024-0004", "CVE-2024-0005"],  # CVE-2024-0002 重复
            collector_id="collector-osv-1",
        )
        print(f"  创建批次: {batch2.name}")
        print(f"  记录数: 3")

        # 验证批次目录
        print("\n验证批次目录...")
        is_valid1, errors1 = validate_batch_directory(batch1)
        is_valid2, errors2 = validate_batch_directory(batch2)
        print(f"  批次 1 有效: {is_valid1}")
        print(f"  批次 2 有效: {is_valid2}")

        return batch1, batch2


def test_batch_import():
    """测试批次导入。"""
    print("\n" + "=" * 60)
    print("测试场景 2: 批次导入")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建源批次
        source_dir = Path(tmpdir) / "source"
        source_dir.mkdir()

        batch1 = create_test_batch(
            source_dir,
            "batch-001",
            "nvd",
            ["CVE-2024-0001", "CVE-2024-0002"],
        )

        # 创建目标目录
        target_dir = Path(tmpdir) / "target"
        target_dir.mkdir()

        # 导入批次
        print("\n导入批次...")
        result = import_batch(batch1, target_dir)
        print(f"  导入成功: {result.success}")
        print(f"  导入记录: {result.imported_records}")
        print(f"  批次 ID: {result.manifest.batch_id if result.manifest else 'N/A'}")

        # 验证导入结果
        print("\n验证导入结果...")
        batches = list_batches(target_dir)
        print(f"  批次数量: {len(batches)}")
        for b in batches:
            print(f"    - {b['batch_id']}: {b['source']} ({b['record_count']} records)")

        # 测试幂等性
        print("\n测试幂等性（再次导入）...")
        result2 = import_batch(batch1, target_dir)
        print(f"  导入成功: {result2.success}")
        print(f"  导入记录: {result2.imported_records}")

        return target_dir


def test_merge_with_conflicts():
    """测试合并带冲突的批次。"""
    print("\n" + "=" * 60)
    print("测试场景 3: 合并带冲突的批次")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建两个有重叠 CVE 的批次
        source_dir = Path(tmpdir) / "source"
        source_dir.mkdir()

        # 批次 1: NVD 来源
        batch1 = create_test_batch(
            source_dir,
            "batch-nvd",
            "nvd",
            ["CVE-2024-0001", "CVE-2024-0002", "CVE-2024-0003"],
            collector_id="collector-nvd",
        )

        # 批次 2: OSV 来源（有重叠）
        batch2 = create_test_batch(
            source_dir,
            "batch-osv",
            "osv",
            ["CVE-2024-0002", "CVE-2024-0004", "CVE-2024-0005"],  # CVE-2024-0002 重叠
            collector_id="collector-osv",
        )

        # 合并批次
        output_dir = Path(tmpdir) / "output"
        print("\n合并批次...")
        merged_docs, report = merge_batches([batch1, batch2], output_dir)

        print(f"  合并结果: {report.merged} 条")
        print(f"  冲突数量: {report.conflicts} 条")
        print(f"  重复数量: {report.duplicates} 条")
        print(f"  待处理: {report.pending} 条")

        # 显示合并后的文档
        print("\n合并后的文档:")
        for doc in merged_docs:
            print(f"  - {doc.id}: {doc.summary}")

        # 验证合并报告
        report_file = output_dir / "merge_report.json"
        if report_file.exists():
            print("\n合并报告:")
            with open(report_file, "r", encoding="utf-8") as f:
                report_data = json.load(f)
            print(f"  接收: {report_data['received']}")
            print(f"  验证: {report_data['validated']}")
            print(f"  合并: {report_data['merged']}")
            print(f"  重复: {report_data['duplicates']}")
            print(f"  冲突: {report_data['conflicts']}")

        return merged_docs, report


def test_idempotent_merge():
    """测试幂等合并。"""
    print("\n" + "=" * 60)
    print("测试场景 4: 幂等合并")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建批次
        source_dir = Path(tmpdir) / "source"
        source_dir.mkdir()

        batch1 = create_test_batch(
            source_dir,
            "batch-001",
            "nvd",
            ["CVE-2024-0001", "CVE-2024-0002"],
        )

        output_dir1 = Path(tmpdir) / "output1"
        output_dir2 = Path(tmpdir) / "output2"

        # 第一次合并
        print("\n第一次合并...")
        merged_docs1, report1 = merge_batches([batch1], output_dir1)
        print(f"  合并结果: {report1.merged} 条")

        # 第二次合并（相同输入）
        print("\n第二次合并（相同输入）...")
        merged_docs2, report2 = merge_batches([batch1], output_dir2)
        print(f"  合并结果: {report2.merged} 条")

        # 验证结果相同
        print("\n验证幂等性...")
        assert len(merged_docs1) == len(merged_docs2), "合并结果数量不同"
        for doc1, doc2 in zip(merged_docs1, merged_docs2):
            assert doc1.id == doc2.id, f"文档 ID 不同: {doc1.id} vs {doc2.id}"
            assert doc1.modified == doc2.modified, f"修改时间不同: {doc1.modified} vs {doc2.modified}"

        print("  幂等性验证通过")


def test_cve_merge_priority():
    """测试 CVE 合并优先级。"""
    print("\n" + "=" * 60)
    print("测试场景 5: CVE 合并优先级")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建来自不同来源的批次
        source_dir = Path(tmpdir) / "source"
        source_dir.mkdir()

        # NVD 来源（优先级高）
        batch_nvd = create_test_batch(
            source_dir,
            "batch-nvd",
            "nvd",
            ["CVE-2024-0001"],
            collector_id="collector-nvd",
        )

        # OSV 来源（优先级低）
        batch_osv = create_test_batch(
            source_dir,
            "batch-osv",
            "osv",
            ["CVE-2024-0001"],  # 相同 CVE
            collector_id="collector-osv",
        )

        # 合并
        output_dir = Path(tmpdir) / "output"
        merged_docs, report = merge_batches([batch_nvd, batch_osv], output_dir)

        print("\n合并结果:")
        for doc in merged_docs:
            print(f"  - {doc.id}")
            print(f"    来源: {doc.database_specific.source if doc.database_specific else 'unknown'}")
            print(f"    标题: {doc.summary}")

        # 验证优先级（NVD 应该优先）
        assert len(merged_docs) == 1
        doc = merged_docs[0]
        assert doc.database_specific.source == "nvd", f"期望 NVD 优先，实际是 {doc.database_specific.source}"
        print("\n优先级验证通过: NVD 优先于 OSV")


def test_batch_protocol():
    """测试批次协议完整性。"""
    print("\n" + "=" * 60)
    print("测试场景 6: 批次协议完整性")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建批次
        source_dir = Path(tmpdir) / "source"
        source_dir.mkdir()

        batch_dir = create_test_batch(
            source_dir,
            "batch-001",
            "nvd",
            ["CVE-2024-0001", "CVE-2024-0002", "CVE-2024-0003"],
        )

        # 验证 manifest 结构
        print("\n验证 manifest 结构...")
        manifest = load_manifest(batch_dir)
        assert manifest is not None, "Manifest 加载失败"

        print(f"  batch_id: {manifest.batch_id}")
        print(f"  collector_id: {manifest.collector_id}")
        print(f"  source: {manifest.source}")
        print(f"  dataset_version: {manifest.dataset_version}")
        print(f"  window_start: {manifest.window_start}")
        print(f"  window_end: {manifest.window_end}")
        print(f"  record_count: {manifest.record_count}")
        print(f"  content_hash: {manifest.content_hash[:16]}...")
        print(f"  status: {manifest.status}")

        # 验证 manifest
        is_valid, errors = validate_manifest(manifest)
        print(f"\nManifest 校验: {'通过' if is_valid else '失败'}")
        if errors:
            for error in errors:
                print(f"  - {error}")

        # 验证 COSV 文件
        print("\n验证 COSV 文件...")
        records_path = batch_dir / "records.cosv.jsonl"
        is_valid, results = validate_cosv_file(records_path)
        print(f"COSV 校验: {'通过' if is_valid else '失败'}")
        for result in results:
            status = "通过" if result["valid"] else "失败"
            print(f"  第 {result['line']} 行: {status}")

        # 验证内容哈希
        print("\n验证内容哈希...")
        actual_hash = calculate_content_hash(records_path)
        print(f"  实际哈希: {actual_hash[:16]}...")
        print(f"  Manifest 哈希: {manifest.content_hash[:16]}...")
        print(f"  哈希匹配: {actual_hash == manifest.content_hash}")


def test_multi_source_merge():
    """测试多来源合并。"""
    print("\n" + "=" * 60)
    print("测试场景 7: 多来源合并")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建多个来源的批次
        source_dir = Path(tmpdir) / "source"
        source_dir.mkdir()

        # NVD
        batch_nvd = create_test_batch(
            source_dir,
            "batch-nvd",
            "nvd",
            ["CVE-2024-0001", "CVE-2024-0002"],
            collector_id="collector-nvd",
        )

        # CISA KEV
        batch_cisa = create_test_batch(
            source_dir,
            "batch-cisa",
            "cisa_kev",
            ["CVE-2024-0002", "CVE-2024-0003"],
            collector_id="collector-cisa",
        )

        # GitHub Advisory
        batch_github = create_test_batch(
            source_dir,
            "batch-github",
            "github_advisory",
            ["CVE-2024-0003", "CVE-2024-0004"],
            collector_id="collector-github",
        )

        # 合并所有来源
        output_dir = Path(tmpdir) / "output"
        merged_docs, report = merge_batches(
            [batch_nvd, batch_cisa, batch_github],
            output_dir,
        )

        print("\n合并结果:")
        print(f"  总记录: {report.merged}")
        print(f"  冲突: {report.conflicts}")
        print(f"  重复: {report.duplicates}")

        print("\n合并后的文档:")
        for doc in merged_docs:
            source = doc.database_specific.source if doc.database_specific else "unknown"
            print(f"  - {doc.id} (来源: {source})")

        # 验证所有 CVE 都被合并
        cve_ids = {doc.id for doc in merged_docs}
        expected_cves = {"CVE-2024-0001", "CVE-2024-0002", "CVE-2024-0003", "CVE-2024-0004"}
        assert cve_ids == expected_cves, f"CVE 集合不匹配: {cve_ids} vs {expected_cves}"

        print("\n多来源合并验证通过")


def main():
    """运行所有测试。"""
    print("=" * 60)
    print("VulnTell 分布式收集与合并功能验证")
    print("=" * 60)

    # 运行所有测试
    test_distributed_collection()
    test_batch_import()
    test_merge_with_conflicts()
    test_idempotent_merge()
    test_cve_merge_priority()
    test_batch_protocol()
    test_multi_source_merge()

    print("\n" + "=" * 60)
    print("所有测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
