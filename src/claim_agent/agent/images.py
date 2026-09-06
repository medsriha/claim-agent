from __future__ import annotations

import asyncio
import base64
from contextlib import suppress
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict

from claim_agent.domain.models import Attachment
from claim_agent.errors import UpstreamError
from claim_agent.observability import get_logger
from claim_agent.settings import Settings

logger = get_logger(__name__)


_FETCHABLE_SCHEMES = frozenset({"http", "https"})


_PNG_MARKER = b"\x89PNG\r\n\x1a\n"
_JPEG_MARKER = b"\xff\xd8\xff"
_GIF_MARKERS = (b"GIF87a", b"GIF89a")


class FetchedImage(BaseModel):
    """One attachment, downloaded and ready to put in front of a model."""

    model_config = ConfigDict(frozen=True)

    attachment_id: str
    media_type: str
    data_base64: str
    byte_count: int


class ImageFetcher:
    """Turns a merchant's attachment into an image a model can be shown."""

    def __init__(self, http: httpx.AsyncClient, settings: Settings) -> None:
        """Wrap an HTTP client, and take the fetching bounds from the settings."""
        self._http = http
        self._timeout_seconds = settings.attachment_timeout_seconds
        self._max_bytes = settings.attachment_max_bytes
        self._allowed_hosts = settings.attachment_allowed_hosts
        self._cache_dir = settings.attachment_cache_dir

    async def fetch(self, attachment: Attachment) -> FetchedImage:
        """Fetch one attachment and hand back the image, ready to show a model."""
        _check_the_address_is_one_we_will_fetch(
            attachment.url, self._allowed_hosts, attachment.attachment_id
        )

        cached = await self._read_from_cache(attachment.attachment_id)
        if cached is not None:
            logger.info(
                "attachment_read_from_cache",
                attachment_id=attachment.attachment_id,
                byte_count=cached.byte_count,
            )
            return cached

        data = await self._download(attachment)
        image = _to_image(attachment.attachment_id, data)
        await self._write_to_cache(attachment.attachment_id, data)
        logger.info(
            "attachment_fetched",
            attachment_id=attachment.attachment_id,
            media_type=image.media_type,
            byte_count=image.byte_count,
        )
        return image

    async def _download(self, attachment: Attachment) -> bytes:
        """Ask for the image and read it back, stopping if it grows past the limit."""
        try:
            request = self._http.build_request("GET", attachment.url, timeout=self._timeout_seconds)
        except httpx.InvalidURL as exc:
            logger.warning("attachment_address_unusable", attachment_id=attachment.attachment_id)
            raise UpstreamError(
                "The attachment's address could not be used.",
                details={"attachment_id": attachment.attachment_id},
            ) from exc

        try:
            response = await self._http.send(request, stream=True, follow_redirects=False)
        except httpx.TransportError as exc:
            logger.warning(
                "attachment_unreachable",
                attachment_id=attachment.attachment_id,
                failure=type(exc).__name__,
            )
            raise UpstreamError(
                "The attached image could not be fetched.",
                details={"attachment_id": attachment.attachment_id},
            ) from exc

        try:
            if response.is_redirect:
                logger.warning(
                    "attachment_redirected",
                    attachment_id=attachment.attachment_id,
                    status_code=response.status_code,
                )
                raise UpstreamError(
                    "The attached image could not be fetched.",
                    details={"attachment_id": attachment.attachment_id},
                )

            if not response.is_success:
                logger.warning(
                    "attachment_refused",
                    attachment_id=attachment.attachment_id,
                    status_code=response.status_code,
                )
                raise UpstreamError(
                    "The attached image could not be fetched.",
                    details={"attachment_id": attachment.attachment_id},
                )

            return await self._read_within_the_limit(response, attachment.attachment_id)
        finally:
            await response.aclose()

    async def _read_within_the_limit(self, response: httpx.Response, attachment_id: str) -> bytes:
        """Read the body a piece at a time, giving up the moment it passes the limit."""
        pieces: list[bytes] = []
        bytes_so_far = 0
        try:
            async for piece in response.aiter_bytes():
                bytes_so_far += len(piece)
                if bytes_so_far > self._max_bytes:
                    logger.warning(
                        "attachment_too_large",
                        attachment_id=attachment_id,
                        max_bytes=self._max_bytes,
                    )
                    raise UpstreamError(
                        "The attached image is too large to read.",
                        details={"attachment_id": attachment_id},
                    )
                pieces.append(piece)
        except httpx.TransportError as exc:
            logger.warning(
                "attachment_download_interrupted",
                attachment_id=attachment_id,
                failure=type(exc).__name__,
            )
            raise UpstreamError(
                "The attached image could not be fetched.",
                details={"attachment_id": attachment_id},
            ) from exc

        return b"".join(pieces)

    def _cache_path(self, attachment_id: str) -> Path | None:
        """Say where this attachment's downloaded copy lives, or that there is nowhere."""
        if self._cache_dir is None:
            return None
        return self._cache_dir / quote(attachment_id, safe="")

    async def _read_from_cache(self, attachment_id: str) -> FetchedImage | None:
        """Hand back an image already on disk, or `None` if there is nothing usable."""
        path = self._cache_path(attachment_id)
        if path is None:
            return None

        data = await asyncio.to_thread(_read_cached_bytes, path, self._max_bytes)
        if data is None:
            return None

        media_type = _sniff_media_type(data)
        if media_type is None:
            logger.warning("attachment_cache_not_an_image", attachment_id=attachment_id)
            return None

        return FetchedImage(
            attachment_id=attachment_id,
            media_type=media_type,
            data_base64=base64.b64encode(data).decode("ascii"),
            byte_count=len(data),
        )

    async def _write_to_cache(self, attachment_id: str, data: bytes) -> None:
        """Keep a downloaded image so it is never downloaded twice (NFR-6)."""
        path = self._cache_path(attachment_id)
        if path is None:
            return
        await asyncio.to_thread(_write_cached_bytes, path, data)


