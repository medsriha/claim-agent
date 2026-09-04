"""Fetching a merchant's attached pictures — and every way that can go wrong.

Every request here is answered by a stand-in running in the same process, so nothing
reaches the network, and every file written goes to a throwaway directory belonging to
the one test that asked for it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import respx

from claim_agent.agent.images import FetchedImage, ImageFetcher
from claim_agent.domain.models import Attachment
from claim_agent.errors import UpstreamError
from claim_agent.settings import Settings

# The first eight bytes are the marker every PNG file starts with; the rest stands in for
# the picture. What follows the marker is never looked at, so it does not have to be real.
PNG_BYTES = b"\x89PNG\r\n\x1a\npretend pixels"
JPEG_BYTES = b"\xff\xd8\xffpretend pixels"
GIF_BYTES = b"GIF89apretend pixels"
WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBPpretend pixels"

# What an expired storage link actually answers with: a web page, not a picture.
ERROR_PAGE = b"<html><body>AuthenticationFailed</body></html>"

IMAGE_URL = "https://shipbob.images.test/case-1003/01_Inv.png"


def build_settings(*, cache_dir: Path | None = None, max_bytes: int = 1_000_000) -> Settings:
    """Settings for a test process, with the attachment bounds spelled out.

    Never reads the developer's own `.env` values for the things under test: the allowed
    hosts, the size limit and the cache directory are all stated here, so a test says in
    one place what it is testing against.
    """
    return Settings(
        environment="test",
        log_level="WARNING",
        anthropic_api_key=None,
        attachment_allowed_hosts=("images.test", "localhost"),
        attachment_cache_dir=cache_dir,
        attachment_max_bytes=max_bytes,
        attachment_timeout_seconds=1.0,
    )


def names_in(directory: Path) -> list[str]:
    """Name everything in a directory, in order, so a test can say exactly what was written.

    Answers "nothing" for a directory that was never created, which is what a test that
    expects no cache at all is really asking about.
    """
    if not directory.exists():
        return []
    return sorted(path.name for path in directory.iterdir())


def attachment(
    url: str = IMAGE_URL,
    *,
    attachment_id: str = "ATT-CASE-1003-01",
    file_name: str | None = None,
    content_type: str | None = None,
) -> Attachment:
    """One of the images a merchant uploaded to a case."""
    return Attachment(
        attachment_id=attachment_id, url=url, file_name=file_name, content_type=content_type
    )


@pytest.fixture
def attachments() -> Iterator[respx.Router]:
    """Stands in for the storage the attachment links point at, so nothing reaches the network.

    Routes are not required to be called: several tests register one only to prove it was
    left alone.
    """
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client for the fetcher to use, built the way the application builds one.

    Redirects are switched **on** here on purpose. The fetcher turns them off for its own
    requests, and a test that handed it a client which never followed them would prove
    nothing about that.
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:
        yield client


async def test_fetching_an_attachment_gives_back_an_image_a_model_can_be_shown(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-1.4: an attachment is a web address until it is fetched; this is what fetches it."""
    attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES)

    image = await ImageFetcher(http, build_settings()).fetch(attachment())

    assert isinstance(image, FetchedImage)
    assert image.attachment_id == "ATT-CASE-1003-01"
    assert image.media_type == "image/png"
    assert image.byte_count == len(PNG_BYTES)


@pytest.mark.parametrize(
    ("body", "expected_media_type"),
    [
        (PNG_BYTES, "image/png"),
        (JPEG_BYTES, "image/jpeg"),
        (GIF_BYTES, "image/gif"),
        (WEBP_BYTES, "image/webp"),
    ],
)
async def test_what_an_image_is_comes_from_its_bytes(
    attachments: respx.Router, http: httpx.AsyncClient, body: bytes, expected_media_type: str
) -> None:
    """FR-1.4: what an attachment is can only be settled by looking at the file itself."""
    attachments.get(IMAGE_URL).respond(200, content=body)

    image = await ImageFetcher(http, build_settings()).fetch(attachment())

    assert image.media_type == expected_media_type


