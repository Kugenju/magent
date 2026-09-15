"""Collect the eight configured live sources for the paper's two-year window."""

from __future__ import annotations

import asyncio
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from apps.vulntell.batch import collect_adapter
from apps.vulntell.sources import (
    CISAKEVAdapter,
    CISAKEVConfig,
    MSRCAdapter,
    MSRCConfig,
    NVDAdapter,
    NVDConfig,
    OSVAdapter,
    OSVConfig,
    RedHatAdapter,
    RedHatConfig,
    UbuntuAdapter,
    UbuntuConfig,
    DebianAdapter,
    DebianConfig,
    GitHubAdvisoryAdapter,
    GitHubAdvisoryConfig,
)
from apps.vulntell.sources.cisa_kev import CISAKEVTransport
from apps.vulntell.sources.msrc import MSRCTransport
from apps.vulntell.sources.nvd import NVDTransport
from apps.vulntell.sources.osv import OSVTransport
from apps.vulntell.sources.redhat import RedHatTransport
from apps.vulntell.sources.ubuntu import UbuntuTransport
from apps.vulntell.sources.debian import DebianTransport
from apps.vulntell.sources.github_advisory import GitHubAdvisoryTransport
from apps.vulntell.sources.protocol import SourceRequest

START = datetime(2024, 9, 10, tzinfo=timezone.utc)
# Include the current UTC calendar day.  The collection window is half-open,
# so ending at midnight on 2026-09-10 would exclude all records published or
# updated during that day by sources such as Ubuntu and MSRC.
END = datetime(2026, 9, 15, tzinfo=timezone.utc)
ROOT = Path("deliveries/live-2y-20260910")
VERSION = "2024-09-10_2026-09-15"


async def collect_one(name: str, adapter, page_size: int, license_name: str) -> dict:
    output = ROOT / name / "batch-20260910T000000Z"
    request = SourceRequest(
        source=name,
        dataset_id=f"{name}-cve",
        dataset_version=VERSION,
        window_start=START,
        window_end=END,
        page_size=page_size,
        filters={"enforce_window": True} if name == "github_advisory" else {},
    )
    print(f"[{name}] start", flush=True)
    try:
        manifest, _documents = await collect_adapter(
            adapter,
            request,
            output,
            collector_id="live-2y",
            license=license_name,
        )
        result = {
            "source": name,
            "records": manifest.record_count,
            "fetched_record_count": manifest.fetched_record_count,
            "page_count": manifest.page_count,
            "truncated": manifest.truncated,
            "collection_complete": manifest.collection_complete,
            "path": str(output),
            "error": None,
        }
        print(
            f"[{name}] done records={manifest.record_count} "
            f"fetched={manifest.fetched_record_count} pages={manifest.page_count} "
            f"complete={manifest.collection_complete}",
            flush=True,
        )
        return result
    except Exception as exc:  # noqa: BLE001 - preserve per-source result
        result = {"source": name, "records": 0, "path": str(output), "error": repr(exc)}
        print(f"[{name}] ERROR {exc!r}", flush=True)
        return result


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", nargs="*", choices=["nvd", "cisa_kev", "redhat", "ubuntu", "msrc", "osv", "debian", "github_advisory"],
                        help="采集指定来源；默认采集全部来源")
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    jobs = [
        ("nvd", NVDAdapter(config=NVDConfig(use_bulk=True, page_size=200, max_response_bytes=20 * 1024 * 1024, timeout_seconds=180), transport=NVDTransport()), 200, "NVD-terms"),
        ("cisa_kev", CISAKEVAdapter(config=CISAKEVConfig(batch_size=500, timeout_seconds=60), transport=CISAKEVTransport()), 500, "CISA-terms"),
        ("redhat", RedHatAdapter(config=RedHatConfig(page_size=100, timeout_seconds=60), transport=RedHatTransport()), 100, "RedHat-terms"),
        ("ubuntu", UbuntuAdapter(config=UbuntuConfig(page_size=100, timeout_seconds=60, initial_offset=25000), transport=UbuntuTransport()), 100, "Ubuntu-terms"),
        ("msrc", MSRCAdapter(config=MSRCConfig(page_size=100, timeout_seconds=180), transport=MSRCTransport()), 100, "Microsoft-terms"),
        ("osv", OSVAdapter(config=OSVConfig(use_bulk=True, page_size=100, timeout_seconds=180), transport=OSVTransport()), 100, "OSV-terms"),
        # Debian's data/json endpoint is an atomic snapshot (the adapter
        # therefore performs no synthetic pagination).
        ("debian", DebianAdapter(config=DebianConfig(page_size=100, timeout_seconds=120), transport=DebianTransport()), 100, "Debian-terms"),
        ("github_advisory", GitHubAdvisoryAdapter(config=GitHubAdvisoryConfig(page_size=100, timeout_seconds=60), transport=GitHubAdvisoryTransport(), token=os.getenv("GITHUB_TOKEN")), 100, "GitHub-terms"),
    ]
    results = []
    selected = set(args.sources or [j[0] for j in jobs])
    for job in jobs:
        if job[0] not in selected:
            continue
        results.append(await collect_one(*job))
    # Preserve results from earlier independent runs.  This is important for
    # long-running feeds (NVD/OSV): rerunning one source must not erase the
    # audit evidence of the other five sources.
    summary_path = ROOT / "collection-summary.json"
    prior = {}
    if summary_path.exists():
        try:
            prior_data = json.loads(summary_path.read_text(encoding="utf-8"))
            prior = {item.get("source"): item for item in prior_data.get("results", [])}
        except (OSError, ValueError, TypeError):
            prior = {}
    prior.update({item["source"]: item for item in results})
    results = [prior[name] for name in ("nvd", "cisa_kev", "redhat", "ubuntu", "msrc", "osv", "debian", "github_advisory") if name in prior]
    summary = {
        "window_start": START.isoformat(),
        "window_end": END.isoformat(),
        "dataset_version": VERSION,
        "results": results,
    }
    (ROOT / "collection-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
