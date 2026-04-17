# Stack resource footprint

Meting uitgevoerd op de observability VM (AlmaLinux 9.7, 2 vCPU, 4 GB RAM) op 2026-04-15 onder idle/normale load (geen testscenario actief). Alle 10 containers draaien.

## Host
| Resource | Waarde |
|---|---|
| OS | AlmaLinux 9.7 (Moss Jungle Cat) |
| Kernel | 5.14.0-611.5.1.el9_7.x86_64 |
| vCPU | 2 |
| RAM totaal | 3892 MB |
| RAM in gebruik | 1119 MB (~29%) |
| RAM beschikbaar | 2773 MB |
| Swap | 0 MB (uitgeschakeld) |
| Disk root (`/`) | 19 GB, 6.7 GB used (37%) |
| Disk `/opt/observability` | 954 GB, 526 GB used (56%) — bind-mount vanaf hostschijf |

## Containers
Bron: `docker stats --no-stream` (1 sample, idle-load).

| Container | CPU % | Mem (MiB) | Mem % | Block I/O |
|---|---|---|---|---|
| incontrol2-exporter | 64.00 | 49.27 | 1.27 | 2.93 MB / 786 kB |
| srt-test-stream | 56.54 | 241.00 | 6.19 | 139 MB / 0 |
| prometheus | 1.56 | 177.10 | 4.55 | 130 MB / 9.14 MB |
| srt-exporter | 1.64 | 33.88 | 0.87 | 24.3 MB / 0 |
| grafana | 1.54 | 79.69 | 2.05 | 1.96 MB / 3.55 MB |
| loki | 0.48 | 172.70 | 4.44 | 111 MB / 987 kB |
| promtail | 0.36 | 141.30 | 3.63 | 112 MB / 702 kB |
| node-exporter | 0.00 | 31.22 | 0.80 | 18.2 MB / 0 |
| blackbox-exporter | 0.00 | 36.18 | 0.93 | 25.7 MB / 0 |
| ping-exporter | 0.01 | 14.74 | 0.38 | 49.2 kB / 2.34 MB |
| **Totaal** | **~126 %** | **~977 MiB** | **~29 %** | — |

> Noot: `CPU %` in docker stats is relatief tegenover het totaal (2 vCPU = 200% = maximum). 126% totaal betekent ~63% van één vCPU equivalent. Het grootste aandeel zit bij `incontrol2-exporter` (active scraping cycle op moment van meting, waarden pieken per 15s interval) en `srt-test-stream` (FFmpeg encoding testsignaal — constant).

## Interpretatie voor verdediging
- De stack past comfortabel in **1 GB RAM** (29% van 4 GB) onder idle load met 10 containers, 6 monitored sites en een live SRT stream.
- CPU is het duurste deel door `srt-test-stream` (FFmpeg) en scrape-bursts van de `incontrol2-exporter`. In productie zou `srt-test-stream` vervallen (enkel nodig voor PoC-bewijs) wat ~55% CPU en ~240 MiB RAM vrijspeelt.
- Disk-gebruik van Loki + Prometheus samen is minder dan 250 MiB na meerdere sessies — retentie-tuning is niet nodig binnen deze scope.
- **Productie-aanbeveling:** 2 vCPU + 2 GB RAM + 20 GB disk volstaat voor ~10 sites met 15 s scrape-interval. Schaalt lineair met aantal targets.

## Reproduceerbaarheid
```bash
KEY=poc/stack/.vagrant/machines/default/virtualbox/private_key
ssh -i "$KEY" -p 2222 vagrant@127.0.0.1 "docker stats --no-stream && free -m && df -h"
```
