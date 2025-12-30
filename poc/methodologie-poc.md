# Methodologie van het Proof of Concept

## Iteratieve aanpak

Het PoC wordt opgebouwd volgens een iteratieve methodologie, waarbij elke fase voortbouwt op de vorige en de scope incrementeel wordt uitgebreid.

```
┌─────────────────────────────────────────────────────────────┐
│  Fase 1: Data Discovery Peplink/InControl2                  │
│  → Welke metrics zijn beschikbaar via API?                  │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Fase 2: Observability Stack Opzetten                       │
│  → Prometheus, Grafana, netwerk integratie                  │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Fase 3: Peplink Metrics Integreren                         │
│  → API polling, exporter, dashboards                        │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Fase 4: Uitbreiding Netwerkapparatuur                      │
│  → Switches, routers, access points                         │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Fase 5: Streaming/AV Laag (NDI & SRT)                      │
│  → Applicatie-niveau metrics, end-to-end latency            │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Fase 6: Iteratie & Verfijning                              │
│  → Alerting, correlatie, documentatie                       │
└─────────────────────────────────────────────────────────────┘
```

## Fase 1: Data Discovery

**Doel:** Inventariseren welke telemetrie beschikbaar is vanuit Peplink FusionHub en InControl2.

**Activiteiten:**
- InControl2 API endpoints testen en documenteren
- Beschikbare metrics per endpoint catalogiseren
- Beperkingen en workarounds identificeren
- SNMP capabilities onderzoeken op device-niveau

**Deliverables:**
- Overzicht geteste endpoints met voorbeeldresponses
- Metrics inventaris (welke data, welke granulariteit)
- Documentatie van API authenticatie flow

## Fase 2: Observability Stack

**Doel:** Basisinfrastructuur opzetten voor metrics collectie en visualisatie.

**Componenten:**
- Prometheus (metrics opslag en querying)
- Grafana (dashboards en alerting)
- Netwerk integratie in testomgeving

**Activiteiten:**
- Stack deployen (Docker/VM)
- Netwerk toegang configureren tot InControl2 API
- Basis connectiviteit valideren

## Fase 3: Peplink Integratie

**Doel:** Peplink metrics beschikbaar maken in de observability stack.

**Activiteiten:**
- Custom exporter ontwikkelen voor InControl2 API
- Polling interval en retry logica implementeren
- Grafana dashboards bouwen voor:
  - Device health (online/offline, uptime)
  - Bandwidth/throughput
  - VPN tunnel status
  - Event/incident timeline

## Fase 4: Uitbreiding Netwerkapparatuur

**Doel:** Scope uitbreiden naar aanvullende netwerkapparatuur.

**Potentiële targets:**
- Managed switches (SNMP)
- Lokale routers
- Access points

**Activiteiten per component:**
- Data discovery (welke metrics beschikbaar)
- Exporter/collector configureren
- Dashboard integratie

## Fase 5: Streaming/AV Laag (NDI & SRT)

**Doel:** Observability uitbreiden naar de applicatielaag van de live streaming infrastructuur.

### NDI (Network Device Interface)

**Data discovery:**
- NDI Discovery service monitoring (welke bronnen zichtbaar)
- NDI stream metrics (resolution, framerate, codec)
- Latency tussen NDI endpoints
- Packet loss en jitter op NDI streams

**Potentiële bronnen:**
- NDI Tools (Studio Monitor, Analysis)
- NDI SDK/API voor programmatische toegang
- Network captures (Wireshark NDI dissector)

### SRT (Secure Reliable Transport)

**Data discovery:**
- SRT connection statistics (RTT, bandwidth, loss)
- Encryption status
- Retransmission rates
- Buffer levels (sender/receiver)

**Potentiële bronnen:**
- SRT native statistics API (`srt-live-transmit` stats)
- Encoder/decoder ingebouwde metrics
- srt-xtransmit logging

### Integratie in stack

**Activiteiten:**
- Onderzoeken welke metrics beschikbaar zijn per protocol
- Exporters/collectors ontwikkelen of bestaande tools integreren
- Correlatie met netwerk metrics (bijv. VPN throughput ↔ SRT bitrate)
- End-to-end latency dashboard (bron → encoder → transport → decoder)

**Uitdagingen:**
- NDI metrics zijn niet altijd extern toegankelijk
- SRT stats vereisen toegang tot encoder/decoder software
- Real-time correlatie tussen netwerk en applicatie metrics

## Fase 6: Iteratie & Verfijning

**Doel:** Verfijnen en uitbreiden binnen beschikbare tijd.

**Mogelijke uitbreidingen:**
- Alerting rules definiëren
- Correlatie tussen metrics
- Historische trending
- Documentatie en overdracht

## Principes

| Principe | Toelichting |
|----------|-------------|
| **Iteratief** | Elke fase levert werkend resultaat op |
| **Documentatie-gedreven** | Bevindingen direct vastleggen |
| **Scope-flexibel** | Uitbreiden waar tijd het toelaat |
| **Praktisch** | Focus op bruikbare output voor Mediaventures |

## Tijdsindicatie

De exacte doorlooptijd per fase hangt af van complexiteit en beschikbare tijd. Het iteratieve karakter zorgt ervoor dat er na elke fase een bruikbaar tussenresultaat is, ook als de volledige scope niet gehaald wordt.