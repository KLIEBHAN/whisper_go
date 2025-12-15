# ADR-002: Windows-Strategie – Portieren vs. Separate App

**Status:** Accepted  
**Datum:** 2025-12-15  
**Kontext:** Multi-Platform Ziel (siehe `docs/VISION.md`)

## Fragestellung

Die macOS-Version von PulseScribe wurde in den letzten Iterationen stark verfeinert (Daemon, Menübar, Overlay, Hotkeys). Windows-Support war geplant, wurde aber mehrfach verschoben. Jetzt stellt sich die strategische Frage:

1. **Option A:** **Ein Repo** mit **Shared Core** und **plattformspezifischen Frontends** (Hybrid-Ansatz innerhalb derselben Codebase).
2. **Option B:** Eine **separate** Windows-App bauen und die macOS-App nur als Referenz nutzen.

## Ausgangslage (heute)

- Der **Kern** (Provider: OpenAI/Deepgram/Groq/Local, Refine-Pipeline, Konfiguration, Audio-Handling) ist weitgehend **plattformneutral**.
- Es existiert eine OS-Abstraktionsschicht `whisper_platform/` (u.a. Sound/Clipboard/App-Detection/Daemon/Hotkey). **Windows-Code ist teilweise vorhanden**, aber **nicht als Windows-Produkt validiert** (insb. Daemon/IPC muss noch end-to-end “verdrahtet” werden).
- Die “Native App”-Teile sind **macOS-spezifisch** (`ui/` via PyObjC/rumps, `pulsescribe_daemon.py` mit NSApplication-Loop).
- Die bisherige Windows-Aufwandsanalyse geht von **~80–120h** (Standard) bis **~120–150h** (voll) aus (`docs/WINDOWS_ANALYSIS.md`) und ist als **Baseline für erfahrene Umsetzung** zu verstehen.

**Einordnung (Best/Baseline/Worst Case):**

| Szenario       | Aufwand | Annahmen                                                            |
| -------------- | ------- | ------------------------------------------------------------------- |
| **Best Case**  | ~80h    | Keine Überraschungen, klare MVP-Scope, erfahrener Windows-Dev       |
| **Baseline**   | ~120h   | Übliche Bugs/Edge-Cases, Packaging/CI “normal”                      |
| **Worst Case** | ~180h   | Hotkey-Konflikte, AV/SmartScreen-Themen, UI/Overlay-Implementierung |

## Entscheidungskriterien

Wir bewerten nach:

1. **Time-to-First-Windows-Release** (MVP-Tempo)
2. **Langfristige Wartbarkeit** (Bugfixes/Features nur einmal bauen)
3. **Divergenz-Risiko** (v.a. Bugfixes/Defaults/Edge-Cases im Core; UI darf/soll divergieren)
4. **UX-Fit** (Windows braucht eigene Tray/Overlay/Hotkey-Mechanik)
5. **Build/Release Aufwand** (CI, Packaging, Installer, Signierung)
6. **Regressionsrisiko für macOS** (Refactors vs. additive Änderungen)

**Divergenz-Schmerzpunkte (absteigend):**

1. **Hoch:** Provider- und Error-Handling (Retries, Timeout-Defaults, Rate-Limits, Netzwerk-Edge-Cases)
2. **Mittel:** Refine-Prompts/Voice-Commands (neue Regeln müssen auf beiden Plattformen konsistent sein)
3. **Niedrig:** UI/UX (bewusst plattformspezifisch)

## Optionen

### Option A: Shared Core + separate Frontends (ein Repo)

**Kernaussage:** Gemeinsamer Core bleibt identisch; nur OS-Integration + UI werden pro Plattform implementiert.

**Vorteile**

- Maximale Wiederverwendung: Provider/Refine/Config/Tests bleiben **eine** Wahrheit.
- Geringeres Divergenz-Risiko: Fixes an Streaming/Prompts/Edge-Cases wirken auf beide Plattformen.
- Passt zur aktuellen Code-Richtung: `whisper_platform/` existiert bereits.

**Nachteile**

- UI/Daemon müssen auf Windows **trotzdem** neu gebaut werden (Tray/Overlay/Hotkeys sind nicht portierbar).
- Höhere Architektur-Disziplin nötig: harte Trennung “Core vs. Plattform” konsequent durchziehen, damit Windows nicht ständig macOS-Imports “anfasst”.
- Potenzielles macOS-Regressionsrisiko, **wenn** Windows-Support nur über größere Refactors erreichbar wäre (sollte vermieden werden).

### Option B: Separate Windows-App (neues Projekt)

**Kernaussage:** Windows bekommt eine eigenständige Codebase; macOS dient als “Blueprint”.

**Vorteile**

- Volle Freiheit für Windows-native Tech/UX (z.B. WinUI/WPF) ohne Rücksicht auf macOS-Strukturen.
- Risikoarme macOS-Weiterentwicklung: Windows-Experimente “stören” nicht.

**Nachteile**

- Doppelter Wartungsaufwand: Provider-Details, Prompt-Engineering, Config-Defaults, Bugfixes werden schnell **zweimal** implementiert.
- Divergenzgefahr ist **real**, aber in der Praxis oft **mittel**: Provider-APIs sind stabil, UI ist bewusst plattformspezifisch; schmerzhaft wird Duplikation v.a. bei Bugfixes/Edge-Cases/Defaults.
- Falls trotzdem “Core teilen” gewünscht ist, entsteht oft ein dritter Layer (IPC/Service/CLI-Bridge) → zusätzliche Komplexität.

