"""Marks the tests as a package, so their sample records have one name.

The development tools in `tools/` serve the same sample claim records the tests use, so
that the demo screen and the tests can never disagree about what CASE-1001 looks like.
That import — `tests.fixtures.shipbob` — only has a single, unambiguous name if this
folder is a package, and the type checker refuses a file it can reach under two names.
"""
