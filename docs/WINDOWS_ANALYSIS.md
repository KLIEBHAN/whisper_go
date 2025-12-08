# Windows-Support Aufwandsanalyse für whisper_go

> **Ziel:** Bewertung des Aufwands, whisper_go auf Windows zu portieren

---

## Executive Summary

| Aspekt                | Bewertung                                     |
| --------------------- | --------------------------------------------- |
| **Gesamtaufwand**     | 80–120 Stunden                                |
| **Kritische Blocker** | 2 (Overlay-Glaseffekt, Daemon-Fork)           |
| **Machbarkeit**       | ✅ Gut – Kern ist bereits plattformunabhängig |
| **Empfehlung**        | Phasenweise Portierung mit Feature-Parität    |

---

## 1. Architektur-Übersicht

```
┌─────────────────────────────────────────────────────────────┐
│                      whisper_go                              │
├──────────────────┬──────────────────────────────────────────┤
│ Komponente       │ macOS-Abhängigkeit                       │
├──────────────────┼──────────────────────────────────────────┤
│ Transkription    │ ✅ Plattformunabhängig (REST/WebSocket)  │
│ LLM-Refine       │ ✅ Plattformunabhängig (OpenAI/Groq)     │
│ Audio-Aufnahme   │ 🟡 sounddevice (PortAudio-Backend)       │
│ Sound-Playback   │ 🔴 CoreAudio / AudioToolbox              │
│ App-Detection    │ 🔴 NSWorkspace (PyObjC)                  │
│ Daemon/IPC       │ 🔴 os.fork + SIGUSR1                     │
│ Overlay UI       │ 🔴 PyObjC (NSWindow, CALayer)            │
│ Menübar          │ 🔴 rumps (macOS-only)                    │
│ Hotkey-Trigger   │ 🔴 Raycast (macOS-only)                  │
└──────────────────┴──────────────────────────────────────────┘
```

**Legende:** ✅ Funktioniert | 🟡 Anpassung nötig | 🔴 Neu implementieren

---

## 2. Komponenten-Analyse

### 2.1 Transkription & LLM (✅ Keine Änderung)

| Funktion                            | Status | Begründung              |
| ----------------------------------- | ------ | ----------------------- |
| `transcribe_with_api()`             | ✅     | OpenAI REST-API         |
| `transcribe_with_deepgram()`        | ✅     | Deepgram REST-API       |
| `transcribe_with_deepgram_stream()` | ✅     | WebSocket (asyncio)     |
| `transcribe_with_groq()`            | ✅     | Groq REST-API           |
| `transcribe_locally()`              | ✅     | OpenAI Whisper (Python) |
| `refine_transcript()`               | ✅     | LLM-API (OpenAI/Groq)   |

**Aufwand:** 0 Stunden

---

### 2.2 Audio-Aufnahme (🟡 Minimale Anpassung)

**Aktuell (macOS):**

```python
import sounddevice as sd
with sd.InputStream(samplerate=16000, channels=1, dtype="float32"):
    ...
```

**Windows-Status:**

- `sounddevice` nutzt PortAudio → funktioniert auf Windows
- `soundfile` für WAV-Export → plattformunabhängig
- Externe Abhängigkeit: PortAudio muss installiert sein

**Anpassungen:**

1. Installation: `pip install sounddevice` (Windows-Binaries enthalten)
2. Dokumentation für Windows-Setup

**Aufwand:** 2–4 Stunden

---

### 2.3 Sound-Playback (🔴 Neu implementieren)

**Aktuell (macOS):** `transcribe.py:203-364`

```python
class _CoreAudioPlayer:
    # Nutzt AudioToolbox.framework via ctypes
    # Fallback: afplay (macOS CLI)
```

**Windows-Alternativen:**

| Option                 | Latenz | Komplexität | Empfehlung   |
| ---------------------- | ------ | ----------- | ------------ |
| `winsound.PlaySound()` | ~50ms  | Niedrig     | ⭐ Empfohlen |
| `pygame.mixer`         | ~20ms  | Mittel      | Alternative  |
| `playsound`            | ~100ms | Niedrig     | Fallback     |
| DirectSound (ctypes)   | ~5ms   | Hoch        | Overkill     |

**Implementierung:**

```python
# platform_sound.py
if sys.platform == "win32":
    import winsound
    SOUNDS = {
        "ready": "SystemAsterisk",
        "stop": "SystemExclamation",
        "error": "SystemHand",
    }
    def play_sound(name):
        winsound.PlaySound(SOUNDS[name], winsound.SND_ALIAS | winsound.SND_ASYNC)
```

