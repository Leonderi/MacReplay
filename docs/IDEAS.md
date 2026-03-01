# MacReplay - Ideen & Roadmap

Eine Sammlung von Verbesserungsvorschlägen und Feature-Ideen für zukünftige Entwicklung.

---

## Legende

| Status | Bedeutung |
| --------| -----------|
| ⬜　　　| Offen     |
| ✅　　　| Erledigt  |
| 🔄　　 | In Arbeit |

---

## UI/UX Verbesserungen

### Dashboard / Übersichtsseite
- ✅ Dashboard als Landingpage + im Menü ganz links
- ✅ Widget-Row: Aktive Streams/Clients, Portale, Channels, Groups, letzter EPG-Refresh
- ✅ Widget: MACs/Logins die in 7/30 Tagen ablaufen
- 🔄 Widget: Zuletzt genutzte Channels
- 🔄 Widget: System-Status (EPG aktuell, letzte Fehler)
- ✅ Widget: Most Used Portals (nur aktive Streams)
- ✅ Widget: Stream-Dauer pro MAC (nur aktive Streams)
- ✅ Widget: Most Failed MACs (24h)
- ✅ Widget: Most Reliable Channels (24h, basierend auf Erfolgsquote)
- ✅ Widget: Letzter Speedtest (Proxy + Direct) inkl. IP/Land/Latenz/Download + manueller Test-Button
- ✅ Periodischer Speedtest per zentralem Settings-Intervall + Provider-Auswahl (HTTP/Ookla falls installiert)
- ✅ Persistente Dashboard-Statistiken (24h Auswertung über DB-Events)
- ✅ Aktive Event-Streams zeigen Original-Quelle (Portal + Channel) im Dashboard
- ✅ Dashboard zeigt Tags des Original-Channels bei Event-Streams
- ✅ Grouped-Play Stabilisierung: EOF-Backoff pro Portal/Channel mit exponentiellem Retry-Abstand
- ✅ Persistenter Stream-Backoff (Channel+Portal) für stabileres Failover nach Neustarts
- ✅ Grouped-Play Ranking berücksichtigt EOF-Historie (24h/30m), um instabile Kandidaten später zu probieren
- ✅ Health-basiertes Ranking mit längerem Fenster (konfigurierbar): stabile Portale/MACs/Channels werden upgevotet, fehlerhafte downgevotet
- ✅ Grouped-Play Ranking berücksichtigt Portal/Channel-Startlatenz (time-to-first-chunk)
- ✅ Background-Check für Stalker-MACs (Intervall in Settings), abgelaufene/unerreichbare MACs werden markiert und beim Streamen übersprungen
- ✅ Globaler Proxy (optional/forciert) für Portal-Anfragen + Proxy-Test (öffentliche IP + Download-Probe)
- ✅ Streamstart optimiert: cached `cmd/link` wird bevorzugt, `getAllChannels` nur noch bei Bedarf/Forced Refresh

### Suche & Filter
- ⬜ Globale Suche über Portale, MACs und Channels
- ⬜ Channels-Seite: Filter "Nur Channels ohne EPG"
- ⬜ Portals-Seite: Filter "Nur ablaufende MACs"
- ⬜ Channels-Seite: Favoriten markieren (Stern-Icon)
- ✅ Channel-Editor: Tag-Filter (Resolution/Video/Country/Event) + Tri-State RAW/EVENT/HEADER
- ✅ Channel-Editor: Buttons für Resolution/Misc + HEVC Toggle
- ✅ Channel-Editor: MATCH-Filter

### Bulk-Operationen
- ⬜ Mehrere MACs gleichzeitig auswählen und löschen
- ⬜ Portal-Konfiguration exportieren (JSON)
- ⬜ Portal-Konfiguration importieren
- ⬜ Channels zwischen Gruppen verschieben (Drag & Drop)

