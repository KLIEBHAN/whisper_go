#!/usr/bin/env python3
"""
whisper_go – Audio-Transkription mit OpenAI Whisper.

Unterstützt sowohl die OpenAI API als auch lokale Whisper-Modelle.
Transkripte werden auf stdout ausgegeben, Status auf stderr.

Usage:
    python transcribe.py audio.mp3
    python transcribe.py audio.mp3 --mode local
    python transcribe.py --record --copy
"""

# Startup-Timing: Zeit erfassen BEVOR andere Imports laden
import time as _time_module  # noqa: E402 - muss vor anderen Imports sein

_PROCESS_START = _time_module.perf_counter()

import argparse  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import signal  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import uuid  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402
from contextlib import asynccontextmanager, contextmanager  # noqa: E402
from typing import TYPE_CHECKING  # noqa: E402
from logging.handlers import RotatingFileHandler  # noqa: E402
from pathlib import Path  # noqa: E402

if TYPE_CHECKING:
    from deepgram.listen.v1.socket_client import AsyncV1SocketClient

from prompts import DEFAULT_APP_CONTEXTS, get_prompt_for_context  # noqa: E402

# Import-Zeit messen (alle Standardlib-Imports abgeschlossen)
_IMPORTS_DONE = _time_module.perf_counter()
time = _time_module  # Alias für restlichen Code

# =============================================================================
# Zentrale Konfiguration importieren
# =============================================================================

from config import (
    # Audio
    WHISPER_SAMPLE_RATE,
    WHISPER_CHANNELS,
    WHISPER_BLOCKSIZE,
    INT16_MAX,
    # Models
    DEFAULT_API_MODEL,
    DEFAULT_LOCAL_MODEL,
    DEFAULT_DEEPGRAM_MODEL,
    DEFAULT_GROQ_MODEL,
    DEFAULT_REFINE_MODEL,
    DEFAULT_GROQ_REFINE_MODEL,
    # API
    OPENROUTER_BASE_URL,
    # IPC
    TEMP_RECORDING_FILENAME,
    PID_FILE,
    TRANSCRIPT_FILE,
    ERROR_FILE,
    STATE_FILE,
    INTERIM_FILE,
    # Streaming
    INTERIM_THROTTLE_MS,
    FINALIZE_TIMEOUT,
    DEEPGRAM_WS_URL,
    DEEPGRAM_CLOSE_TIMEOUT,
    # Paths
    SCRIPT_DIR,
    LOG_DIR,
    LOG_FILE,
    VOCABULARY_FILE,
)

# =============================================================================
# Laufzeit-State (modulglobal)
# =============================================================================

logger = logging.getLogger("whisper_go")
_session_id: str = ""  # Wird pro Durchlauf in setup_logging() gesetzt
_custom_app_contexts_cache: dict | None = None  # Cache für WHISPER_GO_APP_CONTEXTS

# API-Client Singletons (Lazy Init) – für LLM-Refine
# Transkriptions-Clients sind jetzt in providers/
_groq_client = None


def _generate_session_id() -> str:
    """Erzeugt kurze, lesbare Session-ID (8 Zeichen)."""
    return uuid.uuid4().hex[:8]


def _format_duration(milliseconds: float) -> str:
    """Formatiert Dauer menschenlesbar: ms für kurze, s für längere Zeiten."""
    if milliseconds >= 1000:
        return f"{milliseconds / 1000:.2f}s"
    return f"{milliseconds:.0f}ms"


def _log_preview(text: str, max_length: int = 100) -> str:
    """Kürzt Text für Log-Ausgabe mit Ellipsis wenn nötig."""
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}..."