**Aufwand:** 4–8 Stunden

---

### 2.4 App-Detection (🔴 Neu implementieren)

**Aktuell (macOS):** `transcribe.py:1253-1271`

```python
from AppKit import NSWorkspace
app = NSWorkspace.sharedWorkspace().frontmostApplication()
return app.localizedName()  # ~0.2ms
```

**Windows-Alternativen:**

| Option                | Zuverlässigkeit | Latenz |
| --------------------- | --------------- | ------ |
| `pygetwindow`         | Gut             | ~5ms   |
| `win32gui` (pywin32)  | Sehr gut        | ~1ms   |
| `ctypes` + user32.dll | Sehr gut        | ~0.5ms |

**Empfohlene Implementierung:**

```python
# Benötigt: pip install pywin32
import win32gui
import win32process
import psutil

def _get_frontmost_app_windows():
    hwnd = win32gui.GetForegroundWindow()
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    return psutil.Process(pid).name()
```

**Aufwand:** 4–6 Stunden

---

### 2.5 Daemon & IPC (🔴 Grundlegend anders)

**Aktuell (macOS):** `transcribe.py:428-517`

```python
def _daemonize():
    pid = os.fork()  # Unix only!
    os.setsid()       # Unix only!
    pid = os.fork()   # Double-fork

# Signal-basiertes Stoppen
signal.signal(signal.SIGUSR1, handle_stop)
```

**Windows-Probleme:**

1. `os.fork()` existiert nicht auf Windows
2. `SIGUSR1` existiert nicht auf Windows
3. `os.setsid()` existiert nicht auf Windows

**Windows-Alternativen:**

| Aspekt       | macOS        | Windows                               |
| ------------ | ------------ | ------------------------------------- |
| Daemon       | Double-Fork  | `subprocess.CREATE_NEW_PROCESS_GROUP` |
| Signal       | SIGUSR1      | Named Pipe / Event                    |
| PID-Tracking | `/tmp/*.pid` | `%TEMP%\*.pid`                        |

**Empfohlene Architektur:**

```python
if sys.platform == "win32":
    import win32event
    import win32api

    # Stop-Event statt Signal
    STOP_EVENT_NAME = "Global\\WhisperGoStop"
    stop_event = win32event.CreateEvent(None, True, False, STOP_EVENT_NAME)

    # Daemon starten
    subprocess.Popen(
        [sys.executable, "transcribe.py", "--daemon"],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    )
```

**Aufwand:** 12–20 Stunden (inkl. Tests)

---

### 2.6 Overlay UI (🔴 Größter Aufwand)

**Aktuell (macOS):** `overlay.py` (680 Zeilen)

| Feature               | macOS-API                     | Portierbarkeit |
| --------------------- | ----------------------------- | -------------- |
| Borderless Window     | NSWindow                      | 🟡 Möglich     |
| Glass-Morphism (Blur) | NSVisualEffectView            | 🔴 **Blocker** |
| Click-Through         | `ignoresMouseEvents`          | 🟡 Möglich     |
| Wave-Animation        | CABasicAnimation + CALayer    | 🔴 Komplex     |
| Fade In/Out           | `animator().setAlphaValue_()` | 🟡 Möglich     |
| Floating Level        | `setLevel_(25)`               | 🟡 Möglich     |

**Windows-Optionen:**

