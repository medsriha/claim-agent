"""Client for the ShipBob mock API.

Reading only: it fetches records, waits no longer than it should, tries again a
bounded number of times when a failure looks temporary, and turns every failure into a
handled outcome rather than a crash (NFR-6).

There are no separate shapes for what comes off the wire. A reply is read straight
into the same records the rest of the system uses, because ShipBob's fields and ours
are the same fields, and a translation step between two identical shapes would be one
more place for them to drift apart without buying anything.

Which endpoints each layer may call is set out in REQUIREMENTS.md ("endpoint access
by layer").
"""
