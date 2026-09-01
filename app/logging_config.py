"""Application logging setup.

Uvicorn's default dictConfig only attaches handlers to the `uvicorn*` loggers —
it leaves the root logger untouched. Without this module every `app.*` logger
falls through to `logging.lastResort`, which prints WARNING-and-above with no
timestamp and drops INFO entirely, so the enrichment pipeline runs blind in a
deployed container. Configuring root here puts our own records on stderr next to
uvicorn's, which is what Render/Docker collect.
"""

import logging
import sys

from app.config import get_settings

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def configure_logging() -> None:
    """Attach a stderr handler to the root logger at `LOG_LEVEL`.

    Idempotent: called both at import of `app.main` (so `python -m scripts.*`
    gets logs too) and from the lifespan, which runs *after* uvicorn applies its
    own config and is therefore the call that reliably wins.
    """
    global _configured

    level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    root = logging.getLogger()

    if not _configured:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT))
        root.addHandler(handler)
        _configured = True

    root.setLevel(level)
    # httpx logs one INFO line per request with the full URL (which carries the
    # API key as a query param for some providers). Keep it at WARNING.
    logging.getLogger("httpx").setLevel(logging.WARNING)
