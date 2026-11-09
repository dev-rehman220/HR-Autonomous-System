"""Logging bootstrap shared by the Streamlit UI and the CLI entry points."""
from __future__ import annotations

import logging

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format=_FORMAT)
