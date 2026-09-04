"""Fetching the pictures a merchant attached, so a model can look at them (FR-1.4).

A damaged-in-transit claim is argued from photographs: the broken product, the box it
arrived in, a photograph of an invoice, a screenshot of the end customer saying the
parcel turned up damaged. ShipBob hands over a list of those attachments as web
addresses. This is the step in between — turning one of those addresses into the actual
image, in the form a model can be shown.

**What an attachment is can only be settled by looking at it (FR-1.4).** The name and
the declared file type ShipBob sends carry no signal at all, and nothing here reads
them. The kind of image is worked out from the first few bytes of the file, which is
the only part of it that cannot be renamed.

**Four deliberate bounds, because the address comes from somebody else's data.** The web
address is written by an upstream system, and following it is our process making a
request. So:

* Only addresses on an approved list of hosts are fetched, and only over the ordinary
  web protocols. This is what stops an address planted in an upstream payload from
  aiming our requests wherever it likes — at a machine inside our own network, or at a
  file on our own disk. An address that fails the check is refused before any request
  is made.
* Redirects are not followed. A redirect is the host we approved telling us to go
  somewhere else, which would walk straight around the approved list.
* The download is read in pieces and abandoned the moment it passes the size limit,
  rather than read to the end and measured afterwards. An enormous file must not be
  able to exhaust the process.
* Anything that does not turn out to be an image we can show a model is refused, and
  refused whole. There is no half-image and no stand-in: a claim decided on a picture
  we had to guess at would be worse than one that failed plainly (NFR-4).

**Downloaded images are kept on disk.** ShipBob's attachment links are signed until
2036, so once an image has been fetched it never has to be fetched again, and the whole
system can be demonstrated with no network at all (NFR-6). A cache file that is missing,
unreadable, or no longer an image is treated as though it were not there — the image is
simply fetched again. The cache can therefore never be the reason a claim fails.

Every failure here is an `UpstreamError` carrying a plain sentence. The sentence, and
the details beside it, never include the address: it carries a signature that acts as a
password for the file, and error details travel out through the API.
"""

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

# The only protocols an attachment may be fetched over. `file:` is the reason this list
# exists: without it, an address in an upstream payload could ask this process to read a
# file off our own disk and hand it to a model.
_FETCHABLE_SCHEMES = frozenset({"http", "https"})

# The first few bytes of the image formats a model can be shown. Every one of these is a
# marker the format writes at the very start of the file, which is why it can be trusted
# where a filename cannot (FR-1.4).
_PNG_MARKER = b"\x89PNG\r\n\x1a\n"
_JPEG_MARKER = b"\xff\xd8\xff"
_GIF_MARKERS = (b"GIF87a", b"GIF89a")


class FetchedImage(BaseModel):
    """One attachment, downloaded and ready to put in front of a model.

    Frozen, because it is a record of a file as it was fetched. Changing one after the
    fact would make it a record of nothing.

    Attributes:
        attachment_id: ShipBob's id for the attachment, so a finding can always name
            the exact image it came from (FR-2.2).
        media_type: What the bytes actually are — "image/png", "image/jpeg",
            "image/gif" or "image/webp". Worked out by looking at the file itself, not
            taken from anything ShipBob said about it (FR-1.4).
        data_base64: The image written out as plain text, which is the form a message to
            a model carries a picture in.
        byte_count: How big the image was, in bytes. Reported so the cost of looking at
            evidence is visible rather than guessed at (NFR-8).
    """

    model_config = ConfigDict(frozen=True)

    attachment_id: str
    media_type: str
    data_base64: str
    byte_count: int


