"""VulnTell 真实数据采集测试脚本（简化版）。"""

import json
import importlib
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path("F:/personal/tool/muti-agent/test_data")
OUTPUT_DIR.mkdir(exist_ok=True)


def _requests():
    """Load requests lazily; network access is opt-in for this smoke script."""
    return importlib.import_module("requests")

def test_source(name, test_func):
    """测试单个来源。"""
    print(f"\n{'='*60}")
    print(f"Testing {name}")
    print("=" * 60)
    try:
        result = test_func()
        return result
    except Exception as e:
        print(f"Error: {e}")
        return {"source": name, "success": False, "error": str(e)}

def test_nvd():
    """测试 NVD API。"""
    url = "https://services.nvd.nist.gov/rest/json/cves/2.0"
    params = {"resultsPerPage": 100, "startIndex": 0}
    headers = {"User-Agent": "VulnTell/1.0"}
    response = _requests().get(url, params=params, headers=headers, timeout=30)
    
    if response.status_code == 200:
        data = response.json()
        vulns = data.get("vulnerabilities", [])
        total = data.get("totalResults", 0)
        print(f"Records: {len(vulns)}, Total available: {total}")
        return {"source": "nvd", "success": True, "count": len(vulns), "total": total}
    else:
        print(f"Failed: HTTP {response.status_code}")
        return {"source": "nvd", "success": False, "status": response.status_code}

def test_cisa_kev():
    """测试 CISA KEV API。"""
    url = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
    headers = {"User-Agent": "VulnTell/1.0"}
    response = _requests().get(url, headers=headers, timeout=30)
    
    if response.status_code == 200:
        data = response.json()
        vulns = data.get("vulnerabilities", [])
        version = data.get("catalogVersion", "unknown")
        print(f"Records: {len(vulns)}, Version: {version}")
        return {"source": "cisa_kev", "success": True, "count": len(vulns), "version": version}
    else:
        print(f"Failed: HTTP {response.status_code}")
        return {"source": "cisa_kev", "success": False, "status": response.status_code}

def test_osv():
    """测试 OSV.dev API。"""
    url = "https://api.osv.dev/v1/query"
    query = {"package": {"name": "lodash", "ecosystem": "npm"}}
    headers = {"User-Agent": "VulnTell/1.0", "Content-Type": "application/json"}
    response = _requests().post(url, json=query, headers=headers, timeout=30)
    
    if response.status_code == 200:
        data = response.json()
        vulns = data.get("vulns", [])
        print(f"Records: {len(vulns)} (lodash npm)")
        return {"source": "osv", "success": True, "count": len(vulns)}
    else:
        print(f"Failed: HTTP {response.status_code}")
        return {"source": "osv", "success": False, "status": response.status_code}

def test_github_advisory():
    """测试 GitHub Advisory API。"""
    url = "https://api.github.com/advisories"
    params = {"type": "reviewed", "per_page": 100}
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "VulnTell/1.0",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    response = _requests().get(url, params=params, headers=headers, timeout=30)
    
    if response.status_code == 200:
        advisories = response.json()
        print(f"Records: {len(advisories)}")
        return {"source": "github_advisory", "success": True, "count": len(advisories)}
    elif response.status_code == 403:
        print("Rate limited")
        return {"source": "github_advisory", "success": False, "error": "rate_limited"}
    else:
        print(f"Failed: HTTP {response.status_code}")
        return {"source": "github_advisory", "success": False, "status": response.status_code}

