# SRT Stream Monitoring — POC Mediaventures

**Bachelorproef Observability voor Multi-Site Live-Streamingomgevingen**  
**Datum:** april 2026

---

## Overzicht

De observability stack bevat twee containers voor SRT-streamingmonitoring:

| Container | Functie |
|-----------|---------|
| `srt-exporter` | SRT-listener op UDP:9000, exporteert stream-statistieken als Prometheus-metrics |
| `srt-test-stream` | Synthetisch testsignaal via ffmpeg als SRT caller naar srt-exporter |

Deze setup simuleert een live productiescenario waarbij een SRT-encoder (bv. LiveU, vMix) een stream stuurt naar een ontvanger, en de ontvanger de statistieken rapporteert. In productie wordt de srt-exporter vervangen door de echte SRT-ontvanger.

---

## Architectuur

```
srt-test-stream (caller)           srt-exporter (listener)
  ffmpeg testsignaal                  srt-live-transmit
  -- SRT caller --> 127.0.0.1:9000 --> luistert op UDP:9000
                                       |
                                      CSV stats parsing
                                       |
                                  Prometheus metrics :9117
```

Beide containers draaien met `network_mode: host` — verkeer loopt via de **loopback interface (`lo`)**, niet via de Docker bridge.

---

## Geëxporteerde Metrics

| Metric | Eenheid | Beschrijving |
|--------|---------|--------------|
| `srt_stream_active` | bool (0/1) | Of er een actieve SRT-verbinding is |
| `srt_bitrate_kbps` | kbps | Gemeten bitrate van de stream |
| `srt_rtt_ms` | ms | Round-trip time op applicatielaag (SRT ARQ) |
| `srt_packet_loss_percent` | % | Percentage verloren pakketten na ARQ-herstel |
| `srt_jitter_ms` | ms | Aankomsttijdvariatie van pakketten |
| `srt_retransmit_rate` | ratio | Fractie pakketten die opnieuw verzonden werden |
| `srt_retransmit_total` | count | Cumulatief aantal retransmissions (reset bij herstart) |

**Label:** alle metrics hebben het label `stream_name` (standaard: `test`).

### Typische waarden (baseline zonder storingen)
- `srt_stream_active` = 1
- `srt_bitrate_kbps` ~ 1695 kbps
- `srt_rtt_ms` ~ 1.2 ms (loopback)
- `srt_packet_loss_percent` = 0%
- `srt_jitter_ms` ~ 0.1 ms

---

## Prometheus Configuratie

In `prometheus.yml`:

```yaml
- job_name: 'srt_exporter'
  scrape_interval: 15s
  static_configs:
    - targets: ['10.1.1.100:9117']
```

---

## Grafana Dashboard — Sectie 11

Het hoofddashboard bevat sectie **11. SRT Stream Kwaliteit** met de volgende panels:

| Panel | Type | Query |
|-------|------|-------|
| Stream Active | stat | `srt_stream_active{stream_name=~".*"}` |
| Bitrate (kbps) | gauge | `srt_bitrate_kbps{stream_name=~".*"}` |
| Packet Loss (%) | gauge | `srt_packet_loss_percent{stream_name=~".*"}` |
| RTT (ms) | gauge | `srt_rtt_ms{stream_name=~".*"}` |
| RTT & Jitter over tijd | timeseries | `srt_rtt_ms` + `srt_jitter_ms` |
| Packet Loss (%) over tijd | timeseries | `srt_packet_loss_percent` |
| Retransmit Rate over tijd | timeseries | `srt_retransmit_rate` |
| **Cross-layer RTT** | timeseries | `srt_rtt_ms` + `probe_icmp_duration_seconds * 1000` |

Het cross-layer RTT-panel (toegevoegd op 14 april 2026) toont zowel de SRT-applicatielaag RTT (oranje) als de ICMP-netwerklaag RTT per site (blauw). Gelijktijdige pieken in beide signalen bevestigen dat een netwerkverstoring ook de stream beïnvloedt.

---

## Alert Rule

Een dedicated alertregel bewaakt de SRT-streamkwaliteit:

```yaml
uid: alert-srt-packetloss
title: "[WARNING] SRT Stream Packet Loss"
expr: srt_packet_loss_percent{stream_name=~".*"} > 5
for: 1m
severity: warning
```

De drempel van 5% en de wachttijd van 1 minuut zijn afgestemd op live-streaming context. SRT ARQ herstelt korte verliesbarstes (<5%) automatisch; pas bij aanhoudend verlies degradeert de kijkerservaring merkbaar.

---

## Testscenario's (tc netem)

SRT-specifieke testscenario's worden uitgevoerd via `tc netem` op de loopback-interface. Zie `testscenarios.md` sectie 4 voor de volledige stap-voor-stap uitleg.

### tc netem toepassen op SRT (loopback)

Omdat beide containers `network_mode: host` gebruiken, loopt SRT-verkeer via `lo`:

```bash
# Activeer 30% packet loss op UDP:9000
sudo tc qdisc del dev lo root 2>/dev/null
sudo tc qdisc add dev lo root handle 1: prio priomap 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
sudo tc qdisc add dev lo parent 1:3 handle 30: netem loss 30%
sudo tc filter add dev lo protocol ip parent 1:0 prio 3 u32 match ip dport 9000 0xffff flowid 1:3

# Verwijder tc rule
sudo tc qdisc del dev lo root

# Reset SRT stats (cumulatief)
docker compose restart srt-test-stream
```

### Scenario 4a — Packet Loss (30% netem — ~5-10% gemeten)

Vanwege SRT ARQ (Automatic Repeat Request) herstelt de stack een deel van de verloren pakketten. 30% netem loss resulteert slechts in 4-10% gemeten `srt_packet_loss_percent`. Bij langdurige simulatie stijgt de loss progressief door ARQ-cascade: retransmissions zijn zelf ook onderhevig aan de netem-regel, waardoor ze opnieuw verloren gaan.

**Gemeten time-to-detect (14 april 2026):**
- T0 (19:47:51): tc netem actief
- T+31s: Prometheus meet eerste scrape met loss > 5%
- T+118s (19:49:49): Grafana alert gefired (after `for: 1m` + groepsevaluatie 1m)
- **Totale time-to-detect: ~2 minuten (gemeten T+118s)**

### Scenario 4b — Hoge Latency (100ms delay)

100ms delay benadert de SRT latency buffer (~120ms). Pakketten die buiten de buffer aankomen worden als verloren beschouwd, wat ~35% `srt_packet_loss_percent` veroorzaakt — zelfs zonder echte pakketverlies op het netwerk. Dit toont aan dat latency-monitoring op beide lagen (ICMP én SRT) noodzakelijk is.

---

## Productie-integratie

In een echte Mediaventures-omgeving vervangt de `srt-exporter` de teststream-ontvanger:

1. Configureer de SRT-encoder (vMix/LiveU) als **caller** richting obs VM poort 9000
2. `srt-exporter` draait als **listener** en ontvangt de productiestream
3. Dezelfde metrics worden geëxporteerd — zelfde Grafana dashboard, zelfde alert rules

De testomgeving bewijst daarmee dat de monitoringlogica schaalbaar is naar productie zonder aanpassingen aan de Prometheus/Grafana configuratie.
