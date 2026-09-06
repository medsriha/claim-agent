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

PNG_BYTES = b"\x89PNG\r\n\x1a\npretend pixels"
JPEG_BYTES = b"\xff\xd8\xffpretend pixels"
GIF_BYTES = b"GIF89apretend pixels"
WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBPpretend pixels"


ERROR_PAGE = b"<html><body>AuthenticationFailed</body></html>"

IMAGE_URL = "https://shipbob.images.test/case-1003/01_Inv.png"


def build_settings(*, cache_dir: Path | None = None, max_bytes: int = 1_000_000) -> Settings:
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
    return Attachment(
        attachment_id=attachment_id, url=url, file_name=file_name, content_type=content_type
    )


@pytest.fixture
def attachments() -> Iterator[respx.Router]:
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        yield client


async def test_fetching_an_attachment_gives_back_an_image_a_model_can_be_shown(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
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
    attachments.get(IMAGE_URL).respond(200, content=body)

    image = await ImageFetcher(http, build_settings()).fetch(attachment())

    assert image.media_type == expected_media_type


async def test_the_name_and_declared_type_of_an_attachment_are_ignored(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    attachments.get(IMAGE_URL).respond(200, content=JPEG_BYTES)

    image = await ImageFetcher(http, build_settings()).fetch(
        attachment(file_name="Inv.png", content_type="image/png")
    )

    assert image.media_type == "image/jpeg"


async def test_an_address_on_a_host_we_do_not_allow_is_refused_without_a_request(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    somewhere_else = "https://attacker.example/case-1003/01_Inv.png"
    attachments.get(somewhere_else).respond(200, content=PNG_BYTES)

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment(somewhere_else))

    assert attachments.calls.call_count == 0


async def test_a_host_that_merely_ends_with_an_allowed_name_is_refused(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    lookalike = "https://evilimages.test/case-1003/01_Inv.png"
    attachments.get(lookalike).respond(200, content=PNG_BYTES)

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment(lookalike))

    assert attachments.calls.call_count == 0


async def test_an_address_that_is_not_a_web_address_is_refused(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment("file:///etc/passwd"))

    assert attachments.calls.call_count == 0


async def test_an_address_that_cannot_be_read_at_all_is_refused(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment("http://[unclosed/x.png"))

    assert attachments.calls.call_count == 0


async def test_an_address_no_request_can_be_built_from_is_refused(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment("http://❤.localhost/x.png"))

    assert attachments.calls.call_count == 0


async def test_a_redirect_is_not_followed(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    somewhere_else = "https://attacker.example/case-1003/01_Inv.png"
    attachments.get(IMAGE_URL).respond(302, headers={"Location": somewhere_else})
    onward = attachments.get(somewhere_else).respond(200, content=PNG_BYTES)

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment())

    assert not onward.called


async def test_a_refusal_from_the_host_is_a_handled_failure(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    attachments.get(IMAGE_URL).respond(403, content=ERROR_PAGE)

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment())


async def test_an_image_one_byte_over_the_limit_is_refused(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES[:9])

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings(max_bytes=8)).fetch(attachment())


async def test_an_image_exactly_at_the_limit_is_kept(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES[:8])

    image = await ImageFetcher(http, build_settings(max_bytes=8)).fetch(attachment())

    assert image.byte_count == 8
    assert image.media_type == "image/png"


async def test_a_web_page_where_a_picture_should_be_is_refused(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    attachments.get(IMAGE_URL).respond(200, content=ERROR_PAGE)

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment())


async def test_an_empty_reply_is_refused(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    attachments.get(IMAGE_URL).respond(200, content=b"")

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment())


async def test_a_download_that_times_out_is_refused(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    attachments.get(IMAGE_URL).mock(side_effect=httpx.ConnectTimeout("took too long"))

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment())


class _StreamThatDropsPartWay(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield PNG_BYTES[:8]
        raise httpx.ReadTimeout("the connection dropped")


async def test_a_download_that_drops_part_way_gives_no_half_image(
    attachments: respx.Router, http: httpx.AsyncClient
) -> None:
    attachments.get(IMAGE_URL).mock(
        return_value=httpx.Response(200, stream=_StreamThatDropsPartWay())
    )

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings()).fetch(attachment())


async def test_the_second_look_at_an_image_reads_the_cache_instead_of_the_network(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    route = attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES)
    cache_dir = tmp_path / "attachments"
    fetcher = ImageFetcher(http, build_settings(cache_dir=cache_dir))

    first = await fetcher.fetch(attachment())
    second = await fetcher.fetch(attachment())

    assert route.call_count == 1
    assert second == first

    assert names_in(cache_dir) == ["ATT-CASE-1003-01"]


async def test_a_cached_image_is_returned_with_no_network_at_all(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    cache_dir = tmp_path / "attachments"
    cache_dir.mkdir()
    (cache_dir / "ATT-CASE-1003-01").write_bytes(PNG_BYTES)

    image = await ImageFetcher(http, build_settings(cache_dir=cache_dir)).fetch(attachment())

    assert image.media_type == "image/png"
    assert attachments.calls.call_count == 0


async def test_a_corrupt_cache_file_is_ignored_and_the_image_fetched_again(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    route = attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES)
    cache_dir = tmp_path / "attachments"
    cache_dir.mkdir()
    cache_file = cache_dir / "ATT-CASE-1003-01"
    cache_file.write_bytes(b"half a fi")

    image = await ImageFetcher(http, build_settings(cache_dir=cache_dir)).fetch(attachment())

    assert image.media_type == "image/png"
    assert route.call_count == 1

    assert cache_file.read_bytes() == PNG_BYTES


async def test_a_cache_entry_that_cannot_be_read_is_ignored(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    route = attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES)
    cache_dir = tmp_path / "attachments"
    cache_dir.mkdir()

    (cache_dir / "ATT-CASE-1003-01").mkdir()

    image = await ImageFetcher(http, build_settings(cache_dir=cache_dir)).fetch(attachment())

    assert image.media_type == "image/png"
    assert route.call_count == 1


async def test_a_cache_file_bigger_than_the_limit_is_ignored(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
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
    route = attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES)
    fetcher = ImageFetcher(http, build_settings(cache_dir=None))

    await fetcher.fetch(attachment())
    await fetcher.fetch(attachment())

    assert route.call_count == 2
    assert names_in(tmp_path) == []


async def test_something_that_is_not_an_image_is_never_cached(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    attachments.get(IMAGE_URL).respond(200, content=ERROR_PAGE)
    cache_dir = tmp_path / "attachments"

    with pytest.raises(UpstreamError):
        await ImageFetcher(http, build_settings(cache_dir=cache_dir)).fetch(attachment())

    assert not cache_dir.exists()


async def test_an_image_is_still_returned_when_it_cannot_be_cached(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES)

    blocked = tmp_path / "attachments"
    blocked.write_text("not a directory")

    image = await ImageFetcher(http, build_settings(cache_dir=blocked)).fetch(attachment())

    assert image.media_type == "image/png"


async def test_two_attachments_are_cached_under_their_own_names(
    attachments: respx.Router, http: httpx.AsyncClient, tmp_path: Path
) -> None:
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
    attachments.get(IMAGE_URL).respond(200, content=PNG_BYTES)
    cache_dir = tmp_path / "attachments"

    await ImageFetcher(http, build_settings(cache_dir=cache_dir)).fetch(
        attachment(attachment_id="../escaped")
    )

    assert names_in(cache_dir) == ["..%2Fescaped"]
    assert not (tmp_path / "escaped").exists()
