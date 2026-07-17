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
    from .kodi import KodiContext
    from .service_loop import ServiceLoop

    context = KodiContext()
    context.log.info("MyPicsDB 3 service started")
    try:
        ServiceLoop(context).run()
    except Exception as exc:
        context.log.error("MyPicsDB 3 service stopped with an error: %s", exc)
    finally:
        context.log.info("MyPicsDB 3 service stopped")
