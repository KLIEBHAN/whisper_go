#!/usr/bin/env python3
"""
whisper_daemon.py – Unified Daemon für whisper_go.

Konsolidiert in einem Prozess:
- Hotkey-Listener (QuickMacHotKey, keine Accessibility nötig)
- Mikrofon-Aufnahme (sounddevice)
- Transkription (Deepgram Streaming)
- LLM-Nachbearbeitung (optional)
- Auto-Paste (pynput/Quartz)

Architektur:
- Main Thread: NSApplication Event-Loop (QuickMacHotKey, Mikrofon-Callback)
- Worker Thread: asyncio Event-Loop (Deepgram WebSocket, HTTP APIs)

Usage:
    python whisper_daemon.py              # Mit Defaults aus .env
    python whisper_daemon.py --hotkey f19 # Hotkey überschreiben
"""

import asyncio
import logging
import os
import queue
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

# =============================================================================
# Konfiguration
# =============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_DIR = SCRIPT_DIR / "logs"
LOG_FILE = LOG_DIR / "whisper_daemon.log"

# Audio-Konfiguration (Whisper-kompatibel)
WHISPER_SAMPLE_RATE = 16000
WHISPER_CHANNELS = 1
WHISPER_BLOCKSIZE = 1024
INT16_MAX = 32767

# Timeouts
RESULT_POLL_INTERVAL_MS = 50  # NSTimer Polling-Intervall
DEBOUNCE_INTERVAL = 0.3  # Ignoriere Hotkey-Events innerhalb 300ms

# =============================================================================
# Logging
# =============================================================================

logger = logging.getLogger("whisper_daemon")


def setup_logging(debug: bool = False) -> None:
    """Konfiguriert Logging mit Datei-Output."""
    LOG_DIR.mkdir(exist_ok=True)

    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    )
    logger.addHandler(file_handler)

    if debug:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.DEBUG)
        stderr_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(stderr_handler)


# =============================================================================
# Imports aus bestehenden Modulen (DRY: Import statt Duplizieren)
# =============================================================================

# Lazy Imports für schnelleren Startup
_transcribe_module = None
_hotkey_module = None


def _get_transcribe():
    """Lazy Import für transcribe.py."""
    global _transcribe_module
    if _transcribe_module is None:
        import transcribe

        _transcribe_module = transcribe
    return _transcribe_module


def _get_hotkey():
    """Lazy Import für hotkey_daemon.py."""
    global _hotkey_module
    if _hotkey_module is None:
        import hotkey_daemon

        _hotkey_module = hotkey_daemon
    return _hotkey_module


# =============================================================================
# AsyncWorker: Eigener Thread mit asyncio Event-Loop
# =============================================================================


