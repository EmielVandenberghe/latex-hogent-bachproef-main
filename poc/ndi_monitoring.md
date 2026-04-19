# NDI Stream Monitoring — POC Mediaventures

**Bachelorproef Observability voor Multi-Site Live-Streamingomgevingen**
**Datum:** april 2026

---

## Overzicht

NDI (Network Device Interface, NewTek/Vizrt) is het dominante IP-videoprotocol binnen
productie-LAN's (studio, OB-truck, venue). Binnen de PoC demonstreert de stack dat dezelfde
observability-aanpak die voor SRT werkt, ook NDI-streams kan opvolgen op frame-niveau.

Twee containers:

| Container | Functie |
|-----------|---------|
| `ndi-exporter` | NDI-ontvanger op basis van de NDI SDK (ctypes); exporteert per-frame statistieken als Prometheus-metrics op poort 9118 |
| `ndi-test-stream` | Synthetische NDI-bron (SMPTE-kleurbalken, 1280x720 @ 25 fps) voor demo/testscenario's (profile `demo`) |

In productie wordt `ndi-test-stream` vervangen door een echte NDI-bron (camera, mixer, PTZ, vMix-output). De exporter blijft ongewijzigd — hij abonneert zich op een bronnaam.

---

## Architectuur

```
ndi-test-stream (sender)           ndi-exporter (receiver)
  SMPTE color bars                    NDIlib_recv_create_v3
  → libndi.so.6 → NDI-TCP 5960/5961 → NDIlib_recv_capture_v2
     (mDNS advertise via Avahi)        NDIlib_recv_get_performance
                                       NDIlib_recv_get_queue
                                          ↓
                                     Prometheus metrics :9118
```

Beide containers draaien met `network_mode: host`. Discovery verloopt via **mDNS/Avahi**.

---

## Geëxporteerde metrics

| Metric | Eenheid | Beschrijving |
|--------|---------|--------------|
| `ndi_sdk_available` | bool | 1 als de NDI SDK (libndi.so.6) geladen is; 0 = discovery-only fallback |
| `ndi_sources_detected` | count | Aantal NDI-bronnen zichtbaar op het netwerk |
| `ndi_stream_active` | bool | 1 als de exporter frames ontvangt van de geconfigureerde bron |
| `ndi_frames_received_total` | counter | Cumulatief aantal ontvangen videoframes |
| `ndi_frames_dropped_total` | counter | Cumulatief aantal gedropte videoframes (receiver-side) |
| `ndi_frame_drop_rate` | % | Percentage gedropte frames in het laatste scrape-interval |
| `ndi_video_fps` | fps | Huidige framerate van de stream |
| `ndi_video_width` | pixels | Horizontale resolutie |
| `ndi_video_height` | pixels | Verticale resolutie |
| `ndi_queue_depth_frames` | frames | Diepte van de receiver-videobuffer (opstapelende frames = netwerkverstoring) |

Label `source="NDI Test Stream"` op stream-specifieke metrics.

---

## NDI SDK installatie