@contextmanager
def timed_operation(name: str):
    """Kontextmanager für Zeitmessung mit automatischem Logging."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(f"[{_session_id}] {name}: {_format_duration(elapsed_ms)}")


def setup_logging(debug: bool = False) -> None:
    """Konfiguriert Logging: Datei mit Rotation + optional stderr."""
    global _session_id
    
    # Session-ID nur einmal generieren
    if not _session_id:
        _session_id = _generate_session_id()

    # Verhindere doppelte Handler bei mehrfachem Aufruf
    if logger.handlers:
        logger.setLevel(logging.DEBUG if debug else logging.INFO)
        return

    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # Log-Verzeichnis erstellen falls nicht vorhanden
    LOG_DIR.mkdir(exist_ok=True)

    # Datei-Handler mit Rotation (max 1MB, 3 Backups)
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    )
    logger.addHandler(file_handler)

    # Stderr-Handler (nur im Debug-Modus)
    if debug:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.DEBUG)
        stderr_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(stderr_handler)


def log(message: str) -> None:
    """Status-Meldung auf stderr.

    Warum stderr? Hält stdout sauber für Pipes (z.B. `transcribe.py | pbcopy`).
    """
    print(message, file=sys.stderr)


def error(message: str) -> None:
    """Fehlermeldung auf stderr."""
    print(f"Fehler: {message}", file=sys.stderr)


def load_environment() -> None:
    """Lädt .env-Datei falls python-dotenv installiert ist."""
    try:
        from dotenv import load_dotenv

        env_file = SCRIPT_DIR / ".env"
        load_dotenv(env_file if env_file.exists() else None)
    except ImportError:
        pass


def copy_to_clipboard(text: str) -> bool:
    """Kopiert Text in die Zwischenablage. Gibt True bei Erfolg zurück.

    Delegiert an whisper_platform.clipboard für plattformspezifische Implementierung.
    Deprecated: Nutze stattdessen whisper_platform.get_clipboard().copy()
    """
    try:
        from whisper_platform import get_clipboard
        return get_clipboard().copy(text)
    except Exception:
        # Fallback auf pyperclip für Rückwärtskompatibilität
        try:
            import pyperclip
            pyperclip.copy(text)
            return True
        except Exception:
            return False


# =============================================================================
# Sound-Playback (delegiert an whisper_platform.sound)
# =============================================================================

# Lazy-Import des Sound-Players für schnellen Startup
_sound_player = None


def _get_sound_player():
    """Gibt Sound-Player Singleton zurück (lazy init).

    Delegiert an whisper_platform.sound für plattformspezifische Implementierung.
    """
    global _sound_player
    if _sound_player is None:
        try:
            from whisper_platform import get_sound_player
            _sound_player = get_sound_player()
        except ImportError:
            # Fallback: Dummy-Player wenn Modul nicht verfügbar
            class DummySoundPlayer:
                def play(self, name: str) -> None:
                    pass
            _sound_player = DummySoundPlayer()
    return _sound_player


def play_sound(name: str) -> None:
    """Spielt benannten Sound ab (ready, stop, error).

    Delegiert an whisper_platform.sound für plattformspezifische Implementierung.
    """
    _get_sound_player().play(name)


# =============================================================================
# Audio-Aufnahme
# =============================================================================


def record_audio() -> Path:
    """
    Nimmt Audio vom Mikrofon auf (Enter startet, Enter stoppt).
    Gibt Pfad zur temporären WAV-Datei zurück.
    """
    import numpy as np
    import sounddevice as sd
    import soundfile as sf

    recorded_chunks: list = []

    def on_audio_chunk(indata, _frames, _time, _status):
        recorded_chunks.append(indata.copy())

    log("🎤 Drücke ENTER um die Aufnahme zu starten...")
    input()

    play_sound("ready")
    log("🔴 Aufnahme läuft... Drücke ENTER zum Beenden.")
    with sd.InputStream(
        samplerate=WHISPER_SAMPLE_RATE,
        channels=1,
        dtype="float32",
        callback=on_audio_chunk,
    ):
        input()

    log("✅ Aufnahme beendet.")
    play_sound("stop")

    if not recorded_chunks:
        raise ValueError("Keine Audiodaten aufgenommen. Bitte länger aufnehmen.")

    audio_data = np.concatenate(recorded_chunks)
    output_path = Path(tempfile.gettempdir()) / TEMP_RECORDING_FILENAME
    sf.write(output_path, audio_data, WHISPER_SAMPLE_RATE)

    return output_path


# =============================================================================
# Daemon-Hilfsfunktionen (Raycast-Integration)
# =============================================================================


def _is_whisper_go_process(pid: int) -> bool:
    """Prüft ob die PID zu einem whisper_go Prozess gehört.

    Einfache, sichere Implementierung. Die ~50ms sind akzeptabel,
    da diese Funktion nur im seltenen Edge-Case aufgerufen wird
    (Cleanup nach Crash oder bei schnellem Doppelklick).
    """
    import subprocess

    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=1,
        )
        command = result.stdout.strip()
        return "transcribe.py" in command and "--record-daemon" in command
    except Exception:
        return False


def _daemonize() -> None:
    """
    Double-Fork für echte Daemon-Prozesse (verhindert Zombies).

    Wenn Raycast spawn(detached) + unref() nutzt, wird wait() nie aufgerufen.
    Der beendete Python-Prozess bleibt als Zombie. Lösung: Double-Fork.

    Nach dem Double-Fork ist launchd (PID 1) der Parent, der automatisch
    beendete Prozesse aufräumt.
    """
    # Erster Fork: Parent kann sofort exit() machen
    pid = os.fork()
    if pid > 0:
        # Parent: Warte auf Child und exit (Raycast kann jetzt wait() aufrufen)
        os.waitpid(pid, 0)
        sys.exit(0)

    # Child: Neue Session starten (löst von Terminal/Raycast)
    os.setsid()

    # Zweiter Fork: Verhindert Terminal-Übernahme
    pid = os.fork()
    if pid > 0:
        # Erstes Child: Exit sofort (wird von launchd adoptiert)
        os._exit(0)

    # Grandchild: Wir sind jetzt der echte Daemon mit launchd als Parent


def _cleanup_stale_pid_file() -> None:
    """
    Entfernt PID-File und killt alten Prozess falls nötig (Crash-Recovery).

    Sicherheit:
    - Prüft ob PID wirklich zu einem whisper_go Prozess gehört
    - Verhindert versehentliches Killen fremder Prozesse bei PID-Recycling
    """
    if not PID_FILE.exists():
        return

    try:
        old_pid = int(PID_FILE.read_text().strip())

        # Eigene PID? Dann nicht killen!
        if old_pid == os.getpid():
            return

        # Signal 0 ist ein "Ping" – prüft Existenz ohne Seiteneffekte
        os.kill(old_pid, 0)

        # SICHERHEIT: Nur killen wenn es wirklich ein whisper_go Prozess ist!
        if not _is_whisper_go_process(old_pid):
            logger.warning(
                f"[{_session_id}] PID {old_pid} ist kein whisper_go Prozess, "
                f"lösche nur PID-File (PID-Recycling?)"
            )
            PID_FILE.unlink(missing_ok=True)
            return

        # Prozess läuft noch und ist whisper_go → KILL
        logger.warning(
            f"[{_session_id}] Alter Daemon-Prozess {old_pid} läuft noch, beende ihn..."
        )

        # Erst freundlich (SIGTERM), dann hart (SIGKILL)
        try:
            os.kill(old_pid, signal.SIGTERM)
            time.sleep(0.1)
            try:
                os.kill(old_pid, 0)
                os.kill(old_pid, signal.SIGKILL)
                logger.info(
                    f"[{_session_id}] Alter Prozess {old_pid} gekillt (SIGKILL)"
                )
            except ProcessLookupError:
                logger.info(
                    f"[{_session_id}] Alter Prozess {old_pid} beendet (SIGTERM)"
                )
        except ProcessLookupError:
            pass

        PID_FILE.unlink(missing_ok=True)

    except (ValueError, ProcessLookupError):
        # PID ungültig oder Prozess existiert nicht mehr → aufräumen
        logger.info(f"[{_session_id}] Stale PID-File gelöscht: {PID_FILE}")
        PID_FILE.unlink(missing_ok=True)
    except PermissionError:
        logger.warning(f"[{_session_id}] PID-File existiert, keine Berechtigung")


def record_audio_daemon() -> Path:
    """
    Daemon-Modus: Nimmt Audio auf bis SIGUSR1 empfangen wird.
    Schreibt PID-File für externe Steuerung (Raycast).
    Kein globaler State – verwendet Closure für Signal-Flag.
    """
    import numpy as np
    import sounddevice as sd
    import soundfile as sf

    # Stale PID-File von vorherigem Crash aufräumen
    _cleanup_stale_pid_file()

    recorded_chunks: list = []
    recording_start = time.perf_counter()
    should_stop = False

    def on_audio_chunk(indata, _frames, _time_info, _status):
        """Callback: Sammelt Audio-Chunks während der Aufnahme."""
        recorded_chunks.append(indata.copy())

    def handle_stop_signal(_signum: int, _frame) -> None:
        """Signal-Handler: Setzt Stop-Flag bei SIGUSR1."""
        nonlocal should_stop
        logger.debug(f"[{_session_id}] SIGUSR1 empfangen")
        should_stop = True

    pid = os.getpid()
    logger.info(f"[{_session_id}] Daemon gestartet (PID: {pid})")

    # PID-File schreiben für Raycast
    PID_FILE.write_text(str(pid))

    # Signal-Handler registrieren
    signal.signal(signal.SIGUSR1, handle_stop_signal)

    play_sound("ready")
    log("🎤 Daemon: Aufnahme gestartet (warte auf SIGUSR1)...")
    logger.info(f"[{_session_id}] Aufnahme gestartet")

    try:
        with sd.InputStream(
            samplerate=WHISPER_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=on_audio_chunk,
        ):
            while not should_stop:
                sd.sleep(100)  # 100ms warten, dann Signal prüfen
    finally:
        # PID-File aufräumen
        if PID_FILE.exists():
            PID_FILE.unlink()

    recording_duration = time.perf_counter() - recording_start
    logger.info(f"[{_session_id}] Aufnahme: {recording_duration:.1f}s")
    log("✅ Daemon: Aufnahme beendet.")
    play_sound("stop")

    if not recorded_chunks:
        logger.error(f"[{_session_id}] Keine Audiodaten aufgenommen")
        raise ValueError("Keine Audiodaten aufgenommen.")

    audio_data = np.concatenate(recorded_chunks)
    output_path = Path(tempfile.gettempdir()) / TEMP_RECORDING_FILENAME
    sf.write(output_path, audio_data, WHISPER_SAMPLE_RATE)
    return output_path


# =============================================================================
# Custom Vocabulary (Fachbegriffe, Namen)
# =============================================================================


def load_vocabulary() -> dict:
    """Lädt Custom Vocabulary aus JSON-Datei (~/.whisper_go/vocabulary.json).

    Format:
        {
            "keywords": ["Anthropic", "Claude", "Kubernetes"]
        }

    Returns:
        Dict mit "keywords" (Liste). Bei Fehler leeres Dict.
    """
    if not VOCABULARY_FILE.exists():
        return {"keywords": []}
    try:
        data = json.loads(VOCABULARY_FILE.read_text())
        # Validierung: keywords muss Liste sein
        if not isinstance(data.get("keywords"), list):
            data["keywords"] = []
        return data
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"[{_session_id}] Vocabulary-Datei fehlerhaft: {e}")
        return {"keywords": []}


# =============================================================================
# Transkription (delegiert an providers/)
# =============================================================================
# Die Transkriptions-Logik wurde in providers/ ausgelagert:
#   - providers/openai.py → OpenAI Whisper API
#   - providers/deepgram.py → Deepgram Nova-3
#   - providers/groq.py → Groq Whisper (LPU)
#   - providers/local.py → Lokales Whisper
#
# Siehe transcribe() Funktion für den zentralen Einstiegspunkt.
# =============================================================================


# =============================================================================
# Deepgram WebSocket Streaming (delegiert an providers/deepgram_stream.py)
# =============================================================================
# HINWEIS: Die Streaming-Logik befindet sich jetzt in providers/deepgram_stream.py.
# Die folgenden Funktionen sind Wrapper für Rückwärtskompatibilität, damit
# bestehender Code weiterhin `from transcribe import ...` nutzen kann.
#
# Für neuen Code: Importiere direkt aus providers.deepgram_stream
# =============================================================================


def _extract_transcript(result) -> str | None:
    """Re-export von providers.deepgram_stream._extract_transcript."""
    from providers.deepgram_stream import _extract_transcript as impl
    return impl(result)


@asynccontextmanager
async def _create_deepgram_connection(
    api_key: str,
    *,
    model: str,
    language: str | None = None,
    smart_format: bool = True,
    punctuate: bool = True,
    interim_results: bool = True,
    encoding: str = "linear16",
    sample_rate: int = 16000,
    channels: int = 1,
) -> AsyncIterator["AsyncV1SocketClient"]:
    """Deepgram WebSocket Connection - delegiert an providers.deepgram_stream."""
    from providers.deepgram_stream import _create_deepgram_connection as create_impl
    async with create_impl(
        api_key,
        model=model,
        language=language,
        smart_format=smart_format,
        punctuate=punctuate,
        interim_results=interim_results,
        encoding=encoding,
        sample_rate=sample_rate,
        channels=channels,
    ) as connection:
        yield connection


async def _deepgram_stream_core(
    model: str,
    language: str | None,
    *,
    early_buffer: list[bytes] | None = None,
    play_ready: bool = True,
    external_stop_event: threading.Event | None = None,
) -> str:
    """Gemeinsamer Streaming-Core für Deepgram.

    Delegiert an providers.deepgram_stream.deepgram_stream_core.
    Wrapper für Rückwärtskompatibilität.
    """
    from providers.deepgram_stream import deepgram_stream_core
    return await deepgram_stream_core(
        model,
        language,
        early_buffer=early_buffer,
        play_ready=play_ready,
        external_stop_event=external_stop_event,
    )


async def _transcribe_with_deepgram_stream_async(
    model: str = DEFAULT_DEEPGRAM_MODEL,
    language: str | None = None,
) -> str:
    """Async Deepgram Streaming für CLI-Nutzung (Wrapper um Core)."""
    from providers.deepgram_stream import _transcribe_with_deepgram_stream_async as impl
    return await impl(model, language)


def _transcribe_with_deepgram_stream_with_buffer(
    model: str,
    language: str | None,
    early_buffer: list[bytes],
) -> str:
    """Streaming mit vorgepuffertem Audio (Daemon-Mode, Wrapper um Core)."""
    from providers.deepgram_stream import transcribe_with_deepgram_stream_with_buffer as impl
    return impl(model, language, early_buffer)


def transcribe_with_deepgram_stream(
    model: str = DEFAULT_DEEPGRAM_MODEL,
    language: str | None = None,
) -> str:
    """Sync Wrapper für async Deepgram Streaming.

    Verwendet asyncio.run() um die async Implementierung auszuführen.
    Für Raycast-Integration: SIGUSR1 stoppt die Aufnahme sauber.
    """
    from providers.deepgram_stream import transcribe_with_deepgram_stream as impl
    return impl(model, language)


def _get_groq_client():
    """Gibt Groq-Client Singleton zurück (Lazy Init).

    Spart ~30-50ms pro Aufruf durch Connection-Reuse.
    """
    global _groq_client
    if _groq_client is None:
        from groq import Groq

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY nicht gesetzt")
        _groq_client = Groq(api_key=api_key)
        logger.debug(f"[{_session_id}] Groq-Client initialisiert")
    return _groq_client


# transcribe_with_groq und transcribe_locally wurden nach providers/ verschoben


def _extract_message_content(content) -> str:
    """Extrahiert Text aus OpenAI/OpenRouter Message-Content (String, Liste oder None)."""
    if content is None:
        return ""
    if isinstance(content, list):
        # Liste von Content-Parts → Text-Parts extrahieren
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        ).strip()
    return content.strip()


# =============================================================================
# Kontext-Erkennung (Auto-Detection der aktiven App)
# =============================================================================


def _get_frontmost_app() -> str | None:
    """Ermittelt aktive App.

    Delegiert an whisper_platform.app_detection für plattformspezifische Implementierung.
    """
    try:
        from whisper_platform import get_app_detector
        return get_app_detector().get_frontmost_app()
    except ImportError:
        # Fallback auf direkte NSWorkspace-Nutzung (macOS)
        if sys.platform != "darwin":
            return None
        try:
            from AppKit import NSWorkspace
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            return app.localizedName() if app else None
        except ImportError:
            logger.debug(f"[{_session_id}] PyObjC/AppKit nicht verfügbar")
            return None
    except Exception as e:
        logger.debug(f"[{_session_id}] App-Detection fehlgeschlagen: {e}")
        return None


def _get_custom_app_contexts() -> dict:
    """Lädt und cached custom app contexts aus WHISPER_GO_APP_CONTEXTS."""
    global _custom_app_contexts_cache

    if _custom_app_contexts_cache is not None:
        return _custom_app_contexts_cache

    custom = os.getenv("WHISPER_GO_APP_CONTEXTS")
    if custom:
        try:
            _custom_app_contexts_cache = json.loads(custom)
            logger.debug(
                f"[{_session_id}] Custom app contexts geladen: "
                f"{list(_custom_app_contexts_cache.keys())}"
            )
        except json.JSONDecodeError as e:
            logger.warning(
                f"[{_session_id}] WHISPER_GO_APP_CONTEXTS ungültiges JSON: {e}"
            )
            _custom_app_contexts_cache = {}
    else:
        _custom_app_contexts_cache = {}

    return _custom_app_contexts_cache


def _app_to_context(app_name: str) -> str:
    """Mappt App-Name auf Kontext-Typ."""
    custom_map = _get_custom_app_contexts()
    if app_name in custom_map:
        return custom_map[app_name]

    return DEFAULT_APP_CONTEXTS.get(app_name, "default")


def detect_context(override: str | None = None) -> tuple[str, str | None, str]:
    """
    Ermittelt Kontext: CLI > ENV > App-Detection > default.

    Returns:
        Tuple (context, app_name, source) - source zeigt woher der Kontext kommt
    """
    # 1. CLI-Override (höchste Priorität)
    if override:
        return override, None, "CLI"

    # 2. ENV-Override
    env_context = os.getenv("WHISPER_GO_CONTEXT")
    if env_context:
        return env_context.lower(), None, "ENV"

    # 3. Auto-Detection via NSWorkspace (nur macOS)
    if sys.platform == "darwin":
        app_name = _get_frontmost_app()
        if app_name:
            return _app_to_context(app_name), app_name, "App"

    return "default", None, "Default"


# =============================================================================
# LLM-Nachbearbeitung (Refine)
# =============================================================================


def _get_refine_client(provider: str):
    """Erstellt Client für Nachbearbeitung (OpenAI, OpenRouter oder Groq)."""
    if provider == "groq":
        return _get_groq_client()

    from openai import OpenAI

    if provider == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY nicht gesetzt")
        return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)

    # Default: OpenAI (nutzt OPENAI_API_KEY automatisch)
    return OpenAI()


def refine_transcript(
    transcript: str,
    model: str | None = None,
    prompt: str | None = None,
    provider: str | None = None,
    context: str | None = None,
) -> str:
    """Nachbearbeitung mit LLM (Flow-Style). Kontext-aware Prompts."""
    # Leeres Transkript → nichts zu tun
    if not transcript or not transcript.strip():
        logger.debug(f"[{_session_id}] Leeres Transkript, überspringe Nachbearbeitung")
        return transcript

    # Kontext-spezifischen Prompt wählen (falls nicht explizit übergeben)
    # Auch leere Strings werden wie None behandelt (Fallback auf Kontext-Prompt)
    if not prompt:
        effective_context, app_name, source = detect_context(context)
        prompt = get_prompt_for_context(effective_context)
        # Detailliertes Logging mit Quelle
        if app_name:
            logger.info(
                f"[{_session_id}] Kontext: {effective_context} (Quelle: {source}, App: {app_name})"
            )
        else:
            logger.info(
                f"[{_session_id}] Kontext: {effective_context} (Quelle: {source})"
            )

    # Provider und Modell zur Laufzeit bestimmen (CLI > ENV > Default)
    effective_provider = (
        provider or os.getenv("WHISPER_GO_REFINE_PROVIDER", "openai")
    ).lower()

    # Provider-spezifisches Default-Modell (Groq nutzt Llama, andere GPT-5)
    if model:
        effective_model = model
    elif os.getenv("WHISPER_GO_REFINE_MODEL"):
        effective_model = os.getenv("WHISPER_GO_REFINE_MODEL")
    elif effective_provider == "groq":
        effective_model = DEFAULT_GROQ_REFINE_MODEL
    else:
        effective_model = DEFAULT_REFINE_MODEL

    logger.info(
        f"[{_session_id}] LLM-Nachbearbeitung: provider={effective_provider}, model={effective_model}"
    )
    logger.debug(f"[{_session_id}] Input: {len(transcript)} Zeichen")

    client = _get_refine_client(effective_provider)
    full_prompt = f"{prompt}\n\nTranskript:\n{transcript}"

    with timed_operation("LLM-Nachbearbeitung"):
        if effective_provider == "groq":
            # Groq nutzt chat.completions API (wie OpenRouter)
            response = client.chat.completions.create(
                model=effective_model,
                messages=[{"role": "user", "content": full_prompt}],
            )
            result = _extract_message_content(response.choices[0].message.content)
        elif effective_provider == "openrouter":
            # OpenRouter API-Aufruf vorbereiten
            create_kwargs = {
                "model": effective_model,
                "messages": [{"role": "user", "content": full_prompt}],
            }

            # Provider-Routing konfigurieren (optional)
            provider_order = os.getenv("OPENROUTER_PROVIDER_ORDER")
            if provider_order:
                providers = [p.strip() for p in provider_order.split(",")]
                allow_fallbacks = (
                    os.getenv("OPENROUTER_ALLOW_FALLBACKS", "true").lower() == "true"
                )
                create_kwargs["extra_body"] = {
                    "provider": {
                        "order": providers,
                        "allow_fallbacks": allow_fallbacks,
                    }
                }
                logger.info(
                    f"[{_session_id}] OpenRouter Provider: {', '.join(providers)} "
                    f"(fallbacks: {allow_fallbacks})"
                )

            response = client.chat.completions.create(**create_kwargs)
            result = _extract_message_content(response.choices[0].message.content)
        else:
            # OpenAI responses API
            api_params = {"model": effective_model, "input": full_prompt}
            # GPT-5 nutzt "reasoning" API – "minimal" für schnelle Korrekturen
            # statt tiefgehender Analyse (spart Tokens und Latenz)
            if effective_model.startswith("gpt-5"):
                api_params["reasoning"] = {"effort": "minimal"}
            response = client.responses.create(**api_params)
            result = response.output_text.strip()

    logger.debug(f"[{_session_id}] Output: {_log_preview(result)}")
    return result


def maybe_refine_transcript(transcript: str, args: argparse.Namespace) -> str:
    """Wendet LLM-Nachbearbeitung an, falls aktiviert. Gibt Rohtext bei Fehler zurück."""
    from openai import APIError, APIConnectionError, RateLimitError

    if not args.refine or args.no_refine:
        return transcript

    try:
        return refine_transcript(
            transcript,
            model=args.refine_model,
            provider=args.refine_provider,
            context=getattr(args, "context", None),
        )
    except ValueError as e:
        # Fehlende API-Keys (z.B. OPENROUTER_API_KEY)
        logger.warning(f"LLM-Nachbearbeitung übersprungen: {e}")
        return transcript
    except (APIError, APIConnectionError, RateLimitError) as e:
        logger.warning(f"LLM-Nachbearbeitung fehlgeschlagen: {e}")
        return transcript


# Standard-Modelle pro Modus
DEFAULT_MODELS = {
    "openai": DEFAULT_API_MODEL,
    "deepgram": DEFAULT_DEEPGRAM_MODEL,
    "groq": DEFAULT_GROQ_MODEL,
    "local": DEFAULT_LOCAL_MODEL,
}


def transcribe(
    audio_path: Path,
    mode: str,
    model: str | None = None,
    language: str | None = None,
    response_format: str = "text",
) -> str:
    """
    Zentrale Transkriptions-Funktion – wählt API, Deepgram, Groq oder lokal.

    Dies ist der einzige Einstiegspunkt für Transkription,
    unabhängig vom gewählten Modus.

    Nutzt providers.get_provider() für die eigentliche Transkription.
    """
    from providers import get_provider

    # Provider validieren
    if mode not in DEFAULT_MODELS:
        supported = ", ".join(sorted(DEFAULT_MODELS.keys()))
        raise ValueError(f"Ungültiger Modus '{mode}'. Unterstützt: {supported}")

    # Provider holen und transkribieren
    provider = get_provider(mode)

    # Deepgram, Groq und lokal unterstützen kein response_format
    if response_format != "text" and mode != "openai":
        log(f"Hinweis: --format wird im {mode}-Modus ignoriert")

    # OpenAI unterstützt response_format
    if mode == "openai":
        return provider.transcribe(
            audio_path,
            model=model,
            language=language,
            response_format=response_format,
        )

    # Andere Provider
    return provider.transcribe(
        audio_path,
        model=model,
        language=language,
    )


def parse_args() -> argparse.Namespace:
    """Parst und validiert CLI-Argumente."""
    parser = argparse.ArgumentParser(
        description="Audio transkribieren mit Whisper, Deepgram oder Groq",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  %(prog)s audio.mp3
  %(prog)s audio.mp3 --mode local --model large
  %(prog)s audio.mp3 --mode deepgram --language de
  %(prog)s audio.mp3 --mode groq --language de
  %(prog)s --record --copy --language de
        """,
    )

    parser.add_argument("audio", type=Path, nargs="?", help="Pfad zur Audiodatei")
    parser.add_argument(
        "-r", "--record", action="store_true", help="Vom Mikrofon aufnehmen"
    )
    parser.add_argument(
        "--record-daemon",
        action="store_true",
        help="Daemon-Modus: Aufnahme bis SIGUSR1 (für Raycast)",
    )
    parser.add_argument(
        "-c", "--copy", action="store_true", help="Ergebnis in Zwischenablage"
    )
    parser.add_argument(
        "--mode",
        choices=["openai", "local", "deepgram", "groq"],
        default=os.getenv("WHISPER_GO_MODE", "openai"),
        help="Transkriptions-Modus (auch via WHISPER_GO_MODE env)",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("WHISPER_GO_MODEL"),
        help="Modellname (CLI > WHISPER_GO_MODEL env > Provider-Default). Defaults: API=gpt-4o-transcribe, Deepgram=nova-3, Groq=whisper-large-v3, Lokal=turbo",
    )
    parser.add_argument(
        "--language",
        default=os.getenv("WHISPER_GO_LANGUAGE"),
        help="Sprachcode z.B. 'de', 'en' (auch via WHISPER_GO_LANGUAGE env)",
    )
    parser.add_argument(
        "--format",
        dest="response_format",
        choices=["text", "json", "srt", "vtt"],
        default="text",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Debug-Logging aktivieren (auch auf stderr)",
    )
    parser.add_argument(
        "--refine",
        action="store_true",
        default=os.getenv("WHISPER_GO_REFINE", "").lower() == "true",
        help="LLM-Nachbearbeitung aktivieren (auch via WHISPER_GO_REFINE env)",
    )
    parser.add_argument(
        "--no-refine",
        action="store_true",
        help="LLM-Nachbearbeitung deaktivieren (überschreibt env)",
    )
    parser.add_argument(
        "--refine-model",
        default=None,
        help=f"Modell für LLM-Nachbearbeitung (default: {DEFAULT_REFINE_MODEL}, auch via WHISPER_GO_REFINE_MODEL env)",
    )
    parser.add_argument(
        "--refine-provider",
        choices=["openai", "openrouter", "groq"],
        default=None,
        help="LLM-Provider für Nachbearbeitung (auch via WHISPER_GO_REFINE_PROVIDER env)",
    )
    parser.add_argument(
        "--context",
        choices=["email", "chat", "code", "default"],
        default=None,
        help="Kontext für LLM-Nachbearbeitung (auto-detect wenn nicht gesetzt)",
    )
    parser.add_argument(
        "--no-streaming",
        action="store_true",
        help="WebSocket-Streaming deaktivieren (nur für deepgram, auch via WHISPER_GO_STREAMING=false)",
    )

    args = parser.parse_args()

    # Validierung: genau eine Audio-Quelle erforderlich
    has_audio_source = args.record or args.record_daemon or args.audio is not None
    if not has_audio_source:
        parser.error("Entweder Audiodatei, --record oder --record-daemon verwenden")

    # Gegenseitiger Ausschluss
    if args.audio and (args.record or args.record_daemon):
        parser.error("Audiodatei und Aufnahme-Modi schließen sich aus")
    if args.record and args.record_daemon:
        parser.error("--record und --record-daemon schließen sich aus")

    return args


