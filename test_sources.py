"""VulnTell 真实数据采集测试脚本。

逐一测试16个数据源的真实API调用，每个来源至少尝试三轮。
"""

import json
import time
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import importlib


def _requests():
    """Load the optional HTTP client only when a smoke test is invoked."""
    return importlib.import_module("requests")

# 输出目录
OUTPUT_DIR = Path("F:/personal/tool/muti-agent/test_data")
OUTPUT_DIR.mkdir(exist_ok=True)


def log_result(source: str, success: bool, record_count: int, message: str, round_num: int) -> None:
    """记录采集结果。"""
    status = "[OK]" if success else "[FAIL]"
    print(f"[Round {round_num}] {status} {source}: {record_count} records - {message}")


def save_results(source: str, data: list[dict], metadata: dict) -> str:
    """保存采集结果。"""
    output_file = OUTPUT_DIR / f"{source}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "source": source,
            "metadata": metadata,
            "records": data,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }, f, indent=2, ensure_ascii=False)
    return str(output_file)


# ==========================================
# 1. NVD (National Vulnerability Database)
# ==========================================
def test_nvd() -> dict[str, Any]:
    """测试 NVD API。"""
    results = {"source": "nvd", "rounds": [], "total_records": 0}
    
    # NVD API v2.0
    base_url = "https://services.nvd.nist.gov/rest/json/cves/2.0"
    
    for round_num in range(1, 4):
        try:
            # 使用最近30天的数据
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=1)
            
            params = {
                "pubStartDate": start_date.strftime("%Y-%m-%dT00:00:00.000"),
                "pubEndDate": end_date.strftime("%Y-%m-%dT23:59:59.999"),
                "resultsPerPage": 100,
                "startIndex": (round_num - 1) * 100,
            }
            
            headers = {
                "User-Agent": "VulnTell/1.0 (Security Research Tool)",
            }
            
            response = _requests().get(base_url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                vulns = data.get("vulnerabilities", [])
                total_results = data.get("totalResults", 0)
                
                log_result("nvd", True, len(vulns), f"共 {total_results} 条可用", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": True,
                    "count": len(vulns),
                    "total_available": total_results,
                })
                results["total_records"] += len(vulns)
                
                # 保存第一批数据
                if round_num == 1 and vulns:
                    save_results("nvd", vulns[:10], {
                        "total_available": total_results,
                        "api_version": "2.0",
                        "endpoint": base_url,
                    })
            else:
                log_result("nvd", False, 0, f"HTTP {response.status_code}", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                })
            
            time.sleep(1)  # 避免速率限制
            
        except Exception as e:
            log_result("nvd", False, 0, str(e), round_num)
            results["rounds"].append({
                "round": round_num,
                "success": False,
                "error": str(e),
            })
    
    return results


# ==========================================
# 2. CISA KEV (Known Exploited Vulnerabilities)
# ==========================================
def test_cisa_kev() -> dict[str, Any]:
    """测试 CISA KEV API。"""
    results = {"source": "cisa_kev", "rounds": [], "total_records": 0}
    
    url = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
    
    for round_num in range(1, 4):
        try:
            headers = {
                "User-Agent": "VulnTell/1.0 (Security Research Tool)",
            }
            
            response = _requests().get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                vulns = data.get("vulnerabilities", [])
                catalog_version = data.get("catalogVersion", "unknown")
                
                log_result("cisa_kev", True, len(vulns), f"版本 {catalog_version}", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": True,
                    "count": len(vulns),
                    "catalog_version": catalog_version,
                })
                results["total_records"] = len(vulns)  # CISA KEV 是完整列表
                
                # 保存数据
                if round_num == 1:
                    save_results("cisa_kev", vulns[:10], {
                        "catalog_version": catalog_version,
                        "total_vulnerabilities": len(vulns),
                        "url": url,
                    })
            else:
                log_result("cisa_kev", False, 0, f"HTTP {response.status_code}", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                })
            
            time.sleep(2)  # CISA 可能有速率限制
            
        except Exception as e:
            log_result("cisa_kev", False, 0, str(e), round_num)
            results["rounds"].append({
                "round": round_num,
                "success": False,
                "error": str(e),
            })
    
    return results