Het SDK-archief `Install_NDI_SDK_v6_Linux.tar.gz` (gratis na registratie op
<https://ndi.video/for-developers/ndi-sdk/>) moet aanwezig zijn in `poc/stack/` vóór
`docker compose build`. De Dockerfile (`Dockerfile.ndi`):

1. Pakt het archief uit, detecteert de `Install_NDI_SDK_v*_Linux.sh` installer.
2. Voert de installer uit met geaccepteerde EULA.
3. Kopieert `libndi.so*` naar `/usr/local/lib/` en runt `ldconfig`.
4. Verwijdert SDK-bestanden (enkel de gedeelde library blijft).

Zonder het tar-archief start de exporter in **discovery-only modus**: dan worden enkel
`ndi_sdk_available` (=0) en `ndi_sources_detected` via zeroconf-mDNS-browsing geëxporteerd.
Frame-level metrics zijn pas beschikbaar mét SDK.

---

## Discovery via mDNS/Avahi — kritieke configuratie

NDI gebruikt **mDNS** (multicast DNS, `_ndi._tcp.local.`) voor bronnendetectie. De SDK
maakt intern gebruik van `libavahi-client` om de mDNS-service te benaderen. Dit vereist
een **actieve `avahi-daemon`** die het libavahi-client in de container kan bereiken.

**De valkuil:** `libavahi-client` installeren in de container (zoals in `Dockerfile.ndi`)
is **onvoldoende**. De client verbindt via DBus of unix-socket met een dráaiende daemon.
Zonder daemon ziet `NDIlib_find_get_current_sources()` nul bronnen — ook al luistert de
sender op dezelfde host op TCP 5960/5961, en ook al staat `NDI_EXTRA_IPS=127.0.0.1`.
(`p_extra_ips` in de NDI SDK vereist alsnog mDNS-resolutie van de vermelde IPs.)

**Opgelost in de PoC:**

1. **Host-zijde** (AlmaLinux 9, obs VM):
   ```bash
   sudo dnf install -y avahi avahi-tools nss-mdns
   sudo systemctl enable --now avahi-daemon
   ```

2. **Container-zijde** (`docker-compose.yml`) — DBus en Avahi-socket van de host bind-mounten naar beide NDI-containers:
   ```yaml
   ndi-exporter:
     volumes:
       - /var/run/dbus:/var/run/dbus:ro
       - /var/run/avahi-daemon/socket:/var/run/avahi-daemon/socket
   ndi-test-stream:
     volumes:
       - /var/run/dbus:/var/run/dbus:ro
       - /var/run/avahi-daemon/socket:/var/run/avahi-daemon/socket
   ```

3. **Herstart met force-recreate** (zonder recreate worden de nieuwe mounts niet opgepikt):
   ```bash
   docker compose --profile demo up -d --force-recreate ndi-exporter ndi-test-stream
   ```

Na deze ingreep publiceert de sender zich via mDNS (zichtbaar met
`avahi-browse -rt _ndi._tcp` op de host) en ziet de exporter de bron.

---

## Verificatie

```bash
# 1. Avahi ziet de NDI-bron
avahi-browse -rt _ndi._tcp
# Verwacht: "OBSERVABILITY (NDI Test Stream)" op meerdere interfaces

# 2. Metrics endpoint
curl -s http://127.0.0.1:9118/metrics | grep -E 'sdk_available|stream_active|fps|width'
# Verwacht:
# ndi_sdk_available 1
# ndi_stream_active{source="NDI Test Stream"} 1
# ndi_video_fps{source="NDI Test Stream"} 25.0
# ndi_video_width{source="NDI Test Stream"} 1280

# 3. Prometheus target
curl -s http://127.0.0.1:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="ndi_exporter") | .health'
# Verwacht: "up"
```

---

## Troubleshooting matrix

| Symptoom | Diagnose | Fix |
|----------|----------|-----|
| `ndi_sdk_available 0` | SDK-tar ontbrak tijdens build, of installer mislukt | Download SDK, plaats in `poc/stack/`, `docker compose build ndi-exporter` |
| `ndi_sdk_available 1` maar `ndi_sources_detected 0` | Avahi-daemon niet bereikbaar voor container | Zie sectie "Discovery via mDNS/Avahi" |
| `ndi_sources_detected 1` maar `ndi_stream_active 0` | Bronnaam komt niet overeen met `NDI_SOURCE_NAME` env | Controleer `NDI_SOURCE_NAME` (case-insensitive substring match) |
| Metrics blijven 0 na configuratiewijziging | `docker compose restart` leest `env_file` en nieuwe mounts niet opnieuw | `docker compose up -d --force-recreate <service>` |
| Target down in Prometheus | Exporter draait, maar firewall/port-mismatch | `ss -tlnp \| grep 9118`; controleer `prometheus.yml` job `ndi_exporter` |

---

## Bevindingen voor het BAP

1. **NDI-monitoring is haalbaar als blackbox-exporter zonder tap-hardware.** Via de
   SDK-receiver krijgen we realtime frame-level metrics (fps, drops, queue depth) die
   geen andere passieve oplossing biedt.

2. **mDNS is een verborgen netwerkafhankelijkheid.** In multi-site LAN's met
   gesegmenteerde VLAN's is mDNS typisch link-local; NDI werkt daardoor standaard enkel
   binnen één broadcastdomein. Voor cross-site discovery biedt NDI de "Discovery Server"
   (centrale registry via TCP) — buiten scope van deze PoC, wel relevant voor
   Mediaventures als vervolgtraject.

3. **Container + mDNS + host-networking** vergt expliciet exposen van DBus/Avahi-sockets.
   Dit is dezelfde klasse-fout als mDNS in Kubernetes pods: mensen vergeten dat
   `libavahi-client` ≠ `avahi-daemon`.

4. **Receiver-side drops ≠ netwerkdrops.** `ndi_frames_dropped_total` meet frames die
   de receiver intern moest weggooien (queue vol, te late aankomst). Dit correleert met
   netwerkverstoring maar is niet gelijk aan UDP-loss op de link — die zou via tc netem
   op LAN (zoals scenario 4 voor SRT) aangetoond kunnen worden in vervolgwerk.

---

## Locatie in repo

- Stack: `poc/stack/ndi_exporter.py`, `poc/stack/ndi_sender.py`, `poc/stack/Dockerfile.ndi`
- Compose-service: `ndi-exporter`, `ndi-test-stream` (profile `demo`) in `poc/stack/docker-compose.yml`
- SDK (niet in git): `poc/stack/Install_NDI_SDK_v6_Linux.tar.gz`
- Prometheus job: `ndi_exporter` in `poc/stack/prometheus.yml`
