# whisper_go Vision

> Eine minimalistische, Open-Source Alternative zu [Wispr Flow](https://wisprflow.ai) – systemweite Spracheingabe für macOS.

---

## Das Problem

Tippen ist langsam. Gedanken fließen schneller als Finger tippen können.

Bestehende Diktat-Tools sind:

| Tool             | Problem                              |
| ---------------- | ------------------------------------ |
| **Wispr Flow**   | $12/Monat, Cloud-only, closed source |
| **Dragon**       | Veraltet, komplex, teuer             |
| **macOS Diktat** | Eingeschränkt, nicht in allen Apps   |

## Die Lösung

**whisper_go** – ein schlankes Tool das:

1. Per **Hotkey** aktiviert wird
2. Sprache in **Text** umwandelt (via Whisper)
3. Text automatisch **einfügt**

Kein Electron. Kein Cloud-Lock-in. Kein Abo.

---

## Kern-Prinzipien

| Prinzip            | Bedeutung                    |
| ------------------ | ---------------------------- |
| **Minimalistisch** | Eine Sache gut machen        |
| **Offline-first**  | Lokale Modelle als Default   |
| **Atomar**         | Kleine, fokussierte Releases |
| **Open Source**    | Transparent, erweiterbar     |

---

## Roadmap

### Phase 1: Foundation ✅

- [x] CLI-Tool für Transkription (`transcribe.py`)
- [x] API- und lokaler Modus
- [x] Mikrofon-Aufnahme mit Enter-Toggle
- [x] Zwischenablage-Integration (`--copy`)

### Phase 2: System-Integration ✅

- [x] Raycast Extension für Hotkey-Aktivierung
- [x] Auto-Paste nach Transkription
- [x] Akustisches Feedback bei Aufnahmestart (`play_ready_sound`)
- [x] Menübar-Feedback (`menubar.py` mit rumps)

### Phase 3: Smart Features ✅

- [x] LLM-Nachbearbeitung (Füllwörter entfernen, Formatierung)
- [x] Multi-Provider Support (OpenAI, OpenRouter)
- [x] Deepgram Nova-3 Integration (schneller als Whisper API)
- [x] Deepgram WebSocket-Streaming (Echtzeit-Transkription)
- [x] Kontext-Awareness (Email formal, Chat casual, Code technisch)
- [x] Custom Vocabulary (Namen, Fachbegriffe)

### Phase 4: Native App ✅ (größtenteils)

- [x] macOS Menübar-App (`menubar.py` mit rumps)
- [x] Konfigurierbare Hotkeys (via Raycast System-Hotkey)
- [ ] Sprach-Commands ("neuer Absatz", "Punkt")
- [ ] Live-Preview (Interim-Results in Menübar anzeigen)

### Phase 4.5: Quality & Testing ✅

- [x] Unit-Tests mit pytest (124 Tests, ~0.4s)
- [x] CI/CD Pipeline (GitHub Actions auf macOS)
- [x] Code Coverage mit Codecov
- [x] Parametrisierte Tests für Wartbarkeit

### Phase 5: Multi-Platform ← aktuell

- [ ] Linux Support
- [ ] Windows Support
- [ ] iOS Keyboard (optional)

---

## Architektur

```
┌───────────────────────────────────────────────────────────┐
│                      whisper_go                           │
├──────────────┬────────────────────────────────────────────┤
│ Trigger      │ Raycast / Hotkey / CLI                     │
├──────────────┼────────────────────────────────────────────┤
│ Audio        │ sounddevice → WAV (+ Ready-Sound)          │
├──────────────┼────────────────────────────────────────────┤
│ Transkription│ Deepgram Nova-3 / OpenAI API / Whisper     │
├──────────────┼────────────────────────────────────────────┤
│ Nachbearbeit.│ GPT-5 / OpenRouter (Claude, Llama, etc.)   │
├──────────────┼────────────────────────────────────────────┤
│ Output       │ Clipboard → Auto-Paste                     │
└──────────────┴────────────────────────────────────────────┘
```

---

## Nicht-Ziele

Bewusst ausgeschlossen, um Fokus zu halten:

- ❌ Sprachsteuerung ("öffne Safari")
- ❌ Meeting-Transkription (> 5 Min)
- ❌ Team/Enterprise Features
- ❌ Eigenes Modell-Training

> **Update:** Echtzeit-Streaming ist jetzt via Deepgram WebSocket verfügbar (~300ms Latenz).

---

## Tech-Stack

| Layer  | Technologie                 | Warum                        |
| ------ | --------------------------- | ---------------------------- |
| Core   | Python 3.10+                | Whisper-Integration, einfach |
| Audio  | sounddevice                 | Cross-platform, low-level    |
| STT    | Deepgram / OpenAI / Whisper | Flexibel, best-of-breed      |
| LLM    | OpenAI / OpenRouter / Groq  | Multi-Provider für Refine    |
| Hotkey | Raycast Extension           | Native macOS Integration     |
| GUI    | rumps                       | Native macOS Menübar         |
| Test   | pytest + GitHub Actions     | CI/CD mit Coverage           |

---

## Erfolgs-Metriken

| Metrik        | Ziel                 | Status                         |
| ------------- | -------------------- | ------------------------------ |
| Latenz        | < 2s (Hotkey → Text) | ✅ ~300ms (Deepgram Streaming) |
| Genauigkeit   | > 95% (DE/EN)        | ✅ Erreicht mit Nova-3         |
| RAM (Idle)    | < 100 MB             | ✅ Kein Daemon im Idle         |
| Onboarding    | < 1 Minute           | ✅ Schnellstart in README      |
| Test-Coverage | > 60% (Core)         | ✅ 124 Tests, CI/CD aktiv      |

---

## Inspiration

- [Wispr Flow](https://wisprflow.ai) – UX-Vorbild
- [Talon Voice](https://talonvoice.com) – Accessibility-fokussiert
- [OpenAI Whisper](https://github.com/openai/whisper) – Die Engine

---

_Stand: Dezember 2025_
