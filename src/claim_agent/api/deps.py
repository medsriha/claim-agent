"""Request-scoped dependencies.

Settings, policy and the long-lived helpers a route needs are read off
`app.state`, not from module-level caches, so a test (or a second app in the same
process) can build an application with different values and have every route see
them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from claim_agent.policy import Policy
from claim_agent.settings import Settings
from claim_agent.shipbob.client import ShipBobClient
from claim_agent.storage.merchant_memory import MerchantMemory


def get_settings(request: Request) -> Settings:
    """Return the settings the running app was built with."""
    settings: Settings = request.app.state.settings
    return settings


def get_policy(request: Request) -> Policy:
    """Return the claim policy the running app was built with."""
    policy: Policy = request.app.state.policy
    return policy


def get_shipbob_client(request: Request) -> ShipBobClient:
    """Return the reader for ShipBob's cases, shipments and orders.

    One client serves the whole application, so every claim shares the same pool
    of open connections instead of opening its own (FR-0.1).
    """
    client: ShipBobClient = request.app.state.shipbob
    return client


def get_merchant_memory(request: Request) -> MerchantMemory:
    """Return the store of what a rep has already corrected for a merchant (FR-0.5)."""
    memory: MerchantMemory = request.app.state.merchant_memory
    return memory


SettingsDep = Annotated[Settings, Depends(get_settings)]
PolicyDep = Annotated[Policy, Depends(get_policy)]
ShipBobClientDep = Annotated[ShipBobClient, Depends(get_shipbob_client)]
MerchantMemoryDep = Annotated[MerchantMemory, Depends(get_merchant_memory)]
