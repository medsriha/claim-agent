"""Persistence: reports and their versions, rep feedback, merchant corrections,
and the audit trail (FR-R.13, FR-3.7, FR-3.8, NFR-5).

The ShipBob API offers no merchant-history endpoint, so anything the system
needs to remember it stores here. Merchant corrections are kept in one SQLite
file on disk, named by `DATABASE_PATH` and created on first use. Reports, their
versions, rep feedback and the audit trail have no schema yet.
"""
