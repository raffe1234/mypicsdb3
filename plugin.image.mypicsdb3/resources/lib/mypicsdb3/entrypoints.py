from __future__ import annotations

import sys
from typing import Optional, Sequence


DATABASE_BUSY_STRING_ID = 32614
DATABASE_BUSY_FALLBACK = "MyPicsDB 3 is starting. Please try again in a moment."
DIAGNOSTIC_LOG_ROUTE = "action/log-diagnostic"
DIAGNOSTIC_LOG_STRING_ID = 32721
DIAGNOSTIC_LOG_FALLBACK = "Diagnostic entry written to kodi.log"
HOME_STATE_PUBLISH_DELAY_SECONDS = 5.0


def _finish_database_busy_plugin_request(context, handle: int, request) -> None:
    from .utils import parse_bool

    message = context.localize(DATABASE_BUSY_STRING_ID, DATABASE_BUSY_FALLBACK)
    is_widget = parse_bool(request.params.get("widget"), False)
    if not is_widget:
        context.notify(message, milliseconds=5000, force=True)

    # RunPlugin actions do not own a directory listing. Browser and widget
    # requests must still finish successfully so Kodi does not show a raw
    # plug-in error or cache a temporary empty result.
    if not request.route.startswith("action/"):
        import xbmcplugin  # type: ignore

        xbmcplugin.endOfDirectory(
            handle,
            succeeded=True,
            cacheToDisc=False,
        )


def _write_diagnostic_log_entry(context) -> None:
    from . import VERSION

    settings = context.refresh_settings()
    context.log.info(
        "Diagnostic log entry: version=%s debug_logging=%s",
        VERSION,
        "true" if settings.debug_logging else "false",
    )
    context.notify(
        context.localize(DIAGNOSTIC_LOG_STRING_ID, DIAGNOSTIC_LOG_FALLBACK),
        force=True,
    )


def plugin_main(argv: Optional[Sequence[str]] = None) -> None:
    from .kodi import KodiContext
    from .router import parse_request

    arguments = list(argv or sys.argv)
    base_url = arguments[0]
    handle = int(arguments[1])
    query = arguments[2] if len(arguments) > 2 else ""
    request = parse_request(base_url, query)
    context = KodiContext()
    if request.route == DIAGNOSTIC_LOG_ROUTE:
        _write_diagnostic_log_entry(context)
        return

    from .db.migrations import MigrationLockError
    from .runtime import Runtime
    from .views import PluginUI

    try:
        runtime = Runtime(kodi_context=context)
    except MigrationLockError as exc:
        context.log.info("Database initialization is busy: %s", exc)
        _finish_database_busy_plugin_request(context, handle, request)
        return
    PluginUI(runtime, base_url, handle).dispatch(request)


def service_main() -> None:
    from .kodi import KodiContext, create_abort_monitor
    from .service_loop import ServiceLoop

    monitor = create_abort_monitor()

    # During an in-place update Kodi can briefly start the service between
    # unregistering the old add-on and registering the new one.
    context = None
    last_error: Optional[RuntimeError] = None
    for attempt in range(5):
        try:
            context = KodiContext(publish_home_state=False)
            break
        except RuntimeError as exc:
            if "Unknown addon id" not in str(exc):
                raise
            last_error = exc
            if attempt < 4 and monitor.waitForAbort(1.0):
                return

    if context is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError("Could not initialize the MyPicsDB 3 Kodi context")

    if monitor.abortRequested():
        return

    context.log.info("MyPicsDB 3 service started")
    try:
        if monitor.waitForAbort(HOME_STATE_PUBLISH_DELAY_SECONDS):
            context.log.info(
                "Service shutdown requested before delayed home state publication"
            )
            return
        state_checker = getattr(context, "home_layout_state_published", None)
        home_state_was_present = (
            bool(state_checker()) if callable(state_checker) else True
        )
        context.enable_home_state_publishing()
        context.log.info(
            "Home-screen state published after %.1f-second service startup delay",
            HOME_STATE_PUBLISH_DELAY_SECONDS,
        )
        if not home_state_was_present:
            reloader = getattr(
                context, "reload_estuary_home_after_initial_state_publish", None
            )
            if callable(reloader) and reloader():
                context.log.info(
                    "Reloaded Estuary MyPicsDB 3 after initial Home state publication"
                )
        ServiceLoop(context, monitor=monitor).run()
    except Exception as exc:
        context.log.error("MyPicsDB 3 service stopped with an error: %s", exc)
    finally:
        context.log.info("MyPicsDB 3 service stopped")
