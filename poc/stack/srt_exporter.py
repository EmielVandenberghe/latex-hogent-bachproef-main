#!/usr/bin/env python3
"""
SRT Exporter — Bachelorproef Mediaventures
Draait srt-live-transmit als SRT listener, parsed de CSV stats output,
en exposed metrics op http://0.0.0.0:9117/metrics.
"""
import subprocess
import threading
import time
import os
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

SRT_PORT = int(os.environ.get("SRT_LISTEN_PORT", "9000"))
EXPORTER_PORT = int(os.environ.get("EXPORTER_PORT", "9117"))

_metrics = {
    "active": 0, "bitrate_kbps": 0.0, "rtt_ms": 0.0,
    "packet_loss_pct": 0.0, "jitter_ms": 0.0, "retransmit_rate": 0.0,
    "retransmit_total": 0.0,
}
_lock = threading.Lock()


def parse_csv_stats(header: list[str], values: list[str]) -> dict | None:
    """Parse a CSV stats line using the header row for column lookup."""
    if len(header) != len(values):
        return None

    col = dict(zip(header, values))

    def get(key):
        try:
            return float(col.get(key, 0))
        except (ValueError, TypeError):
            return 0.0

    recv_rate = get("mbpsRecvRate")
    rtt = get("msRTT")
    recv_total = get("pktRecv")
    loss_total = get("pktRcvLoss")
    rcv_buf = get("msRcvBuf")
    retrans = get("pktRetrans") + get("pktRcvRetrans")
    loss_pct = (loss_total / recv_total * 100.0) if recv_total > 0 else 0.0

    return {
        "active": 1,
        "bitrate_kbps": round(recv_rate * 1000, 2),
        "rtt_ms": round(rtt, 2),
        "packet_loss_pct": round(loss_pct, 4),
        "jitter_ms": round(rcv_buf, 2),
        "retransmit_rate": round((loss_total / recv_total) if recv_total > 0 else 0.0, 6),
        "retransmit_total": retrans,
    }


def srt_receiver_loop():
    while True:
        log.info("Starting SRT listener on port %d", SRT_PORT)
        csv_header = None
        first_stats = True
        try:
            proc = subprocess.Popen(
                [
                    "stdbuf", "-oL",
                    "srt-live-transmit",
                    f"srt://:{SRT_PORT}?mode=listener",
                    "udp://127.0.0.1:19999",
                    "-s", "1000",
                    "-f",
                    "-pf", "csv",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            log.info("srt-live-transmit started (PID %s)", proc.pid)
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue

                # CSV header line starts with column names
                if line.startswith("Timepoint,") or line.startswith("Time,"):
                    csv_header = line.split(",")
                    log.info("CSV header: %d columns", len(csv_header))
                    continue

                # CSV data lines start with a timestamp (2026-...)
                if csv_header and line[0:2] == "20":
                    values = line.split(",")
                    stats = parse_csv_stats(csv_header, values)
                    if stats:
                        if first_stats:
                            log.info("First SRT stats: bitrate=%.1f kbps, RTT=%.2f ms, loss=%.4f%%",
                                     stats["bitrate_kbps"], stats["rtt_ms"], stats["packet_loss_pct"])
                            first_stats = False
                        with _lock:
                            _metrics.update(stats)
                    continue

                # Log non-stats lines (connection events etc.)
                if "connect" in line.lower() or "accept" in line.lower() or "disconnect" in line.lower():
                    log.info("SRT event: %s", line)

            proc.wait()
        except Exception as e:
            log.error("SRT receiver error: %s", e)
        log.info("SRT stream ended, resetting metrics")
        with _lock:
            _metrics.update({
                "active": 0, "bitrate_kbps": 0.0, "rtt_ms": 0.0,
                "packet_loss_pct": 0.0, "jitter_ms": 0.0, "retransmit_rate": 0.0,
                "retransmit_total": 0.0,
            })
        time.sleep(2)


def build_prometheus_output() -> str:
    lines = []
    with _lock:
        m = dict(_metrics)
    defs = [
        ("srt_stream_active", "gauge", "1 if SRT stream is active, 0 otherwise", m["active"]),
        ("srt_bitrate_kbps", "gauge", "SRT receive bitrate in kilobits per second", m["bitrate_kbps"]),
        ("srt_rtt_ms", "gauge", "Round-trip time in milliseconds", m["rtt_ms"]),
        ("srt_packet_loss_percent", "gauge", "Packet loss percentage", m["packet_loss_pct"]),
        ("srt_jitter_ms", "gauge", "Receive buffer delay in milliseconds", m["jitter_ms"]),
        ("srt_retransmit_rate", "gauge", "Ratio of lost to received packets", m["retransmit_rate"]),
        ("srt_retransmit_total", "counter", "Total retransmitted packets", m["retransmit_total"]),
    ]
    for name, kind, help_text, value in defs:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
        lines.append(f'{name}{{stream_name="test_stream"}} {value}')
    return "\n".join(lines) + "\n"


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/metrics", "/metrics/"):
            body = build_prometheus_output().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(302)
            self.send_header("Location", "/metrics")
            self.end_headers()

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    log.info("SRT Exporter gestart — poort %d", EXPORTER_PORT)
    t = threading.Thread(target=srt_receiver_loop, daemon=True)
    t.start()
    server = HTTPServer(("0.0.0.0", EXPORTER_PORT), MetricsHandler)
    log.info("Metrics beschikbaar op http://0.0.0.0:%d/metrics", EXPORTER_PORT)
    server.serve_forever()
