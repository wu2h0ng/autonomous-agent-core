"""Compatibility alias; Data Agent admission has one domain-pack owner."""

import sys

from domain_packs.data_agent import report_admission as _implementation

sys.modules[__name__] = _implementation
