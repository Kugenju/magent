"""静态 HTML 前端（阶段 10 桥接：日报的"展示"产物）。

纯服务端渲染：单文件、零依赖、无外部 URL（无 CDN/无 img/无 script src）、
UTF-8、双击可开、可按 run 归档。展示内容 = 多 agent 协作工作流本身：

1. 运行页眉（run_id / 窗口 / 版本 / insufficient_data 旗标）；
2. 多智能体执行时间线（GraphExecutor steps：agent/状态/耗时/消息）；
3. 数据源状态表（采集/失败样本计数）；
4. 每来源指标卡（``compute_source_metrics`` 来源级快照——"之前的方法"直接
   复用；样本不足展示 insufficient_data 状态，不做无依据排名）；
5. 质量告警聚合（missing/invalid/ambiguous 按来源/严重度统计）；
6. OSV 双路径一致性对照（live：REST 直连 vs MCP 的 canonical hash 与字段）；
7. canonical 预览（按 modified 倒序展示近期活动，非严重性排名）。

完整数据以 ``<script type="application/json" id="vulntell-data">`` 附带
（``<`` => ``\\u003c`` 加固），供未来客户端增强，不依赖任何运行时框架。
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from apps.vulntell.domain.metrics import compute_source_metrics


def _esc(value: Any) -> str:
    return html.escape(str(value) if value is not None else "—", quote=True)


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _fmt_pct(value: Any) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


_STATUS_CLASS = {"ok": "ok", "partial": "partial", "failed": "failed",
                 "success": "ok", "insufficient_data": "partial"}


def _badge(status: str) -> str:
    cls = _STATUS_CLASS.get(status, "unknown")
    return f'<span class="badge badge-{cls}">{_esc(status)}</span>'


def _table(headers: list[str], rows: list[str]) -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    return f"<table><tr>{head}</tr>{''.join(rows)}</table>"


def _cells(*values: Any, cls: str = "") -> str:
    klass = f" class='{cls}'" if cls else ""
    return "".join(f"<td{klass}>{_esc(v)}</td>" for v in values)


def render_dashboard(
    *,
    run_id: str,
    meta: Any,
    report: Optional[Any],
    final_state: Any,
    execution_report: Any,
    dual_path: Optional[dict],
    source_summaries: dict,
) -> str:
    """渲染完整 dashboard HTML（纯函数；写文件用 :func:`write_dashboard`）。"""
    from apps.vulntell.domain.models import CanonicalVulnerability, SourceObservation

    observations = [
        SourceObservation(**d) for lst in final_state.observations_by_source.values() for d in lst
    ]
    per_source_order = sorted(set(final_state.source_status) | set(source_summaries))
    status = dict(final_state.source_status)
    for src in per_source_order:
        status.setdefault(src, "unknown")
    snapshots = compute_source_metrics(observations, source_status=status) if observations else {}

    window = f"{meta.window_start:%Y-%m-%d %H:%M}…{meta.window_end:%Y-%m-%d %H:%M} UTC"
    versions = (
        f"framework {_esc(meta.framework_version)} · parser {_esc(meta.parser_version)}"
        f" · dedupe {_esc(meta.deduplication_version)} · metric {_esc(meta.metric_version)}"
    )
    generated = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}"

    parts: list[str] = []
    parts.append(f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>VulnTell 每日简报 — %RUN%</title>
<style>
:root {{ --ok:#1a7f37; --partial:#9a6700; --failed:#cf222e; --unknown:#77798c; }}
body {{ font-family:"Microsoft YaHei","Segoe UI",system-ui,sans-serif; margin:0;
       background:#f6f8fa; color:#1f2328; font-size:14px; }}
header {{ border-bottom:3px solid #1f6feb; padding:18px 28px; background:#fff; }}
header h1 {{ margin:0 0 6px; font-size:20px; }}
header .meta {{ color:#57606a; font-size:13px; line-height:1.7; }}
main {{ padding:18px 28px; max-width:1100px; margin:0 auto; }}
h2 {{ font-size:16px; border-bottom:1px solid #d0d7de; padding-bottom:6px; margin-top:34px; }}
table {{ border-collapse:collapse; width:100%; background:#fff; margin-top:10px; }}
th, td {{ border:1px solid #d0d7de; padding:6px 10px; text-align:left; vertical-align:top; }}
th {{ background:#f6f8fa; font-weight:600; white-space:nowrap; }}
tr:hover td {{ background:#f3f6fd; }}
.badge {{ display:inline-block; padding:1px 9px; border-radius:10px; color:#fff; font-size:12px; }}
.badge-ok {{ background:var(--ok); }}
.badge-partial {{ background:var(--partial); }}
.badge-failed {{ background:var(--failed); }}
.badge-unknown {{ background:var(--unknown); }}
.card {{ background:#fff; border:1px solid #d0d7de; border-radius:8px; padding:12px 16px; margin:12px 0; }}
.card h3 {{ margin:0 0 8px; font-size:14px; }}
.banner {{ background:#fff8c5; border:1px solid #d4a72c; padding:10px 14px; border-radius:8px; margin:14px 0; }}
.note {{ color:#57606a; font-size:12px; margin-top:6px; }}
.ok-text {{ color:var(--ok); font-weight:600; }}
.fail-text {{ color:var(--failed); font-weight:600; }}
</style>
</head>
<body>
<header>
  <h1>VulnTell 每日简报 <span class="pi">%RUN%</span></h1>
  <div class="meta">窗口：<b>%WINDOW%</b><br>数据集：<b>%DATASET%</b> · %VERSIONS%<br>生成时间：%GENERATED%（指标确定性可重放）</div>
</header>
<main>""".replace("%RUN%", _esc(run_id)).replace("%WINDOW%", _esc(window))
        .replace("%DATASET%", f"{_esc(meta.dataset_id)}@{_esc(meta.dataset_version)}")
        .replace("%VERSIONS%", versions).replace("%GENERATED%", _esc(generated)))

    if report is not None and report.insufficient_data:
        parts.append(
            '<div class="banner"><b>insufficient_data</b>：样本未达评估门槛；'
            "只展示原始状态与告警，不进行无依据排名。</div>"
        )

    # ---- 1. 多智能体执行时间线 --------------------------------------------
    steps = sorted(getattr(execution_report, "steps", []), key=lambda s: s.order)
    agent_rows = []
    for step in steps:
        sname = getattr(step.status, "name", str(step.status)).lower()
        msg = (step.message or "")[:90]
        agent_rows.append(
            f"<tr><td>{step.order}</td><td><b>{_esc(step.agent_name)}</b></td>"
            f"<td class='pi'>{_esc(getattr(step, 'node_id', '') or '')}</td>"
            f"<td>{_badge(_STATUS_CLASS.get(sname, sname))}</td>"
            f"<td class='pi'>{step.duration_ms:.0f} ms</td><td>{_esc(msg)}</td></tr>"
        )
    parts.append(
        "<h2>多智能体执行时间线</h2>"
        + _table(["#", "Agent", "node", "状态", "耗时", "消息"], agent_rows)
        + f"<p class='note'>Graph 摘要：并发峰值 {getattr(execution_report, 'peak_concurrency', 0)}"
        f" · 重试 {getattr(execution_report, 'retry_count', 0)}"
        f" · 总耗时 {getattr(execution_report, 'duration_ms', 0.0):.0f} ms。</p>"
    )

    # ---- 2. 数据源状态 ------------------------------------------------------
    src_rows = []
    for src in per_source_order:
        summary = source_summaries.get(src) or {}
        failed_field = summary.get("failed")
        failed_n = len(failed_field) if isinstance(failed_field, dict) else 0
        src_rows.append(
            f"<tr><td><b>{_esc(src)}</b></td><td>{_badge(status.get(src, 'unknown'))}</td>"
            f"{_cells(summary.get('fetched') if summary.get('fetched') is not None else '—', cls='pi')}"
            f"{_cells(failed_n, cls='pi')}</tr>"
        )
    parts.append(
        "<h2>数据源状态</h2>"
        + _table(["来源", "采集状态", "采集记录数", "失败样本"], src_rows)
        + "<p class='note'>失败来源按 CollectAgent 语义降级（部分失败继续评估），不阻塞其他分支。</p>"
    )

    # ---- 3. 每来源指标卡 -----------------------------------------------------
    for src in per_source_order:
        snap = snapshots.get(src)
        rows = []
        if snap is None:
            rows.append("<tr><td colspan='2' class='pi'>该来源本次无观测记录，指标不适用。</td></tr>")
            header = f"{_esc(src)} {_badge('unknown')}"
        else:
            n = snap.normalized
            t = (snap.raw or {}).get("timeliness") or {}
            pres = " · ".join(
                f"{str(k).replace('_rate', '')} {_fmt_pct(v)}"
                for k, v in sorted((n.get("presence_rate") or {}).items()) if v is not None
            ) or "—"
            rows.append(
                f"<tr><td>时效</td><td>avg {_fmt(t.get('avg_delay_days'))} 天 · "
                f"p50 {_fmt(t.get('p50_delay_days'))} · p90 {_fmt(t.get('p90_delay_days'))} · "
                f"时效率 {_fmt(n.get('timeliness_score'))}</td></tr>")
            rows.append(f"<tr><td>字段在位率</td><td>{_esc(pres)}</td></tr>")
            rows.append(
                f"<tr><td>可验证性</td><td>URL 覆盖 {_fmt_pct(n.get('url_coverage'))} · "
                f"已验证引用率 {_fmt_pct(n.get('verified_reference_rate'))}</td></tr>")
            rows.append(
                f"<tr><td>溯源</td><td>traceable {_fmt_pct(n.get('traceable_rate'))} · "
                f"完整度 {_fmt_pct((n.get('normalized_score') or {}).get('completeness'))}</td></tr>")
            conf_cls = {"high": "ok", "medium": "partial", "low": "failed"}.get(snap.confidence, "unknown")
            confidence = f"<span class='badge badge-{conf_cls}'>{_esc(snap.confidence)}</span>"
            header = f"{_esc(src)} {_badge(snap.status)} 置信 {confidence}"
        parts.append(
            f"<div class='card'><h3>{header}</h3>"
            + _table(["指标", "值"], rows) + "</div>"
        )
    parts.append(
        "<h2>每来源指标（按既有确定性评估方法）</h2>"
        "<p class='note'>指标定义版本冻结；样本不足时给出 insufficient_data，不做无依据排名。</p>"
    )

    # ---- 4. 质量告警聚合 ------------------------------------------------------
    qi_counts: dict[tuple[str, str, str], int] = {}
    for obs in observations:
        for qi in obs.quality_issues:
            key = (qi.source, qi.issue_type, qi.severity)
            qi_counts[key] = qi_counts.get(key, 0) + 1
    if qi_counts:
        qi_rows = [
            f"<tr><td><b>{_esc(src)}</b></td>{_cells(kind, sev, count, cls='pi')}</tr>"
            for (src, kind, sev), count in sorted(qi_counts.items())
        ]
        parts.append(
            f"<h2>质量告警聚合（共 {sum(qi_counts.values())} 条）</h2>"
            + _table(["来源", "类型", "严重度", "条数"], qi_rows)
            + "<p class='note'>missing / invalid / ambiguous 分别记账，不用默认值掩盖缺失。</p>"
        )
    else:
        parts.append("<h2>质量告警聚合</h2><p>本次采集未产生质量告警。</p>")

    # ---- 5. OSV 双路径一致性对照 ------------------------------------------------
    if dual_path is not None:
        summary = dual_path.get("summary") or {}
        if "error" in summary:
            parts.append(
                "<h2>OSV 双路径一致性对照</h2>"
                f"<div class='banner'>探针执行失败：{_esc(summary['error'])}</div>"
            )
        else:
            def _path_cell(row: dict, side: str) -> str:
                if row.get(f"{side}_ok"):
                    latency = row.get(f"{side}_latency_ms") or 0
                    return f"<td class='ok-text'>ok · {latency:.0f} ms</td>"
                err = (row.get(f"{side}_error") or "")[:60]
                return f"<td class='fail-text'>失败 · {_esc(err)}</td>"

            rows = []
            for row in dual_path.get("rows") or []:
                equal = row.get("payload_hash_equal")
                fields_eq = row.get("fields_equal")
                hash_cell = (
                    "<td class='ok-text'>一致</td>" if equal is True else
                    "<td class='fail-text'>不一致</td>" if equal is False else "<td class='pi'>—</td>"
                )
                fields_cell = (
                    "<td class='ok-text'>一致</td>" if fields_eq is True else
                    "<td class='fail-text'>不一致</td>" if fields_eq is False else "<td class='pi'>—</td>"
                )
                rows.append(
                    f"<tr><td><b>{_esc(row.get('cve_id'))}</b></td>"
                    f"{_path_cell(row, 'rest')}{_path_cell(row, 'mcp')}{hash_cell}{fields_cell}</tr>"
                )
            parts.append(
                "<h2>OSV 双路径一致性对照</h2>"
                + _table(["CVE ID", "REST 直连", "MCP 协议", "canonical hash", "归一化字段"], rows)
                + "<p class='note'>同一 OSV.dev 端点两条采集路径："
                f"样本 {summary.get('sample_size', 0)} · 双路径全通 {summary.get('both_ok', 0)}"
                f" · hash 一致 {summary.get('hash_equal', 0)}"
                f" · 字段一致 {summary.get('fields_equal', 0)}"
                f" · 同形失败 {summary.get('same_shape_failures', 0)}。"
                "MCP 采集路径与直连路径对同一端点不产生不同字节。</p>"
            )

    # ---- 6. canonical 预览 -------------------------------------------------------
    canonical = [CanonicalVulnerability(**d) for d in final_state.canonical]
    if canonical:
        def _order_key(c: CanonicalVulnerability) -> str:
            stamp = c.modified_at or c.published_at or c.first_observed_at
            return stamp.isoformat() if stamp else ""
        ordered = sorted(canonical, key=_order_key, reverse=True)[:12]
        rows = []
        for c in ordered:
            score = c.cvss.score if c.cvss else None
            stamp_text = (c.modified_at or c.published_at or "") if (c.modified_at or c.published_at) else "—"
            rows.append(
                f"<tr><td><b>{_esc(c.cve_id)}</b></td>"
                f"<td>{_esc((c.title or (c.description or ''))[:80])}</td>"
                f"{_cells(score, cls='pi')}"
                f"{_cells(f'{len(c.sources)} ({", ".join(sorted(c.sources))})', cls='pi')}"
                f"{_cells(stamp_text, cls='pi')}</tr>"
            )
        parts.append(
            f"<h2>Canonical 漏洞预览（共 {len(canonical)}，展示前 {len(ordered)}）</h2>"
            + _table(["CVE", "标题/描述", "CVSS", "来源", "modified"], rows)
            + "<p class='note'>按 modified 时间倒序仅展示近期活动；本系统不按严重性做无依据排名。</p>"
        )
    else:
        parts.append("<h2>Canonical 漏洞预览</h2><p>本次窗口内未合并出 canonical 实体。</p>")

    # ---- 数据帧（JSON 产物，零运行时依赖） ----------------------------------
    embed = {
        "run_id": run_id,
        "dataset": meta.model_dump(mode="json"),
        "source_status": dict(final_state.source_status),
        "failed_sources": list(final_state.failed_sources),
        "report": report.model_dump(mode="json") if report is not None else None,
        "per_source_metrics": {
            k: v.model_dump(mode="json") for k, v in snapshots.items()
        },
        "dual_path": dual_path,
        "source_summaries": source_summaries,
    }
    parts.append(
        '<script type="application/json" id="vulntell-data">'
        + _json_embed(embed)
        + "</script>"
    )
    parts.append("</main></body></html>")
    return "".join(parts)


def _json_embed(payload: Any) -> str:
    blob = json.dumps(payload, ensure_ascii=False, default=str)
    # script-tag 加固：转义 < 防止 "</script>" 提前闭合
    return blob.replace("<", "\\u003c")


def write_dashboard(path: Path, **kwargs: Any) -> Path:
    """渲染并写出 dashboard 文件（UTF-8）。"""
    path.write_text(render_dashboard(**kwargs), encoding="utf-8")
    return path