| Option            | Glass-Effekt           | Animationen           | Aufwand |
| ----------------- | ---------------------- | --------------------- | ------- |
| **tkinter + PIL** | ❌ Nein                | 🟡 Manuell            | 20h     |
| **PyQt6/PySide6** | 🟡 Acrylic (Win11)     | ✅ QPropertyAnimation | 30h     |
| **Electron**      | ✅ CSS backdrop-filter | ✅ CSS Animations     | 40h     |
| **WinUI 3 (C#)**  | ✅ Mica/Acrylic        | ✅ Composition        | 60h     |

**Empfehlung: PyQt6**

- Cross-Platform (auch Linux)
- Acrylic-Effekt auf Windows 11 möglich
- QPropertyAnimation für Wellen
- Python-nativ (kein separater Prozess)

**Minimal-Variante (ohne Glass):**

```python
# tkinter Overlay (funktional, aber nicht so schön)
import tkinter as tk

root = tk.Tk()
root.overrideredirect(True)  # Borderless
root.attributes('-topmost', True)  # Always on top
root.attributes('-alpha', 0.9)  # Semi-transparent
root.wm_attributes('-transparentcolor', 'black')  # Click-through
```

**Aufwand:**

- Minimal (tkinter, ohne Glass): 15–20 Stunden
- Vollständig (PyQt6, mit Acrylic): 30–40 Stunden

---

### 2.7 Menübar → System Tray (🔴 Neu implementieren)

**Aktuell (macOS):** `menubar.py` (100 Zeilen)

```python
import rumps  # macOS-only

class WhisperGoMenuBar(rumps.App):
    def __init__(self):
        super().__init__("🎤 Bereit", quit_button="Beenden")
```

**Windows-Alternative: pystray**

```python
import pystray
from PIL import Image

def create_tray():
    icon = pystray.Icon(
        "whisper_go",
        Image.open("icon.png"),
        "Whisper Go",
        menu=pystray.Menu(
            pystray.MenuItem("Status: Bereit", None, enabled=False),
            pystray.MenuItem("Beenden", lambda: icon.stop())
        )
    )
    icon.run()
```

**Unterschiede:**

| Aspekt        | macOS Menübar    | Windows Tray         |
| ------------- | ---------------- | -------------------- |
| Sichtbarkeit  | Immer sichtbar   | Im Tray versteckt    |
| Text          | Direkt anzeigbar | Nur Tooltip          |
| Icons         | Emoji möglich    | PNG/ICO erforderlich |
| Update-Latenz | Sofort           | ~100ms               |

**Aufwand:** 6–10 Stunden

---

### 2.8 Hotkey-Trigger (🔴 Komplett anders)

**Aktuell (macOS):** Raycast Extension

- TypeScript/React
- Systemweiter Hotkey via Raycast
- Keine eigene Hotkey-Implementierung

**Windows-Optionen:**

| Option                | Systemweit | Komplexität | UX               |
| --------------------- | ---------- | ----------- | ---------------- |
| **AutoHotkey Script** | ✅         | Niedrig     | Externe App      |
| **PowerToys Run**     | ✅         | Niedrig     | Gute Integration |
| **keyboard (Python)** | ✅         | Mittel      | Eigene Lösung    |
| **pynput**            | ✅         | Mittel      | Eigene Lösung    |

**Empfehlung: Eigenes Python-Modul + PowerToys**

```python
# hotkey.py (Windows)
from pynput import keyboard

HOTKEY = {keyboard.Key.ctrl, keyboard.Key.alt, keyboard.KeyCode.from_char('r')}
current_keys = set()

def on_press(key):
    current_keys.add(key)
    if current_keys == HOTKEY:
        toggle_recording()

def on_release(key):
    current_keys.discard(key)

with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
    listener.join()
```

**Aufwand:** 8–12 Stunden

---

## 3. Zusammenfassung: Aufwandsschätzung

| Komponente               | Aufwand | Kritikalität | Priorität |
| ------------------------ | ------- | ------------ | --------- |
| Audio-Aufnahme           | 2–4h    | Niedrig      | P1        |
| Sound-Playback           | 4–8h    | Mittel       | P1        |
| App-Detection            | 4–6h    | Mittel       | P2        |
| Daemon/IPC               | 12–20h  | **Hoch**     | P1        |
| Overlay UI (minimal)     | 15–20h  | Hoch         | P2        |
| Overlay UI (vollständig) | 30–40h  | Mittel       | P3        |
| System Tray              | 6–10h   | Mittel       | P2        |
| Hotkey-Trigger           | 8–12h   | Hoch         | P1        |
| Testing & Bugfixes       | 15–20h  | Hoch         | P1        |
| Dokumentation            | 4–6h    | Niedrig      | P3        |

### Gesamt-Aufwand

| Variante        | Stunden  | Beschreibung                             |
| --------------- | -------- | ---------------------------------------- |
| **Minimal**     | 50–70h   | CLI-only, kein Overlay, PowerToys-Hotkey |
| **Standard**    | 80–100h  | + System Tray, + tkinter Overlay         |
| **Vollständig** | 120–150h | + PyQt6 Overlay mit Acrylic-Effekt       |

---

## 4. Empfohlene Portierungs-Strategie

### Abhängigkeits-Übersicht

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ABHÄNGIGKEITS-GRAPH                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────┐                                                                │
│  │ Phase 0  │  Vorbereitung (keine Abhängigkeiten)                          │
│  └────┬─────┘                                                                │
│       │                                                                      │
│       ▼                                                                      │
│  ┌──────────┐                                                                │
│  │ Phase 1  │  Core-Funktionalität                                          │
│  └────┬─────┘                                                                │
│       │                                                                      │
│       ├────────────────┬────────────────┬────────────────┐                  │
│       ▼                ▼                ▼                ▼                  │
│  ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐               │
│  │ 2.1     │     │ 2.2     │     │ 2.3     │     │ 2.4     │               │
│  │ Tray    │     │ Hotkey  │     │ App-Det │     │ Clipb.  │  ← parallel   │
│  └────┬────┘     └────┬────┘     └────┬────┘     └────┬────┘               │
│       │               │               │               │                     │
│       └───────────────┴───────┬───────┴───────────────┘                     │
│                               ▼                                              │
│                         ┌──────────┐                                         │
│                         │ Phase 3  │  Overlay UI                            │
│                         └────┬─────┘                                         │
│                              │                                               │
│                              ▼                                               │
│                         ┌──────────┐                                         │
│                         │ Phase 4  │  Testing & Release                     │
│                         └──────────┘                                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Kritischer Pfad

Der **kritische Pfad** (längste Abhängigkeitskette) bestimmt die Mindest-Projektdauer:

```
Phase 0 → Phase 1.2 (Daemon/IPC) → Phase 2.2 (Hotkey) → Phase 3 → Phase 4
   4h    +      16h              +       12h          +   50h   +   25h   = 107h
```

### Detaillierte Abhängigkeitsmatrix

| Aufgabe                      | Hängt ab von | Blockiert | Parallelisierbar mit |
| ---------------------------- | ------------ | --------- | -------------------- |
| **0.1** Dev-Setup            | –            | Alles     | –                    |
| **0.2** Projektstruktur      | 0.1          | 1.x       | 0.3                  |
| **0.3** CI/CD                | 0.1          | 4.1       | 0.2                  |
|                              |              |           |                      |
| **1.1.1** Sound abstrahieren | 0.2          | 2.1       | 1.1.2, 1.3           |
| **1.1.2** Temp-Pfade         | 0.2          | 1.2       | 1.1.1, 1.3           |
| **1.2.1** Prozess-Start      | 1.1.2        | 1.2.2     | –                    |
| **1.2.2** Stop-Signal        | 1.2.1        | 2.2       | –                    |
| **1.2.3** PID-Management     | 1.2.1        | 2.2       | 1.2.2                |
| **1.3** Audio verifizieren   | 0.2          | 2.4       | 1.1.x                |
|                              |              |           |                      |
| **2.1** System Tray          | 1.1.1        | 3.1.4     | 2.2, 2.3, 2.4        |
| **2.2** Hotkey-System        | 1.2.2, 1.2.3 | 3.1.4     | 2.1, 2.3, 2.4        |
| **2.3** App-Detection        | 1.1.2        | –         | 2.1, 2.2, 2.4        |
| **2.4** Clipboard            | 1.3          | –         | 2.1, 2.2, 2.3        |
|                              |              |           |                      |
| **3.1** tkinter Overlay      | 2.1, 2.2     | 3.2       | –                    |
| **3.2** PyQt6 Upgrade        | 3.1          | 4.1       | –                    |
|                              |              |           |                      |
| **4.1** Testing              | 3.x, 0.3     | 4.2       | –                    |
| **4.2** Packaging            | 4.1          | 4.3       | –                    |
| **4.3** Dokumentation        | 4.2          | –         | –                    |

### Parallelisierungs-Möglichkeiten

**Innerhalb Phase 1 (2 Entwickler):**

```
Entwickler A: 1.1.1 → 1.1.2 → 1.2.1 → 1.2.2 → 1.2.3
Entwickler B: 1.3 (parallel zu 1.1.x)
```

**Innerhalb Phase 2 (bis zu 4 Entwickler):**

```
Entwickler A: 2.1 System Tray
Entwickler B: 2.2 Hotkey-System
Entwickler C: 2.3 App-Detection
Entwickler D: 2.4 Clipboard
```

**Sequentiell (nicht parallelisierbar):**

- Phase 1.2 (Daemon) → Basis für Phase 2.2 (Hotkeys)
- Phase 3.1 (tkinter) → Phase 3.2 (PyQt6)
- Phase 4.1 (Testing) → Phase 4.2 (Packaging) → Phase 4.3 (Docs)

---

### Phase 0: Vorbereitung (2–4h)

**Ziel:** Entwicklungsumgebung und Projektstruktur vorbereiten
**Abhängigkeiten:** Keine (Startpunkt)

- [ ] **0.1 Entwicklungsumgebung** ⚡ _Start hier_
  - [ ] Windows 11 VM oder Rechner einrichten
  - [ ] Python 3.10+ installieren
  - [ ] Git + VS Code konfigurieren

- [ ] **0.2 Projektstruktur anlegen** ← _benötigt 0.1_
  - [ ] `platform/` Ordner erstellen
  - [ ] `platform/__init__.py` mit Platform-Detection
  - [ ] `requirements-windows.txt` anlegen

- [ ] **0.3 CI/CD vorbereiten** ← _benötigt 0.1, parallel zu 0.2_
  - [ ] GitHub Actions Workflow für Windows-Tests
  - [ ] Matrix-Build (macOS + Windows)

**Meilenstein:** `python transcribe.py --help` läuft auf Windows (ohne Funktionalität)

---

### Phase 1: Core-Funktionalität (20–30h)

**Ziel:** CLI funktioniert vollständig auf Windows
**Abhängigkeiten:** Phase 0 abgeschlossen
**Blockiert:** Phase 2 (alle Teile)

#### 1.1 Plattform-Abstraktion (4–6h)

- [ ] **1.1.1 Sound-Playback abstrahieren** ← _benötigt 0.2_ | _parallel zu 1.1.2, 1.3_
  - [ ] Interface definieren: `play_sound(name: str) -> None`
  - [ ] macOS-Impl: Bestehenden CoreAudio-Code extrahieren
  - [ ] Windows-Impl: `winsound.PlaySound()` mit System-Sounds
  - [ ] Fallback: `playsound` Library als Backup
  - [ ] Tests: Unit-Tests für beide Plattformen

- [ ] **1.1.2 Temp-Pfade abstrahieren** ← _benötigt 0.2_ | _parallel zu 1.1.1, 1.3_
  - [ ] `get_temp_dir()` → `/tmp` (macOS) / `%TEMP%` (Windows)
  - [ ] Alle hardcodierten `/tmp/whisper_go.*` Pfade ersetzen
  - [ ] Tests: Pfade auf beiden Plattformen verifizieren

#### 1.2 Daemon & IPC (12–16h) 🔴 _Kritischer Pfad_

- [ ] **1.2.1 Prozess-Start abstrahieren** ← _benötigt 1.1.2_
  - [ ] macOS: Bestehenden Double-Fork extrahieren
  - [ ] Windows: `subprocess.CREATE_NEW_PROCESS_GROUP`
  - [ ] Windows: `subprocess.DETACHED_PROCESS` Flag
  - [ ] Tests: Daemon startet und läuft unabhängig

- [ ] **1.2.2 Stop-Signal abstrahieren** ← _benötigt 1.2.1_ | 🔴 _blockiert 2.2_
  - [ ] Interface: `send_stop_signal(pid: int) -> bool`
  - [ ] macOS: `os.kill(pid, signal.SIGUSR1)`
  - [ ] Windows: Named Event (`Global\\WhisperGoStop_{pid}`)
  - [ ] Polling-Mechanismus als Fallback
  - [ ] Tests: Daemon stoppt zuverlässig

- [ ] **1.2.3 PID-Management anpassen** ← _benötigt 1.2.1_ | _parallel zu 1.2.2_
  - [ ] `_cleanup_stale_pid_file()` für Windows
  - [ ] Prozess-Validierung via `psutil` (cross-platform)
  - [ ] Tests: Zombie-Prozess-Handling

#### 1.3 Audio-Aufnahme verifizieren (2–4h)

- [ ] **1.3.1 sounddevice auf Windows testen** ← _benötigt 0.2_ | _parallel zu 1.1.x_
  - [ ] PortAudio-Binaries (in pip enthalten)
  - [ ] Standard-Mikrofon erkennen
  - [ ] Aufnahme-Qualität verifizieren (16kHz, mono)
  - [ ] Tests: Audio-Roundtrip

**Meilenstein:** `python transcribe.py --record --mode deepgram` funktioniert auf Windows

---

### Phase 2: System-Integration (30–40h)

**Ziel:** Nahtlose Windows-Nutzung mit Tray und Hotkeys
**Abhängigkeiten:** Phase 1 abgeschlossen
**Blockiert:** Phase 3 (Overlay braucht Tray + Hotkey)

```
          Phase 1 fertig
               │
    ┌──────────┼──────────┬──────────┐
    ▼          ▼          ▼          ▼
  ┌─────┐   ┌─────┐   ┌─────┐   ┌─────┐
  │ 2.1 │   │ 2.2 │   │ 2.3 │   │ 2.4 │  ← alle parallel möglich!
  │Tray │   │Hotky│   │App-D│   │Clip │
  └──┬──┘   └──┬──┘   └─────┘   └─────┘
     │         │
     └────┬────┘
          ▼
      Phase 3
```

#### 2.1 System Tray (6–10h)

- [ ] **2.1.1 pystray-Integration** ← _benötigt 1.1.1_ | _parallel zu 2.2, 2.3, 2.4_
  - [ ] `platform/tray.py` mit Interface
  - [ ] Icon-Assets erstellen (ICO-Format, 16x16, 32x32, 64x64)
  - [ ] Status-Updates: Idle → Recording → Transcribing → Done
  - [ ] Rechtsklick-Menü: Status, Einstellungen, Beenden

- [ ] **2.1.2 IPC mit Tray verbinden** ← _benötigt 2.1.1_
  - [ ] State-File polling (wie macOS menubar.py)
  - [ ] Tooltip mit aktuellem Status
  - [ ] Balloon-Notifications bei Erfolg/Fehler (optional)

- [ ] **2.1.3 Autostart (optional)** ← _benötigt 2.1.1_
  - [ ] Registry-Eintrag oder Startup-Ordner
  - [ ] Toggle in Einstellungen

**Meilenstein:** System Tray zeigt korrekten Status während Aufnahme

#### 2.2 Hotkey-System (8–12h) 🔴 _Kritischer Pfad_

- [ ] **2.2.1 Globale Hotkeys implementieren** ← _benötigt 1.2.2, 1.2.3_ | _parallel zu 2.1, 2.3, 2.4_
  - [ ] `platform/hotkey.py` mit pynput
  - [ ] Konfigurierbare Tastenkombination (Default: Ctrl+Alt+R)
  - [ ] Double-Tap Detection (wie macOS ⌥⌥)
  - [ ] Konflikt-Erkennung mit anderen Apps

- [ ] **2.2.2 Push-to-Talk Modus** ← _benötigt 2.2.1_
  - [ ] Taste halten = Aufnahme
  - [ ] Taste loslassen = Transkription + Einfügen
  - [ ] Konfigurierbare Taste (z.B. F13, Caps Lock)

- [ ] **2.2.3 Integration mit Tray** ← _benötigt 2.1.1, 2.2.1_
  - [ ] Hotkey-Status im Tray-Menü
  - [ ] "Hotkey ändern" Dialog (einfacher Input)

**Meilenstein:** Hotkey startet/stoppt Aufnahme systemweit

#### 2.3 App-Detection (4–6h)

- [ ] **2.3.1 Aktives Fenster erkennen** ← _benötigt 1.1.2_ | _parallel zu 2.1, 2.2, 2.4_
  - [ ] `platform/app_detection.py`
  - [ ] `win32gui.GetForegroundWindow()` + `psutil`
  - [ ] Prozessname → App-Name Mapping
  - [ ] Fallback bei UWP-Apps (besondere Behandlung)

- [ ] **2.3.2 Kontext-Mapping erweitern** ← _benötigt 2.3.1_
  - [ ] Windows-spezifische Apps: Outlook.exe, Teams.exe, etc.
  - [ ] `prompts.py` um Windows-Apps erweitern
  - [ ] Tests: Kontext-Erkennung für Top-10 Apps

**Meilenstein:** Kontext-Awareness funktioniert auf Windows

#### 2.4 Clipboard & Auto-Paste (4–6h)

- [ ] **2.4.1 pyperclip verifizieren** ← _benötigt 1.3_ | _parallel zu 2.1, 2.2, 2.3_
  - [ ] Clipboard-Operationen testen
  - [ ] Unicode-Support (Emojis, Umlaute)

- [ ] **2.4.2 Auto-Paste implementieren** ← _benötigt 2.4.1_
  - [ ] `pyautogui` oder `keyboard` für Ctrl+V
  - [ ] Timing-Anpassung (Windows braucht evtl. mehr Delay)
  - [ ] Focus-Handling (korrektes Fenster aktivieren)

**Meilenstein:** Transkript wird automatisch eingefügt

---

### Phase 3: Overlay UI (30–50h) 🔴 _Kritischer Pfad_

**Ziel:** Visuelles Feedback während der Aufnahme
**Abhängigkeiten:** 2.1 (Tray) + 2.2 (Hotkey) müssen funktionieren
**Blockiert:** Phase 4

```
    2.1 Tray ──────┐
                   ├──▶ 3.1 tkinter ──▶ 3.2 PyQt6 ──▶ Phase 4
    2.2 Hotkey ────┘         │              │
                             │              │
                      funktional      optional (polish)
```

#### 3.1 Basis-Overlay mit tkinter (15–20h)

- [ ] **3.1.1 Fenster-Setup** ← _benötigt 2.1, 2.2_
  - [ ] Borderless Window (`overrideredirect`)
  - [ ] Always-on-Top (`-topmost`)
  - [ ] Semi-transparent (`-alpha`)
  - [ ] Click-Through (`-transparentcolor`)
  - [ ] Position: Unten-Mitte des Bildschirms

- [ ] **3.1.2 Status-Anzeige** ← _benötigt 3.1.1_
  - [ ] Text-Label für Status ("Aufnahme läuft...")
  - [ ] Text-Label für Live-Transkript (Interim-Text)
  - [ ] Schriftart: System-Sans-Serif, groß genug

- [ ] **3.1.3 Einfache Animation** ← _benötigt 3.1.1_ | _parallel zu 3.1.2_
  - [ ] Pulsierender Punkt während Aufnahme
  - [ ] Canvas-basierte Wellen (5 Balken)
  - [ ] Timer-basierte Animation (50ms Update)

- [ ] **3.1.4 State-Machine** ← _benötigt 3.1.2, 3.1.3_ | 🔴 _blockiert 3.2, 4.1_
  - [ ] Idle (versteckt) → Recording → Transcribing → Done → Idle
  - [ ] Fade-In/Out Animationen
  - [ ] File-Polling wie macOS overlay.py

**Meilenstein:** Funktionales Overlay ohne Glass-Effekt

#### 3.2 PyQt6 Upgrade (15–25h) – Optional, aber empfohlen

- [ ] **3.2.1 Qt-Fenster-Setup** ← _benötigt 3.1.4_
  - [ ] `QMainWindow` mit `Qt.FramelessWindowHint`
  - [ ] `Qt.WindowStaysOnTopHint`
  - [ ] `setAttribute(Qt.WA_TranslucentBackground)`

- [ ] **3.2.2 Acrylic-Effekt (Windows 11)** ← _benötigt 3.2.1_
  - [ ] `ctypes` + `dwmapi.dll` für `DwmSetWindowAttribute`
  - [ ] `DWMWA_USE_IMMERSIVE_DARK_MODE`
  - [ ] `DWMWA_SYSTEMBACKDROP_TYPE` = `DWMSBT_TRANSIENTWINDOW`
  - [ ] Fallback für Windows 10 (ohne Acrylic)

- [ ] **3.2.3 QPropertyAnimation für Wellen** ← _benötigt 3.2.1_ | _parallel zu 3.2.2_
  - [ ] `QPropertyAnimation` auf `geometry` oder custom property
  - [ ] Easing: `QEasingCurve.InOutSine`
  - [ ] Parallele Animationen mit Delay

- [ ] **3.2.4 Styling** ← _benötigt 3.2.2, 3.2.3_
  - [ ] QSS (Qt Stylesheets) für konsistentes Design
  - [ ] Dunkles Theme (passend zu macOS)
  - [ ] Schlagschatten auf Text

**Meilenstein:** Overlay mit Windows 11 Acrylic-Effekt

---

### Phase 4: Testing & Release (15–25h)

**Ziel:** Stabile, verteilbare Windows-Version
**Abhängigkeiten:** Phase 3.1 (mindestens tkinter Overlay), 0.3 (CI/CD)
**Blockiert:** Nichts (Endpunkt)

```
    Phase 3.1 ─────┐
                   ├──▶ 4.1 Testing ──▶ 4.2 Packaging ──▶ 4.3 Docs ──▶ 🎉 Release!
    Phase 0.3 ─────┘         │
    (CI/CD)                  │
                        strikt sequentiell
```

#### 4.1 Testing (8–12h)

- [ ] **4.1.1 Unit-Tests erweitern** ← _benötigt 3.1.4, 0.3_
  - [ ] Platform-spezifische Tests mit `pytest.mark.skipif`
  - [ ] Mocks für Windows-APIs
  - [ ] CI/CD: Windows-Runner in GitHub Actions

- [ ] **4.1.2 Integration-Tests** ← _benötigt 4.1.1_
  - [ ] End-to-End: Hotkey → Aufnahme → Transkript → Paste
  - [ ] Verschiedene Windows-Versionen (10, 11)
  - [ ] Verschiedene Audio-Devices

- [ ] **4.1.3 Edge-Cases** ← _benötigt 4.1.2_
  - [ ] Kein Mikrofon angeschlossen
  - [ ] Kein Internet (Offline-Feedback)
  - [ ] Konflikt mit Antivirus
  - [ ] UAC-Prompts (Admin-Rechte)

#### 4.2 Packaging & Distribution (5–8h)

- [ ] **4.2.1 Executable erstellen** ← _benötigt 4.1.3 (alle Tests grün)_
  - [ ] PyInstaller oder cx_Freeze
  - [ ] Single-File EXE (--onefile)
  - [ ] Icon einbetten
  - [ ] Version-Info einbetten

- [ ] **4.2.2 Installer (optional)** ← _benötigt 4.2.1_
  - [ ] NSIS oder Inno Setup
  - [ ] Startmenü-Einträge
  - [ ] Uninstaller
  - [ ] Optionaler Autostart

- [ ] **4.2.3 Code-Signing** ← _benötigt 4.2.1_ | _parallel zu 4.2.2_
  - [ ] Code-Signing-Zertifikat beschaffen
  - [ ] EXE und Installer signieren
  - [ ] Windows SmartScreen Reputation aufbauen

#### 4.3 Dokumentation (3–5h)

- [ ] **4.3.1 README erweitern** ← _benötigt 4.2.2 oder 4.2.3_
  - [ ] Windows-Installationsanleitung
  - [ ] Troubleshooting-Sektion
  - [ ] Screenshots

- [ ] **4.3.2 Release erstellen** ← _benötigt 4.3.1_ | 🎉 _Endpunkt_
  - [ ] GitHub Release mit Assets
  - [ ] Changelog
  - [ ] Upgrade-Hinweise für bestehende Nutzer

**Meilenstein:** Erste öffentliche Windows-Beta

---

## 5. Technische Risiken

| Risiko                       | Wahrscheinlichkeit | Impact  | Mitigation                |
| ---------------------------- | ------------------ | ------- | ------------------------- |
| PortAudio-Probleme           | Mittel             | Hoch    | Pre-built Binaries nutzen |
| Antivirus-Blockierung        | Mittel             | Mittel  | Code-Signing              |
| Admin-Rechte für Hotkeys     | Niedrig            | Mittel  | Dokumentation             |
| Windows Defender SmartScreen | Hoch               | Niedrig | Installer signieren       |

---

## 6. Abhängigkeiten (Windows)

```
# requirements-windows.txt
openai>=1.0.0
deepgram-sdk>=3.0.0
groq>=0.4.0
sounddevice
soundfile
pyperclip
python-dotenv
pystray          # System Tray (ersetzt rumps)
Pillow           # Icons für pystray
pywin32          # Windows API
pynput           # Hotkeys
```

**Optionale Abhängigkeiten:**

- `PyQt6` – Für Overlay mit Acrylic-Effekt
- `keyboard` – Alternative zu pynput

---

## 7. Fazit

### Bewertung: Lohnt sich die Portierung?

| Faktor                     | Bewertung                                          |
| -------------------------- | -------------------------------------------------- |
| **Technische Machbarkeit** | ✅ Gut – keine unlösbaren Blocker                  |
| **Aufwand**                | 🟡 Mittel-Hoch (120–150h für vollständige Parität) |
| **Marktpotenzial**         | ✅ Hoch – Windows hat größere Nutzerbasis          |
| **Wartungsaufwand**        | 🟡 Verdoppelt sich (zwei Plattformen)              |

### Architektur-Empfehlung

Eine Portierung sollte mit einem `platform/`-Ordner beginnen:

```
whisper_go/
├── transcribe.py          # Bleibt unverändert (Core-Logik)
├── platform/
│   ├── __init__.py        # Platform-Detection + Factory
│   ├── sound.py           # Interface + macOS/Windows Impl.
│   ├── daemon.py          # Interface + macOS/Windows Impl.
│   ├── app_detection.py   # Interface + macOS/Windows Impl.
│   ├── tray.py            # rumps (macOS) / pystray (Windows)
│   └── overlay.py         # PyObjC (macOS) / PyQt6 (Windows)
```

### Kritische Entscheidungen vor Implementierung

1. **Overlay-Framework:** PyQt6 (Cross-Platform) oder native Lösungen pro OS?
2. **Hotkey-Lösung:** Eigenes Modul oder externe Tools (PowerToys)?
3. **Installer:** MSI, NSIS oder portable EXE?
4. **Code-Signing:** Notwendig für Windows Defender Bypass

---

_Erstellt: 2025-12-08_