class ImageFetcher:
    """Turns a merchant's attachment into an image a model can be shown.

    Give it a ready-made HTTP client. It does not build its own, so the application
    decides how long connections live and can share one pool across every claim, and a
    test can hand in a client that answers from memory instead of over a network.

    The bounds it works inside — how long to wait, how large a file may be, which hosts
    may be fetched from, and where downloads are kept — are read from the settings once,
    when the fetcher is built. A claim being investigated therefore finishes on the
    values it started with, the same way the claim policy is read once per request.

    One fetcher can be shared by everything happening in a claim: it holds no state of
    its own beyond those settings, and two claim lines asking for the same image at the
    same moment is safe. It is not, however, how the same image is stopped from being
    *analysed* twice — that is what the observation memo in `observations.py` is for
    (NFR-8).
    """

    def __init__(self, http: httpx.AsyncClient, settings: Settings) -> None:
        """Wrap an HTTP client, and take the fetching bounds from the settings."""
        self._http = http
        self._timeout_seconds = settings.attachment_timeout_seconds
        self._max_bytes = settings.attachment_max_bytes
        self._allowed_hosts = settings.attachment_allowed_hosts
        self._cache_dir = settings.attachment_cache_dir

    async def fetch(self, attachment: Attachment) -> FetchedImage:
        """Fetch one attachment and hand back the image, ready to show a model.

        The address is checked before anything else, so an attachment we would never
        fetch is refused whether or not a copy happens to be on disk. Then the cache is
        tried, and only a miss becomes a request.

        Args:
            attachment: The attachment to fetch. Only its id and its address are used;
                its filename and declared file type are deliberately ignored (FR-1.4).

        Returns:
            The image, with what it actually is worked out from the bytes.

        Raises:
            UpstreamError: The address is not one this system will fetch from, the
                download failed or timed out, the file was larger than the limit, or
                what came back was not an image. Never a partial or stand-in image.
        """
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
        """Ask for the image and read it back, stopping if it grows past the limit.

        Not retried. One failed download is one failed tool call, and how many times an
        investigation may try a tool call again is counted by that run's budget, which
        belongs to the caller (FR-1.3).

        Raises:
            UpstreamError: the host could not be reached, took too long, redirected us,
                refused the request, or sent more bytes than the limit allows.
        """
        try:
            request = self._http.build_request("GET", attachment.url, timeout=self._timeout_seconds)
        except httpx.InvalidURL as exc:
            logger.warning("attachment_address_unusable", attachment_id=attachment.attachment_id)
            raise UpstreamError(
                "The attachment's address could not be used.",
                details={"attachment_id": attachment.attachment_id},
            ) from exc

        try:
            # Redirects are off for this request whatever the shared client is set to,
            # because following one would take us to a host nobody approved.
            # `stream=True` hands back the headers before the body, which is what makes
            # it possible to give up part-way through an oversized file.
            response = await self._http.send(request, stream=True, follow_redirects=False)
        except httpx.TransportError as exc:
            # Covers running out of time as well: httpx counts a request that timed out
            # as one kind of transport failure, alongside a refused or dropped connection.
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
        """Read the body a piece at a time, giving up the moment it passes the limit.

        Measuring afterwards would mean the whole file was already in memory, which is
        the very thing the limit exists to prevent. Reading in pieces means we never
        hold more than the limit plus one piece, however large the file claims to be.

        The declared length in the reply headers is not consulted: it is written by the
        sender and can simply be wrong, whereas counting what actually arrives cannot.

        Raises:
            UpstreamError: the body went past the limit, or the connection failed
                part-way through.
        """
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
        """Say where this attachment's downloaded copy lives, or that there is nowhere.

        `None` means caching is switched off, which is what the tests use so that one
        test cannot see another's downloads.

        The id comes from an upstream payload, so anything in it that could change which
        file gets written — a slash, a `..` — is escaped rather than trusted. There is
        no file extension on purpose: what the file is gets worked out from its bytes,
        and an extension would be a second answer to that question, free to disagree.
        """
        if self._cache_dir is None:
            return None
        return self._cache_dir / quote(attachment_id, safe="")

    async def _read_from_cache(self, attachment_id: str) -> FetchedImage | None:
        """Hand back an image already on disk, or `None` if there is nothing usable.

        `None` covers every way the cache can let us down — switched off, nothing stored
        yet, a file that cannot be read, a file that is no longer an image. Every one of
        them simply means the image is fetched again, so a damaged cache can never turn
        into a failed claim (NFR-6).
        """
        path = self._cache_path(attachment_id)
        if path is None:
            return None

        # On a worker thread: reading a file blocks, and claim lines are investigated
        # alongside each other, so a slow disk must not stall the others.
        data = await asyncio.to_thread(_read_cached_bytes, path, self._max_bytes)
        if data is None:
            return None

        media_type = _sniff_media_type(data)
        if media_type is None:
            # Something is on disk that is not an image: a write cut short by a crash,
            # or a file somebody else put there. Fetching again is always safe.
            logger.warning("attachment_cache_not_an_image", attachment_id=attachment_id)
            return None

        return FetchedImage(
            attachment_id=attachment_id,
            media_type=media_type,
            data_base64=base64.b64encode(data).decode("ascii"),
            byte_count=len(data),
        )

    async def _write_to_cache(self, attachment_id: str, data: bytes) -> None:
        """Keep a downloaded image so it is never downloaded twice (NFR-6).

        Does nothing when caching is switched off. A cache that cannot be written is not
        a failure — the image is in hand and the claim goes on — so the trouble is
        logged rather than raised.
        """
        path = self._cache_path(attachment_id)
        if path is None:
            return
        await asyncio.to_thread(_write_cached_bytes, path, data)


