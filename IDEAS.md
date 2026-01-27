# MacReplay - Ideen & Roadmap

Eine Sammlung von Verbesserungsvorschlägen und Feature-Ideen für zukünftige Entwicklung.

---

## Legende

- [ ] Offen
- [x] Erledigt
- [~] In Arbeit

---

## UI/UX Verbesserungen

### Dashboard / Übersichtsseite
- [ ] Neue Startseite mit Gesamtübersicht
- [ ] Widget: Aktive Portale, MACs, Channels Statistik
- [ ] Widget: MACs die in 7/30 Tagen ablaufen
- [ ] Widget: Zuletzt genutzte Channels
- [ ] Widget: System-Status (EPG aktuell, letzte Fehler)

### Suche & Filter
- [ ] Globale Suche über Portale, MACs und Channels
- [ ] Channels-Seite: Filter "Nur Channels ohne EPG"
- [ ] Portals-Seite: Filter "Nur ablaufende MACs"
- [ ] Channels-Seite: Favoriten markieren (Stern-Icon)

### Bulk-Operationen
- [ ] Mehrere MACs gleichzeitig auswählen und löschen
- [ ] Portal-Konfiguration exportieren (JSON)
- [ ] Portal-Konfiguration importieren
- [ ] Channels zwischen Gruppen verschieben (Drag & Drop)

### Allgemeine UI
- [ ] Responsive Design für Mobile verbessern
- [ ] Tastatur-Shortcuts (z.B. `/` für Suche)
- [ ] Sortierung der Portale per Drag & Drop
- [ ] Kompakte Ansicht für Channel-Liste

---

## Benachrichtigungen

### MAC-Ablauf-Warnungen
- [ ] E-Mail-Benachrichtigung X Tage vor Ablauf
- [ ] Konfigurierbare Warnschwellen (z.B. 30, 14, 7, 1 Tag)
- [ ] Webhook-Support für externe Services
  - [ ] Discord
  - [ ] Telegram
  - [ ] Slack
  - [ ] Generic Webhook (POST JSON)
- [ ] Browser Push-Notifications

### System-Benachrichtigungen
- [ ] Warnung wenn Portal nicht erreichbar
- [ ] Benachrichtigung bei EPG-Fehler
- [ ] Info wenn neue Channels verfügbar sind
- [ ] Tägliche/Wöchentliche Zusammenfassung per E-Mail

---

## Analytics & Monitoring

### Nutzungsstatistiken
- [ ] Channel-Popularität tracken (Aufrufe zählen)
- [ ] Bandbreitenverbrauch pro Portal/MAC
- [ ] Stream-Uptime pro Channel
- [ ] Grafiken mit Chart.js oder ähnlich

### History & Logs
- [ ] MAC-Änderungs-Historie (wann hinzugefügt/gelöscht)
- [ ] Erweitertes Log-Viewing mit Filter
- [ ] API-Zugriffs-Log
- [ ] Log-Export als Datei

---

## Technische Erweiterungen

### Multi-User Support
- [ ] Benutzerregistrierung und Login
- [ ] Rollen-System (Admin, Editor, Viewer)
- [ ] Portale bestimmten Benutzern zuweisen
- [ ] Audit-Log für alle Änderungen
- [ ] Session-Management

### API-Erweiterungen
- [ ] REST API mit Authentifizierung
- [ ] API-Dokumentation (OpenAPI/Swagger)
- [ ] Prometheus Metrics Endpoint `/metrics`
- [ ] Health-Check Endpoint `/health`
- [ ] Rate-Limiting für API

### Backup & Restore
- [ ] Manuelles Backup erstellen (Button in Settings)
- [ ] Automatische Backups (täglich/wöchentlich)
- [ ] Backup-Rotation (nur X Backups behalten)
- [ ] One-Click Restore
- [ ] Backup-Download als verschlüsselte Datei

### Performance
- [ ] Redis-Cache für häufige Abfragen
- [ ] Channel-Logo Caching lokal
- [ ] Lazy-Loading für große Channel-Listen
- [ ] Database Connection Pooling

---

## Streaming-Features