class AsyncWorker:
    """
    Worker-Thread mit eigenem asyncio Event-Loop.

    Verarbeitet async Tasks (Deepgram WebSocket, HTTP APIs) ohne
    den Main-Thread (NSApplication) zu blockieren.

    Thread-Sicherheit:
    - submit() ist von jedem Thread aufrufbar
    - result_queue ist thread-sicher für Cross-Thread Kommunikation
    """

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = threading.Event()
        self.result_queue: queue.Queue[str | Exception | None] = queue.Queue()

    def start(self) -> None:
        """Startet Worker-Thread."""
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="AsyncWorker"
        )
        self._thread.start()
        # Warten bis Event-Loop bereit ist
        self._started.wait(timeout=5.0)
        logger.info("AsyncWorker gestartet")

    def _run(self) -> None:
        """Event-Loop im Worker-Thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._started.set()

        try:
            self._loop.run_forever()
        except Exception as e:
            logger.exception(f"AsyncWorker crashed: {e}")
            # Auto-Restart bei Crash
            time.sleep(1)
            self._run()
        finally:
            self._loop.close()

    def submit(self, coro) -> "asyncio.Future":
        """
        Submit async Coroutine zur Ausführung im Worker-Thread.

        Thread-sicher: Kann von Main-Thread aufgerufen werden.
        """
        if not self._loop:
            raise RuntimeError("AsyncWorker not started")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)  # type: ignore[return-value]

    def stop(self) -> None:
        """Stoppt Worker-Thread sauber."""
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=2.0)


# =============================================================================
# WhisperDaemon: Hauptklasse
# =============================================================================


class WhisperDaemon:
    """
    Unified Daemon für whisper_go.

    Koordiniert:
    - QuickMacHotKey Listener (Main-Thread)
    - Mikrofon-Aufnahme (Main-Thread Callback)
    - Deepgram Streaming (Worker-Thread)
    - Auto-Paste (Main-Thread)
    """

    def __init__(
        self,
        hotkey: str = "f19",
        mode: str = "toggle",
        language: str | None = None,
        model: str | None = None,
        refine: bool = False,
        refine_model: str | None = None,
        refine_provider: str | None = None,
        context: str | None = None,
    ):
        self.hotkey = hotkey
        self.mode = mode  # toggle (PTT nicht unterstützt mit QuickMacHotKey)
        self.language = language
        self.model = model
        self.refine = refine
        self.refine_model = refine_model
        self.refine_provider = refine_provider
        self.context = context

        # State
        self._recording = False
        self._toggle_lock = threading.Lock()
        self._last_hotkey_time = 0.0

        # Worker für async Tasks
        self.worker = AsyncWorker()

        # Audio-Buffer für Early-Recording
        self._audio_buffer: list[bytes] = []
        self._buffer_lock = threading.Lock()
        self._mic_stream = None
        self._stop_event = threading.Event()

        # NSTimer für Result-Polling
        self._result_timer = None

        # Callback für State-Updates (für spätere Menübar-Integration)
        self.on_state_change: Callable[[str], None] | None = None

    def _update_state(self, state: str) -> None:
        """Benachrichtigt über State-Änderung."""
        logger.debug(f"State: {state}")
        if self.on_state_change:
            self.on_state_change(state)

    def _on_hotkey(self) -> None:
        """Callback bei Hotkey-Aktivierung."""
        # Debouncing
        now = time.time()
        if now - self._last_hotkey_time < DEBOUNCE_INTERVAL:
            logger.debug("Debounce: Event ignoriert")
            return
        self._last_hotkey_time = now

        # Thread-Lock
        if not self._toggle_lock.acquire(blocking=False):
            logger.warning("Hotkey ignoriert - Toggle bereits aktiv")
            return

        try:
            logger.debug(f"Hotkey gedrückt! Recording={self._recording}")
            self._toggle_recording()
        finally:
            self._toggle_lock.release()

    def _toggle_recording(self) -> None:
        """Toggle-Mode: Start/Stop bei jedem Tastendruck."""
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        """Startet Mikrofon-Aufnahme."""
        import numpy as np
        import sounddevice as sd

        transcribe = _get_transcribe()
        transcribe.play_sound("ready")

        self._audio_buffer.clear()
        self._stop_event.clear()
        self._recording = True
        self._update_state("recording")

        def audio_callback(indata, _frames, _time_info, status):
            """Mikrofon-Callback: Audio in Buffer sammeln."""
            if status:
                logger.warning(f"Audio-Status: {status}")
            if not self._stop_event.is_set():
                # float32 [-1,1] → int16 für Deepgram
                audio_bytes = (indata * INT16_MAX).astype(np.int16).tobytes()
                with self._buffer_lock:
                    self._audio_buffer.append(audio_bytes)

        self._mic_stream = sd.InputStream(
            samplerate=WHISPER_SAMPLE_RATE,
            channels=WHISPER_CHANNELS,
            blocksize=WHISPER_BLOCKSIZE,
            dtype=np.float32,
            callback=audio_callback,
        )
        self._mic_stream.start()
        logger.info("Aufnahme gestartet")

    def _stop_recording(self) -> None:
        """Stoppt Aufnahme und startet Transkription."""
        if not self._recording:
            return

        transcribe = _get_transcribe()
        transcribe.play_sound("stop")

        # Mikrofon stoppen
        self._stop_event.set()
        if self._mic_stream:
            self._mic_stream.stop()
            self._mic_stream.close()
            self._mic_stream = None

        # Buffer kopieren
        with self._buffer_lock:
            audio_chunks = list(self._audio_buffer)
            self._audio_buffer.clear()

        self._recording = False
        self._update_state("transcribing")

        logger.info(f"Aufnahme beendet: {len(audio_chunks)} Chunks")

        if not audio_chunks:
            logger.warning("Keine Audio-Daten aufgenommen")
            self._update_state("idle")
            return

        # Transkription im Worker-Thread starten
        self.worker.submit(self._transcribe_and_paste(audio_chunks))

        # Result-Polling starten (NSTimer im Main-Thread)
        self._start_result_polling()

    async def _transcribe_and_paste(self, audio_chunks: list[bytes]) -> None:
        """
        Async Transkription (läuft im Worker-Thread).

        Sendet gepufferte Audio-Chunks an Deepgram WebSocket.
        KEIN eigenes Mikrofon - Audio kam bereits vom Main-Thread.
        """
        transcribe = _get_transcribe()

        try:
            model = self.model or transcribe.DEFAULT_DEEPGRAM_MODEL
            transcript = await self._stream_audio_to_deepgram(audio_chunks, model)

            # LLM-Nachbearbeitung (optional)
            if self.refine and transcript:
                transcript = transcribe.refine_transcript(
                    transcript,
                    model=self.refine_model,
                    provider=self.refine_provider,
                    context=self.context,
                )

            self.worker.result_queue.put(transcript)

        except Exception as e:
            logger.exception(f"Transkription fehlgeschlagen: {e}")
            self.worker.result_queue.put(e)

    async def _stream_audio_to_deepgram(
        self, audio_chunks: list[bytes], model: str
    ) -> str:
        """
        Sendet Audio-Buffer an Deepgram und wartet auf Transkript.

        Schlanke Version von _deepgram_stream_core() - OHNE Mikrofon.
        Nutzt _create_deepgram_connection() für WebSocket-Handling.
        """
        transcribe = _get_transcribe()
        from deepgram.core.events import EventType
        from deepgram.extensions.types.sockets import ListenV1ControlMessage

        api_key = os.getenv("DEEPGRAM_API_KEY")
        if not api_key:
            raise ValueError("DEEPGRAM_API_KEY nicht gesetzt")

        final_transcripts: list[str] = []
        finalize_done = asyncio.Event()

        def on_message(result):
            if getattr(result, "from_finalize", False):
                finalize_done.set()
            transcript = transcribe._extract_transcript(result)
            if transcript and getattr(result, "is_final", False):
                final_transcripts.append(transcript)
                logger.debug(f"Final: {transcript[:50]}...")

        def on_error(error):
            logger.error(f"Deepgram Error: {error}")

        logger.info(f"Streaming {len(audio_chunks)} Chunks an Deepgram...")

        async with transcribe._create_deepgram_connection(
            api_key,
            model=model,
            language=self.language,
            sample_rate=WHISPER_SAMPLE_RATE,
            channels=WHISPER_CHANNELS,
            interim_results=False,  # Nur finale Ergebnisse
        ) as connection:
            connection.on(EventType.MESSAGE, on_message)
            connection.on(EventType.ERROR, on_error)

            # Listener-Task starten
            listen_task = asyncio.create_task(connection.start_listening())

            # Alle Audio-Chunks senden
            for chunk in audio_chunks:
                await connection.send_media(chunk)

            # Finalize senden
            logger.debug("Sende Finalize...")
            await connection.send_control(ListenV1ControlMessage(type="Finalize"))

            # Warten auf finale Transkripte
            try:
                await asyncio.wait_for(finalize_done.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Finalize-Timeout")

            # CloseStream für sauberen Shutdown
            await connection.send_control(ListenV1ControlMessage(type="CloseStream"))

            listen_task.cancel()
            await asyncio.gather(listen_task, return_exceptions=True)

        result = " ".join(final_transcripts)
        logger.info(f"Transkript: {len(result)} Zeichen")
        return result

    def _start_result_polling(self) -> None:
        """Startet NSTimer für Result-Polling."""
        from Foundation import NSTimer  # type: ignore[import-not-found]

        def check_result() -> None:
            try:
                result = self.worker.result_queue.get_nowait()
                self._stop_result_polling()

                if isinstance(result, Exception):
                    logger.error(f"Fehler: {result}")
                    transcribe = _get_transcribe()
                    transcribe.play_sound("error")
                    self._update_state("error")
                elif result:
                    self._paste_result(result)
                    self._update_state("done")
                else:
                    logger.warning("Leeres Transkript")
                    self._update_state("idle")

            except queue.Empty:
                pass  # Noch kein Result

        # NSTimer für regelmäßiges Polling
        interval = RESULT_POLL_INTERVAL_MS / 1000.0
        self._result_timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            interval, True, lambda _: check_result()
        )

    def _stop_result_polling(self) -> None:
        """Stoppt NSTimer."""
        if self._result_timer:
            self._result_timer.invalidate()
            self._result_timer = None

    def _paste_result(self, transcript: str) -> None:
        """Fügt Transkript via Auto-Paste ein."""
        hotkey = _get_hotkey()
        success = hotkey.paste_transcript(transcript)
        if success:
            logger.info(f"✓ Text eingefügt: '{transcript[:50]}...'")
        else:
            logger.error("Auto-Paste fehlgeschlagen")

    def run(self) -> None:
        """Startet Daemon (blockiert)."""
        from quickmachotkey import quickHotKey
        from AppKit import NSApplication  # type: ignore[import-not-found]

        hotkey = _get_hotkey()

        # Worker starten
        self.worker.start()

        # Hotkey parsen
        virtual_key, modifier_mask = hotkey.parse_hotkey(self.hotkey)

        logger.info(
            f"Daemon gestartet: hotkey={self.hotkey}, "
            f"virtualKey={virtual_key}, modifierMask={modifier_mask}"
        )
        print("🎤 whisper_daemon läuft", file=sys.stderr)
        print(f"   Hotkey: {self.hotkey}", file=sys.stderr)
        print("   Beenden mit Ctrl+C", file=sys.stderr)

        # Hotkey registrieren (type: ignore wegen fehlender VirtualKey/ModifierKey Stubs)
        @quickHotKey(virtualKey=virtual_key, modifierMask=modifier_mask)  # type: ignore[arg-type]
        def hotkey_handler() -> None:
            self._on_hotkey()

        # NSApplication Event-Loop (blockiert)
        app = NSApplication.sharedApplication()
        app.run()


# =============================================================================
# Environment Loading
# =============================================================================


def load_environment() -> None:
    """Lädt .env-Datei falls vorhanden."""
    try:
        from dotenv import load_dotenv

        env_file = SCRIPT_DIR / ".env"
        load_dotenv(env_file if env_file.exists() else None)
    except ImportError:
        pass


# =============================================================================
# Main
# =============================================================================


def main() -> int:
    """CLI-Einstiegspunkt."""
    import argparse

    parser = argparse.ArgumentParser(
        description="whisper_daemon – Unified Daemon für whisper_go",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  %(prog)s                          # Mit Defaults aus .env
  %(prog)s --hotkey f19             # F19 als Hotkey
  %(prog)s --hotkey cmd+shift+r     # Tastenkombination
  %(prog)s --refine                 # Mit LLM-Nachbearbeitung
        """,
    )

    parser.add_argument(
        "--hotkey",
        default=None,
        help="Hotkey (default: WHISPER_GO_HOTKEY oder 'f19')",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Sprachcode z.B. 'de', 'en'",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Deepgram-Modell (default: nova-3)",
    )
    parser.add_argument(
        "--refine",
        action="store_true",
        default=os.getenv("WHISPER_GO_REFINE", "").lower() == "true",
        help="LLM-Nachbearbeitung aktivieren",
    )
    parser.add_argument(
        "--refine-model",
        default=None,
        help="Modell für LLM-Nachbearbeitung",
    )
    parser.add_argument(
        "--refine-provider",
        choices=["openai", "openrouter", "groq"],
        default=None,
        help="LLM-Provider für Nachbearbeitung",
    )
    parser.add_argument(
        "--context",
        choices=["email", "chat", "code", "default"],
        default=None,
        help="Kontext für LLM-Nachbearbeitung",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Debug-Logging aktivieren",
    )

    args = parser.parse_args()

    # Environment laden
    load_environment()
    setup_logging(debug=args.debug)

    # Konfiguration: CLI > ENV > Default
    hotkey = args.hotkey or os.getenv("WHISPER_GO_HOTKEY", "f19")
    language = args.language or os.getenv("WHISPER_GO_LANGUAGE")
    model = args.model or os.getenv("WHISPER_GO_MODEL")

    # Daemon starten
    try:
        daemon = WhisperDaemon(
            hotkey=hotkey,
            language=language,
            model=model,
            refine=args.refine,
            refine_model=args.refine_model,
            refine_provider=args.refine_provider,
            context=args.context,
        )
        daemon.run()
    except ValueError as e:
        print(f"Konfigurationsfehler: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n👋 Daemon beendet", file=sys.stderr)
        return 0
    except Exception as e:
        logger.exception(f"Unerwarteter Fehler: {e}")
        print(f"Fehler: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