async def test_the_name_and_declared_type_of_an_attachment_are_ignored(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-1.4: ShipBob's filename and content type carry no signal, so nothing may read them."""
    # ShipBob calls this one a PNG named "Inv.png". The file is a JPEG.
    attachments.get(IMAGE_URL).respond(200, content=JPEG_BYTES)

    image = await ImageFetcher(http, build_settings()).fetch(
        attachment(file_name="Inv.png", content_type="image/png")
    )

    assert image.media_type == "image/jpeg"


async def test_an_address_on_a_host_we_do_not_allow_is_refused_without_a_request(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: an address in an upstream payload must not be able to aim our requests."""
    somewhere_else = "https://attacker.example/case-1003/01_Inv.png"
    attachments.get(somewhere_else).respond(200, content=PNG_BYTES)

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment(somewhere_else))

    assert attachments.calls.call_count == 0


async def test_a_host_that_merely_ends_with_an_allowed_name_is_refused(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: `evilimages.test` is a different host from `images.test` and belongs to somebody else."""
    lookalike = "https://evilimages.test/case-1003/01_Inv.png"
    attachments.get(lookalike).respond(200, content=PNG_BYTES)

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment(lookalike))

    assert attachments.calls.call_count == 0


async def test_an_address_that_is_not_a_web_address_is_refused(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: without this, an address could ask us to read a file off our own disk."""
    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment("file:///etc/passwd"))

    assert attachments.calls.call_count == 0


async def test_an_address_that_cannot_be_read_at_all_is_refused(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: a malformed address is a handled outcome, not a crash."""
    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment("http://[unclosed/x.png"))

    assert attachments.calls.call_count == 0


async def test_an_address_no_request_can_be_built_from_is_refused(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: an allowed host can still be spelled in a way no request can be made to."""
    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment("http://❤.localhost/x.png"))

    assert attachments.calls.call_count == 0


async def test_a_redirect_is_not_followed(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: following a redirect would step straight around the list of allowed hosts."""
    somewhere_else = "https://attacker.example/case-1003/01_Inv.png"
    attachments.get(IMAGE_URL).respond(302, headers={"Location": somewhere_else})
    onward = attachments.get(somewhere_else).respond(200, content=PNG_BYTES)

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment())

    assert not onward.called


async def test_a_refusal_from_the_host_is_a_handled_failure(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: an expired link answers with a refusal, and that is an outcome, not a crash."""
    attachments.get(IMAGE_URL).respond(403, content=ERROR_PAGE)

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment())


async def test_an_image_one_byte_over_the_limit_is_refused(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: one enormous file must not be able to exhaust the process."""
    attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES[:9])

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings(max_bytes=8)).fetch(attachment())


async def test_an_image_exactly_at_the_limit_is_kept(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: the limit is a limit, not a margin — the largest allowed size still works."""
    attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES[:8])

    image = await ImageFetcher(http, build_settings(max_bytes=8)).fetch(attachment())

    assert image.byte_count == 8
    assert image.media_type == "image/png"


async def test_a_web_page_where_a_picture_should_be_is_refused(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-1.4, NFR-4: a page is not evidence, and no stand-in image is invented for it."""
    attachments.get(IMAGE_URL).respond(200, content=ERROR_PAGE)

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment())


async def test_an_empty_reply_is_refused(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-4: nothing at all is not a picture, and must not pass as one."""
    attachments.get(IMAGE_URL).respond(200, content=b"")

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment())


async def test_a_download_that_times_out_is_refused(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: an unreachable image is a handled state with a clear message, not a crash."""
    attachments.get(IMAGE_URL).mock(side_effect=httpx.ConnectTimeout("took too long"))

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment())


class _StreamThatDropsPartWay(httpx.AsyncByteStream):
    """A reply that starts arriving and then fails, the way a dropped connection does."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        """Hand over the start of a picture, then fail like a dropped connection."""
        yield PNG_BYTES[:8]
        raise httpx.ReadTimeout("the connection dropped")


async def test_a_download_that_drops_part_way_gives_no_half_image(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-4: half a picture is not evidence, so a broken download fails rather than returns."""
    attachments.get(IMAGE_URL).mock(
        return_value=httpx.Response(200, stream=_StreamThatDropsPartWay())
    )

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment())


async def test_the_second_look_at_an_image_reads_the_cache_instead_of_the_network(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    """NFR-6: links are signed until 2036, so a fetched image never has to be fetched twice."""
    route = attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES)
    cache_dir = tmp_path / "attachments"
    fetcher = ImageFetcher(http, build_settings(cache_dir=cache_dir))

    first = await fetcher.fetch(attachment())
    second = await fetcher.fetch(attachment())

    assert route.call_count == 1
    assert second == first
    # One file and no leftovers: the half-written copy is moved into place, not left beside it.
    assert names_in(cache_dir) == ["ATT-CASE-1003-01"]