def _check_the_address_is_one_we_will_fetch(
    url: str, allowed_hosts: tuple[str, ...], attachment_id: str
) -> None:
    """Refuse an attachment address before a single request is made.

    The address is written by an upstream system, which means it decides where this
    process sends a request. Checking it here is what stops an address planted in
    somebody else's data from aiming our requests wherever it likes — at a machine
    inside our own network, or at a file on our own disk.

    Two things have to hold: the address must use an ordinary web protocol, and its host
    must be on the approved list in the settings.

    Raises:
        UpstreamError: the address cannot be read, uses another protocol, or names a
            host that is not approved.
    """
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        # A malformed address, such as an unclosed bracket. Reading it is the one thing
        # here that can fail on the address itself rather than on what it points at.
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
        # The host is safe to log and is the useful part; the rest of the address is
        # not, because it carries a signature that acts as a password for the file.
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
    """Say whether a host is on the approved list, matching whole names only.

    Each approved entry is a suffix, so `blob.core.windows.net` covers every ShipBob
    storage account under it. The match is anchored at a dot on purpose: plain "ends
    with" would also accept `evilblob.core.windows.net`, which is a different host
    entirely and belongs to somebody else.
    """
    return any(
        host == allowed.lower() or host.endswith(f".{allowed.lower()}") for allowed in allowed_hosts
    )


def _sniff_media_type(data: bytes) -> str | None:
    """Work out what kind of image some bytes are by looking at the bytes themselves.

    Every image format starts with a fixed marker of its own. That marker is part of the
    file, so unlike a filename or a declared file type it cannot be wrong about what the
    file is — which is exactly what FR-1.4 asks for.

    Returns the type as a model would be told it ("image/png"), or `None` for anything
    that is not one of the four kinds a model can be shown. A web page returned in place
    of a picture, and an empty file, both come back as `None`.
    """
    if data.startswith(_PNG_MARKER):
        return "image/png"
    if data.startswith(_JPEG_MARKER):
        return "image/jpeg"
    if data.startswith(_GIF_MARKERS):
        return "image/gif"
    # WebP writes its name four bytes in, inside a wrapper it shares with sound and
    # video files, so the opening bytes alone do not settle it.
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _to_image(attachment_id: str, data: bytes) -> FetchedImage:
    """Turn downloaded bytes into an image a model can be shown, or refuse them.

    Refusing is the interesting case. An address that answers with an error page, a
    document, or nothing at all has given us something no model can look at, and passing
    it on as though it were evidence would put a claim on a footing we invented.

    Raises:
        UpstreamError: the bytes are not one of the image kinds we can show a model.
    """
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
    """Read a downloaded image back off disk, or say there is nothing usable there.

    Runs on a worker thread, so it blocks nothing.

    `None` means "fetch it again" and covers three cases: nothing has been stored yet,
    the file cannot be read, and the file is bigger than the download limit. The last
    one matters because reading it would defeat the limit — a huge file on our own disk
    can exhaust the process just as easily as a huge one on somebody else's.
    """
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
        # Nothing cached for this attachment yet. The ordinary case on a first run, and
        # not worth a line in the logs.
        return None
    except OSError as exc:
        logger.warning("attachment_cache_unreadable", cache_file=path.name, reason=str(exc))
        return None


def _write_cached_bytes(path: Path, data: bytes) -> None:
    """Put a downloaded image on disk under the name the next run will look for.

    Runs on a worker thread, so it blocks nothing.

    Written to a uniquely named neighbour and then moved into place. Two claim lines can
    be fetching the same attachment at the same moment, and a half-written file must
    never be readable as though it were a whole one.

    Trouble here is logged and not raised: the image has already been fetched, so a full
    or read-only disk costs the next run a download rather than costing this claim
    anything.
    """
    partial = path.with_name(f"{path.name}.{uuid4().hex}.partial")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(data)
        partial.replace(path)
    except OSError as exc:
        logger.warning("attachment_not_cached", cache_file=path.name, reason=str(exc))
        # Whatever was written before the failure is not a usable cache entry, so it is
        # taken back out. If even that fails there is nothing further worth trying, and
        # nothing depends on it.
        with suppress(OSError):
            partial.unlink(missing_ok=True)