def _check_the_address_is_one_we_will_fetch(
    url: str, allowed_hosts: tuple[str, ...], attachment_id: str
) -> None:
    """Refuse an attachment address before a single request is made."""
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        logger.warning("attachment_address_unreadable", attachment_id=attachment_id)
        raise UpstreamError(
            "The attachment's address could not be read.",
            details={"attachment_id": attachment_id},
        ) from exc

    if parts.scheme not in _FETCHABLE_SCHEMES:
        logger.warning(
            "attachment_address_refused",
            attachment_id=attachment_id,
            reason="scheme",
            scheme=parts.scheme,
        )
        raise UpstreamError(
            "The attachment is not somewhere this system will fetch from.",
            details={"attachment_id": attachment_id},
        )

    host = parts.hostname
    if host is None or not _host_is_allowed(host, allowed_hosts):
        logger.warning(
            "attachment_address_refused",
            attachment_id=attachment_id,
            reason="host",
            host=host,
        )
        raise UpstreamError(
            "The attachment is not somewhere this system will fetch from.",
            details={"attachment_id": attachment_id},
        )


def _host_is_allowed(host: str, allowed_hosts: tuple[str, ...]) -> bool:
    """Say whether a host is on the approved list, matching whole names only."""
    return any(
        host == allowed.lower() or host.endswith(f".{allowed.lower()}") for allowed in allowed_hosts
    )


def _sniff_media_type(data: bytes) -> str | None:
    """Work out what kind of image some bytes are by looking at the bytes themselves."""
    if data.startswith(_PNG_MARKER):
        return "image/png"
    if data.startswith(_JPEG_MARKER):
        return "image/jpeg"
    if data.startswith(_GIF_MARKERS):
        return "image/gif"

    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _to_image(attachment_id: str, data: bytes) -> FetchedImage:
    """Turn downloaded bytes into an image a model can be shown, or refuse them."""
    media_type = _sniff_media_type(data)
    if media_type is None:
        logger.warning("attachment_not_an_image", attachment_id=attachment_id, byte_count=len(data))
        raise UpstreamError(
            "The attachment could not be read as an image.",
            details={"attachment_id": attachment_id},
        )

    return FetchedImage(
        attachment_id=attachment_id,
        media_type=media_type,
        data_base64=base64.b64encode(data).decode("ascii"),
        byte_count=len(data),
    )


def _read_cached_bytes(path: Path, max_bytes: int) -> bytes | None:
    """Read a downloaded image back off disk, or say there is nothing usable there."""
    try:
        stored_bytes = path.stat().st_size
        if stored_bytes > max_bytes:
            logger.warning(
                "attachment_cache_file_too_large",
                cache_file=path.name,
                byte_count=stored_bytes,
                max_bytes=max_bytes,
            )
            return None
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("attachment_cache_unreadable", cache_file=path.name, reason=str(exc))
        return None


def _write_cached_bytes(path: Path, data: bytes) -> None:
    """Put a downloaded image on disk under the name the next run will look for."""
    partial = path.with_name(f"{path.name}.{uuid4().hex}.partial")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(data)
        partial.replace(path)
    except OSError as exc:
        logger.warning("attachment_not_cached", cache_file=path.name, reason=str(exc))

        with suppress(OSError):
            partial.unlink(missing_ok=True)
