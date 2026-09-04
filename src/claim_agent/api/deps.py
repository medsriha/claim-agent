"""Request-scoped dependencies.

Settings, policy and the long-lived helpers a route needs are read off
`app.state`, not from module-level caches, so a test (or a second app in the same
process) can build an application with different values and have every route see
them.

The claim policy is the one that can change while the service runs, because the
admin panel can change it (FR-0.7). A route asks for it once, when the request
arrives, and hands that one answer to everything it calls — so a change landing
midway through a screening cannot affect the claim being screened.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from claim_agent.live_policy import LivePolicy
from claim_agent.policy import Policy
from claim_agent.settings import Settings
from claim_agent.shipbob.client import ShipBobClient
from claim_agent.storage.merchant_memory import MerchantMemory


def get_settings(request: Request) -> Settings:
    """Return the settings the running app was built with."""
    settings: Settings = request.app.state.settings
    return settings


def get_live_policy(request: Request) -> LivePolicy:
    """Return the holder of the claim policy in force (FR-0.7).

    Only the admin panel needs this, because only the admin panel changes the
    policy. Anything that merely judges a claim wants `get_policy` instead.
    """
    live: LivePolicy = request.app.state.live_policy
    return live


def get_policy(request: Request) -> Policy:
    """Return the claim policy in force at the moment this request arrived.

    Read once per request on purpose: a threshold must not change midway through
    judging a claim (FR-0.6). The claim after this one sees any change that has
    landed since.
    """
    return get_live_policy(request).current()


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
LivePolicyDep = Annotated[LivePolicy, Depends(get_live_policy)]
ShipBobClientDep = Annotated[ShipBobClient, Depends(get_shipbob_client)]
MerchantMemoryDep = Annotated[MerchantMemory, Depends(get_merchant_memory)]
