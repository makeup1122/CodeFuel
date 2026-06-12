from __future__ import annotations

import logging

from codefuel.log import resolve_level


def test_resolve_level_names():
    assert resolve_level("DEBUG") == logging.DEBUG
    assert resolve_level("info") == logging.INFO
    assert resolve_level("Warning") == logging.WARNING
    assert resolve_level("ERROR") == logging.ERROR


def test_resolve_level_passthrough_and_fallback():
    assert resolve_level(logging.DEBUG) == logging.DEBUG  # int passthrough
    assert resolve_level("nonsense") == logging.INFO       # unknown -> INFO
    assert resolve_level(None) == logging.INFO             # None -> INFO
