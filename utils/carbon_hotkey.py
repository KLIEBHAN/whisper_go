"""Safe Carbon hotkey registration for macOS.

We use quickmachotkey's Carbon bindings, but add two safeguards:

1) `RegisterEventHotKey` returns an OSStatus. If registration fails, we must not
   keep an invalid reference, otherwise later unregister can crash the process.
2) We should also remove the handler from quickmachotkey's global handler dict.
"""

from __future__ import annotations

from typing import Callable


class CarbonHotKeyRegistration:
    """Register/unregister a single Carbon hotkey via quickmachotkey."""

    def __init__(self, *, virtual_key: int, modifier_mask: int, callback: Callable[[], None]):
        self._virtual_key = int(virtual_key)
        self._modifier_mask = int(modifier_mask)
        self._callback = callback
        self._hotkey_id: int | None = None
        self._ref = None

    @staticmethod
    def _call_on_main_sync(fn, *, timeout_s: float = 2.0):
        """Run `fn` on the main thread and wait for the result (best-effort)."""
        try:
            from Foundation import NSThread  # type: ignore[import-not-found]

            if NSThread.isMainThread():
                return True, fn()
        except Exception:
            return True, fn()

        try:
            from PyObjCTools import AppHelper  # type: ignore[import-not-found]
        except Exception:
            # No dispatcher available – run directly (best-effort).
            return True, fn()

        import threading

        done = threading.Event()
        box: dict[str, object] = {}

        def run() -> None:
            try:
                box["result"] = fn()
            except Exception as e:  # pragma: no cover
                box["error"] = e
            finally:
                done.set()

        AppHelper.callAfter(run)
        if not done.wait(timeout_s):
            return False, TimeoutError("Timed out waiting for main thread")
        if "error" in box:
            raise box["error"]  # type: ignore[misc]
        return True, box.get("result")

    def register(self) -> tuple[bool, str | None]:
        """Registers the hotkey. Returns (ok, error_message)."""
        def _impl() -> tuple[bool, str | None]:
            try:
                import sys

                if sys.platform != "darwin":
                    return False, "Carbon hotkeys are only supported on macOS"
            except Exception:
                pass

            try:
                import quickmachotkey
                from quickmachotkey._MinimalHIToolbox import (  # type: ignore[attr-defined]
                    GetEventDispatcherTarget,
                    RegisterEventHotKey,
                )
                from struct import unpack
            except Exception as e:  # pragma: no cover
                return False, f"quickmachotkey unavailable: {e}"

            qmhk = getattr(quickmachotkey, "_QMHK", None)
            if qmhk is None:
                try:
                    (qmhk,) = unpack("@I", b"QMHK")
                except Exception:  # pragma: no cover
                    qmhk = 0

            hkid = None
            try:
                quickmachotkey.registrationCounter += 1
                hkid = quickmachotkey.registrationCounter
                quickmachotkey.hotKeyHandlers[hkid] = self._callback
                hotkey_id = (qmhk, hkid)
                result, ref = RegisterEventHotKey(
                    self._virtual_key,
                    self._modifier_mask,
                    hotkey_id,
                    GetEventDispatcherTarget(),
                    0,
                    None,
                )
            except Exception as e:
                if hkid is not None:
                    try:
                        quickmachotkey.hotKeyHandlers.pop(hkid, None)
                    except Exception:
                        pass
                return False, str(e)

            if int(result) != 0 or ref is None:
                try:
                    quickmachotkey.hotKeyHandlers.pop(hkid, None)
                except Exception:
                    pass
                return False, f"RegisterEventHotKey failed (OSStatus={int(result)})"

            self._hotkey_id = int(hkid)
            self._ref = ref
            return True, None

        try:
            ok, out = self._call_on_main_sync(_impl)
        except Exception as e:  # pragma: no cover
            return False, str(e)

        if not ok:
            return False, str(out)
        if isinstance(out, tuple):
            return out  # type: ignore[return-value]
        return False, "Hotkey registration failed"

    def unregister(self) -> None:
        """Unregisters the hotkey (best-effort)."""
        def _impl() -> None:
            try:
                import quickmachotkey
                from quickmachotkey._MinimalHIToolbox import (  # type: ignore[attr-defined]
                    UnregisterEventHotKey,
                )
            except Exception:
                quickmachotkey = None  # type: ignore[assignment]
                UnregisterEventHotKey = None  # type: ignore[assignment]

            ref = self._ref
            self._ref = None
            hkid = self._hotkey_id
            self._hotkey_id = None

            if quickmachotkey is not None and hkid is not None:
                try:
                    quickmachotkey.hotKeyHandlers.pop(int(hkid), None)
                except Exception:
                    pass

            if ref is not None and UnregisterEventHotKey is not None:
                try:
                    UnregisterEventHotKey(ref)
                except Exception:
                    pass

        try:
            self._call_on_main_sync(_impl)
        except Exception:
            pass


__all__ = ["CarbonHotKeyRegistration"]