**Variante (Option B2):** Separate App **zuerst**, Shared Core **später** (YAGNI)

- Kann sinnvoll sein bei **hohem Zeitdruck** oder **sehr niedriger Risikotoleranz** (macOS soll garantiert unberührt bleiben).
- Sollte ein klares Exit-Signal haben: sobald beide Apps aktiv gepflegt werden und Core-Änderungen häufiger werden, wird ein Shared-Core-Paket (oder ein Repo mit `core/` + 2 Frontends) wirtschaftlich.

## Bewertung (Kurzfazit)

- **Wenn** Windows “ein zweites Produkt” mit komplett anderer Tech-Stack-Strategie werden soll (z.B. C#/WinUI, eigener Installer-Flow, eigenes Release-Team), dann ist **Option B** plausibel.
- Für das aktuelle Projekt (Python-Core, vorhandene Tests, bestehende Plattform-Abstraktion, Ziel: Feature-Parität) ist **Option A** in Summe klar günstiger.

## Empfehlung (Entscheidung)

**Wir verfolgen Option A: Shared Core + separate Frontends (ein Repo).**

Das heißt konkret:

- **Core bleibt plattformneutral** (Provider/Refine/Config/Audio-Pipeline).
- **OS-Integration** läuft ausschließlich über `whisper_platform/` (Clipboard/App-Detection/Sound/Daemon/Hotkey).
- **UI/Daemon sind pro Plattform separat** (macOS: bestehend; Windows: eigener Tray/Overlay/Hotkey-Loop), ohne den Anspruch, UI-Code “wiederzuverwenden”.

Diese Variante liefert den Hauptnutzen von “ein Projekt” (kein doppelter Core, keine Prompt-Divergenz), akzeptiert aber, dass Windows trotzdem eine eigene UI-Schicht braucht.

## Konsequenzen

- Wir brauchen eine klare “Capability-Matrix”: was ist auf Windows im MVP wirklich Pflicht (z.B. Hotkey + Aufnahme + Paste), was ist “nice to have” (Glass/Animations-Overlay).
- Wir müssen CI mittelfristig als Matrix fahren (macOS + Windows), damit Portabilität nicht wieder “weggedriftet”.
- Windows-Release-Risiken (SmartScreen, Antivirus, Code-Signing) werden ein eigenes Arbeitspaket; sie sprechen **nicht** gegen eine gemeinsame Codebase, aber gegen “schnell mal nebenbei”.

### CI-Matrix (Timing)

- **Kurzfristig (MVP):** Windows-Tests manuell/auf VM, macOS-CI bleibt bestehen.
- **Nach MVP:** GitHub Actions Matrix (macOS + Windows) für `whisper_platform/` + Core.
- **Trigger:** Sobald der erste Windows-User produktiv nutzt oder Windows-Fixes häufiger werden.

### Aufwandspuffer (Distribution)

Zusätzlich zur reinen Implementierung ist für Windows erfahrungsgemäß ein eigenes Paket nötig (Richtwert **+8–15h** plus Wartezeit):

- Code-Signing (Zertifikat + Setup)
- CI/Build-Pipeline fürs Signieren
- SmartScreen-/Reputation-Themen (nicht nur Code)
- Antivirus-False-Positives / Ausnahme-Handling

### MVP Exit-Kriterien (Windows)

- [ ] Globaler Hotkey startet/stoppt Aufnahme zuverlässig
- [ ] Deepgram-Streaming oder gewählter Provider funktioniert reproduzierbar
- [ ] Ergebnis landet in Clipboard und kann optional auto-pasten
- [ ] Tray/Status-Feedback (mindestens: Recording/Done/Error)
- [ ] Installer/Exe läuft ohne SmartScreen-/AV-Blocker (so weit realistisch ohne Reputation)

### Guardrails (macOS schützen)

- Windows-Entwicklung ist **additiv**: keine großen Refactors “für Windows”, solange es einen MVP-Pfad gibt.
- macOS-spezifische Imports bleiben in macOS-Modulen; Plattformlogik nur über `whisper_platform/`.
- Release-Ziel für Windows ist zunächst **funktional**, nicht “UI/UX-Parität”.

## Nächste Schritte (MVP-orientiert)

1. **Windows-MVP definieren** (Ziel: nutzbar, nicht “perfekt”): Hotkey → Record → Transcribe → Paste/Clipboard, optional Tray-Status.
2. **Windows-Entry-Point** klar trennen (separater Daemon/Runner statt `pulsescribe_daemon.py` 1:1 zu portieren).
3. **UI später**: erst funktional (Tray + minimal Overlay), dann kosmetisch (Acrylic/Animation).

## Revisit-Kriterien (Pivot erlauben)

Wir prüfen Option B/B2 erneut, wenn:

- Windows eine klar andere Tech-Strategie verlangt (z.B. C#/WinUI statt Python-UI) und das gemeinsame Repo mehr bremst als hilft.
- Der Windows-Port nur durch invasive Änderungen am macOS-Produkt möglich wäre.
- Die Pflege von zwei Frontends + Shared-Core im selben Repo organisatorisch nicht funktioniert.
