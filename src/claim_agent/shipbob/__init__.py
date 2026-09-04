"""Clients for the ShipBob mock API — two of them, deliberately kept apart.

One reads the three cheap records a claim is screened from: the case, the shipment
and the order. The other reads the two an investigation needs: the case's images and
a priced invoice. They are separate classes rather than one because looking at
photographs is the expensive part of investigating a claim, and a claim turned away
by the pre-flight screen must never pay for it. Keeping the expensive reads out of
the cheap client makes that a matter of what is reachable from where, rather than a
rule someone has to remember (NFR-8).

Reading only: they fetch records, wait no longer than they should, try again a
bounded number of times when a failure looks temporary, and turn every failure into a
handled outcome rather than a crash (NFR-6). Neither can email a merchant or pay
one — those live behind a rep's approval, somewhere an investigation cannot reach
(FR-1.2).

There are no separate shapes for what comes off the wire. A reply is read straight
into the same records the rest of the system uses, because ShipBob's fields and ours
are the same fields, and a translation step between two identical shapes would be one
more place for them to drift apart without buying anything.

Which endpoints each layer may call is set out in REQUIREMENTS.md ("endpoint access
by layer").
"""