### Genre/Gruppen-Auswahl beim Portal-Hinzufügen
- ✅ **Genre-Auswahl beim Hinzufügen eines Portals**
  - 2-Schritt Wizard: Erst Portal-Info, dann Genre-Checkboxen
  - API-Endpunkt `/api/portal/genres` holt verfügbare Genres vom Portal
  - ✅ Implementiert: Nur ausgewählte Genres werden beim Channel-Sync importiert

- ✅ **Genre-Auswahl beim Bearbeiten eines Portals**
  - Button "Load Genres" im Edit-Modal
  - Bestehende Genre-Auswahl wird beibehalten
  - ✅ Implementiert: Genre-Filter kann jederzeit geändert werden

- ✅ **Groups-Tabelle für schnelles Umschalten**
  - Neue `groups` DB-Tabelle mit `active` Flag
  - ALLE Channels werden in DB gespeichert (kein Genre-Filter beim Import)
  - Genre de/aktivieren ändert nur `groups.active` - kein Re-Import nötig
  - Groups werden aus DB geladen (schnell) statt Portal-API
  - Stats zeigen `active / total` für Channels und Groups
  - ✅ Modal-API: `/api/portal/groups` (DB) + `/api/portal/genres/list` (Fallback)

### Portal-Import aus Textdateien
- ⬜ Import von Portalen aus formatierten Scan-Ergebnis-Dateien
- ⬜ Automatische Erkennung von Portal-URL und MAC-Adresse
- ⬜ Optional: Ablaufdatum extrahieren
- ⬜ Mehrere Portale pro Datei unterstützen
- ⬜ Preview vor Import (welche Portale erkannt wurden)
- ⬜ Duplikat-Erkennung (Portal+MAC bereits vorhanden)

**Beispiel-Eingabeformat:**
```
🌐 Panel     ➤ http://example.com:80/c/
🔢 MAC Addr  ➤ 00:1A:79:2D:24:01
📆 Expiração = 24-04-2026 [89 dias]
```

**Erkennungs-Patterns:**
```python
patterns = {
    'url': r'(?:Panel|Server|URL|Host)\s*[➤:=]\s*(https?://[^\s]+)',
    'mac': r'(?:MAC\s*Addr|MAC)\s*[➤:=]\s*([0-9A-Fa-f:]{17})',
    'expiry': r'(?:Expir|Ablauf|Exp)\w*\s*[=:]\s*(\d{2}-\d{2}-\d{4})',
}
```

### Allgemeine UI
- ⬜ Responsive Design für Mobile verbessern
- ⬜ Tastatur-Shortcuts (z.B. `/` für Suche)
- ⬜ Sortierung der Portale per Drag & Drop
- ✅ Favicon im Browser-Tab
- ✅ Playlist-Export optional als gruppierte Single-Channel-Variante (zusätzlich zu per-Portal)
- ✅ Settings neu strukturieren (Side-Nav + mehrere Seiten, klare Sektionen)
- ⬜ Settings: Globale Portal-Defaults in Settings, Portal-Verwaltung bleibt in `/portals`
- ✅ Kompakte Ansicht für Channel-Liste
- ✅ Editor zeigt nur Channels aus aktivierten Portalen
- ✅ Editor: Aufklappbare Subline mit Match-Details + EPG-ID Edit
- ✅ Editor: Logo aus Match in Subline (nur wenn gematched)
- ✅ Editor: Nummer-Spalte vor Name, EPG-ID aus Hauptzeile entfernt
- ✅ Editor: EPG-Quelle im Vorschlags-Dropdown + Hinweis neben EPG-ID
- ✅ Editor: EPG-Refresh pro Channel (Button in der Subline)
- ✅ Editor: EPG-Refresh für geänderte EPG-IDs nach Save
- ⬜ Editor: Subline Inhalte konfigurierbar (ein-/ausblenden)
- 🔄 Editor: Gruppierung gleicher Channels (Match + Tags) + Bulk-Edit für Gruppe
  - ✅ Event-Channels werden auch ohne `matched_name` gruppiert

