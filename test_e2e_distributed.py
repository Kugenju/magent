"""VulnTell 端到端分布式采集与合并测试。"""

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests

from apps.vulntell.batch.manifest import (
    calculate_content_hash,
    create_batch_manifest,
    save_manifest,
    load_manifest,
)
from apps.vulntell.batch.importer import import_batch, list_batches
from apps.vulntell.batch.merger import merge_batches
from apps.vulntell.cosv.models import COSVDocument
from apps.vulntell.cosv.serializer import serialize_cosv_to_file


def collect_from_nvd(limit: int = 50) -> list[dict]:
    """从 NVD 采集数据。"""
    print("[NVD] 采集中...")
    url = "https://services.nvd.nist.gov/rest/json/cves/2.0"
    params = {"resultsPerPage": limit, "startIndex": 0}
    headers = {"User-Agent": "VulnTell/1.0"}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            vulns = data.get("vulnerabilities", [])
            print(f"[NVD] 采集到 {len(vulns)} 条记录")
            return vulns
        else:
            print(f"[NVD] 失败: HTTP {response.status_code}")
            return []
    except Exception as e:
        print(f"[NVD] 错误: {e}")
        return []


def collect_from_cisa_kev() -> list[dict]:
    """从 CISA KEV 采集数据。"""
    print("[CISA KEV] 采集中...")
    url = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
    headers = {"User-Agent": "VulnTell/1.0"}

    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            vulns = data.get("vulnerabilities", [])
            print(f"[CISA KEV] 采集到 {len(vulns)} 条记录")
            return vulns[:50]  # 限制数量
        else:
            print(f"[CISA KEV] 失败: HTTP {response.status_code}")
            return []
    except Exception as e:
        print(f"[CISA KEV] 错误: {e}")
        return []


def collect_from_github_advisory(limit: int = 50) -> list[dict]:
    """从 GitHub Advisory 采集数据。"""
    print("[GitHub Advisory] 采集中...")
    url = "https://api.github.com/advisories"
    params = {"type": "reviewed", "per_page": limit}
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "VulnTell/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        if response.status_code == 200:
            advisories = response.json()
            print(f"[GitHub Advisory] 采集到 {len(advisories)} 条记录")
            return advisories
        else:
            print(f"[GitHub Advisory] 失败: HTTP {response.status_code}")
            return []
    except Exception as e:
        print(f"[GitHub Advisory] 错误: {e}")
        return []


def convert_nvd_to_cosv(vulns: list[dict]) -> list[COSVDocument]:
    """将 NVD 数据转换为 COSV 格式。"""
    docs = []
    for vuln in vulns:
        cve = vuln.get("cve", {})
        cve_id = cve.get("id", "")

        # 提取描述
        descriptions = cve.get("descriptions", [])
        summary = ""
        details = ""
        for desc in descriptions:
            if desc.get("lang") == "en":
                summary = desc.get("value", "")
                break
        if not summary and descriptions:
            summary = descriptions[0].get("value", "")

        # 提取严重性
        metrics = cve.get("metrics", {})
        severity = []
        cvss_v31 = metrics.get("cvssMetricV31", [])
        if cvss_v31:
            cvss_data = cvss_v31[0].get("cvssData", {})
            severity.append({
                "type": "CVSS_V31",
                "score": str(cvss_data.get("baseScore", "")),
                "vector": cvss_data.get("vectorString", ""),
            })

        # 处理时间格式 - 确保是 RFC 3339 UTC
        modified = cve.get("lastModified", "2024-01-01T00:00:00")
        if not modified.endswith("Z"):
            modified = modified + "Z" if "+" not in modified else modified

        published = cve.get("published", "")
        if published and not published.endswith("Z"):
            published = published + "Z" if "+" not in published else published

        doc = COSVDocument(
            id=cve_id,
            modified=modified,
            published=published if published else None,
            summary=summary,
            severity=severity,
            database_specific={"source": "nvd", "source_id": cve_id},
        )
        docs.append(doc)

    return docs


