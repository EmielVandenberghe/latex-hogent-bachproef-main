# BirdDog Device Monitoring

## Architectuur

```
Grafana ←── Prometheus ←── birddog-exporter :9119
                                  │
                           HTTP REST API
                                  │
                         birddog-mock :8090
                       (of echte BirdDog :8080)
```

Beide containers draaien in de standaard Docker-bridge-netwerk en activeren via `--profile demo`.

## Containers

| Container | Poort | Functie |
|-----------|-------|---------|
| `birddog-mock` | 8090 | Flask server die BirdDog REST API 2.0 nabootst |
| `birddog-exporter` | 9119 | Scrapt de BirdDog API en exposed Prometheus-metrics |

## Geëxposeerde metrics

| Metric | Type | Beschrijving |
|--------|------|-------------|
| `birddog_device_online{device}` | gauge | 1 = REST API bereikbaar, 0 = offline |
| `birddog_operation_mode_encode{device}` | gauge | 1 als device in encode-modus staat |
| `birddog_operation_mode_decode{device}` | gauge | 1 als device in decode-modus staat |
| `birddog_decode_connected{device}` | gauge | 1 als een NDI-bron actief gedecoded wordt |
| `birddog_decode_fps{device}` | gauge | Huidig framerate van de NDI-bron |
| `birddog_decode_width{device}` | gauge | Framebreedte in pixels |
| `birddog_decode_height{device}` | gauge | Framehoogte in pixels |
| `birddog_decode_dropped_frames_total{device}` | counter | Cumulatief aantal gedropt frames |
| `birddog_ndi_sources_count{device}` | gauge | Aantal NDI-bronnen gevonden via `/list` |
| `birddog_scrape_errors_total{device}` | counter | Fouten per scrape-cyclus |
| `birddog_scrape_duration_seconds{device}` | gauge | Duur van de laatste scrape |

## Activeren op de obs VM

```bash
KEY="poc/stack/.vagrant/machines/default/virtualbox/private_key"

# 1. Bestanden uploaden
for f in birddog_mock.py birddog_exporter.py Dockerfile.birddog-mock Dockerfile.birddog-exporter add_birddog_panels.py docker-compose.yml prometheus.yml; do
  scp -i "$KEY" -P 2222 -o StrictHostKeyChecking=no -o PubkeyAcceptedKeyTypes=+ssh-rsa \
    "poc/stack/$f" vagrant@127.0.0.1:/opt/observability/
done

# Alerting uploaden
scp -i "$KEY" -P 2222 -o StrictHostKeyChecking=no -o PubkeyAcceptedKeyTypes=+ssh-rsa \
  poc/stack/provisioning/alerting/alerts.yml \
  vagrant@127.0.0.1:/opt/observability/provisioning/alerting/alerts.yml

# 2. Containers bouwen en starten (demo profile)
ssh -i "$KEY" -p 2222 -o StrictHostKeyChecking=no -o PubkeyAcceptedKeyTypes=+ssh-rsa \
  vagrant@127.0.0.1 "cd /opt/observability && docker compose --profile demo up -d --build birddog-mock birddog-exporter"

# 3. Dashboard-panels toevoegen
ssh -i "$KEY" -p 2222 -o StrictHostKeyChecking=no -o PubkeyAcceptedKeyTypes=+ssh-rsa \
  vagrant@127.0.0.1 "cd /opt/observability && python3 add_birddog_panels.py"

# 4. Prometheus herladen (nieuwe scrape-config)
ssh -i "$KEY" -p 2222 -o StrictHostKeyChecking=no -o PubkeyAcceptedKeyTypes=+ssh-rsa \
  vagrant@127.0.0.1 "curl -s -X POST http://localhost:9090/-/reload"

# 5. Grafana herstarten (nieuwe dashboard + alerting provisioning)
ssh -i "$KEY" -p 2222 -o StrictHostKeyChecking=no -o PubkeyAcceptedKeyTypes=+ssh-rsa \
  vagrant@127.0.0.1 "cd /opt/observability && docker compose restart grafana"
```

## Verificatie

```bash
# Metrics controleren (op obs VM)
curl http://localhost:9119/metrics | grep birddog_device_online
# Verwacht: birddog_device_online{device="mock-01"} 1

# Mock-endpoints direct testen
curl http://localhost:8090/about
curl http://localhost:8090/operationmode
curl http://localhost:8090/decodeStatus
curl http://localhost:8090/list

# Prometheus check
curl -s 'http://localhost:9090/api/v1/query?query=birddog_device_online' | python3 -m json.tool
```

## Fail-mode (scenario 9a)

```bash
# Device offline simuleren — container herstarten met BIRDDOG_MOCK_FAIL=1
ssh ... "cd /opt/observability && \
  docker stop birddog-mock && \
  docker compose --profile demo run -d -e BIRDDOG_MOCK_FAIL=1 --name birddog-mock-fail birddog-mock"
# OF simpelweg de container stoppen:
docker stop birddog-mock
# → birddog_device_online{device="mock-01"} gaat naar 0
# → Alert [CRITICAL] BirdDog Device Offline firet binnen 1 minuut
```

## Uitbreiden naar echte hardware

Vervang in `docker-compose.yml` de env-variabele:
```yaml
BIRDDOG_TARGETS: "cam01:192.168.x.y:8080,cam02:192.168.x.z:8080"
```

De mock-container kan uitgeschakeld worden; de exporter werkt identiek op fysieke hardware.

## Limitaties

- **Synthetische bron:** De mock bootst de BirdDog API na op basis van de officiële documentatie (BirdDog RESTful API 2.0). Geen fysiek BirdDog device beschikbaar in de PoC-omgeving.
- **Geen `/about` firmware-validatie:** De exporter controleert niet of de firmware-versie compatibel is met API v2.0.
- **mDNS niet vereist:** BirdDog gebruikt zijn eigen NDI-implementatie; de exporter haalt bronnenlijsten op via `/list` zonder lokale Avahi (anders dan de NDI-exporter).
- **Poort 8090:** Echte BirdDog-hardware gebruikt poort 8080; de mock draait op 8090 om conflict met incontrol2-exporter te vermijden.