### Tagging & Name Normalisierung
- ✅ Auto-Normalisierung pro Portal (optional)
- ✅ Auto-Namen in eigenes Feld (`auto_name`) speichern
- ✅ Tag-Extraktion mit Settings-Patterns (Resolution/Codec/Audio/Country/Event/Header)
- ✅ Event-Tags (z.B. PPV/NO EVENT) separat speichern und filterbar
- ✅ NO EVENT / NO EVENT STREAMING im Editor über gelb gefärbtes EVENT anzeigen
- ✅ Reset-Button für Tag-Patterns in den Settings
- ⬜ Regeln/Regex pro Portal oder Portal-Gruppe
- 🔄 Matching: Name vor Match leicht bereinigen (Country + Quality+Suffix abschneiden)

### EPG & Quellen
- ✅ Settings: EPG-Quellen verwalten (Add/Enable/Interval/Refresh/Remove)
- ✅ XMLTV (.xml/.gz) Download + lokal cachen
- ✅ Editor: EPG-ID Vorschläge per Channel-Map
- ✅ Editor: EPG-Quelle anzeigen (Dropdown + Hinweis)
- ✅ Editor: EPG-Refresh pro Channel
- ✅ Editor: EPG-Refresh nach EPG-ID Änderung beim Speichern
- ✅ EPG-Refresh bei Portal-Refresh nur für dieses Portal
- ✅ Partial-EPG-Rewrite: Channel-Metadaten bleiben im `<channel>` (keine losen display-name/icon)
- ✅ Besseres EPG-Logging beim Portal-Fetch (Status/Empty/JSON-Fehler)
- ⬜ EPG-Refresh Queue/Retry statt "already running" Fehler
- 🔄 Hybrid-EPG: Zentrale Channel-Metadaten + Programme pro Quelle in eigener DB

---

## Benachrichtigungen

### MAC-Ablauf-Warnungen
- ⬜ E-Mail-Benachrichtigung X Tage vor Ablauf
- ⬜ Konfigurierbare Warnschwellen (z.B. 30, 14, 7, 1 Tag)
- ⬜ Webhook-Support für externe Services
  - ⬜ Discord
  - ⬜ Telegram
  - ⬜ Slack
  - ⬜ Generic Webhook (POST JSON)
- ⬜ Browser Push-Notifications

### System-Benachrichtigungen
- ⬜ Warnung wenn Portal nicht erreichbar
- ⬜ Benachrichtigung bei EPG-Fehler
- ⬜ Info wenn neue Channels verfügbar sind
- ⬜ Tägliche/Wöchentliche Zusammenfassung per E-Mail

---

## Analytics & Monitoring

### Erweiterte MAC-Informationen (inspiriert von macreplay)
Die Stalker Portal API liefert via `?type=stb&action=get_profile` zusätzliche Informationen:

- ✅ **Max Streams anzeigen** (`playback_limit`)
  - Zeigt wie viele gleichzeitige Streams pro MAC erlaubt sind
  - In der MAC-Übersicht als Spalte darstellen
  - ✅ Implementiert: Wird beim Hinzufügen/Aktualisieren eines Portals abgerufen und in der MAC-Tabelle angezeigt

- ✅ **Watchdog Timeout anzeigen** (`watchdog_timeout`)
  - Zeigt Sekunden seit letzter Aktivität der MAC-Adresse
  - Interpretation:
    - < 60s = Sehr aktiv (🔴 gerade am Streamen)
    - 60-300s = Aktiv (🟡 kürzlich benutzt)
    - 300-1800s = Moderate Aktivität (🔵)
    - > 1800s = Idle (🟢 sicher zu benutzen)
  - ✅ Implementiert: Farbkodierte Badges in der MAC-Übersicht

