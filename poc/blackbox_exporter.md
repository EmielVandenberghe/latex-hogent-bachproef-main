# Blackbox Exporter — Latency, Packet Loss & Jitter via ICMP

**Bachelorproef Mediaventures Observability POC — maart 2026**

---

## Wat is de blackbox exporter?

De Prometheus [blackbox exporter](https://github.com/prometheus/blackbox_exporter) voert actieve probes uit naar externe endpoints. In dit POC gebruiken we ICMP (ping) probes om de netwerkkwaliteit tussen de observability-VM en elke FusionHub site te meten.

Dit is **synthetic monitoring**: de observability-stack initieert zelf meetverkeer, in tegenstelling tot passieve monitoring waarbij je wacht op data van de apparaten.

---

## Waarom blackbox exporter voor dit POC?

De InControl2 API en SNMP op FusionHub leveren geen latency, jitter of packet loss data terug. Dit is een bekende beperking van FusionHub (virtuele appliance):

| Metric | InControl2 API | SNMP op FusionHub | Blackbox Exporter |
|--------|---------------|-------------------|-------------------|
| Latency (RTT) | ❌ | ❌ | ✅ |
| Packet Loss | ❌ | ❌ | ✅ |
| Jitter | ❌ | ❌ | ✅ (berekend) |
| Tunnel Up/Down | ✅ | ❌ | ❌ |
| Bandwidth | ✅ | ✅ | ❌ |

> **Opmerking voor productie:** Fysieke Peplink-routers (20X, 380X) bieden via de lokale device API wél latency en jitter per SpeedFusion tunnel. De blackbox exporter is een universele aanvulling die onafhankelijk werkt van het routermerk.

---

## Architectuur

```
[Observability VM 10.1.1.100]
    |
    | ICMP probe elke 15s
    |
    +---> 10.1.1.2 (Bornem)    → via intnet-bornem (direct)
    +---> 10.1.2.2 (Venue)     → via VyOS routing
    +---> 10.1.3.2 (Live1)     → via VyOS routing
    +---> 10.1.4.2 (Live2)     → via VyOS routing
```

De blackbox exporter draait als Docker container met `network_mode: host` zodat hij de FusionHub IPs kan bereiken via de VM's netwerk stack.

---

## Configuratiebestanden

### `poc/stack/blackbox.yml`
```yaml
modules:
  icmp:
    prober: icmp
    timeout: 5s
    icmp:
      preferred_ip_protocol: ip4
```

### `poc/stack/prometheus.yml` — relevante sectie
```yaml
- job_name: 'blackbox_icmp'
  metrics_path: /probe
  params:
    module: [icmp]
  static_configs:
    - targets: ['10.1.1.2']
      labels:
        site: 'Bornem'
    - targets: ['10.1.2.2']
      labels:
        site: 'Venue'
    - targets: ['10.1.3.2']
      labels:
        site: 'Live1'
    - targets: ['10.1.4.2']
      labels:
        site: 'Live2'
  relabel_configs:
    - source_labels: [__address__]
      target_label: __param_target
    - source_labels: [__param_target]
      target_label: instance
    - target_label: __address__
      replacement: 10.1.1.100:9115
```

---

## Verzamelde metrics

| Metric | Eenheid | Beschrijving |
|--------|---------|-------------|
| `probe_success{site="..."}` | 0/1 | Probe geslaagd (1) of mislukt (0) |
| `probe_icmp_duration_seconds{phase="rtt"}` | seconden | Round-trip time van de ICMP ping |
| `probe_duration_seconds` | seconden | Totale duur van de probe |
| `probe_icmp_reply_hop_limit` | hops | TTL van het ontvangen antwoord |

### Berekende metrics (PromQL in dashboard)

| Wat | PromQL expressie |
|-----|-----------------|
| RTT in ms | `probe_icmp_duration_seconds{phase="rtt"} * 1000` |
| Packet loss % | `(1 - avg_over_time(probe_success[5m])) * 100` |

> **Jitter:** Zie `ping_exporter.md` — de ping-jitter exporter geeft nauwkeurigere jitter via `ping -c 10 -i 0.2`. In het Grafana dashboard wordt `ping_jitter_ms` gebruikt.

---

## Relatie met Ping-Jitter Exporter

De blackbox exporter is ideaal voor het meten van **bereikbaarheid, RTT en packet loss**. Voor jitter is een aparte exporter gebouwd (`ping_exporter.py`) die 10 snelle pings stuurt en de `mdev` (mean deviation) rapporteert — dit is de echte jitter zoals ook `ping` zelf dat weergeeft.

| Metric | Blackbox Exporter | Ping-Jitter Exporter |
|--------|------------------|---------------------|
| Bereikbaarheid (probe_success) | ✅ | ✅ (ping_reachable) |
| RTT gemiddeld | ✅ | ✅ (ping_rtt_avg_ms) |
| RTT min/max | ❌ | ✅ |
| Packet loss | ✅ (over tijdvenster) | ✅ (per 10 pings) |
| Jitter (mdev) | ❌ (benadering via stddev) | ✅ (echte mdev) |

---

## Drempelwaarden voor AV-productie

Op basis van de Mediaventures use case (live surgery streaming):

| Metric | Groen | Geel | Rood |
|--------|-------|------|------|
| RTT | < 50ms | 50–150ms | > 150ms |
| Packet Loss | 0% | < 1% | > 5% |
| Jitter | < 5ms | 5–20ms | > 20ms |

SRT heeft ingebouwde herstelcapaciteit via retransmissie, maar bij packet loss > 5% of latency > 200ms kunnen zichtbare artifacts optreden.

---

## Handmatig testen

Vanuit de observability VM:
```bash
curl "http://localhost:9115/probe?target=10.1.1.2&module=icmp"
```

Output bevat:
```
probe_success 1
probe_icmp_duration_seconds{phase="rtt"} 0.000596
probe_duration_seconds 0.000785
```

---

## Troubleshooting

| Probleem | Oplossing |
|----------|-----------|
| `probe_success = 0` voor alle sites | Controleer of `network_mode: host` actief is in docker-compose.yml |
| `probe_success = 0` voor één site | FusionHub VM mogelijk uitgeschakeld of ICMP geblokkeerd |
| Blackbox target DOWN in Prometheus | Controleer of `10.1.1.100:9115` bereikbaar is (`curl http://10.1.1.100:9115/metrics`) |
| Geen `site` label in Grafana | Prometheus relabeling niet correct — check prometheus.yml `site` label definitie |
