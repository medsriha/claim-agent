"""Persistence: reports and their versions, rep feedback, merchant corrections,
and the audit trail (FR-R.13, FR-3.7, FR-3.8, NFR-5).

The ShipBob API offers no merchant-history endpoint, so anything the system
needs to remember it stores here. Backing store is an open decision — see
CLAUDE.md.
"""
