# AGENTS.md

## Zweck

Dieses Repository enthaelt eine inoffizielle Home-Assistant-HACS-Integration fuer das oesterreichische Techem Kundenportal unter `https://kundenportal.techem.at`.

Ziel der Integration:

- Login ins Kundenportal
- Laden der `devices`-Ansicht
- Abruf der letzten verfuegbaren Zaehlerstaende
- Bereitstellung als Home-Assistant-Sensoren

## Wichtiger technischer Stand

Der aktuell funktionierende Flow ist:

1. `GET /devices`
2. Login ueber das Liferay-Login-Formular
3. `GET /o/rest/resident/list-for-user?p_auth=...`
4. `GET /o/rest/meter-device/list?unit_id=...&p_auth=...`

Diese beiden Endpunkte sind die relevante und funktionierende Datenquelle:

- `/o/rest/resident/list-for-user`
- `/o/rest/meter-device/list`

## Nicht wieder aufmachen ohne guten Grund

Folgende alte Pfade waren in der Analyse enthalten, sind fuer dieses Objekt aber nicht die produktive Loesung und sollen nicht wieder als Hauptweg eingebaut werden:

- `/o/rest/meter-reading/resident-consumption-all-types`
- alte `meter-reading/*`-Listen
- `archive-rest` fuer Abrechnungs-/Dokumentenversuche

Grund:

- Consumption war serverseitig gesperrt
- Legacy-Meter-Reading lieferte keine freigegebenen Daten
- Archive/Billing war leer oder ebenfalls gesperrt

## Projektregeln

- Fokus auf clean code und DRY
- keine Zugangsdaten hardcoden
- keine alten Test-/Experimentierpfade im Produktivcode
- keine generierten JSON-Dateien oder `__pycache__`-Artefakte committen
- `.env` ist nur fuer das lokale Hilfsskript gedacht, nicht fuer Home Assistant

## Wichtige Dateien

- `custom_components/techem_at/`
  - eigentliche HACS-/Home-Assistant-Integration
- `techem_export.py`
  - lokales Hilfsskript zum Verifizieren des echten Portal-Flows
- `README.md`
  - Installations- und Nutzungsanleitung
- `.gitignore`
  - verhindert Commit von Secrets und Artefakten

## Hinweise fuer spaetere Aenderungen

- Wenn Techem den Login oder die JS-Bundles aendert, zuerst den echten Browser-Flow neu analysieren.
- Nicht blind alte Vermutungen oder fruehere Endpoint-Experimente wiederverwenden.
- Vor groesseren API-Aenderungen immer den funktionierenden Devices-Flow gegen das echte Portal verifizieren.

## Haftung / Status

- Dieses Projekt ist inoffiziell.
- Komplett vibecode.
- Ohne Gewaehr.