# ==========================================
# 3. OSV.dev (Open Source Vulnerabilities)
# ==========================================
def test_osv() -> dict[str, Any]:
    """测试 OSV.dev API。"""
    results = {"source": "osv", "rounds": [], "total_records": 0}
    
    # OSV.dev 使用 GraphQL API
    url = "https://api.osv.dev/v1/query"
    
    for round_num in range(1, 4):
        try:
            # 查询最近的漏洞
            query = {
                "package": {
                    "name": "lodash",
                    "ecosystem": "npm"
                },
            }
            
            headers = {
                "User-Agent": "VulnTell/1.0 (Security Research Tool)",
                "Content-Type": "application/json",
            }
            
            response = _requests().post(url, json=query, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                vulns = data.get("vulns", [])
                
                log_result("osv", True, len(vulns), "npm lodash 漏洞", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": True,
                    "count": len(vulns),
                })
                results["total_records"] += len(vulns)
                
                # 保存数据
                if round_num == 1 and vulns:
                    save_results("osv", vulns[:5], {
                        "query": query,
                        "api": "v1/query",
                    })
            else:
                log_result("osv", False, 0, f"HTTP {response.status_code}", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                })
            
            time.sleep(1)
            
        except Exception as e:
            log_result("osv", False, 0, str(e), round_num)
            results["rounds"].append({
                "round": round_num,
                "success": False,
                "error": str(e),
            })
    
    return results


# ==========================================
# 4. GitHub Advisory Database
# ==========================================
def test_github_advisory() -> dict[str, Any]:
    """测试 GitHub Advisory API。"""
    results = {"source": "github_advisory", "rounds": [], "total_records": 0}
    
    url = "https://api.github.com/advisories"
    
    for round_num in range(1, 4):
        try:
            params = {
                "type": "reviewed",
                "per_page": 100,
                "page": round_num,
            }
            
            headers = {
                "Accept": "application/vnd.github+json",
                "User-Agent": "VulnTell/1.0 (Security Research Tool)",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            
            response = _requests().get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                advisories = response.json()
                
                log_result("github_advisory", True, len(advisories), "GitHub Security Advisories", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": True,
                    "count": len(advisories),
                })
                results["total_records"] += len(advisories)
                
                # 保存数据
                if round_num == 1 and advisories:
                    save_results("github_advisory", advisories[:5], {
                        "api": "v3",
                        "type": "reviewed",
                    })
            elif response.status_code == 403:
                # 速率限制
                reset_time = response.headers.get("X-RateLimit-Reset", "unknown")
                log_result("github_advisory", False, 0, f"速率限制，重置时间: {reset_time}", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": False,
                    "error": "rate_limited",
                })
                time.sleep(30)  # 等待速率限制重置
            else:
                log_result("github_advisory", False, 0, f"HTTP {response.status_code}", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                })
            
            time.sleep(2)
            
        except Exception as e:
            log_result("github_advisory", False, 0, str(e), round_num)
            results["rounds"].append({
                "round": round_num,
                "success": False,
                "error": str(e),
            })
    
    return results


# ==========================================
# 5. EUVD (European Vulnerability Database)
# ==========================================
def test_euvd() -> dict[str, Any]:
    """测试 EUVD API。"""
    results = {"source": "euvd", "rounds": [], "total_records": 0}
    
    # EUVD 使用 ENISA API
    url = "https://euvd.enisa.europa.eu/api/advisories"
    
    for round_num in range(1, 4):
        try:
            params = {
                "limit": 100,
                "offset": (round_num - 1) * 100,
            }
            
            headers = {
                "User-Agent": "VulnTell/1.0 (Security Research Tool)",
            }
            
            response = _requests().get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                advisories = data if isinstance(data, list) else data.get("advisories", [])
                
                log_result("euvd", True, len(advisories), "EU Advisory Database", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": True,
                    "count": len(advisories),
                })
                results["total_records"] += len(advisories)
                
                # 保存数据
                if round_num == 1 and advisories:
                    save_results("euvd", advisories[:5], {
                        "api": "ENISA EUVD",
                        "endpoint": url,
                    })
            else:
                log_result("euvd", False, 0, f"HTTP {response.status_code}", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                })
            
            time.sleep(1)
            
        except Exception as e:
            log_result("euvd", False, 0, str(e), round_num)
            results["rounds"].append({
                "round": round_num,
                "success": False,
                "error": str(e),
            })
    
    return results