def convert_cisa_to_cosv(vulns: list[dict]) -> list[COSVDocument]:
    """将 CISA KEV 数据转换为 COSV 格式。"""
    docs = []
    for vuln in vulns:
        cve_id = vuln.get("cveID", "")
        product = vuln.get("product", "")
        vendor = vuln.get("vendorProject", "")

        # 处理时间格式
        date_added = vuln.get("dateAdded", "2024-01-01")
        if "T" not in date_added:
            date_added = date_added + "T00:00:00Z"
        elif not date_added.endswith("Z"):
            date_added = date_added + "Z"

        doc = COSVDocument(
            id=cve_id,
            modified=date_added,
            summary=f"{product} vulnerability ({vendor})",
            database_specific={
                "source": "cisa_kev",
                "source_id": cve_id,
                "kev_date_added": vuln.get("dateAdded", ""),
                "kev_due_date": vuln.get("requiredAction", ""),
                "kev_ransomware_use": vuln.get("knownRansomwareCampaignUse", "") == "Known",
            },
        )
        docs.append(doc)

    return docs


def convert_github_to_cosv(advisories: list[dict]) -> list[COSVDocument]:
    """将 GitHub Advisory 数据转换为 COSV 格式。"""
    docs = []
    for adv in advisories:
        ghsa_id = adv.get("ghsa_id", "")
        cve_id = adv.get("cve_id", "")
        doc_id = cve_id if cve_id else ghsa_id

        severity = []
        if adv.get("severity") == "critical":
            severity.append({"type": "CVSS_V31", "score": "9.0"})
        elif adv.get("severity") == "high":
            severity.append({"type": "CVSS_V31", "score": "7.0"})

        # 处理时间格式
        modified = adv.get("updated_at", "2024-01-01T00:00:00")
        if not modified.endswith("Z"):
            modified = modified + "Z" if "+" not in modified else modified

        published = adv.get("published_at", "")
        if published and not published.endswith("Z"):
            published = published + "Z" if "+" not in published else published

        doc = COSVDocument(
            id=doc_id,
            modified=modified,
            published=published if published else None,
            summary=adv.get("summary", ""),
            severity=severity,
            database_specific={
                "source": "github_advisory",
                "source_id": ghsa_id,
            },
        )
        docs.append(doc)

    return docs


def create_batch_from_docs(
    base_dir: Path,
    batch_id: str,
    source: str,
    docs: list[COSVDocument],
) -> Path:
    """从文档列表创建批次。"""
    batch_dir = base_dir / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    # 写入 COSV 文件
    records_path = batch_dir / "records.cosv.jsonl"
    for doc in docs:
        serialize_cosv_to_file(doc, records_path, mode="a")

    # 计算内容哈希
    file_hash = calculate_content_hash(records_path)

    # 创建 manifest
    manifest = create_batch_manifest(
        collector_id=f"collector-{source}",
        source=source,
        dataset_version="2024-01-01",
        window_start="2024-01-01T00:00:00Z",
        window_end="2024-01-02T00:00:00Z",
        record_count=len(docs),
        content_hash=file_hash,
    )
    save_manifest(manifest, batch_dir)

    return batch_dir


