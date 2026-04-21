# Loki & Promtail — Log Aggregatie

Loki is de logaggregator in de PLG-stack. In combinatie met Promtail worden logs van drie bronnen verzameld: FusionHub syslog, Docker container logs en het VM-systeemlogboek.

---

## Overzicht

Drie bronnen:

1. **FusionHub syslog** — apparaatgebeurtenissen van alle 4 FusionHub VMs via UDP syslog op poort 514
2. **Docker container logs** — logs van alle containers in de observability stack
3. **VM systeemlogboek** — `/var/log/messages` van de AlmaLinux 9 observability VM

---

## Architectuur

```
[FusionHub Bornem]  --UDP:514--+
[FusionHub Venue]   --UDP:514--+
[FusionHub Live1]   --UDP:514--+--> [rsyslog :514] --> /var/log/fusionhub_syslog.log
[FusionHub Live2]   --UDP:514--+                              |
                                                    [Promtail file tail]
                                                              |
[Docker logs /var/run/docker.sock] -----------------> [Loki :3100] --> [Grafana]
[/var/log/messages] -------------------------------->
```

> **Waarom rsyslog als tussenstap?** FusionHub stuurt RFC 3164 (oud BSD syslog formaat). Promtail's syslog listener verwacht RFC 5424. rsyslog ontvangt op UDP 514, schrijft naar `/var/log/fusionhub_syslog.log`, en Promtail leest het bestand — zo omzeilen we het formatprobleem.

---

## Configuratiebestanden

### `poc/stack/loki.yml`
Eenvoudige single-node Loki setup met lokale filesystem opslag. 30 dagen retentie.

### `poc/stack/promtail.yml`
Drie scrape jobs:
- `system_logs` — `/var/log/messages`
- `docker_containers` — Docker service discovery via socket
- `fusionhub_syslog` — bestand `/var/log/fusionhub_syslog.log` (geschreven door rsyslog)

### `/etc/rsyslog.d/fusionhub.conf` (op de observability VM)
```
module(load="imudp")
input(type="imudp" port="514")

if $inputname == 'imudp' then /var/log/fusionhub_syslog.log
& stop
```

---

## FusionHub syslog instellen

Voer dit in op **elke FusionHub** via de webadmin:

1. Ga naar **System → Event Log**
2. Vink **Remote Syslog** aan
3. **Remote Syslog Host:** `10.1.1.100`
4. **Port:** `514` (standaard — FusionHub ondersteunt geen andere poort)
5. Klik **Save**

> **Poort 514:** De FusionHub webadmin laat alleen de standaard syslogpoort (514) toe. rsyslog op de VM luistert op UDP 514 en schrijft naar een bestand. Promtail leest dat bestand.

---

## Verificatie

### Controleer of syslog aankomt op de VM
```bash
sudo tcpdump -i any -n udp port 514 -c 10
# Verwacht: IP 10.1.x.2.xxxxx > 10.1.1.100.syslog: SYSLOG ...
```

### Controleer het syslog bestand
```bash
sudo tail -f /var/log/fusionhub_syslog.log
```

### Events triggeren (als bestand leeg is)
FusionHub stuurt syslog alleen bij events (geen heartbeat). Trigger via:
- Save klikken op een FusionHub pagina — admin login event
- FusionHub VM rebooten — VPN tunnel events bij herverbinding

### Controleer in Grafana
Grafana Explore Loki: `{job="fusionhub_syslog"}`

---

## Labels en filtering in Grafana

### Beschikbare labels

| Label | Bron | Voorbeeld waarde |
|-------|------|-----------------|
| `job` | Promtail | `fusionhub_syslog`, `docker_containers`, `system` |
| `device` | Regex uit syslog hostname | `bornem`, `venue`, `live2` |
| `app` | Regex uit syslog app name | `SpeedFusion`, `peplink` |
| `container` | Docker | `prometheus`, `grafana`, `incontrol2-exporter` |

### Nuttige LogQL queries

```logql
# Alle FusionHub logs
{job="fusionhub_syslog"}

# SpeedFusion/VPN events
{job="fusionhub_syslog"} |= "SpeedFusion"

# VPN verbindingen van een specifiek device
{job="fusionhub_syslog", device="live2"}

# Tunnel connected/disconnected events
{job="fusionhub_syslog"} |= "connected" or |= "disconnected"

# InControl2 exporter logs
{job="docker_containers", container="incontrol2-exporter"}

# Alle fouten in container logs
{job="docker_containers"} |= "error"
```

---

## Dashboard log panels

In het Grafana dashboard (sectie 6) zijn twee log panels aanwezig:
- **FusionHub Syslog** — `{job="fusionhub_syslog"}` — toont SpeedFusion VPN events, admin acties
- **Docker Container Logs** — `{job="docker_containers"}` — toont stack-interne logs

---

## Troubleshooting

| Probleem | Oplossing |
|----------|-----------|
| Geen FusionHub syslog in bestand | Check rsyslog: `systemctl status rsyslog` en `ss -ulnp \| grep 514` |
| rsyslog luistert niet op 514 | Check `/etc/rsyslog.d/fusionhub.conf` aanwezig? `sudo systemctl restart rsyslog` |
| Promtail leest bestand niet | Check permissions: `ls -la /var/log/fusionhub_syslog.log` — moet 644 zijn |
| Loki container start niet | Controleer volume permissions: `docker exec loki ls -la /loki` |
| Geen Docker logs in Grafana | Check of `/var/run/docker.sock` gemount is: `docker inspect promtail` |
| Loki "ingester not ready" | Normaal na opstart — wacht 15s, Loki is daarna ready |
| Grafana Loki datasource "No data" | Check Loki health: `curl http://10.1.1.100:3100/ready` moet "ready" teruggeven |