- ⬜ **MAC-Status-Prüfung**
  - Button "Status prüfen" für einzelne MACs oder alle MACs eines Portals
  - Zeigt: Watchdog, Max Streams, Account-Status, Ablaufdatum
  - Hilft zu erkennen, ob eine MAC gerade von jemand anderem genutzt wird

- ✅ **Intelligente MAC-Auswahl**
  - Automatisch die "beste" MAC für einen Stream wählen
  - ✅ Implementiert: Scoring basierend auf Watchdog (idle bevorzugen) und verfügbare Streams
  - MACs werden vor dem Streaming nach Score sortiert

**Referenz:** Siehe `/host_opt/macreplay/stb.py` Zeilen 1522-1732 für Implementation

### Nutzungsstatistiken
- ⬜ Channel-Popularität tracken (Aufrufe zählen)
- ⬜ Bandbreitenverbrauch pro Portal/MAC
- ⬜ Stream-Uptime pro Channel
- ⬜ Grafiken mit Chart.js oder ähnlich

### History & Logs
- ⬜ MAC-Änderungs-Historie (wann hinzugefügt/gelöscht)
- 🔄 Erweitertes Log-Viewing mit Stream-Exit-Gründen (disconnect/error/eof), Dauer und FFmpeg-RC
- ⬜ API-Zugriffs-Log
- ⬜ Log-Export als Datei

---

## Technische Erweiterungen

### Datenbank & Schema
- ✅ Channels-Tabelle aufgeräumt (fallback_channel/audio_tags entfernt, Spalten gruppiert)

### Multi-User Support
- 🔄 Access-Users mit Flags (enabled/web/admin/m3u/xc) in Settings
- ⬜ Benutzerregistrierung und Login
- ⬜ Rollen-System (Admin, Editor, Viewer)
- ⬜ Portale bestimmten Benutzern zuweisen
- ⬜ Audit-Log für alle Änderungen
- ⬜ Session-Management

### API-Erweiterungen
- ⬜ REST API mit Authentifizierung
- ⬜ API-Dokumentation (OpenAPI/Swagger)
- ⬜ Prometheus Metrics Endpoint `/metrics`
- ⬜ Health-Check Endpoint `/health`
- ⬜ Rate-Limiting für API

### Backup & Restore
- ⬜ Manuelles Backup erstellen (Button in Settings)
- ⬜ Automatische Backups (täglich/wöchentlich)
- ⬜ Backup-Rotation (nur X Backups behalten)
- ⬜ One-Click Restore
- ⬜ Backup-Download als verschlüsselte Datei

### Performance
- ⬜ Redis-Cache für häufige Abfragen
- ⬜ Channel-Logo Caching lokal
- ⬜ Lazy-Loading für große Channel-Listen
- ⬜ Database Connection Pooling
- ✅ ChannelsDVR Cache persistiert auf Disk (pro Land)
- 🔄 ChannelsDVR Cache: Migration/Kompatibilität prüfen
- ✅ Adaptive Link-Cache-TTL pro Stalker-Portal (Auto-Tuning bei 401/403)

---

## Settings UX

- ✅ Settings-Menü neu strukturieren (Abschnitte gruppieren, klarere Labels)
- ✅ Linke Navigation oder Tabs für schnelle Orientierung
- ⬜ Suchfeld für Settings (Filterung nach Label/Keyword)
- ⬜ Zusammenfassung oben (z. B. aktive Scheduler, letzter Refresh, DB-Status)
- ⬜ „Danger Zone“ klar getrennt (Reset, Delete, Vacuum, etc.)
- ✅ Einheitliche Bestätigungs-Modal-UX für alle Aktionen
- ⬜ Kontext-Hilfen/Tooltips für komplexe Felder
- ⬜ Inline-Validierung und bessere Fehlermeldungen
- ⬜ Settings: Auto-Group-Selection visuell erklären (Beispiele/Preview)
- ✅ Settings: Auto-Group-Selection (Patterns) + Button "Lade Standarts" in Gruppen-Modal

