# Teams Alerting via Power Automate Webhook

## Architectuur

```
Grafana Unified Alerting
    → contact point: teams-webhook (type: webhook)
    → POST JSON payload
        → Power Automate Workflow (HTTP-trigger)
            → "Post adaptive card in a chat or channel"
                → Microsoft Teams kanaal "Observability-PoC"
```

## Waarom Power Automate en niet het native "Microsoft Teams" contact point?

Microsoft heeft de **Office 365 Connector webhooks deprecated op 2024-10-01**. Bestaande
`https://outlook.office.com/webhook/...` URLs werken niet meer in nieuwe tenants en lopen
af in bestaande. Het ingebouwde Grafana "Microsoft Teams"-contact-point gebruikt dit
verouderde mechanisme.

De enige ondersteunde aanpak in 2025/2026 is via **Power Automate Workflow** met trigger
"When a Teams webhook request is received". Grafana verstuurt de alert-payload naar de
Power Automate HTTP-endpoint, Power Automate plaatst het bericht in het kanaal.

## Stap 2.2 — Power Automate flow aanmaken (handmatig)

1. Ga naar [flow.microsoft.com](https://flow.microsoft.com) en log in met het Mediaventures-account.
2. Klik **+ Create** → **Instant cloud flow** → zoek op "Post to a channel when a webhook request is received".
3. Kies het Teams-team en kanaal (voorstel: kanaal **"Observability-PoC"**).
4. Sla de flow op. Kopieer de gegenereerde **HTTP POST URL** (ziet eruit als
   `https://prod-XX.westeurope.logic.azure.com:443/workflows/.../triggers/manual/paths/invoke?...`).
5. Plak de URL in `poc/stack/.env`:
   ```
   TEAMS_WEBHOOK_URL=https://prod-XX.westeurope.logic.azure.com:443/workflows/...
   ```
6. Herstart de Grafana-container op de observability VM:
   ```bash
   KEY="poc/stack/.vagrant/machines/default/virtualbox/private_key"
   ssh -i "$KEY" -p 2222 -o StrictHostKeyChecking=no -o PubkeyAcceptedKeyTypes=+ssh-rsa \
     vagrant@127.0.0.1 "cd /opt/observability && docker compose up -d --force-recreate grafana"
   ```

## Optioneel: adaptive card aanpassen in Power Automate

De default Power Automate template plaatst de ruwe JSON-body van Grafana in Teams.
Voor een leesbaardere kaart kun je in de flow een **Parse JSON**-stap toevoegen op de
trigger-body, gevolgd door een **Post adaptive card**-actie met dit template:

```json
{
  "type": "AdaptiveCard",
  "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
  "version": "1.4",
  "body": [
    {
      "type": "TextBlock",
      "text": "🚨 Grafana Alert",
      "weight": "Bolder",
      "size": "Medium"
    },
    {
      "type": "FactSet",
      "facts": [
        { "title": "Status",    "value": "@{triggerBody()?['status']}" },
        { "title": "Alert",     "value": "@{triggerBody()?['alerts'][0]?['labels']?['alertname']}" },
        { "title": "Severity",  "value": "@{triggerBody()?['alerts'][0]?['labels']?['severity']}" },
        { "title": "Samenvatting", "value": "@{triggerBody()?['alerts'][0]?['annotations']?['summary']}" }
      ]
    }
  ]
}
```

Grafana stuurt een JSON-body met structuur:
```json
{
  "receiver": "teams-webhook",
  "status": "firing",
  "alerts": [
    {
      "labels": { "alertname": "...", "severity": "critical", "device_name": "..." },
      "annotations": { "summary": "...", "description": "..." },
      "status": "firing",
      "startsAt": "2026-04-23T10:00:00Z"
    }
  ]
}
```

## Provisioning

`provisioning/alerting/alerts.yml` bevat:
- Contact point `teams-webhook` (type: `webhook`, url: `${TEAMS_WEBHOOK_URL}`)
- Routing policy:
  - Alle CRITICAL alerts → teams-webhook (+ default, via `continue: true`)
  - SRT / NDI / BirdDog WARNINGs → teams-webhook (+ default, via `continue: true`)
- Default receiver: `mediaventures-default` (Grafana UI)

## Testen

In Grafana → Alerting → Contact points → `teams-webhook` → **Test**:
- Er verschijnt een testbericht in het Teams-kanaal.
- Controleer de Power Automate flow-run history op eventuele fouten.

Daarna: scenario 10 (zie `testscenarios.md`).

## Beveiliging

- `.env` staat in `.gitignore` — de webhook-URL komt nooit in git.
- De Power Automate webhook-URL bevat geen OAuth-secret maar is een unauthenticated endpoint.
  Behandel het als een semi-privé URL: deel het niet publiek, maar het hoeft niet te roteren
  tenzij het kanaal gecompromitteerd zou raken.

## Uitbreidbaarheid naar productie

In productie:
- Vervang de mock-webhook-URL door de echte Power Automate URL van het NOC-kanaal.
- Voeg extra routes toe voor specifieke teams (bijv. AV-techniekers voor BirdDog-alerts,
  netwerkingenieurs voor PepVPN-alerts) via label-matchers in de notification policy.
- Overweeg **PagerDuty** of **OpsGenie** als escalatiekanaal boven Teams (via Grafana
  contact points van hetzelfde type: webhook).