def test_euvd():
    """测试 EUVD API。"""
    # 尝试多个端点
    endpoints = [
        "https://euvd.enisa.europa.eu/api/advisories",
        "https://euvd.enisa.europa.eu/api/advisories/search",
        "https://euvd.enisa.europa.eu/api/catalogue",
    ]
    
    for url in endpoints:
        try:
            params = {"limit": 10}
            headers = {"User-Agent": "VulnTell/1.0"}
            response = _requests().get(url, params=params, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                count = len(data) if isinstance(data, list) else len(data.get("advisories", []))
                print(f"Records: {count} (from {url})")
                return {"source": "euvd", "success": True, "count": count, "endpoint": url}
        except Exception as e:
            continue
    
    print("All endpoints failed")
    return {"source": "euvd", "success": False, "error": "all_endpoints_failed"}

def test_msrc():
    """测试 Microsoft MSRC API。"""
    url = "https://api.msrc.microsoft.com/cvrf/v3.0/updates"
    headers = {"Accept": "application/json", "User-Agent": "VulnTell/1.0"}
    response = _requests().get(url, headers=headers, timeout=30)
    
    if response.status_code == 200:
        data = response.json()
        updates = data.get("value", [])
        print(f"Updates: {len(updates)}")
        return {"source": "msrc", "success": True, "count": len(updates)}
    else:
        print(f"Failed: HTTP {response.status_code}")
        return {"source": "msrc", "success": False, "status": response.status_code}

def test_redhat():
    """测试 Red Hat Security Data API。"""
    # 尝试多个端点
    endpoints = [
        ("https://access.redhat.com/labs/securitydataapi/v2/cve.json", "JSON API"),
        ("https://access.redhat.com/security/data/oval/v2", "OVAL Data"),
    ]
    
    for url, name in endpoints:
        try:
            headers = {"User-Agent": "VulnTell/1.0"}
            response = _requests().get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                print(f"Endpoint {name}: OK")
                return {"source": "redhat", "success": True, "count": 0, "endpoint": name}
        except Exception as e:
            continue
    
    print("All endpoints failed")
    return {"source": "redhat", "success": False, "error": "all_endpoints_failed"}

def test_ubuntu():
    """测试 Ubuntu CVE Tracker。"""
    url = "https://ubuntu.com/security/notices.json"
    params = {"limit": 100}
    headers = {"User-Agent": "VulnTell/1.0"}
    response = _requests().get(url, params=params, headers=headers, timeout=30)
    
    if response.status_code == 200:
        data = response.json()
        notices = data.get("notices", [])
        print(f"Records: {len(notices)}")
        return {"source": "ubuntu", "success": True, "count": len(notices)}
    else:
        print(f"Failed: HTTP {response.status_code}")
        return {"source": "ubuntu", "success": False, "status": response.status_code}

def test_debian():
    """测试 Debian Security Tracker。"""
    url = "https://security-tracker.debian.org/tracker/data/json"
    headers = {"User-Agent": "VulnTell/1.0"}
    response = _requests().get(url, headers=headers, timeout=60)
    
    if response.status_code == 200:
        data = response.json()
        package_count = len(data)
        print(f"Packages: {package_count}")
        return {"source": "debian", "success": True, "count": package_count}
    else:
        print(f"Failed: HTTP {response.status_code}")
        return {"source": "debian", "success": False, "status": response.status_code}

def test_jvn():
    """测试 JVN API。"""
    # 尝试多个端点
    endpoints = [
        ("https://jvndb.jvn.jp/myjvn", {"method": "getVulnOverviewList", "feed": "hnd", "maxCountItem": 10}),
        ("https://jvndb.jvn.jp/jvndb/rss", {}),
    ]
    
    for url, params in endpoints:
        try:
            headers = {"User-Agent": "VulnTell/1.0"}
            response = _requests().get(url, params=params, headers=headers, timeout=30)
            if response.status_code == 200:
                content = response.text
                item_count = content.count("<item>") + content.count("<entry")
                print(f"Records: {item_count}")
                return {"source": "jvn", "success": True, "count": item_count}
        except Exception as e:
            continue
    
    print("All endpoints failed")
    return {"source": "jvn", "success": False, "error": "all_endpoints_failed"}

def main():
    """运行所有测试。"""
    print("=" * 60)
    print("VulnTell Data Collection Test")
    print("=" * 60)
    
    tests = [
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
    
    results = []
    for name, test_func in tests:
        result = test_source(name, test_func)
        results.append(result)
    
    # 汇总
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    
    successful = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]
    
    print(f"Successful: {len(successful)}/{len(results)}")
    for r in successful:
        print(f"  [OK] {r['source']}: {r.get('count', 0)} records")
    
    if failed:
        print(f"Failed: {len(failed)}")
        for r in failed:
            print(f"  [FAIL] {r['source']}: {r.get('error', r.get('status', 'unknown'))}")
    
    # 保存结果
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_tested": len(results),
            "successful": len(successful),
            "total_records": sum(r.get("count", 0) for r in successful),
        },
        "results": results,
    }
    
    report_file = OUTPUT_DIR / "collection_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\nReport saved to: {report_file}")
    
    return len(successful)

if __name__ == "__main__":
    successful = main()
    print(f"\nResult: {successful} sources working")
