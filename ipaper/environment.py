"""Read iPaper configuration with explicit legacy-prefix compatibility."""
from __future__ import annotations

import logging
import os
from typing import Mapping


def getenv(name: str, default=None, *, environ: Mapping[str, str] | None = None):
    values = os.environ if environ is None else environ
    if not name.startswith("IPAPER_"):
        return values.get(name, default)
    legacy = "PAPERPILOT_" + name[len("IPAPER_"):]
    if name in values:
        if legacy in values and values[name] != values[legacy]:
            logging.getLogger(__name__).warning("Configuration %s overrides %s", name, legacy)
        return values[name]
    return values.get(legacy, default)
