"""Compatibility alias; Data Agent report policy has one domain-pack owner."""

import sys

from domain_packs.data_agent import report_policy as _implementation

sys.modules[__name__] = _implementation