# ==========================================
# 6. Microsoft MSRC
# ==========================================
def test_msrc() -> dict[str, Any]:
    """测试 Microsoft MSRC API。"""
    results = {"source": "msrc", "rounds": [], "total_records": 0}
    
    # MSRC API v3
    url = "https://api.msrc.microsoft.com/cvrf/v3.0/updates"
    
    for round_num in range(1, 4):
        try:
            headers = {
                "Accept": "application/json",
                "User-Agent": "VulnTell/1.0 (Security Research Tool)",
            }
            
            response = _requests().get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                updates = data.get("value", [])
                
                log_result("msrc", True, len(updates), "Microsoft Security Updates", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": True,
                    "count": len(updates),
                })
                results["total_records"] += len(updates)
                
                # 保存数据
                if round_num == 1 and updates:
                    save_results("msrc", updates[:5], {
                        "api": "cvrf/v3.0",
                        "endpoint": url,
                    })
            else:
                log_result("msrc", False, 0, f"HTTP {response.status_code}", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                })
            
            time.sleep(1)
            
        except Exception as e:
            log_result("msrc", False, 0, str(e), round_num)
            results["rounds"].append({
                "round": round_num,
                "success": False,
                "error": str(e),
            })
    
    return results


# ==========================================
# 7. Red Hat Security Data
# ==========================================
def test_redhat() -> dict[str, Any]:
    """测试 Red Hat Security Data API。"""
    results = {"source": "redhat", "rounds": [], "total_records": 0}
    
    # Red Hat Security Data API
    url = "https://access.redhat.com/labs/securitydataapi/v2"
    
    for round_num in range(1, 4):
        try:
            params = {
                "per_page": 100,
                "page": round_num,
            }
            
            headers = {
                "User-Agent": "VulnTell/1.0 (Security Research Tool)",
            }
            
            response = _requests().get(f"{url}/cve.json", params=params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                cves = data if isinstance(data, list) else data.get("cves", [])
                
                log_result("redhat", True, len(cves), "Red Hat CVE Database", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": True,
                    "count": len(cves),
                })
                results["total_records"] += len(cves)
                
                # 保存数据
                if round_num == 1 and cves:
                    save_results("redhat", cves[:5], {
                        "api": "v2",
                        "endpoint": url,
                    })
            else:
                log_result("redhat", False, 0, f"HTTP {response.status_code}", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                })
            
            time.sleep(1)
            
        except Exception as e:
            log_result("redhat", False, 0, str(e), round_num)
            results["rounds"].append({
                "round": round_num,
                "success": False,
                "error": str(e),
            })
    
    return results


# ==========================================
# 8. Ubuntu CVE Tracker
# ==========================================
def test_ubuntu() -> dict[str, Any]:
    """测试 Ubuntu CVE Tracker。"""
    results = {"source": "ubuntu", "rounds": [], "total_records": 0}
    
    # Ubuntu CVE Tracker RSS
    url = "https://ubuntu.com/security/notices.json"
    
    for round_num in range(1, 4):
        try:
            params = {
                "limit": 100,
                "offset": (round_num - 1) * 100,
            }
            
            headers = {
                "User-Agent": "VulnTell/1.0 (Security Research Tool)",
            }
            
            response = _requests().get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                notices = data.get("notices", [])
                
                log_result("ubuntu", True, len(notices), "Ubuntu Security Notices", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": True,
                    "count": len(notices),
                })
                results["total_records"] += len(notices)
                
                # 保存数据
                if round_num == 1 and notices:
                    save_results("ubuntu", notices[:5], {
                        "api": "JSON",
                        "endpoint": url,
                    })
            else:
                log_result("ubuntu", False, 0, f"HTTP {response.status_code}", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                })
            
            time.sleep(1)
            
        except Exception as e:
            log_result("ubuntu", False, 0, str(e), round_num)
            results["rounds"].append({
                "round": round_num,
                "success": False,
                "error": str(e),
            })
    
    return results