async def test_a_cached_image_is_returned_with_no_network_at_all(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    """NFR-6: the system has to be demonstrable with no access to ShipBob's storage."""
    cache_dir = tmp_path / "attachments"
    cache_dir.mkdir()
    (cache_dir / "ATT-CASE-1003-01").write_bytes(PNG_BYTES)

    image = await ImageFetcher(http, build_settings(cache_dir=cache_dir)).fetch(attachment())

    assert image.media_type == "image/png"
    assert attachments.calls.call_count == 0


async def test_a_corrupt_cache_file_is_ignored_and_the_image_fetched_again(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    """NFR-6: a damaged cache costs a download, and must never cost a claim."""
    route = attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES)
    cache_dir = tmp_path / "attachments"
    cache_dir.mkdir()
    cache_file = cache_dir / "ATT-CASE-1003-01"
    cache_file.write_bytes(b"half a fi")

    image = await ImageFetcher(http, build_settings(cache_dir=cache_dir)).fetch(attachment())

    assert image.media_type == "image/png"
    assert route.call_count == 1
    # The good copy replaces the damaged one, so the next run is a cache hit again.
    assert cache_file.read_bytes() == PNG_BYTES


async def test_a_cache_entry_that_cannot_be_read_is_ignored(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    """NFR-6: anything unreadable where a cached image should be simply means fetch it again."""
    route = attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES)
    cache_dir = tmp_path / "attachments"
    cache_dir.mkdir()
    # A directory where a file should be: readable enough to find, impossible to read.
    (cache_dir / "ATT-CASE-1003-01").mkdir()

    image = await ImageFetcher(http, build_settings(cache_dir=cache_dir)).fetch(attachment())

    assert image.media_type == "image/png"
    assert route.call_count == 1


async def test_a_cache_file_bigger_than_the_limit_is_ignored(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    """NFR-6: reading a huge file off our own disk would defeat the point of the limit."""
    route = attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES[:8])
    cache_dir = tmp_path / "attachments"
    cache_dir.mkdir()
    (cache_dir / "ATT-CASE-1003-01").write_bytes(PNG_BYTES + b"x" * 500)

    image = await ImageFetcher(http, build_settings(cache_dir=cache_dir, max_bytes=8)).fetch(
        attachment()
    )

    assert image.byte_count == 8
    assert route.call_count == 1


async def test_nothing_is_cached_when_caching_is_switched_off(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    """NFR-6: caching off means every look is a fresh download, and nothing is written."""
    route = attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES)
    fetcher = ImageFetcher(http, build_settings(cache_dir=None))

    await fetcher.fetch(attachment())
    await fetcher.fetch(attachment())

    assert route.call_count == 2
    assert names_in(tmp_path) == []


async def test_something_that_is_not_an_image_is_never_cached(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    """FR-1.4: a web page kept as though it were evidence would be found again on the next run."""
    attachments.get(IMAGE_URL).respond(200, content=ERROR_PAGE)
    cache_dir = tmp_path / "attachments"

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings(cache_dir=cache_dir)).fetch(attachment())

    assert not cache_dir.exists()


async def test_an_image_is_still_returned_when_it_cannot_be_cached(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    """NFR-6: the cache is a saving, not a dependency — a disk it cannot write to costs nothing."""
    attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES)
    # A file where the cache directory should be, so it cannot be created.
    blocked = tmp_path / "attachments"
    blocked.write_text("not a directory")

    image = await ImageFetcher(http, build_settings(cache_dir=blocked)).fetch(attachment())

    assert image.media_type == "image/png"


async def test_two_attachments_are_cached_under_their_own_names(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    """NFR-6: two images in one case must not overwrite each other on disk."""
    second_url = "https://shipbob.images.test/case-1003/02_Screenshot.png"
    attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES)
    attachments.get(second_url).respond(200, content=JPEG_BYTES)
    cache_dir = tmp_path / "attachments"
    fetcher = ImageFetcher(http, build_settings(cache_dir=cache_dir))

    await fetcher.fetch(attachment())
    await fetcher.fetch(attachment(second_url, attachment_id="ATT-CASE-1003-02"))

    assert names_in(cache_dir) == ["ATT-CASE-1003-01", "ATT-CASE-1003-02"]


async def test_an_attachment_id_cannot_escape_the_cache_directory(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    """NFR-6: the id comes from an upstream payload, so it must not choose where we write."""
    attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES)
    cache_dir = tmp_path / "attachments"

    await ImageFetcher(http, build_settings(cache_dir=cache_dir)).fetch(
        attachment(attachment_id="../escaped")
    )

    assert names_in(cache_dir) == ["..%2Fescaped"]
    assert not (tmp_path / "escaped").exists()
