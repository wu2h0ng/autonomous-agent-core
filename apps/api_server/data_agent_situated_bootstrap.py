"""Compatibility alias; Data Agent situated runtime has one domain-pack owner."""

import sys

from domain_packs.data_agent import situated as _implementation

sys.modules[__name__] = _implementation