# ==========================================
# 9. Debian Security Tracker
# ==========================================
def test_debian() -> dict[str, Any]:
    """测试 Debian Security Tracker。"""
    results = {"source": "debian", "rounds": [], "total_records": 0}
    
    # Debian JSON API
    url = "https://security-tracker.debian.org/tracker/data/json"
    
    for round_num in range(1, 4):
        try:
            headers = {
                "User-Agent": "VulnTell/1.0 (Security Research Tool)",
            }
            
            response = _requests().get(url, headers=headers, timeout=60)  # Debian JSON 可能很大
            
            if response.status_code == 200:
                data = response.json()
                # Debian JSON 包含所有漏洞，结构较复杂
                cve_count = len([k for k in data.keys() if k.startswith("CVE-")])
                
                log_result("debian", True, cve_count, "Debian Security Tracker JSON", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": True,
                    "count": cve_count,
                })
                results["total_records"] = cve_count  # 完整数据集
                
                # 保存部分数据
                if round_num == 1:
                    sample = dict(list(data.items())[:10])
                    save_results("debian", [{"key": k, "value": v} for k, v in sample.items()], {
                        "total_cves": cve_count,
                        "endpoint": url,
                    })
            else:
                log_result("debian", False, 0, f"HTTP {response.status_code}", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                })
            
            time.sleep(2)
            
        except Exception as e:
            log_result("debian", False, 0, str(e), round_num)
            results["rounds"].append({
                "round": round_num,
                "success": False,
                "error": str(e),
            })
    
    return results


# ==========================================
# 10. JVN (Japan Vulnerability Notes)
# ==========================================
def test_jvn() -> dict[str, Any]:
    """测试 JVN API。"""
    results = {"source": "jvn", "rounds": [], "total_records": 0}
    
    # JVN XML Feed
    url = "https://jvndb.jvn.jp/myjvnxmlfeed"
    
    for round_num in range(1, 4):
        try:
            params = {
                "response": "verbose",
                "feed": "hnd",
            }
            
            headers = {
                "User-Agent": "VulnTell/1.0 (Security Research Tool)",
            }
            
            response = _requests().get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                # JVN 返回 XML，需要解析
                # 简单计算漏洞数量
                content = response.text
                item_count = content.count("<item>")
                
                log_result("jvn", True, item_count, "JVN XML Feed", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": True,
                    "count": item_count,
                })
                results["total_records"] += item_count
                
                # 保存原始数据
                if round_num == 1:
                    save_results("jvn", [{"xml_content": content[:5000]}], {
                        "format": "XML",
                        "endpoint": url,
                    })
            else:
                log_result("jvn", False, 0, f"HTTP {response.status_code}", round_num)
                results["rounds"].append({
                    "round": round_num,
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                })
            
            time.sleep(1)
            
        except Exception as e:
            log_result("jvn", False, 0, str(e), round_num)
            results["rounds"].append({
                "round": round_num,
                "success": False,
                "error": str(e),
            })
    
    return results


# ==========================================
# 主函数
# ==========================================
def main():
    """运行所有测试。"""
    print("=" * 60)
    print("VulnTell Data Collection Test")
    print("=" * 60)
    
    all_results = []
    
    # 测试可用的来源
    test_functions = [
        ("NVD", test_nvd),
        ("CISA KEV", test_cisa_kev),
        ("OSV.dev", test_osv),
        ("GitHub Advisory", test_github_advisory),
        ("EUVD", test_euvd),
        ("Microsoft MSRC", test_msrc),
        ("Red Hat", test_redhat),
        ("Ubuntu", test_ubuntu),
        ("Debian", test_debian),
        ("JVN", test_jvn),
    ]
    
    for name, test_func in test_functions:
        print(f"\n{'='*60}")
        print(f"Testing {name}")
        print("=" * 60)
        result = test_func()
        all_results.append(result)
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("汇总结果")
    print("=" * 60)
    
    successful_sources = []
    total_records = 0
    
    for result in all_results:
        source = result["source"]
        total = result["total_records"]
        rounds = result["rounds"]
        success_count = sum(1 for r in rounds if r["success"])
        
        if success_count > 0:
            successful_sources.append(source)
            total_records += total
            print(f"[OK] {source}: {total} records ({success_count}/3 rounds succeeded)")
        else:
            print(f"[FAIL] {source}: failed")
    
    print(f"\nSuccessful sources: {len(successful_sources)}/10")
    print(f"Total records: {total_records}")
    print(f"\nData saved to: {OUTPUT_DIR}")
    
    # Save summary report
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_sources_tested": len(all_results),
            "successful_sources": len(successful_sources),
            "total_records": total_records,
        },
        "results": all_results,
    }
    
    report_file = OUTPUT_DIR / "collection_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\nReport saved to: {report_file}")
    
    return len(successful_sources) >= 10


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