def main():
    """运行端到端测试。"""
    print("=" * 60)
    print("VulnTell 端到端分布式采集与合并测试")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 模拟不同采集者在不同目录采集
        collector1_dir = Path(tmpdir) / "collector1_nvd"
        collector2_dir = Path(tmpdir) / "collector2_cisa"
        collector3_dir = Path(tmpdir) / "collector3_github"
        collector1_dir.mkdir()
        collector2_dir.mkdir()
        collector3_dir.mkdir()

        # 采集者 1: NVD
        print("\n" + "=" * 60)
        print("采集者 1: NVD")
        print("=" * 60)
        nvd_vulns = collect_from_nvd(limit=30)
        nvd_docs = convert_nvd_to_cosv(nvd_vulns)
        batch1 = create_batch_from_docs(collector1_dir, "batch-nvd", "nvd", nvd_docs)

        # 采集者 2: CISA KEV
        print("\n" + "=" * 60)
        print("采集者 2: CISA KEV")
        print("=" * 60)
        cisa_vulns = collect_from_cisa_kev()
        cisa_docs = convert_cisa_to_cosv(cisa_vulns[:30])
        batch2 = create_batch_from_docs(collector2_dir, "batch-cisa", "cisa_kev", cisa_docs)

        # 采集者 3: GitHub Advisory
        print("\n" + "=" * 60)
        print("采集者 3: GitHub Advisory")
        print("=" * 60)
        github_advisories = collect_from_github_advisory(limit=30)
        github_docs = convert_github_to_cosv(github_advisories)
        batch3 = create_batch_from_docs(collector3_dir, "batch-github", "github_advisory", github_docs)

        # 导入所有批次到统一目录
        print("\n" + "=" * 60)
        print("导入批次到统一目录")
        print("=" * 60)
        import_dir = Path(tmpdir) / "imported"
        import_dir.mkdir()

        result1 = import_batch(batch1, import_dir)
        result2 = import_batch(batch2, import_dir)
        result3 = import_batch(batch3, import_dir)

        print(f"批次 1 (NVD): 导入 {result1.imported_records} 条")
        print(f"批次 2 (CISA): 导入 {result2.imported_records} 条")
        print(f"批次 3 (GitHub): 导入 {result3.imported_records} 条")

        # 列出所有批次
        batches = list_batches(import_dir)
        print(f"\n导入的批次总数: {len(batches)}")
        for b in batches:
            print(f"  - {b['batch_id'][:8]}...: {b['source']} ({b['record_count']} records)")

        # 合并所有批次
        print("\n" + "=" * 60)
        print("合并所有批次")
        print("=" * 60)
        output_dir = Path(tmpdir) / "merged"
        merged_docs, report = merge_batches(
            [batch1, batch2, batch3],
            output_dir,
        )

        print(f"\n合并结果:")
        print(f"  接收: {report.received}")
        print(f"  验证: {report.validated}")
        print(f"  合并: {report.merged}")
        print(f"  重复: {report.duplicates}")
        print(f"  冲突: {report.conflicts}")

        # 统计各来源
        source_counts = {}
        for doc in merged_docs:
            source = doc.database_specific.source if doc.database_specific else "unknown"
            source_counts[source] = source_counts.get(source, 0) + 1

        print(f"\n各来源记录数:")
        for source, count in sorted(source_counts.items()):
            print(f"  {source}: {count}")

        # 显示部分合并后的文档
        print(f"\n合并后的文档示例 (前 10 个):")
        for doc in merged_docs[:10]:
            source = doc.database_specific.source if doc.database_specific else "unknown"
            print(f"  - {doc.id} ({source}): {doc.summary[:50] if doc.summary else 'N/A'}...")

        # 保存完整结果
        result_file = output_dir / "merge_result.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump({
                "summary": {
                    "total_merged": report.merged,
                    "total_duplicates": report.duplicates,
                    "total_conflicts": report.conflicts,
                    "sources": source_counts,
                },
                "documents": [
                    {
                        "id": doc.id,
                        "source": doc.database_specific.source if doc.database_specific else "unknown",
                        "summary": doc.summary[:100] if doc.summary else "",
                        "modified": doc.modified,
                    }
                    for doc in merged_docs
                ],
            }, f, indent=2, ensure_ascii=False)

        print(f"\n完整结果已保存至: {result_file}")

        # 最终统计
        print("\n" + "=" * 60)
        print("最终统计")
        print("=" * 60)
        print(f"采集来源数: 3")
        print(f"导入批次数: {len(batches)}")
        print(f"合并记录数: {report.merged}")
        print(f"去重记录数: {report.duplicates}")
        print(f"冲突记录数: {report.conflicts}")

        # 验证
        assert report.merged > 0, "合并记录数应大于 0"
        assert len(source_counts) >= 2, "应至少有 2 个来源"
        print("\n验证通过!")


if __name__ == "__main__":
    main()
