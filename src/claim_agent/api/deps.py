from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from langchain_core.language_models import BaseChatModel

from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.llm import StructuredModel, build_chat_model, build_structured_model
from claim_agent.agent.threads import PassThreads
from claim_agent.live_policy import LivePolicy
from claim_agent.policy import Policy
from claim_agent.settings import Settings
from claim_agent.shipbob.client import ShipBobClient
from claim_agent.shipbob.evidence_client import EvidenceClient
from claim_agent.storage.decision_store import DecisionStore
from claim_agent.storage.merchant_memory import MerchantMemory
from claim_agent.storage.precedent_store import PrecedentStore
from claim_agent.storage.report_store import ReportStore

ModelsFor = Callable[[], tuple[BaseChatModel, StructuredModel]]
"""How a caller gets the models once it knows it needs them. See `get_models`."""


def get_settings(request: Request) -> Settings:
    """Return the settings the running app was built with."""
    settings: Settings = request.app.state.settings
    return settings


def get_live_policy(request: Request) -> LivePolicy:
    """Return the holder of the claim policy in force (FR-0.7)."""
    live: LivePolicy = request.app.state.live_policy
    return live


def get_policy(request: Request) -> Policy:
    """Return the claim policy in force at the moment this request arrived."""
    return get_live_policy(request).current()


def get_shipbob_client(request: Request) -> ShipBobClient:
    """Return the reader for ShipBob's cases, shipments and orders."""
    client: ShipBobClient = request.app.state.shipbob
    return client


def get_merchant_memory(request: Request) -> MerchantMemory:
    """Return the store of what a rep has already corrected for a merchant (FR-0.5)."""
    memory: MerchantMemory = request.app.state.merchant_memory
    return memory


def get_decision_store(request: Request) -> DecisionStore:
    """Return the record of what representatives decided (FR-C.1)."""
    store: DecisionStore = request.app.state.decision_store
    return store


def get_precedent_store(request: Request) -> PrecedentStore:
    """Return the record of claims already investigated (FR-S.1, FR-S.5)."""
    store: PrecedentStore = request.app.state.precedent_store
    return store


def get_report_store(request: Request) -> ReportStore:
    """Return the store of reports a representative decides from (FR-2.9b, FR-R.13)."""
    store: ReportStore = request.app.state.report_store
    return store


def get_evidence_client(request: Request) -> EvidenceClient:
    """Return the reader for a case's images and for a priced invoice (FR-1.4, FR-1.18)."""
    client: EvidenceClient = request.app.state.evidence
    return client


def get_image_fetcher(request: Request) -> ImageFetcher:
    """Return the downloader for attachment images (FR-1.4, NFR-6)."""
    fetcher: ImageFetcher = request.app.state.image_fetcher
    return fetcher


def get_pass_threads(request: Request) -> PassThreads:
    """Return the conversations of the investigations this process has run (FR-R.2)."""
    threads: PassThreads = request.app.state.pass_threads
    return threads


def get_models(request: Request) -> ModelsFor:
    """Return a way to build the models, rather than the models themselves."""
    settings = get_settings(request)

    def build() -> tuple[BaseChatModel, StructuredModel]:
        """Build both, or raise `ConfigurationError` if there is no key configured."""
        return build_chat_model(settings), build_structured_model(settings)

    return build


SettingsDep = Annotated[Settings, Depends(get_settings)]
PolicyDep = Annotated[Policy, Depends(get_policy)]
LivePolicyDep = Annotated[LivePolicy, Depends(get_live_policy)]
ShipBobClientDep = Annotated[ShipBobClient, Depends(get_shipbob_client)]
MerchantMemoryDep = Annotated[MerchantMemory, Depends(get_merchant_memory)]
PrecedentStoreDep = Annotated[PrecedentStore, Depends(get_precedent_store)]
ReportStoreDep = Annotated[ReportStore, Depends(get_report_store)]
DecisionStoreDep = Annotated[DecisionStore, Depends(get_decision_store)]
EvidenceClientDep = Annotated[EvidenceClient, Depends(get_evidence_client)]
ImageFetcherDep = Annotated[ImageFetcher, Depends(get_image_fetcher)]
ModelsDep = Annotated[ModelsFor, Depends(get_models)]
PassThreadsDep = Annotated[PassThreads, Depends(get_pass_threads)]
