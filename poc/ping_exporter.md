# Ping-Jitter Exporter — Nauwkeurige Jittermeting

**Bachelorproef Mediaventures Observability POC — maart 2026**

---

## Waarom een aparte jitter exporter?

De Prometheus blackbox exporter stuurt 1 ICMP ping per 15 seconden. Jitter berekend als `stddev_over_time(rtt[5m])` is slechts een benadering: het meet de variatie van losse meetpunten over 5 minuten, niet de echte pakket-naar-pakket variatie.

De **ping-jitter exporter** voert `ping -c 10 -i 0.2` uit: 10 snelle pings met 0.2s tussentijd. Dit geeft de `mdev` (mean deviation) die `ping` zelf berekent — dit is de echte jitter, conform hoe netwerktechnici jitter definiëren voor streaming.

| Methode | Formule | Nauwkeurigheid |
|---------|---------|---------------|
| Blackbox stddev | `stddev_over_time(rtt[5m])` | Lage nauwkeurigheid — meet RTT-trend-variatie |
| Ping mdev (deze exporter) | `ping -c 10 -i 0.2` → mdev | Hoge nauwkeurigheid — meet pakket-naar-pakket variatie |

---

## Architectuur

```
[ping_exporter container — network_mode: host]
    |
    | ping -c 10 -i 0.2 <ip>    (elke 30s, per site)
    |
    +---> 10.1.1.2 (Bornem)
    +---> 10.1.2.2 (Venue)
    +---> 10.1.3.2 (Live1)
    +---> 10.1.4.2 (Live2)
    |
    ↓
HTTP :9116/metrics
    ↑
[Prometheus scrape elke 30s]
```

---

## Configuratiebestanden

### `poc/stack/ping_exporter.py`
Python script dat per site `ping -c 10 -i 0.2 <ip>` uitvoert, de output parseert en Prometheus metrics exposed op poort 9116.

### `poc/stack/Dockerfile.ping`
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends iputils-ping
WORKDIR /app
COPY ping_exporter.py .
EXPOSE 9116
CMD ["python", "-u", "ping_exporter.py"]
```

### `poc/stack/docker-compose.yml` — relevante sectie
```yaml
ping-exporter:
  build:
    context: .
    dockerfile: Dockerfile.ping
  container_name: ping-exporter
  restart: unless-stopped
  network_mode: host
  cap_add:
    - NET_RAW
```

> `cap_add: NET_RAW` is vereist voor raw socket access (ICMP ping) in een Docker container.

### `poc/stack/prometheus.yml` — relevante sectie
```yaml
- job_name: 'ping_jitter'
  static_configs:
    - targets: ['10.1.1.100:9116']
  scrape_interval: 30s
  scrape_timeout: 25s
```

> Scrape interval 30s: ping duurt ~2s per site × 4 sites = ~8s. 30s geeft voldoende buffer.

---

## Verzamelde metrics

| Metric | Eenheid | Beschrijving |
|--------|---------|-------------|
| `ping_reachable{site="..."}` | 0/1 | Host bereikbaar via ICMP |
| `ping_packet_loss_percent{site="..."}` | % | Packet loss van 10 pings |
| `ping_rtt_min_ms{site="..."}` | ms | Minimale RTT van 10 pings |
| `ping_rtt_avg_ms{site="..."}` | ms | Gemiddelde RTT van 10 pings |
| `ping_rtt_max_ms{site="..."}` | ms | Maximale RTT van 10 pings |
| `ping_jitter_ms{site="..."}` | ms | **Jitter = mdev van 10 pings** |

### Voorbeeld ping output
```
PING 10.1.1.2 (10.1.1.2) 56(84) bytes of data.
64 bytes from 10.1.1.2: icmp_seq=1 ttl=64 time=0.312 ms
...
--- 10.1.1.2 ping statistics ---
10 packets transmitted, 10 received, 0% packet loss, time 1815ms
rtt min/avg/max/mdev = 0.287/0.412/0.891/0.172 ms
```

De exporter leest: `min=0.287`, `avg=0.412`, `max=0.891`, `jitter=0.172`.

---

## Drempelwaarden voor AV-productie

| Metric | Groen | Geel | Rood |
|--------|-------|------|------|
| Jitter | < 5ms | 5–20ms | > 20ms |
| RTT gemiddeld | < 50ms | 50–150ms | > 150ms |
| Packet loss | 0% | < 1% | > 5% |

---

## Grafana dashboard

Het dashboard gebruikt `ping_jitter_ms` op twee plaatsen in sectie 2 (Connectiviteit & Netwerkkwaliteit):
- **4 stat panels** — huidige jitter per site (kleurcodering groen/geel/rood)
- **Tijdreeks panel** — jitter historiek voor alle sites over tijd

---

## Handmatig testen

```bash
# Metrics opvragen
curl http://10.1.1.100:9116/metrics

# Container logs bekijken
docker logs ping-exporter -f

# Verwachte output
ping_reachable{site="Bornem"} 1
ping_packet_loss_percent{site="Bornem"} 0
ping_rtt_min_ms{site="Bornem"} 0.287
ping_rtt_avg_ms{site="Bornem"} 0.412
ping_rtt_max_ms{site="Bornem"} 0.891
ping_jitter_ms{site="Bornem"} 0.172
```

---

## Troubleshooting

| Probleem | Oplossing |
|----------|-----------|
| `ping_reachable = 0` voor alle sites | Controleer `network_mode: host` en `cap_add: NET_RAW` in docker-compose.yml |
| Container crasht bij opstart | Controleer of `iputils-ping` geïnstalleerd is: `docker exec ping-exporter ping -V` |
| `No data` in Grafana | Prometheus scrape interval is 30s — even wachten na (her)start |
| Jitter altijd 0.000ms | Alle 10 pings identieke RTT (VM loopback?). Normaal op lokale VM-naar-VM, zie waarden bij tc netem simulatie |