---

## Streaming-Features

### Aufnahme / DVR
- ⬜ EPG-basierte Aufnahmeplanung
- ⬜ Aufnahme-Manager UI
- ⬜ Speicherort konfigurierbar
- ⬜ Automatisches Löschen alter Aufnahmen

### Stream-Qualität
- ⬜ Qualitätsauswahl pro Channel (wenn verfügbar)
- ⬜ Transkodierung für schwache Verbindungen
- ⬜ Adaptive Bitrate Streaming

### Wiedergabe
- ⬜ Integrierter Web-Player
- ⬜ Timeshift-Funktion
- ⬜ Catch-up TV Support

---

## Channel-Management

### Channel-Name Normalisierung
- ⬜ Länder-Tags entfernen oder vereinheitlichen (z.B. `[DE]`, `DE:`, `🇩🇪`)
- ⬜ Qualitäts-Tags normalisieren (HD, FHD, 4K, UHD → einheitliches Format)
- ⬜ Unnötige Sonderzeichen und Leerzeichen entfernen
- ⬜ Tag-Extraktion beim Import: Auflösung, Audio-Codec, Video-Codec, Country-Code in strukturierte Felder speichern
- ⬜ Bereinigter Name in `custom_name` sichern, Originalname bleibt in `name`
- ⬜ Regex-Regeln in Settings pro Tag-Gruppe konfigurierbar (z.B. resolution/audio/video/country)
- ⬜ Option: Normalisierung automatisch beim Import/Sync ausführen
- ⬜ Regelbasiertes System für Normalisierung (konfigurierbar)
- ⬜ Preview vor Anwendung der Normalisierung

**Offene Fragen:**
- Wie Normalisierung konsistent halten, wenn Channels regelmäßig vom Portal aktualisiert werden?
  - Möglichkeit: Mapping-Tabelle (Original-Name → Normalisierter Name)
  - Möglichkeit: Normalisierung bei jedem Sync automatisch anwenden
- Wie EPG-Zuordnung trotz geänderter Namen sicherstellen?
  - Möglichkeit: EPG-Mapping über Channel-ID statt Name
  - Möglichkeit: Fuzzy-Matching für EPG-Zuordnung

### Event-Channels (EPG-basiert)
- ✅ Channels automatisch aus EPG-Einträgen generieren
- 🔄 Mehrere Events pro Quell-Channel → mehrere Event-Channels
- ⬜ Kein EPG für Event-Channels nötig (Name = Info)
- ✅ Konfigurierbare Regeln (welche Channels, welche Event-Typen)
- ✅ Automatische Löschung nach Event-Ende
- ✅ Beim Deaktivieren eines Portals werden dessen Event-Channels automatisch deaktiviert

### Event-Channels (ESPN)
- 🔄 ESPN-Provider: Sport/Liga-Auswahl, Upcoming-Events, Output-Template, Preview
- 🔄 Matching von ESPN-Events gegen EPG (inkl. Zeitfenster)
- ✅ Liga-Codes erweitert (u.a. `ger.2`, `ger.dfb_pokal`)

**EPG-Muster Beispiele:**
```
Eishockey:
  Titel: "LIVE: Augsburger Panther - Eisbären Berlin"
  Text:  "Augsburger Panther - Eisbären Berlin, PENNY DEL, Spieltag 44"

Fußball:
  Titel: "Live BL: Werder Bremen - TSG Hoffenheim, Nachholspiel vom 16. Spieltag"
```

