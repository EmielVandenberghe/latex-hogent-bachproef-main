#!/usr/bin/env python3
"""
srt_exporter.py — Prometheus exporter for SRT stream metrics
Exposes metrics on http://0.0.0.0:9117/metrics
Consistent with ping_exporter.py style.
"""

import socket
import struct
import threading
import time
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    import srt as libsrt
    SRT_AVAILABLE = True
except ImportError:
    SRT_AVAILABLE = False

# ─── Configuration ────────────────────────────────────────────────────────────

STREAMS = {
    "test_stream": {
        "host": "0.0.0.0",
        "port": int(os.environ.get("SRT_LISTEN_PORT", "9000")),
    },
}

EXPORTER_PORT  = int(os.environ.get("EXPORTER_PORT", "9117"))
COLLECT_INTERVAL = 5   # seconds between stat refreshes

# ─── Shared state ─────────────────────────────────────────────────────────────

# Per stream_name → dict of latest metric values
_metrics: dict[str, dict] = {}
_metrics_lock = threading.Lock()

_METRIC_DEFAULTS = {
    "active":           0,
    "bitrate_kbps":     0.0,
    "rtt_ms":           0.0,
    "packet_loss_pct":  0.0,
    "jitter_ms":        0.0,
    "retransmit_rate":  0.0,
}

def _init_stream(name: str) -> None:
    with _metrics_lock:
        if name not in _metrics:
            _metrics[name] = dict(_METRIC_DEFAULTS)

for name in STREAMS:
    _init_stream(name)

# ─── SRT helpers ──────────────────────────────────────────────────────────────

def _parse_srt_stats(perf) -> dict:
    """
    Convert a libsrt CBytePerfMon / SRTStats object to our metric dict.
    Field names match the srt-python bindings (srt >= 0.1.8).
    """
    def safe(attr, default=0.0):
        try:
            return float(getattr(perf, attr, default))
        except Exception:
            return default

    mbps_recv = safe("mbpsRecvRate")          # Mbit/s
    kbps      = mbps_recv * 1000.0

    # pktRcvLossTotal / pktRecvTotal → loss %
    rcv_total = safe("pktRecvTotal")
    loss_total = safe("pktRcvLossTotal")
    loss_pct   = (loss_total / rcv_total * 100.0) if rcv_total > 0 else 0.0

    # retransmitted / received
    retrans    = safe("pktRetransTotal")
    retrans_rate = (retrans / rcv_total) if rcv_total > 0 else 0.0

    return {
        "active":          1,
        "bitrate_kbps":    round(kbps, 2),
        "rtt_ms":          round(safe("msRTT"), 2),
        "packet_loss_pct": round(loss_pct, 4),
        "jitter_ms":       round(safe("msRcvTsbPdDelay"), 2),
        "retransmit_rate": round(retrans_rate, 6),
    }

# ─── Collector thread (libsrt path) ───────────────────────────────────────────

def _collect_libsrt(name: str, cfg: dict) -> None:
    """
    Runs an SRT receiver in a dedicated thread using python-srt bindings.
    Reads stats every COLLECT_INTERVAL seconds while a sender is connected.
    Reconnects automatically on disconnect.
    """
    while True:
        try:
            sock = libsrt.socket()
            sock.setsockopt(libsrt.SRTO_RCVSYN, True)
            sock.bind((cfg["host"], cfg["port"]))
            sock.listen(1)
            conn, _addr = sock.accept()
            # Drain and stat loop
            buf = bytearray(1316)  # one TS packet
            while True:
                try:
                    conn.recv_into(buf)
                except libsrt.SRTError:
                    break
                perf = conn.bistats(clear=False)
                with _metrics_lock:
                    _metrics[name] = _parse_srt_stats(perf)
                time.sleep(COLLECT_INTERVAL)
            conn.close()
            sock.close()
        except Exception:
            pass
        with _metrics_lock:
            _metrics[name] = dict(_METRIC_DEFAULTS)
        time.sleep(2)

# ─── Fallback: raw UDP listener to detect activity ────────────────────────────
# Used when libsrt is not installed. Measures rough bitrate only.