### Aufnahme / DVR
- [ ] EPG-basierte Aufnahmeplanung
- [ ] Aufnahme-Manager UI
- [ ] Speicherort konfigurierbar
- [ ] Automatisches Löschen alter Aufnahmen

### Stream-Qualität
- [ ] Qualitätsauswahl pro Channel (wenn verfügbar)
- [ ] Transkodierung für schwache Verbindungen
- [ ] Adaptive Bitrate Streaming

### Wiedergabe
- [ ] Integrierter Web-Player
- [ ] Timeshift-Funktion
- [ ] Catch-up TV Support

---

## Channel-Management

### Channel-Name Normalisierung
- [ ] Länder-Tags entfernen oder vereinheitlichen (z.B. `[DE]`, `DE:`, `🇩🇪`)
- [ ] Qualitäts-Tags normalisieren (HD, FHD, 4K, UHD → einheitliches Format)
- [ ] Unnötige Sonderzeichen und Leerzeichen entfernen
- [ ] Regelbasiertes System für Normalisierung (konfigurierbar)
- [ ] Preview vor Anwendung der Normalisierung

**Offene Fragen:**
- Wie Normalisierung konsistent halten, wenn Channels regelmäßig vom Portal aktualisiert werden?
  - Möglichkeit: Mapping-Tabelle (Original-Name → Normalisierter Name)
  - Möglichkeit: Normalisierung bei jedem Sync automatisch anwenden
- Wie EPG-Zuordnung trotz geänderter Namen sicherstellen?
  - Möglichkeit: EPG-Mapping über Channel-ID statt Name
  - Möglichkeit: Fuzzy-Matching für EPG-Zuordnung

### Event-Channels (EPG-basiert)
- [ ] Channels automatisch aus EPG-Einträgen generieren
- [ ] Beispiel: Sky Sport Bundesliga mit Spiel um 15:00 → Channel "BVB vs Bayern - 27.01 15:00"
- [ ] Mehrere Events pro Quell-Channel → mehrere Event-Channels
- [ ] Kein EPG für Event-Channels nötig (Name = Info)
- [ ] Konfigurierbare Regeln (welche Channels, welche Event-Typen)
- [ ] Automatische Löschung nach Event-Ende

### Automatische Backup-Channels
- [ ] Channels mit gleichem (normalisierten) Namen erkennen
- [ ] Automatisch als Backup-Gruppe zusammenfassen
- [ ] Failover bei Stream-Ausfall zum nächsten Backup
- [ ] Priorität per Drag & Drop festlegen

**Offene Fragen:**
- Automatisches Probing mit ffmpeg/ffprobe bei vielen Channels zu aufwendig?
  - Möglichkeit: Nur bei Wiedergabe-Start proben
  - Möglichkeit: Hintergrund-Job mit Rate-Limiting
  - Möglichkeit: Nur manuell ausgelöstes Probing

---

## Infrastruktur

### Docker
- [ ] Multi-Arch Images (ARM64 für Raspberry Pi)
- [ ] Docker Healthcheck verbessern
- [ ] Docker Compose Beispiele erweitern
- [ ] Kubernetes Helm Chart

### Deployment
- [ ] SSL/TLS Konfiguration vereinfachen
- [ ] Reverse Proxy Dokumentation
- [ ] One-Click Deploy für populäre Plattformen

---

## Dokumentation

- [ ] Benutzerhandbuch
- [ ] API-Dokumentation
- [ ] Entwickler-Setup Guide
- [ ] FAQ / Troubleshooting
- [ ] Video-Tutorials

---

## Priorisierte Roadmap

### Phase 1 - Quick Wins
1. Dashboard mit Übersicht
2. Globale Suche
3. MAC-Ablauf E-Mail-Benachrichtigungen

### Phase 2 - Core Features
4. Backup & Restore
5. Multi-User Support (Basic)
6. Webhook-Benachrichtigungen

### Phase 3 - Advanced
7. REST API
8. Analytics Dashboard
9. Aufnahme-Funktion

---

## Beitragen

Ideen und Vorschläge sind willkommen! Erstelle ein Issue oder PR auf GitHub.
