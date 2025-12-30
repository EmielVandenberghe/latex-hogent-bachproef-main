# InControl2 API - Data Discovery

Testomgeving: 4x FusionHub VM, InControl2 cloud  
Datum: 2025-12-29

---

## Authenticatie

Token ophalen via OAuth2 client credentials:

```powershell
Invoke-RestMethod -Method Post -Uri "https://api.ic.peplink.com/api/oauth2/token" -Body @{
    client_id = "7162ddbce09f2051c184d687b20e0ab8"
    client_secret = "564f6c84416bef056e05edb3afc654e9"
    grant_type = "client_credentials"
}
```

Output:
```
access_token                     refresh_token                    token_type expires_in
------------                     -------------                    ---------- ----------
03246c260a1ec6ec9c4a5db7e0c4a0fc 7f1539320bc9c8062027a14833894f21 Bearer         172799
```

Token is 2 dagen geldig. Refresh token 30 dagen. Voor alle volgende calls:

```powershell
$Headers = @{ Authorization = "Bearer $env:IC_TOKEN"; Accept = "application/json" }
```

---

## Organisatie & Device Discovery

### Org ID vinden

```powershell
Invoke-RestMethod "https://api.ic.peplink.com/rest/o" -Headers $Headers
```

Output:
```
data: {@{id=a1pokv; name=EmielVandenberghe; org_code=B7419C; ...}}
```

Org ID = `a1pokv`, dit gebruiken we in alle volgende calls.

### Device lijst ophalen

```powershell
Invoke-RestMethod "https://api.ic.peplink.com/rest/o/a1pokv/d" -Headers $Headers
```

Output (4 devices):
```
id=13  name=Bornem        sn=11F4-01BB-DA4B  status=online
id=14  name=Venue         sn=11A6-6CDB-A9D8  status=online
id=15  name=Live-Surgery1 sn=1129-54CA-B389  status=online
id=16  name=Live-Surgery2 sn=11FF-F882-7284  status=online
```

Bruikbaar: device inventory, group_id=4 (MediaVentures), firmware versies, serienummers.

---

## Live Device Status

Probleem: standaard device lijst geeft geen real-time metrics (usage, tx, rx zijn leeg).

Oplossing: `has_status=1` parameter triggert devices om verse data te sturen.

```powershell
# Eerste call triggert
Invoke-RestMethod "https://api.ic.peplink.com/rest/o/a1pokv/d?has_status=1" -Headers $Headers
Start-Sleep 2
# Tweede call heeft verse data
Invoke-RestMethod "https://api.ic.peplink.com/rest/o/a1pokv/d?has_status=1" -Headers $Headers
```

Output na trigger:
```
id site_id  onlineStatus client_count usage  tx  rx uptime fw_ver
-- -------  ------------ ------------ -----  --  -- ------ ------
13 Bornem   ONLINE                  1   0.0 0.0 0.0  16952 8.5.1s045 build 5258
15 Surgery1 ONLINE                  1   0.0 0.0 0.0  16775 8.5.1s045 build 5258
16 Surgery2 ONLINE                  1   0.0 0.0 0.0  16751 8.5.1s045 build 5258
14 Venue    ONLINE                  1   0.0 0.0 0.0  16752 8.5.1s045 build 5258
```

Bruikbaar: real-time health monitoring, uptime tracking, client count.

Let op: usage/tx/rx zijn 0 omdat er geen echt verkeer is in testomgeving.

---

## Event Logs

```powershell
Invoke-RestMethod "https://api.ic.peplink.com/rest/o/a1pokv/g/4/d/13/event_log" -Headers $Headers
```

Output (54 events):
```
ts                  event_type  detail
--                  ----------  ------
2025-12-29T12:46:48 Admin       Remote Web Admin initiated from InControl 2 by vandenemiel@gmail.com
2025-12-29T11:18:00 System      Changes Applied
2025-12-29T11:18:00 System      InControl is updating PepVPN configuration
2025-12-29T11:17:59 System      PepVPN configuration has been updated by InControl
```

Bruikbaar: audit trail, config changes detecteren, incident timeline.

Group-level events (alle devices):
```powershell
Invoke-RestMethod "https://api.ic.peplink.com/rest/o/a1pokv/g/4/event_log" -Headers $Headers
```

Geeft 100 events over alle 4 devices.

---

## Online/Offline History

```powershell
Invoke-RestMethod "https://api.ic.peplink.com/rest/o/a1pokv/g/4/d/13/online_history" -Headers $Headers
```

Output:
```
online_time          offline_time         duration  duration_in_second
-----------          ------------         --------  ------------------
2025-12-29T10:38:32  (still online)       -         -
2025-12-29T10:12:31  2025-12-29T10:33:43  00:21:12  1272
2025-12-29T09:03:37  2025-12-29T09:08:32  00:04:55  295
```

Bruikbaar: availability berekenen, downtime tracking, SLA reporting.

---

## Bandwidth per Device

```powershell
$date = (Get-Date).ToString("yyyy-MM-dd")
Invoke-RestMethod "https://api.ic.peplink.com/rest/o/a1pokv/bandwidth_per_device?type=daily&report_date=$date" -Headers $Headers
```

Output:
```
device_id  group_id  sn              type   wans            usages
---------  --------  --              ----   ----            ------
13         4         11F4-01BB-DA4B  daily  System.Object[] System.Object[]
...
```

