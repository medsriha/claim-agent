"""Persistence: reports and their versions, rep feedback, merchant corrections,
and the audit trail (FR-R.13, FR-3.7, FR-3.8, NFR-5).

The ShipBob API offers no merchant-history endpoint, so anything the system
needs to remember it stores here. Merchant corrections, and the record of every
claim line already investigated (FR-S.1), are kept in one SQLite file on disk,
named by `DATABASE_PATH` and created on first use. So are the reports a
representative decides from, each keeping every version of itself (FR-2.1, FR-R.13),
and the record of what they then decided (FR-C.1). What a run did step by step still
has no schema, so the ordered history of a case is not kept yet (NFR-5).
"""
