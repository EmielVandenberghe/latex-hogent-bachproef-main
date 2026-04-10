#!/usr/bin/env python3
"""
Ping Jitter Exporter — Bachelorproef Mediaventures
Voert 'ping -c 10 -i 0.2' uit per site en exposed min/avg/max/mdev als Prometheus metrics.
Scrape interval: elke 30s (ping duurt ~2s per site).
"""

import subprocess
import re
import time
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

SITES = {
    "Bornem":     "10.1.1.2",
    "Venue":      "10.1.2.2",
    "Live1":      "10.1.3.2",
    "Live2":      "10.1.4.2",
    "Balance20X": "192.168.1.1",
}

# Opgeslagen meetresultaten (gedeeld geheugen)
latest_metrics: dict[str, dict] = {}


def ping_site(site: str, ip: str) -> dict:
    """Voer ping uit en parse de statistieken. Geeft dict terug met min/avg/max/mdev en loss."""
    try:
        result = subprocess.run(
            ["ping", "-c", "20", "-i", "0.2", "-W", "2", ip],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout
        # Parse packet loss: "10 packets transmitted, 8 received, 20% packet loss"
        loss_match = re.search(r"(\d+)% packet loss", output)
        loss_pct = float(loss_match.group(1)) if loss_match else 100.0

        # Parse rtt stats: "rtt min/avg/max/mdev = 0.312/0.512/0.891/0.172 ms"
        rtt_match = re.search(
            r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms",
            output,
        )
        if rtt_match:
            rtt_min, rtt_avg, rtt_max, rtt_mdev = (float(x) for x in rtt_match.groups())
            reachable = 1
        else:
            rtt_min = rtt_avg = rtt_max = rtt_mdev = 0.0
            reachable = 0 if loss_pct == 100.0 else 1

        log.info(
            "%-6s  loss=%.0f%%  rtt min/avg/max/mdev = %.2f/%.2f/%.2f/%.2f ms",
            site, loss_pct, rtt_min, rtt_avg, rtt_max, rtt_mdev,
        )
        return {
            "reachable": reachable,
            "loss_pct": loss_pct,
            "rtt_min": rtt_min,
            "rtt_avg": rtt_avg,
            "rtt_max": rtt_max,
            "jitter": rtt_mdev,
        }
    except subprocess.TimeoutExpired:
        log.warning("Ping timeout voor %s (%s)", site, ip)
        return {"reachable": 0, "loss_pct": 100.0, "rtt_min": 0.0, "rtt_avg": 0.0, "rtt_max": 0.0, "jitter": 0.0}
    except Exception as exc:
        log.error("Ping fout voor %s: %s", site, exc)
        return {"reachable": 0, "loss_pct": 100.0, "rtt_min": 0.0, "rtt_avg": 0.0, "rtt_max": 0.0, "jitter": 0.0}


def collect_all():
    """Ping alle sites en sla resultaten op."""
    for site, ip in SITES.items():
        latest_metrics[site] = ping_site(site, ip)


def build_prometheus_output() -> str:
    lines = []

    lines.append('# HELP ping_reachable Host bereikbaar via ICMP (1=ja, 0=nee)')
    lines.append('# TYPE ping_reachable gauge')
    for site, m in latest_metrics.items():
        lines.append(f'ping_reachable{{site="{site}"}} {m["reachable"]}')

    lines.append('# HELP ping_packet_loss_percent Packet loss percentage (0-100)')
    lines.append('# TYPE ping_packet_loss_percent gauge')
    for site, m in latest_metrics.items():
        lines.append(f'ping_packet_loss_percent{{site="{site}"}} {m["loss_pct"]}')

    lines.append('# HELP ping_rtt_min_ms Minimale RTT in milliseconden')
    lines.append('# TYPE ping_rtt_min_ms gauge')
    for site, m in latest_metrics.items():
        lines.append(f'ping_rtt_min_ms{{site="{site}"}} {m["rtt_min"]}')

    lines.append('# HELP ping_rtt_avg_ms Gemiddelde RTT in milliseconden')
    lines.append('# TYPE ping_rtt_avg_ms gauge')
    for site, m in latest_metrics.items():
        lines.append(f'ping_rtt_avg_ms{{site="{site}"}} {m["rtt_avg"]}')

    lines.append('# HELP ping_rtt_max_ms Maximale RTT in milliseconden')
    lines.append('# TYPE ping_rtt_max_ms gauge')
    for site, m in latest_metrics.items():
        lines.append(f'ping_rtt_max_ms{{site="{site}"}} {m["rtt_max"]}')

    lines.append('# HELP ping_jitter_ms Jitter (mdev van RTT) in milliseconden — echte ping jitter')
    lines.append('# TYPE ping_jitter_ms gauge')
    for site, m in latest_metrics.items():
        lines.append(f'ping_jitter_ms{{site="{site}"}} {m["jitter"]}')

    return "\n".join(lines) + "\n"


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            body = build_prometheus_output().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass  # Geen HTTP access logs in stdout


def background_collector(interval: int = 30):
    """Loop die elke `interval` seconden alle sites pingt."""
    while True:
        try:
            collect_all()
        except Exception as exc:
            log.error("Collectie fout: %s", exc)
        time.sleep(interval)


if __name__ == "__main__":
    import threading

    # Eerste meting direct bij opstart
    log.info("Ping Exporter gestart — eerste meting...")
    collect_all()

    # Achtergrond collector thread
    t = threading.Thread(target=background_collector, args=(30,), daemon=True)
    t.start()

    # HTTP server op poort 9116
    server = HTTPServer(("0.0.0.0", 9116), MetricsHandler)
    log.info("Metrics beschikbaar op http://0.0.0.0:9116/metrics")
    server.serve_forever()
