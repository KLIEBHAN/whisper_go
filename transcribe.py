#!/usr/bin/env python3
"""
Hauptmodul und CLI-Einstiegspunkt für PulseScribe.

Dieses Modul fungiert als zentraler Orchestrator, der die spezialisierten
Sub-Module koordiniert:
- audio/: Audio-Aufnahme und -Verarbeitung
- providers/: Transkriptions-Dienste (Deepgram, OpenAI, etc.)
- refine/: LLM-Nachbearbeitung und Kontext-Erkennung
- utils/: Logging, Timing und Hilfsfunktionen

Es stellt die `main()` Routine bereit und verwaltet die CLI-Argumente.

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
import logging  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from typing import TYPE_CHECKING  # noqa: E402

from pathlib import Path  # noqa: E402

if TYPE_CHECKING:
    pass

# Import-Zeit messen (alle Standardlib-Imports abgeschlossen)
_IMPORTS_DONE = _time_module.perf_counter()
time = _time_module  # Alias für restlichen Code

# =============================================================================
# Zentrale Konfiguration importieren
# =============================================================================

from config import (  # noqa: E402
    # Models
    DEFAULT_API_MODEL,
    DEFAULT_LOCAL_MODEL,
    DEFAULT_DEEPGRAM_MODEL,
    DEFAULT_GROQ_MODEL,
    DEFAULT_REFINE_MODEL,
    # Paths
    VOCABULARY_FILE,
)

# =============================================================================
# Laufzeit-State (modulglobal)
# =============================================================================

logger = logging.getLogger("pulsescribe")
_custom_app_contexts_cache: dict | None = None  # Cache für PULSESCRIBE_APP_CONTEXTS

# API-Client Singletons (Lazy Init) – für LLM-Refine
# Transkriptions-Clients sind jetzt in providers/
_groq_client = None


from utils.logging import (  # noqa: E402
    setup_logging,
    log,
    error,
    get_session_id as _get_session_id,
)
from utils.env import get_env_bool_default  # noqa: E402
from utils.environment import load_environment  # noqa: E402
from utils.timing import (  # noqa: E402
    format_duration as _format_duration,
    log_preview as _shared_log_preview,
)
from utils.vocabulary import load_vocabulary as _load_vocabulary_shared  # noqa: E402


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
# Sound-Playback & Audio-Aufnahme
# =============================================================================

from whisper_platform import get_sound_player  # noqa: E402


def play_sound(name: str) -> None:
    """Delegiert an whisper_platform."""
    try:
        get_sound_player().play(name)
    except Exception:
        pass


from audio.recording import record_audio  # noqa: E402

# =============================================================================
# Logging-Helfer
# =============================================================================


def _log_preview(text: str, max_length: int = 100) -> str:
    """Kürzt Logtexte, um Logfiles schlank zu halten.

    Wrapper um utils.timing.log_preview für vereinheitlichte Log-Formatierung.
    """
    return _shared_log_preview(text, max_length)


 


# =============================================================================
# Custom Vocabulary (Fachbegriffe, Namen)
# =============================================================================


def load_vocabulary() -> dict:
    """Lädt Custom Vocabulary aus JSON-Datei.

    Wrapper für utils.vocabulary.load_vocabulary(), damit die öffentliche
    API von transcribe.py stabil bleibt und Tests weiter greifen.
    """
    return _load_vocabulary_shared(VOCABULARY_FILE)


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
# Kontext-Erkennung (delegiert an refine.context)
# =============================================================================


# =============================================================================
# LLM-Nachbearbeitung (delegiert an refine.llm)
# =============================================================================

from refine.llm import maybe_refine_transcript  # noqa: E402


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
        from typing import cast
        from providers.openai import OpenAIProvider

        openai_provider = cast(OpenAIProvider, provider)
        return openai_provider.transcribe(
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
        "-c", "--copy", action="store_true", help="Ergebnis in Zwischenablage"
    )
    parser.add_argument(
        "--mode",
        choices=["openai", "local", "deepgram", "groq"],
        default=os.getenv("PULSESCRIBE_MODE", "openai"),
        help="Transkriptions-Modus (auch via PULSESCRIBE_MODE env)",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("PULSESCRIBE_MODEL"),
        help="Modellname (CLI > PULSESCRIBE_MODEL env > Provider-Default). Defaults: API=gpt-4o-transcribe, Deepgram=nova-3, Groq=whisper-large-v3, Lokal=turbo",
    )
    parser.add_argument(
        "--language",
        default=os.getenv("PULSESCRIBE_LANGUAGE"),
        help="Sprachcode z.B. 'de', 'en' (auch via PULSESCRIBE_LANGUAGE env)",
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
        default=get_env_bool_default("PULSESCRIBE_REFINE", False),
        help="LLM-Nachbearbeitung aktivieren (auch via PULSESCRIBE_REFINE env)",
    )
    parser.add_argument(
        "--no-refine",
        action="store_true",
        help="LLM-Nachbearbeitung deaktivieren (überschreibt env)",
    )
    parser.add_argument(
        "--refine-model",
        default=None,
        help=f"Modell für LLM-Nachbearbeitung (default: {DEFAULT_REFINE_MODEL}, auch via PULSESCRIBE_REFINE_MODEL env)",
    )
    parser.add_argument(
        "--refine-provider",
        choices=["openai", "openrouter", "groq"],
        default=None,
        help="LLM-Provider für Nachbearbeitung (auch via PULSESCRIBE_REFINE_PROVIDER env)",
    )
    parser.add_argument(
        "--context",
        choices=["email", "chat", "code", "default"],
        default=None,
        help="Kontext für LLM-Nachbearbeitung (auto-detect wenn nicht gesetzt)",
    )

    args = parser.parse_args()

    # Validierung: genau eine Audio-Quelle erforderlich
    has_audio_source = args.record or args.audio is not None
    if not has_audio_source:
        parser.error("Entweder Audiodatei oder --record verwenden")

    # Gegenseitiger Ausschluss
    if args.audio and args.record:
        parser.error("Audiodatei und Aufnahme-Modi schließen sich aus")

    return args


def main() -> int:
    """CLI-Einstiegspunkt."""
    load_environment()
    args = parse_args()
    setup_logging(debug=args.debug)

    # Startup-Timing loggen (seit Prozessstart)
    startup_ms = (time.perf_counter() - _PROCESS_START) * 1000
    logger.info(f"[{_get_session_id()}] Startup: {_format_duration(startup_ms)}")

    logger.debug(f"[{_get_session_id()}] Args: {args}")

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
        f"[{_get_session_id()}] ✓ Pipeline: {_format_duration(total_ms)}, "
        f"{len(transcript)} Zeichen"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
