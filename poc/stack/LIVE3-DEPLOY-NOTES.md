# Live3 deployment notes

> **⚠️ OPGEGEVEN — 16 april 2026**
> De PepVPN-tunnelstrategie (Bornem-Live3 P2P, Balance 20X op 10.1.5.1) is opgegeven. De tunnel bleef steken in een auth-cyclus en het FH-Bornem-profiel was IC2-locked en niet debugbaar. Deadline-druk en marginale meerwaarde t.o.v. de 4 werkende FusionHub-tunnels waren de doorslag.
>
> **Definitieve aanpak:** Balance 20X bereikbaar via **WiFi-direct (192.168.1.1)** op de bridged WiFi-adapter van de obs VM. De .env, prometheus.yml en ping_exporter.py zijn dienovereenkomstig bijgewerkt (Live3 → 192.168.1.1). De code-wijzigingen in dit bestand (exporter-patch, tunnel_count metric, nieuwe alert) zijn wél doorgevoerd en gepusht — enkel het 10.1.5.1 IP-pad is nooit gebruikt.
>
> Dit bestand dient als historische referentie voor de beslissing en de code-wijzigingen die uit deze fase zijn voortgekomen.

**Oorspronkelijke status (voor opgave):** code-wijzigingen aangebracht in bron-bestanden als voorbereiding op deploy via Bornem-Live3 PepVPN-tunnel naar 10.1.5.1. Die deploy heeft nooit plaatsgevonden.

## Wat is gewijzigd in deze repo

Code + config:
- `incontrol2_exporter.py` — **2 wijzigingen** samengevoegd:
  1. Exporter-patch voor [monitoring_blindspot.md](../monitoring_blindspot.md): `get_tunnel_stat` returnt nu `(count, all_ok)` tuple, nieuwe `peplink_tunnel_count` metric, `.clear()` cycle voor stale-label opruiming.
  2. Geen Live3-specifieke code nodig — werkt volledig via env-vars.
- `.env` — `SNMP_TARGETS` en `LOCAL_API_TARGETS` uitgebreid met `Live3:10.1.5.1`
- `ping_exporter.py` — `SITES` dict uitgebreid met `"Live3": "10.1.5.1"`
- `prometheus.yml` — nieuwe blackbox_icmp target `10.1.5.1` met label `site=Live3`
- `provisioning/alerting/alerts.yml` — nieuwe alert `alert-pepvpn-no-profiles` (10 regels totaal)
- `provisioning/dashboards/peplink.json` — Live3 panels + `peplink_tunnel_count` placeholder + panel 183 kleuroverrides

Documentatie:
- `../monitoring_blindspot.md` — root cause + fix-strategie
- `../omgeving_opzetten.md.live3-draft` — vervangende "Waarom een fysieke Peplink?" sectie (merge zodra tunnel up)

## Pre-deploy checklist (jij, met hardware/IC2)

1. **MediaVentures-Hub fixen** in IC2 → hub=Bornem, endpoints=Venue/Live1/Live2
2. **Bornem-Live3 P2P profiel** opzetten en Connected verifiëren
3. **Balance LAN migreren naar 10.1.5.0/24** (Optie X uit MEMORY.md)
4. **VyOS statische route**: `set protocols static route 10.1.5.0/24 next-hop 10.1.1.2` + `commit` + `save`
5. **Connectiviteit** verifiëren: vanaf obs VM 10.1.1.100 → `ping 10.1.5.1` moet werken via de tunnel
6. **Balance syslog** target aanpassen naar `10.1.1.100:1514` (via tunnel) zodat locatie-onafhankelijk

## Deploy commando's (na pre-deploy)

Vanuit `latex-hogent-bachproef-main/poc/`:

```bash
KEY="stack/.vagrant/machines/default/virtualbox/private_key"
SSH_OPTS="-i $KEY -P 2222 -o StrictHostKeyChecking=no -o PubkeyAcceptedKeyTypes=+ssh-rsa"
SSH="ssh -i $KEY -p 2222 -o StrictHostKeyChecking=no -o PubkeyAcceptedKeyTypes=+ssh-rsa vagrant@127.0.0.1"

# 1. Gewijzigde bestanden naar obs VM kopiëren
scp $SSH_OPTS stack/incontrol2_exporter.py vagrant@127.0.0.1:/opt/observability/
scp $SSH_OPTS stack/ping_exporter.py vagrant@127.0.0.1:/opt/observability/
scp $SSH_OPTS stack/prometheus.yml vagrant@127.0.0.1:/opt/observability/
scp $SSH_OPTS stack/.env vagrant@127.0.0.1:/opt/observability/
scp $SSH_OPTS stack/provisioning/alerting/alerts.yml vagrant@127.0.0.1:/opt/observability/provisioning/alerting/
scp $SSH_OPTS stack/provisioning/dashboards/peplink.json vagrant@127.0.0.1:/opt/observability/provisioning/dashboards/

# 2. Containers rebuilden waar Python-code is gewijzigd
$SSH "cd /opt/observability && docker compose up -d --build incontrol2-exporter ping-exporter"

# 3. Prometheus config reload (geen rebuild nodig)
$SSH "curl -X POST http://localhost:9090/-/reload"

# 4. Grafana herstart voor dashboard + alerting provisioning reload
$SSH "cd /opt/observability && docker compose restart grafana"
```

## Verificatie (na deploy)

- [ ] `curl http://192.168.137.10:9090/api/v1/query?query=peplink_tunnel_count` → waarden > 0 voor elk device
- [ ] `curl http://192.168.137.10:9090/api/v1/query?query=peplink_tunnel_up{device_name="Balance_2622"}` → 1 (mits Bornem-Live3 tunnel up)
- [ ] Grafana sectie 5 toont 5 tunnel stats (4 Star + Live3 hybrid) + profielen-count panel
- [ ] Grafana sectie 1 toont Live3 kolom met data (api/snmp/icmp)
- [ ] Prometheus targets page → `blackbox_icmp{site="Live3"}` = UP
- [ ] Alert `alert-pepvpn-no-profiles` state = Normal (geen fire)
- [ ] Nieuwe alert test: tijdelijk profielen verwijderen → binnen 5 min moet `alert-pepvpn-no-profiles` firen en `peplink_tunnel_up` voor elk device naar 0 gaan (i.p.v. de oude bug waar het op 1 bleef)

## Rollback

Als iets stukgaat:

```bash
# Dashboard
cp provisioning/dashboards/peplink.json.bak-pre-task2 provisioning/dashboards/peplink.json

# Exporter (git revert op incontrol2_exporter.py + alerts.yml)
git checkout HEAD~1 -- stack/incontrol2_exporter.py stack/provisioning/alerting/alerts.yml
```