def _schedule_state_cleanup(delay: float = 2.0) -> None:
    """Löscht STATE_FILE nach Verzögerung in Background-Thread.

    Warum Verzögerung? Die Menübar-App pollt alle 200ms – ohne Delay
    würde sie den "done"/"error"-Status verpassen.
    """
    import threading

    def cleanup():
        time.sleep(delay)
        STATE_FILE.unlink(missing_ok=True)

    # Daemon-Thread: Beendet sich automatisch wenn Hauptprozess endet
    thread = threading.Thread(target=cleanup, daemon=True)
    thread.start()


def _should_use_streaming(args: argparse.Namespace) -> bool:
    """Prüft ob Streaming für den aktuellen Modus aktiviert ist."""
    if args.mode != "deepgram":
        return False
    if getattr(args, "no_streaming", False):
        return False
    return os.getenv("WHISPER_GO_STREAMING", "true").lower() != "false"


def run_daemon_mode_streaming(args: argparse.Namespace) -> int:
    """
    Daemon-Modus mit Deepgram Streaming (SDK v5.3).

    Audio wird parallel zur Transkription gesendet - minimale Latenz.
    Transkription läuft während der Aufnahme, nicht erst danach.

    Optimierung: Mikrofon startet SOFORT nach numpy/sounddevice Import,
    Deepgram lädt parallel im Hintergrund.
    """
    pipeline_start = time.perf_counter()

    # WICHTIG: Alte Zombie-Prozesse killen bevor neuer Daemon startet
    _cleanup_stale_pid_file()

    # Alte IPC-Dateien aufräumen
    ERROR_FILE.unlink(missing_ok=True)
    INTERIM_FILE.unlink(missing_ok=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # ULTRA-FAST STARTUP: Mikrofon SOFORT starten, Deepgram parallel laden
    # ═══════════════════════════════════════════════════════════════════════════

    # 1. Nur numpy + sounddevice laden (schnell: ~170ms)
    import numpy as np
    import sounddevice as sd

    # Zeit seit PROZESSSTART (nicht pipeline_start)
    since_process_start = (time.perf_counter() - _PROCESS_START) * 1000
    logger.info(
        f"[{_session_id}] numpy+sounddevice geladen: "
        f"{(time.perf_counter() - pipeline_start)*1000:.0f}ms "
        f"(seit Prozessstart: {since_process_start:.0f}ms)"
    )

    # Audio-Buffer für frühe Aufnahme
    early_audio_buffer: list[bytes] = []
    early_buffer_lock = threading.Lock()
    early_stop_event = threading.Event()

    def early_audio_callback(indata, _frames, _time_info, status):
        """Nimmt Audio auf während Deepgram noch lädt."""
        if status:
            logger.warning(f"[{_session_id}] Early-Audio-Status: {status}")
        if not early_stop_event.is_set():
            audio_bytes = (indata * 32767).astype(np.int16).tobytes()
            with early_buffer_lock:
                early_audio_buffer.append(audio_bytes)

    # 2. Mikrofon SOFORT starten
    logger.info(f"[{_session_id}] Starte Mikrofon (ultra-early)...")
    early_mic_stream = sd.InputStream(
        samplerate=WHISPER_SAMPLE_RATE,
        channels=WHISPER_CHANNELS,
        blocksize=WHISPER_BLOCKSIZE,
        dtype=np.float32,
        callback=early_audio_callback,
    )
    early_mic_stream.start()

    # 2b. Deepgram-Import parallel starten (~100ms) während User spricht
    deepgram_ready = threading.Event()
    deepgram_error: Exception | None = None

    def _preload_deepgram():
        """Lädt Deepgram SDK im Hintergrund."""
        nonlocal deepgram_error
        try:
            from deepgram import AsyncDeepgramClient  # noqa: F401

            logger.debug(f"[{_session_id}] Deepgram SDK vorgeladen")
        except Exception as e:
            deepgram_error = e
        finally:
            deepgram_ready.set()

    preload_thread = threading.Thread(target=_preload_deepgram, daemon=True)
    preload_thread.start()

    # Ready-Sound SOFORT - User kann sprechen!
    mic_ready_ms = (time.perf_counter() - pipeline_start) * 1000
    since_process = (time.perf_counter() - _PROCESS_START) * 1000
    logger.info(
        f"[{_session_id}] Mikrofon bereit nach {mic_ready_ms:.0f}ms "
        f"(seit Prozessstart: {since_process:.0f}ms) → READY SOUND!"
    )
    play_sound("ready")

    # State + PID für Raycast
    STATE_FILE.write_text("recording")
    PID_FILE.write_text(str(os.getpid()))
    logger.info(f"[{_session_id}] Streaming-Daemon gestartet (PID: {os.getpid()})")

    try:
        # 3. Early-Mikrofon stoppen und Buffer übergeben
        early_stop_event.set()
        early_mic_stream.stop()
        early_mic_stream.close()

        with early_buffer_lock:
            early_chunks = list(early_audio_buffer)
            early_audio_buffer.clear()

        logger.info(
            f"[{_session_id}] Early-Buffer: {len(early_chunks)} Chunks gepuffert"
        )

        # 4. Warten auf Deepgram-Preload (sollte längst fertig sein)
        deepgram_ready.wait(timeout=5.0)
        if deepgram_error:
            raise deepgram_error

        # 5. Streaming mit vorgepuffertem Audio starten
        transcript = _transcribe_with_deepgram_stream_with_buffer(
            model=args.model or DEFAULT_DEEPGRAM_MODEL,
            language=args.language,
            early_buffer=early_chunks,
        )

        play_sound("stop")
        log("✅ Streaming-Aufnahme beendet.")

        # State: Transcribing (für Refine-Phase)
        STATE_FILE.write_text("transcribing")

        # LLM-Nachbearbeitung (optional)
        transcript = maybe_refine_transcript(transcript, args)

        TRANSCRIPT_FILE.write_text(transcript)
        print(transcript)

        if args.copy:
            copy_to_clipboard(transcript)

        # State: Done
        STATE_FILE.write_text("done")

        # Pipeline-Summary
        total_ms = (time.perf_counter() - pipeline_start) * 1000
        logger.info(
            f"[{_session_id}] ✓ Streaming-Pipeline: {_format_duration(total_ms)}, "
            f"{len(transcript)} Zeichen"
        )
        return 0

    except ImportError as e:
        early_stop_event.set()
        early_mic_stream.stop()
        early_mic_stream.close()
        msg = f"Deepgram-Streaming nicht verfügbar: {e}"
        logger.error(f"[{_session_id}] {msg}")
        error(msg)
        ERROR_FILE.write_text(msg)
        STATE_FILE.write_text("error")
        play_sound("error")
        return 1
    except Exception as e:
        early_stop_event.set()
        try:
            early_mic_stream.stop()
            early_mic_stream.close()
        except Exception:
            pass
        logger.exception(f"[{_session_id}] Streaming-Fehler: {e}")
        error(str(e))
        ERROR_FILE.write_text(str(e))
        STATE_FILE.write_text("error")
        play_sound("error")
        return 1
    finally:
        PID_FILE.unlink(missing_ok=True)
        INTERIM_FILE.unlink(missing_ok=True)
        _schedule_state_cleanup()


def run_daemon_mode(args: argparse.Namespace) -> int:
    """
    Daemon-Modus für Raycast: Aufnahme → Transkription → Datei.
    Schreibt Fehler in ERROR_FILE für besseres Feedback.
    Aktualisiert STATE_FILE für Menübar-Feedback.

    Bei deepgram-Modus wird Streaming verwendet (Standard),
    außer --no-streaming oder WHISPER_GO_STREAMING=false.
    """
    # Double-Fork für echten Daemon (verhindert Zombies bei Raycast spawn+unref)
    _daemonize()

    # Streaming ist Default für Deepgram
    if _should_use_streaming(args):
        return run_daemon_mode_streaming(args)

    # Klassischer Modus: Erst aufnehmen, dann transkribieren
    temp_file: Path | None = None
    pipeline_start = time.perf_counter()

    # Alte Error-Datei aufräumen
    if ERROR_FILE.exists():
        ERROR_FILE.unlink()

    try:
        # State: Recording
        STATE_FILE.write_text("recording")

        audio_path = record_audio_daemon()
        temp_file = audio_path

        # State: Transcribing
        STATE_FILE.write_text("transcribing")

        transcript = transcribe(
            audio_path,
            mode=args.mode,
            model=args.model,
            language=args.language,
            response_format=args.response_format,
        )

        # LLM-Nachbearbeitung (optional)
        transcript = maybe_refine_transcript(transcript, args)

        TRANSCRIPT_FILE.write_text(transcript)
        print(transcript)

        if args.copy:
            copy_to_clipboard(transcript)

        # State: Done
        STATE_FILE.write_text("done")

        # Pipeline-Summary
        total_ms = (time.perf_counter() - pipeline_start) * 1000
        logger.info(
            f"[{_session_id}] ✓ Pipeline: {_format_duration(total_ms)}, "
            f"{len(transcript)} Zeichen"
        )
        return 0

    except ImportError:
        msg = "Für Aufnahme: pip install sounddevice soundfile"
        logger.error(f"[{_session_id}] {msg}")
        error(msg)
        ERROR_FILE.write_text(msg)
        STATE_FILE.write_text("error")
        return 1
    except Exception as e:
        logger.exception(f"[{_session_id}] Fehler im Daemon-Modus: {e}")
        error(str(e))
        ERROR_FILE.write_text(str(e))
        STATE_FILE.write_text("error")
        return 1
    finally:
        if temp_file and temp_file.exists():
            temp_file.unlink()
        # State-Datei nach kurzer Verzögerung aufräumen (non-blocking)
        _schedule_state_cleanup()


def main() -> int:
    """CLI-Einstiegspunkt."""
    load_environment()
    args = parse_args()
    setup_logging(debug=args.debug)

    # Startup-Timing loggen (seit Prozessstart)
    startup_ms = (time.perf_counter() - _PROCESS_START) * 1000
    logger.info(f"[{_session_id}] Startup: {_format_duration(startup_ms)}")

    logger.debug(f"[{_session_id}] Args: {args}")

    # Daemon-Modus hat eigene Logik (für Raycast)
    if args.record_daemon:
        return run_daemon_mode(args)

    # Audio-Quelle bestimmen
    temp_file: Path | None = None

    if args.record:
        try:
            audio_path = record_audio()
            temp_file = audio_path
        except ImportError:
            error("Für Aufnahme: pip install sounddevice soundfile")
            return 1
        except ValueError as e:
            error(str(e))
            return 1
    else:
        audio_path = args.audio
        if not audio_path.exists():
            error(f"Datei nicht gefunden: {audio_path}")
            return 1

    # Transkription durchführen
    try:
        transcript = transcribe(
            audio_path,
            mode=args.mode,
            model=args.model,
            language=args.language,
            response_format=args.response_format,
        )
    except ImportError as e:
        err_str = str(e).lower()
        if "openai" in err_str:
            package = "openai"
        elif "deepgram" in err_str:
            package = "deepgram-sdk"
        else:
            package = "openai-whisper"
        error(f"Modul nicht installiert: pip install {package}")
        return 1
    except Exception as e:
        error(str(e))
        return 1
    finally:
        if temp_file and temp_file.exists():
            temp_file.unlink()

    # LLM-Nachbearbeitung (optional)
    transcript = maybe_refine_transcript(transcript, args)

    # Ausgabe
    print(transcript)

    if args.copy:
        if copy_to_clipboard(transcript):
            log("📋 In Zwischenablage kopiert!")
        else:
            log("⚠️  Zwischenablage nicht verfügbar")

    # Pipeline-Summary
    total_ms = (time.perf_counter() - _PROCESS_START) * 1000
    logger.info(
        f"[{_session_id}] ✓ Pipeline: {_format_duration(total_ms)}, "
        f"{len(transcript)} Zeichen"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