**Regel-Konfiguration (Konzept):**
```yaml
event_rules:
  - name: "Bundesliga"
    channels:
      - "Sky Sport Bundesliga*"
      - "Sky Sport Top Event"
    pattern: "Live.*BL:|Bundesliga"
    extract: "(?P<home>.+?) - (?P<away>.+?),"
    output: "{home} vs {away} | {date} {time}"

  - name: "DEL Eishockey"
    channels:
      - "Sport1*"
      - "MagentaSport*"
    pattern: "LIVE:.*DEL|PENNY DEL"
    extract: "(?P<home>.+?) - (?P<away>.+)"
    output: "{home} vs {away} | DEL | {date} {time}"
```

**Generiertes Ergebnis:**
```
Original-Channel: Sky Sport Bundesliga 1
EPG-Eintrag:      "Live BL: Werder Bremen - TSG Hoffenheim" @ 15:30

→ Event-Channel:  "Werder Bremen vs Hoffenheim | 27.01 15:30"
                  (verlinkt auf Sky Sport Bundesliga 1)
```

### Automatische Backup-Channels
- ⬜ Channels mit gleichem (normalisierten) Namen erkennen
- ⬜ Automatisch als Backup-Gruppe zusammenfassen
- ✅ Grouped-Playback Failover im gleichen Client-Request (bei EOF auf nächsten Kandidaten wechseln)
- ⬜ Priorität per Drag & Drop festlegen

**Offene Fragen:**
- Automatisches Probing mit ffmpeg/ffprobe bei vielen Channels zu aufwendig?
  - Möglichkeit: Nur bei Wiedergabe-Start proben
  - Möglichkeit: Hintergrund-Job mit Rate-Limiting
  - Möglichkeit: Nur manuell ausgelöstes Probing

---

## Infrastruktur

### Docker
- ⬜ Multi-Arch Images (ARM64 für Raspberry Pi)
- ⬜ Docker Healthcheck verbessern
- ⬜ Docker Compose Beispiele erweitern
- ⬜ Kubernetes Helm Chart

### Deployment
- ⬜ SSL/TLS Konfiguration vereinfachen
- ⬜ Reverse Proxy Dokumentation
- ⬜ One-Click Deploy für populäre Plattformen

---

## Dokumentation

- ⬜ Benutzerhandbuch
- ⬜ API-Dokumentation
- ⬜ Entwickler-Setup Guide
- ⬜ FAQ / Troubleshooting
- ⬜ Video-Tutorials

---

## Portal Types

- ✅ Xtream Codes Portale integriert (zusätzlicher Portal-Typ neben Stalker/MAC)
  - ✅ Login via `player_api.php`
  - ✅ Kategorien/Streams/EPG ins bestehende Schema gemappt
  - ✅ UI um Xtream-Felder erweitert (URL, mehrere Logins, User-Agent, Proxy)
  - ✅ Hintergrund-Login-Checks + Markierung invalider Logins (z. B. 403)
  - 🔄 Feinschliff bei Mapping/UX und Fehlerfällen

---

## Priorisierte Roadmap

### Phase 1 - Quick Wins
1. ✅ Xtream Codes Basis integriert (inkl. Player API, mehrere Logins, User-Agent)
2. ✅ Event-Channel Auto-Create + Cleanup Scheduler
3. 🔄 Dashboard-Übersicht erweitern (weitere Widgets/Stats)
4. 🔄 Editor/Filter Stabilität & Performance weiter verbessern
5. ⬜ Globale Suche über Portale/MACs/Channels

### Phase 2 - Core Features
1. 🔄 Multi-User Support (Access-Flags vorhanden, Rollenmodell ausbauen)
2. ⬜ Backup & Restore
3. ⬜ Webhook-/Mail-Benachrichtigungen (EPG/Portal/MAC)
4. ⬜ Settings-Suche + bessere Inline-Validierung

### Phase 3 - Advanced
1. ⬜ REST API + OpenAPI
2. ⬜ Analytics Dashboard
3. ⬜ Aufnahme-Funktion / DVR

---

## Beitragen

Ideen und Vorschläge sind willkommen! Erstelle ein Issue oder PR auf GitHub.
