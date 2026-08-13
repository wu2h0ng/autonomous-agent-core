"""Compatibility alias; Data Agent report behavior has one domain-pack owner."""

import sys

from domain_packs.data_agent import report_adapter as _implementation

sys.modules[__name__] = _implementation
