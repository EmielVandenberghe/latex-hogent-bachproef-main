# Grafana Alerting — Proactieve Notificaties

**Bachelorproef Mediaventures Observability POC — maart 2026**

---

## Overzicht

Grafana Alerting evalueert alert rules elke minuut op basis van Prometheus-queries. Wanneer een conditie voldaan is gedurende de ingestelde duur, gaat de alert naar "Firing" en wordt een notificatie gestuurd.

In het POC zijn **8 alert rules** geconfigureerd via `poc/stack/provisioning/alerting/alerts.yml`.

---

## Geconfigureerde alerts

| Alert | Prioriteit | Trigger | For |
|-------|-----------|---------|-----|
| Device Offline | CRITICAL | `peplink_device_online == 0` | 1 min |
| PepVPN Tunnel Down | CRITICAL | `peplink_tunnel_up == 0` | 1 min |
| Site onbereikbaar (ICMP) | WARNING | `probe_success == 0` | 2 min |
| Hoge VPN-latency | WARNING | RTT > 150ms | 5 min |
| Hoog packet loss | WARNING | Packet loss > 5% | 5 min |
| WAN Link Down | WARNING | `peplink_snmp_wan_link_up{wan_name="WAN"} == 0` | 2 min |
| Hoge CPU Load | WARNING | `peplink_local_cpu_load_percent > 85` | 5 min |
| Exporter down | CRITICAL | `peplink_scrape_success == 0` | 2 min |

---

## Alerts bekijken in Grafana

1. Ga naar http://192.168.137.10:3000
2. Klik in het linkermenu op **Alerting** (belicoon)
3. Klik op **Alert rules** — hier zie je alle regels met hun huidige status:
   - **Normal** — conditie niet actief
   - **Pending** — conditie actief maar nog niet lang genoeg
   - **Firing** — alert actief, notificatie verstuurd

---

## Contact point (notificaties)

Het POC is geconfigureerd met een email contact point naar `admin@mediaventures.be`. Omdat er geen SMTP-server is ingesteld, mislukken de email notificaties maar zijn de alerts wel zichtbaar in de Grafana UI.

**Voor productie:** SMTP instellen via `GF_SMTP_*` environment variabelen in docker-compose.yml:
```yaml
environment:
  - GF_SMTP_ENABLED=true
  - GF_SMTP_HOST=smtp.example.com:587
  - GF_SMTP_USER=alerts@mediaventures.be
  - GF_SMTP_PASSWORD=<wachtwoord>
  - GF_SMTP_FROM_ADDRESS=alerts@mediaventures.be
```

**Alternatief voor productie:** Webhook naar Teams/Slack/PagerDuty — veel eenvoudiger dan email:
```yaml
receivers:
  - uid: teams-webhook
    type: teams
    settings:
      url: https://mediaventures.webhook.office.com/...
```

---

## Alert rules aanpassen

Drempelwaarden aanpassen in `poc/stack/provisioning/alerting/alerts.yml` en dan:
```bash
KEY="poc/stack/.vagrant/machines/default/virtualbox/private_key"
scp -i "$KEY" -P 2222 -o StrictHostKeyChecking=no -o PubkeyAcceptedKeyTypes=+ssh-rsa \
  poc/stack/provisioning/alerting/alerts.yml \
  vagrant@127.0.0.1:/opt/observability/provisioning/alerting/
ssh -i "$KEY" -p 2222 -o StrictHostKeyChecking=no -o PubkeyAcceptedKeyTypes=+ssh-rsa \
  vagrant@127.0.0.1 "docker restart grafana"
```

---

## Testen van alerts

### Alert manueel triggeren: site onbereikbaar maken

Op VyOS (SSH naar 192.168.137.10), blokkeer ICMP naar Live1:
```
configure
set firewall name BLOCK-LIVE1 rule 1 action drop
set firewall name BLOCK-LIVE1 rule 1 protocol icmp
set firewall name BLOCK-LIVE1 rule 1 destination address 10.1.3.2
set interfaces ethernet eth3 firewall in name BLOCK-LIVE1
commit
```

Na 2 minuten → alert "Site onbereikbaar (ICMP)" gaat naar Firing.

Terugzetten:
```
delete interfaces ethernet eth3 firewall
delete firewall name BLOCK-LIVE1
commit
save
```

### Alert manueel triggeren: hoge latency

Op VyOS, voeg kunstmatige vertraging toe via `tc netem` (zie `testscenarios.md` voor volledige handleiding).

---

## Relatie met thesis

Het voorstel vermeldt expliciet:
> "Een alerting-mechanisme integreren dat techniekers proactief waarschuwt bij kritieke afwijkingen"

Dit is bereikt via Grafana's ingebouwde alerting met:
- Provisioned alert rules (reproduceerbaar, versiebeheerbaar)
- 6 regels gericht op de kritieke parameters voor live AV-productie
- Koppeling aan een contact point (extensible naar productie notificaties)
