"""Marks the development tools as a package, so each one has a single name.

They are run as `tools.shipbob_mock` and `tools.seed_merchant_memory`, and
a test reads the stand-in's claim list to check the demo data can still demonstrate what it is
there for. Without this file the type checker reaches the same module under two names and
refuses it, exactly as it would for `tests/`.

Nothing in `src/` may import from here.
"""
