# Techem AT

HACS-Custom-Integration fuer das oesterreichische Techem Kundenportal.

Die Integration loggt sich im Portal ein, liest die Seite `devices` und erzeugt aus den aktiven Geraeten Home-Assistant-Sensoren mit dem jeweils letzten verfuegbaren Zaehlerstand.

## Hinweis

Dieses Projekt ist:

- inoffiziell
- komplett vibecode
- ohne Gewaehr

Es besteht keine Verbindung zu Techem oder Home Assistant. Nutzung auf eigenes Risiko.

## Was die Integration liefert

- ein Sensor pro aktivem Geraet
- aktueller letzter Zaehlerstand als Sensor-State
- zusaetzliche Attribute wie `reading_date`, `reading_iso8601`, `device_number`, `device_type`, `device_sub_category`, `factor` und `percentage`

Wichtig:

- Die Integration nutzt bewusst nicht die gesperrten Consumption-/Billing-Endpunkte.
- Grundlage ist der funktionierende Devices-Flow mit `/o/rest/resident/list-for-user` und `/o/rest/meter-device/list`.

## Installation mit HACS

1. Repository nach GitHub pushen.
2. In Home Assistant `HACS -> Integrationen -> Benutzerdefinierte Repositories` oeffnen.
3. Die GitHub-URL dieses Repositories eintragen.
4. Kategorie `Integration` waehlen.
5. `Techem AT` in HACS installieren.
6. Home Assistant neu starten.
7. Unter `Einstellungen -> Geraete & Dienste -> Integration hinzufuegen` nach `Techem AT` suchen.
8. Techem-E-Mail, Passwort und Abrufintervall eintragen.

## Manuelle Installation ohne HACS

1. Den Ordner `custom_components/techem_at` nach `/config/custom_components/techem_at` kopieren.
2. Home Assistant neu starten.
3. Die Integration danach ueber die UI konfigurieren.

## Sensoren

Fuer jedes aktive Geraet wird ein eigener Sensor angelegt. Die Entitaetsnamen orientieren sich an Raum und Geraetetyp, zum Beispiel:

- `sensor.techem_abstellraum_heating`
- `sensor.techem_kueche_warmwasser`
- `sensor.techem_bad_warmwasser`

Die exakten Entity-IDs vergibt Home Assistant automatisch.

## Konfiguration

Die Integration wird ausschliesslich ueber den Config Flow eingerichtet. YAML-Konfiguration ist nicht noetig.

Eingaben im Dialog:

- `E-Mail`
- `Passwort`
- `Abrufintervall (Minuten)`

## Entwicklung und Test

Die eigentliche HTTP-Logik steckt in `custom_components/techem_at/techem_api.py`. Fuer einen lokalen Portal-Test ohne Home Assistant gibt es das Hilfsskript `techem_export.py`.

Syntax-Pruefung:

```bash
python3 -m compileall custom_components/techem_at
python3 -m py_compile techem_export.py
```

## Lizenz

Dieses Repository steht unter der MIT-Lizenz. Siehe `LICENSE`.
