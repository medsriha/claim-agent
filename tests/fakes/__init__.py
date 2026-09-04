"""Stand-ins the tests use in place of things that would leave this process.

Nothing in here reaches a network, a model provider, or a clock. Each stand-in is
told in advance what to answer, so a test that uses one runs the same way on a
laptop with no credentials as it does in the build.
"""