class _UDPStats:
    def __init__(self):
        self.bytes_window: list[tuple[float, int]] = []
        self.lock = threading.Lock()

    def add(self, nbytes: int) -> None:
        now = time.monotonic()
        with self.lock:
            self.bytes_window.append((now, nbytes))
            # keep last 5 s
            cutoff = now - 5.0
            self.bytes_window = [(t, b) for t, b in self.bytes_window if t > cutoff]

    def bitrate_kbps(self) -> float:
        now = time.monotonic()
        with self.lock:
            cutoff = now - 5.0
            recent = [(t, b) for t, b in self.bytes_window if t > cutoff]
        if len(recent) < 2:
            return 0.0
        total_bytes = sum(b for _, b in recent)
        span = recent[-1][0] - recent[0][0]
        if span <= 0:
            return 0.0
        return round(total_bytes * 8 / span / 1000.0, 2)

    def is_active(self) -> bool:
        now = time.monotonic()
        with self.lock:
            return any(t > now - 3.0 for t, _ in self.bytes_window)


def _collect_udp_fallback(name: str, cfg: dict) -> None:
    """
    Listens on UDP (same port the SRT sender targets).
    SRT uses UDP underneath, so raw datagrams arrive even without libsrt.
    Only bitrate and active are meaningful here.
    """
    stats = _UDPStats()

    def _recv_loop():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((cfg["host"], cfg["port"]))
        sock.settimeout(2.0)
        while True:
            try:
                data, _ = sock.recvfrom(65535)
                stats.add(len(data))
            except socket.timeout:
                pass
            except Exception:
                time.sleep(1)

    t = threading.Thread(target=_recv_loop, daemon=True)
    t.start()

    while True:
        active = 1 if stats.is_active() else 0
        with _metrics_lock:
            _metrics[name] = {
                **_METRIC_DEFAULTS,
                "active":       active,
                "bitrate_kbps": stats.bitrate_kbps() if active else 0.0,
            }
        time.sleep(COLLECT_INTERVAL)


# ─── Prometheus output builder ────────────────────────────────────────────────

_METRIC_DEFS = [
    ("srt_stream_active",       "gauge",   "1 if SRT stream is active, 0 otherwise"),
    ("srt_bitrate_kbps",        "gauge",   "SRT receive bitrate in kilobits per second"),
    ("srt_rtt_ms",              "gauge",   "Round-trip time in milliseconds"),
    ("srt_packet_loss_percent", "gauge",   "Packet loss percentage"),
    ("srt_jitter_ms",           "gauge",   "Receive jitter / buffer delay in milliseconds"),
    ("srt_retransmit_rate",     "gauge",   "Ratio of retransmitted to received packets"),
]

_METRIC_KEYS = {
    "srt_stream_active":       "active",
    "srt_bitrate_kbps":        "bitrate_kbps",
    "srt_rtt_ms":              "rtt_ms",
    "srt_packet_loss_percent": "packet_loss_pct",
    "srt_jitter_ms":           "jitter_ms",
    "srt_retransmit_rate":     "retransmit_rate",
}


def build_prometheus_output() -> str:
    lines: list[str] = []
    snapshot: dict[str, dict] = {}
    with _metrics_lock:
        for name, data in _metrics.items():
            snapshot[name] = dict(data)

    for prom_name, kind, help_text in _METRIC_DEFS:
        lines.append(f"# HELP {prom_name} {help_text}")
        lines.append(f"# TYPE {prom_name} {kind}")
        key = _METRIC_KEYS[prom_name]
        for stream_name, data in snapshot.items():
            value = data.get(key, 0)
            lines.append(f'{prom_name}{{stream_name="{stream_name}"}} {value}')

    lines.append("")
    return "\n".join(lines)


# ─── HTTP handler ─────────────────────────────────────────────────────────────

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

    def log_message(self, fmt, *args):  # suppress access logs
        pass


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    collect_fn = _collect_libsrt if SRT_AVAILABLE else _collect_udp_fallback
    backend    = "python-srt" if SRT_AVAILABLE else "udp-fallback"
    print(f"[srt_exporter] backend={backend}")

    for name, cfg in STREAMS.items():
        t = threading.Thread(
            target=collect_fn,
            args=(name, cfg),
            daemon=True,
            name=f"collector-{name}",
        )
        t.start()
        print(f"[srt_exporter] listening on {cfg['host']}:{cfg['port']} for stream '{name}'")

    server = HTTPServer(("0.0.0.0", EXPORTER_PORT), MetricsHandler)
    print(f"[srt_exporter] metrics → http://0.0.0.0:{EXPORTER_PORT}/metrics")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[srt_exporter] shutting down")


if __name__ == "__main__":
    main()
