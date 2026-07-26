from __future__ import annotations

import sys
from typing import Optional, Sequence


def plugin_main(argv: Optional[Sequence[str]] = None) -> None:
    from .router import parse_request
    from .runtime import Runtime
    from .views import PluginUI

    arguments = list(argv or sys.argv)
    base_url = arguments[0]
    handle = int(arguments[1])
    query = arguments[2] if len(arguments) > 2 else ""
    runtime = Runtime()
    request = parse_request(base_url, query)
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
            context = KodiContext()
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
        ServiceLoop(context, monitor=monitor).run()
    except Exception as exc:
        context.log.error("MyPicsDB 3 service stopped with an error: %s", exc)
    finally:
        context.log.info("MyPicsDB 3 service stopped")
