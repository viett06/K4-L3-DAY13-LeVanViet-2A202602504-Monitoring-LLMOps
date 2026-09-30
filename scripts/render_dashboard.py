"""Dựng dashboard 6 panel và các trang evidence từ data/logs.jsonl."""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.metrics import percentile


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_logs(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def window(records: list[dict], minutes: int) -> list[dict]:
    stamped = [record for record in records if record.get("ts")]
    if not stamped:
        return records
    latest = max(parse_ts(record["ts"]) for record in stamped)
    cutoff = latest.timestamp() - minutes * 60
    return [record for record in stamped if parse_ts(record["ts"]).timestamp() >= cutoff]


def fmt_ts(value: datetime | None) -> str:
    if value is None:
        return "n/a"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def summarize(records: list[dict]) -> dict:
    received = [record for record in records if record.get("event") == "request_received"]
    sent = [record for record in records if record.get("event") == "response_sent"]
    failed = [record for record in records if record.get("event") == "request_failed"]
    latencies = [int(record["latency_ms"]) for record in sent if record.get("latency_ms") is not None]
    ttft = [int(record["ttft_ms"]) for record in sent if record.get("ttft_ms") is not None]
    costs = [float(record.get("cost_usd") or 0) for record in sent]
    tokens_in = sum(int(record.get("tokens_in") or 0) for record in sent)
    tokens_out = sum(int(record.get("tokens_out") or 0) for record in sent)
    qualities = [float(record["quality_score"]) for record in sent if record.get("quality_score") is not None]
    tool_rows = [record for record in records if record.get("tool_success") is not None]
    tool_ok = sum(1 for record in tool_rows if record.get("tool_success") is True)
    timestamps = [parse_ts(record["ts"]) for record in records if record.get("ts")]
    start = min(timestamps) if timestamps else None
    end = max(timestamps) if timestamps else None
    span_minutes = 1.0
    if start and end:
        span_minutes = max((end - start).total_seconds() / 60, 1 / 60)
    error_rate = (len(failed) / len(received) * 100) if received else 0.0
    retrieval_rate = (tool_ok / len(tool_rows) * 100) if tool_rows else 0.0
    return {
        "received": len(received),
        "sent": len(sent),
        "failed": len(failed),
        "latency_p50": percentile(latencies, 50),
        "latency_p95": percentile(latencies, 95),
        "latency_p99": percentile(latencies, 99),
        "ttft_p95": percentile(ttft, 95),
        "rate_per_minute": round(len(received) / span_minutes, 3),
        "error_rate_pct": round(error_rate, 3),
        "error_breakdown": sorted(
            {record.get("error_type") or "unknown" for record in failed}
        ),
        "failed_types": {
            error_type: sum(1 for record in failed if (record.get("error_type") or "unknown") == error_type)
            for error_type in {record.get("error_type") or "unknown" for record in failed}
        },
        "retrieval_success_pct": round(retrieval_rate, 3),
        "tool_rows": len(tool_rows),
        "cost_total": round(sum(costs), 6),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "quality_mean": round(sum(qualities) / len(qualities), 4) if qualities else 0.0,
        "start": start,
        "end": end,
    }


def status_text(ok: bool) -> str:
    return "Trong ngưỡng" if ok else "Vượt ngưỡng"


def panel_html(title: str, unit: str, lines: list[tuple[str, str]], threshold: str, ok: bool) -> str:
    rows = "".join(
        f"<div class='metric'><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>"
        for label, value in lines
    )
    badge = "ok" if ok else "bad"
    return f"""
    <section class="panel">
      <header>
        <h2>{html.escape(title)}</h2>
        <span class="badge {badge}">{html.escape(status_text(ok))}</span>
      </header>
      {rows}
      <p class="meta">Đơn vị: {html.escape(unit)} · Ngưỡng: {html.escape(threshold)}</p>
    </section>
    """


def page(title: str, subtitle: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(title)}</title>
  <style>
    body {{ margin: 0; font-family: "Segoe UI", sans-serif; background: #f4f7fb; color: #142033; }}
    main {{ padding: 28px 32px 40px; }}
    h1 {{ margin: 0 0 6px; font-size: 28px; }}
    .sub {{ margin: 0 0 22px; color: #496079; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .panel, .card {{ background: white; border: 1px solid #d5e0ec; border-radius: 14px; padding: 16px 18px; }}
    .panel header, .card header {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; }}
    h2 {{ margin: 0; font-size: 18px; }}
    .metric {{ display: flex; justify-content: space-between; margin-top: 10px; font-size: 16px; }}
    .metric strong {{ font-size: 20px; }}
    .meta {{ color: #5c7090; margin: 12px 0 0; }}
    .badge {{ border-radius: 999px; padding: 4px 10px; font-size: 13px; font-weight: 700; }}
    .ok {{ background: #e5f6ea; color: #146c36; }}
    .bad {{ background: #fde8e8; color: #9f1239; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #0f172a; color: #e2e8f0; padding: 16px; border-radius: 12px; font-size: 14px; line-height: 1.45; }}
    table {{ width: 100%; border-collapse: collapse; }}
    td, th {{ text-align: left; padding: 8px 6px; border-bottom: 1px solid #e2e8f0; }}
    .bar {{ height: 18px; background: #dbe7f5; border-radius: 999px; overflow: hidden; }}
    .bar span {{ display: block; height: 100%; background: #1d4ed8; }}
  </style>
</head>
<body>
  <main>
    <h1>{html.escape(title)}</h1>
    <p class="sub">{subtitle}</p>
    {body}
  </main>
</body>
</html>
"""


def dashboard_page(config: dict, stats: dict) -> str:
    dashboard = config["dashboard"]
    data_window = f"{fmt_ts(stats['start'])} → {fmt_ts(stats['end'])}"
    subtitle = (
        f"Time range: {dashboard['time_range_minutes']} phút · refresh {dashboard['refresh_seconds']}s · "
        f"dữ liệu thực tế {data_window} · nguồn data/logs.jsonl"
    )
    panels = [
        panel_html(
            "Latency percentiles and TTFT",
            "ms",
            [
                ("P50 latency", f"{stats['latency_p50']:.0f}"),
                ("P95 latency", f"{stats['latency_p95']:.0f}"),
                ("P99 latency", f"{stats['latency_p99']:.0f}"),
                ("TTFT P95", f"{stats['ttft_p95']:.0f}"),
            ],
            "p95 latency ≤ 3000 ms",
            stats["latency_p95"] <= 3000,
        ),
        panel_html(
            "Request traffic",
            "requests_per_minute",
            [
                ("Request count", str(stats["received"])),
                ("Rate / phút", f"{stats['rate_per_minute']:.3f}"),
            ],
            "rate_per_minute ≥ 1",
            stats["rate_per_minute"] >= 1,
        ),
        panel_html(
            "Error rate and retrieval success",
            "percent",
            [
                ("Error rate", f"{stats['error_rate_pct']:.3f}%"),
                ("Retrieval success", f"{stats['retrieval_success_pct']:.3f}%"),
                ("Failed events", str(stats["failed"])),
                ("Error types", ", ".join(stats["error_breakdown"]) or "none"),
            ],
            "error_rate ≤ 2% · retrieval success ≥ 90%",
            stats["error_rate_pct"] <= 2 and stats["retrieval_success_pct"] >= 90,
        ),
        panel_html(
            "Cost over time",
            "usd",
            [("Total cost", f"{stats['cost_total']:.6f}")],
            "total ≤ 2.5 USD",
            stats["cost_total"] <= 2.5,
        ),
        panel_html(
            "Input and output tokens",
            "tokens",
            [
                ("tokens_in", str(stats["tokens_in"])),
                ("tokens_out", str(stats["tokens_out"])),
            ],
            "mỗi field ≤ 50000 tokens",
            stats["tokens_in"] <= 50000 and stats["tokens_out"] <= 50000,
        ),
        panel_html(
            "Quality proxy",
            "score_0_to_1",
            [("Mean quality", f"{stats['quality_mean']:.4f}")],
            "mean ≥ 0.75",
            stats["quality_mean"] >= 0.75,
        ),
    ]
    return page(dashboard["title"], subtitle, "<div class='grid'>" + "".join(panels) + "</div>")


def terminal_page(title: str, text: str) -> str:
    return page(title, "Output chạy trên commit làm việc", f"<pre>{html.escape(text)}</pre>")


def log_page(title: str, intro: str, record: dict) -> str:
    pretty = json.dumps(record, ensure_ascii=False, indent=2)
    return page(title, intro, f"<pre>{html.escape(pretty)}</pre>")


def incident_pages(baseline: dict, incident: dict, sample: dict | None) -> tuple[str, str, str]:
    rows = ""
    for label, before, after in (
        ("Latency P95 (ms)", f"{baseline['latency_p95']:.0f}", f"{incident['latency_p95']:.0f}"),
        ("TTFT P95 (ms)", f"{baseline['ttft_p95']:.0f}", f"{incident['ttft_p95']:.0f}"),
        ("Error rate %", f"{baseline['error_rate_pct']:.3f}", f"{incident['error_rate_pct']:.3f}"),
        ("Retrieval success %", f"{baseline['retrieval_success_pct']:.3f}", f"{incident['retrieval_success_pct']:.3f}"),
        ("Requests", str(baseline["received"]), str(incident["received"])),
    ):
        rows += f"<tr><td>{html.escape(label)}</td><td>{html.escape(before)}</td><td>{html.escape(after)}</td></tr>"
    window_text = f"Baseline {fmt_ts(baseline['start'])} → {fmt_ts(baseline['end'])}. Incident {fmt_ts(incident['start'])} → {fmt_ts(incident['end'])}."
    metric = page(
        "Incident metric — practice rag_slow",
        window_text + " Triệu chứng: latency P95 tăng vì retrieval bị làm chậm.",
        f"<div class='card'><table><tr><th>Chỉ số</th><th>Baseline</th><th>Sau rag_slow</th></tr>{rows}</table></div>",
    )
    if sample is None:
        empty = page("Incident log", "Không có response_sent trong cửa sổ incident.", "<p>Không có log.</p>")
        return metric, empty, empty
    log_view = log_page(
        "Incident log",
        f"event=response_sent · correlation_id={sample.get('correlation_id')} · latency_ms={sample.get('latency_ms')}",
        sample,
    )
    retrieval = int(sample.get("retrieval_ms") or 0)
    generation = int(sample.get("generation_ms") or 0)
    total = max(retrieval + generation, 1)
    bars = f"""
    <div class="card">
      <p>correlation_id <strong>{html.escape(str(sample.get('correlation_id')))}</strong></p>
      <p>retrieval {retrieval} ms</p>
      <div class="bar"><span style="width:{retrieval / total * 100:.1f}%"></span></div>
      <p>generation {generation} ms</p>
      <div class="bar"><span style="width:{generation / total * 100:.1f}%"></span></div>
      <p class="meta">Span timing đo trong process cho cùng correlation_id. Trang này không phải ảnh Langfuse.</p>
    </div>
    """
    span = page(
        "Incident span timing",
        "Bước retrieval chiếm gần như toàn bộ latency của request bị ảnh hưởng.",
        bars,
    )
    return metric, log_view, span


def pii_page(records: list[dict]) -> str:
    received = next(
        (
            record
            for record in records
            if record.get("event") == "request_received"
            and "REDACTED_" in json.dumps(record.get("payload", {}), ensure_ascii=False)
        ),
        None,
    )
    sample_input = (
        "Input giả từ data/sample_queries.jsonl:\n"
        "What is your refund policy? My email is student@vinuni.edu.vn\n"
        "Here is my phone 0987654321, what should be logged?\n"
        "What is the policy for PII and credit card 4111 1111 1111 1111?"
    )
    output = json.dumps(received, ensure_ascii=False, indent=2) if received else "Không tìm thấy preview đã redact."
    body = f"<pre>{html.escape(sample_input)}</pre><pre>{html.escape(output)}</pre>"
    return page(
        "PII redaction",
        "Input chứa PII giả. Log request_received chỉ còn preview đã scrub.",
        body,
    )


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def screenshot(html_dir: Path, name: str, destination: Path, width: int, height: int) -> None:
    import subprocess

    destination.parent.mkdir(parents=True, exist_ok=True)
    handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(  # noqa: E731
        *args, directory=str(html_dir), **kwargs
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    try:
        subprocess.run(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--force-device-scale-factor=1",
                f"--window-size={width},{height}",
                f"--screenshot={destination}",
                f"http://127.0.0.1:{port}/{name}",
            ],
            check=True,
            timeout=30,
        )
    finally:
        server.shutdown()


def pick_incident_sample(records: list[dict]) -> dict | None:
    sent = [record for record in records if record.get("event") == "response_sent"]
    if not sent:
        return None
    return max(sent, key=lambda record: int(record.get("latency_ms") or 0))


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs", type=Path, default=REPO_ROOT / "data" / "logs.jsonl")
    parser.add_argument("--dashboard", type=Path, default=REPO_ROOT / "config" / "dashboard.yaml")
    parser.add_argument("--evidence-dir", type=Path, default=REPO_ROOT / "submission" / "evidence")
    parser.add_argument("--html-dir", type=Path, default=Path("/tmp/day13-evidence"))
    parser.add_argument("--incident-start", default="")
    parser.add_argument("--pytest-output", type=Path)
    parser.add_argument("--log-validator-output", type=Path)
    parser.add_argument("--dashboard-validator-output", type=Path)
    parser.add_argument("--no-screenshot", action="store_true")
    args = parser.parse_args()

    config = yaml.safe_load(args.dashboard.read_text(encoding="utf-8"))
    records = load_logs(args.logs)
    visible = window(records, int(config["dashboard"]["time_range_minutes"]))
    stats = summarize(visible)
    incident_start = parse_ts(args.incident_start) if args.incident_start else None
    pages: dict[str, str] = {
        "11-dashboard-overview.html": dashboard_page(config, stats),
        "04-structured-log.html": log_page(
            "Structured log",
            "Một event response_sent đủ timestamp, correlation_id, model, env, feature và latency.",
            next(record for record in reversed(visible) if record.get("event") == "response_sent"),
        ),
        "05-pii-redaction.html": pii_page(visible),
    }
    summary = {"dashboard_window": stats_public(stats)}
    if incident_start is not None:
        before = [record for record in records if record.get("ts") and parse_ts(record["ts"]) < incident_start]
        after = [record for record in records if record.get("ts") and parse_ts(record["ts"]) >= incident_start]
        baseline_stats = summarize(before)
        incident_stats = summarize(after)
        sample = pick_incident_sample(after)
        metric, log_view, span = incident_pages(baseline_stats, incident_stats, sample)
        pages["12-incident-metric.html"] = metric
        pages["13-incident-log.html"] = log_view
        pages["14-incident-trace.html"] = span
        summary["baseline"] = stats_public(baseline_stats)
        summary["incident"] = stats_public(incident_stats)
        summary["incident_correlation_id"] = None if sample is None else sample.get("correlation_id")
        summary["incident_log"] = sample
    if args.pytest_output and args.pytest_output.exists():
        pages["01-pytest.html"] = terminal_page("Pytest", args.pytest_output.read_text(encoding="utf-8"))
    if args.log_validator_output and args.log_validator_output.exists():
        pages["02-log-validator.html"] = terminal_page(
            "Log validator", args.log_validator_output.read_text(encoding="utf-8")
        )
    if args.dashboard_validator_output and args.dashboard_validator_output.exists():
        pages["03-dashboard-validator.html"] = terminal_page(
            "Dashboard validator", args.dashboard_validator_output.read_text(encoding="utf-8")
        )

    args.html_dir.mkdir(parents=True, exist_ok=True)
    for name, content in pages.items():
        write(args.html_dir / name, content)
    write(args.evidence_dir / "metrics-summary.json", json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    if not args.no_screenshot:
        heights = {
            "11-dashboard-overview.html": 1280,
            "01-pytest.html": 900,
            "02-log-validator.html": 820,
            "03-dashboard-validator.html": 520,
            "04-structured-log.html": 980,
            "05-pii-redaction.html": 1100,
            "12-incident-metric.html": 760,
            "13-incident-log.html": 980,
            "14-incident-trace.html": 760,
        }
        for name in pages:
            png_name = name.replace(".html", ".png")
            screenshot(args.html_dir, name, args.evidence_dir / png_name, 1440, heights.get(name, 900))
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


def stats_public(stats: dict) -> dict:
    exported = dict(stats)
    exported["start"] = fmt_ts(stats["start"])
    exported["end"] = fmt_ts(stats["end"])
    return exported


if __name__ == "__main__":
    raise SystemExit(main())