Parameters zijn verplicht:
- `type=daily` (of monthly, hourly)
- `report_date=YYYY-MM-DD`

Zonder parameters: `INVALID_INPUT: missing_type` of `missing_report_date`

Bruikbaar: dagelijkse bandwidth rapporten per device.

---

## WAN Quality

```powershell
$start = (Get-Date).AddHours(-1).ToString("yyyy-MM-ddTHH:mm:ss")
Invoke-RestMethod "https://api.ic.peplink.com/rest/o/a1pokv/g/4/d/13/wan_quality?start=$start" -Headers $Headers
```

Output:
```
wan_id: 0
```

Minimale data in testomgeving (geen cellular/WAN variatie). In productie zou dit RSRP, RSRQ, SINR etc. bevatten voor cellular WANs.

`start` parameter is verplicht, anders: `INVALID_INPUT: missing_start`

---

## WAN History

```powershell
Invoke-RestMethod "https://api.ic.peplink.com/rest/o/a1pokv/g/4/d/13/wan_history" -Headers $Headers
```

Output:
```
device_id: 13
wan_id: 0
wans: [...]
```

Bruikbaar: WAN up/down events, failover geschiedenis.

---

## PepVPN / SpeedFusion

### Status endpoints - WERKEN NIET

```powershell
Invoke-RestMethod "https://api.ic.peplink.com/rest/o/a1pokv/pepvpn/status" -Headers $Headers
```

Output:
```
resp_code: INTERNAL_ERROR
```

Zelfde voor:
- `/rest/o/a1pokv/pepvpn/status_v2` (POST)
- `/rest/o/a1pokv/g/4/pepvpn/status`

Alle PepVPN status endpoints op org/group level geven INTERNAL_ERROR. Waarschijnlijk server-side issue of feature niet beschikbaar op free tier.

### Tunnel stat - WERKT MET POLLING

```powershell
Invoke-RestMethod "https://api.ic.peplink.com/rest/o/a1pokv/g/4/d/13/pepvpn/tunnel_stat" -Headers $Headers
```

Eerste call:
```
resp_code: PENDING
data: {}
```

Poll tot SUCCESS (meestal 2-3 pogingen):
```
resp_code: SUCCESS
data: @{timestamp=0; organization_id=a1pokv; group_id=4; sn=11F4-01BB-DA4B; stat=ok}
```

Probleem: alleen `stat=ok`, geen gedetailleerde metrics (latency, jitter, packet loss).

tunnel_stat_v2 (POST) geeft zelfde resultaat:
```powershell
Invoke-RestMethod "https://api.ic.peplink.com/rest/o/a1pokv/g/4/d/13/pepvpn/tunnel_stat_v2" -Method POST -Headers $Headers -ContentType "application/json" -Body "{}"
```

Conclusie: API geeft alleen basic "tunnel is up" status, geen quality metrics. Voor latency/jitter/loss waarschijnlijk SNMP of device-level API nodig.

---

## Client Info

```powershell
Invoke-RestMethod "https://api.ic.peplink.com/rest/o/a1pokv/g/4/d/13/client" -Headers $Headers
```

Output:
```
client_id        mac                ip            last_seen            status  active
---------        ---                --            ---------            ------  ------
01080027B7D050   08:00:27:B7:D0:50  10.1.1.10     2025-12-29T15:18:41  online  true
```

Bruikbaar: wie is verbonden, MAC/IP mapping, connection tracking.

---

## Endpoints die NIET werken

| Endpoint | Error | Reden |
|----------|-------|-------|
| `/d/{device}/info` | INVALID_INPUT | Onbekend |
| `/d/{device}/bandwidth` | invalid_type | Parameter nodig maar onduidelijk welke |
| `/d/{device}/wan_usage` | UNDEFINED | Endpoint bestaat niet/anders |
| `/d/{device}/availability` | invalid_date_range | Start/end params nodig |
| `/d/{device}/top_clients` | missing start date | Start param nodig |
| `/g/{group}/bandwidth` | Invalid type | Parameter nodig |
| Alle `/pepvpn/status` | INTERNAL_ERROR | Server-side of feature beperking |

---

## Samenvatting

### Wat we kunnen monitoren via InControl2 API

| Metric | Endpoint | Polling interval |
|--------|----------|------------------|
| Device online/offline | `/d?has_status=1` | 30-60s |
| Uptime | `/d?has_status=1` | 30-60s |
| Client count | `/d?has_status=1` | 30-60s |
| Live tx/rx | `/d?has_status=1` | 30-60s |
| Events/changes | `/event_log` | 60s |
| Uptime history | `/online_history` | 5min |
| Daily bandwidth | `/bandwidth_per_device` | 15min |
| VPN tunnel up/down | `/pepvpn/tunnel_stat` | 60s (met polling) |

### Wat we NIET kunnen monitoren via InControl2 API

- VPN tunnel latency
- VPN tunnel jitter
- VPN tunnel packet loss
- Gedetailleerde WAN quality (in testomgeving)

-> In deze fase van het onderzoek nemen we genoegen met deze resultaten om te beginnen aan de observability stack, er kunnen altijd nog api endpoints toegevoegd worden aan de stack naarmate we verder raken in het project.

    -> Nu dus door met fase 2 van het POC, de observability stack

### Rate limit

Max 20 requests/seconde per organisatie. Bij overschrijding: HTTP 429.

---
