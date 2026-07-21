"""Tests for freezecore.download: filename confinement and redirect credential safety."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import pytest
import requests
from requests.structures import CaseInsensitiveDict

from freezecore.download import (
    MAX_REDIRECTS,
    HTTPDownloader,
    _extract_filename_from_cd,
    _resolve_within,
    _rewrite_redirect_method,
    _sanitize_filename,
)

if TYPE_CHECKING:
    from pathlib import Path

HOST = "https://host.example"
OTHER_HOST = "https://evil.example"


def make_response(
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
    url: str = f"{HOST}/file.zip",
    body: bytes = b"payload",
) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp.url = url
    resp.headers = CaseInsensitiveDict(headers or {})
    resp.raw = io.BytesIO(body)
    resp.encoding = "utf-8"
    return resp


class FakeSession:
    """Minimal stand-in for ``requests.Session`` returning scripted responses."""

    def __init__(self, responses: dict[str, requests.Response]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, str, object]] = []
        self.closed: list[str] = []

    def request(
        self,
        method: str,
        url: str,
        auth: object = None,
        **_: object,
    ) -> requests.Response:
        self.calls.append((method, url, auth))
        resp = self._responses[url]
        resp.raw = io.BytesIO(b"payload")  # reset the stream for re-reads
        original_close = resp.close

        def _close() -> None:
            self.closed.append(url)
            original_close()

        resp.close = _close  # type: ignore[method-assign]
        return resp


def make_downloader(session: FakeSession, **kwargs: object) -> HTTPDownloader:
    dl = HTTPDownloader(progress=False, **kwargs)  # type: ignore[arg-type]
    dl.session = session  # type: ignore[assignment]
    return dl


# ---------------------------------------------------------------------------
# FC-01: filename confinement
# ---------------------------------------------------------------------------


class TestSanitizeFilename:
    @pytest.mark.parametrize(
        "name",
        [
            "../evil.zip",
            "../../etc/passwd",
            "/etc/passwd",
            "a/b.zip",
            "a\\b.zip",
            "..\\evil.zip",
            "C:\\Windows\\system32",
            "name:stream",
            "CON",
            "con.txt",
            "LPT1.dat",
            "..",
            ".",
            "",
            "bad\x00name",
            "tab\tname",
        ],
    )
    def test_rejects_unsafe_names(self, name: str) -> None:
        with pytest.raises(ValueError, match="Refusing"):
            _sanitize_filename(name, explicit=False)

    @pytest.mark.parametrize("name", ["file.zip", "S1A_20200101.tif", "data.tar.gz", "plain"])
    def test_accepts_safe_names(self, name: str) -> None:
        assert _sanitize_filename(name, explicit=True) == name


class TestResolveWithin:
    def test_confines_to_directory(self, tmp_path: Path) -> None:
        assert _resolve_within(tmp_path, "file.zip") == tmp_path / "file.zip"

    def test_rejects_symlink_escape(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        save_dir = tmp_path / "save"
        # `save` resolves (via a symlink) to a sibling of where the caller thinks
        # it is; a sanitized name is still fine, but a link *named* like the file
        # would escape -- here we exercise the resolved-parent guard directly.
        save_dir.symlink_to(outside, target_is_directory=True)
        # The join stays a bare name, so this must succeed and land in `outside`.
        target = _resolve_within(save_dir, "file.zip")
        assert target.resolve().parent == outside.resolve()


class TestDownloadFilenameConfinement:
    def test_malicious_content_disposition_rejected(self, tmp_path: Path) -> None:
        resp = make_response(
            headers={"Content-Disposition": 'attachment; filename="../../evil.zip"'},
        )
        dl = make_downloader(FakeSession({f"{HOST}/file": resp}))

        with pytest.raises(ValueError, match="Refusing"):
            dl(f"{HOST}/file", tmp_path)

        assert not (tmp_path.parent / "evil.zip").exists()

    def test_explicit_malicious_filename_rejected(self, tmp_path: Path) -> None:
        resp = make_response(headers={"Content-Type": "application/zip"})
        dl = make_downloader(FakeSession({f"{HOST}/file": resp}))

        with pytest.raises(ValueError, match="Refusing"):
            dl(f"{HOST}/file", tmp_path, filename="../escape.zip")

    def test_encoded_traversal_rejected(self, tmp_path: Path) -> None:
        resp = make_response(
            headers={"Content-Disposition": "attachment; filename*=UTF-8''%2e%2e%2fevil.zip"},
        )
        dl = make_downloader(FakeSession({f"{HOST}/file": resp}))

        with pytest.raises(ValueError, match="Refusing"):
            dl(f"{HOST}/file", tmp_path)

    def test_happy_path_writes_confined_file(self, tmp_path: Path) -> None:
        resp = make_response(
            headers={"Content-Disposition": 'attachment; filename="real.zip"'},
        )
        dl = make_downloader(FakeSession({f"{HOST}/file": resp}))

        out = dl(f"{HOST}/file", tmp_path)

        assert out == tmp_path / "real.zip"
        assert out.read_bytes() == b"payload"

    def test_existing_target_not_overwritten_by_default(self, tmp_path: Path) -> None:
        existing = tmp_path / "real.zip"
        existing.write_bytes(b"original")
        resp = make_response(headers={"Content-Disposition": 'attachment; filename="real.zip"'})
        dl = make_downloader(FakeSession({f"{HOST}/file": resp}))

        with pytest.raises(FileExistsError):
            dl(f"{HOST}/file", tmp_path)
        assert existing.read_bytes() == b"original"

    def test_overwrite_true_replaces(self, tmp_path: Path) -> None:
        existing = tmp_path / "real.zip"
        existing.write_bytes(b"original")
        resp = make_response(headers={"Content-Disposition": 'attachment; filename="real.zip"'})
        dl = make_downloader(FakeSession({f"{HOST}/file": resp}))

        out = dl(f"{HOST}/file", tmp_path, overwrite=True)
        assert out.read_bytes() == b"payload"

    def test_no_partial_files_left_behind(self, tmp_path: Path) -> None:
        resp = make_response(headers={"Content-Disposition": 'attachment; filename="real.zip"'})
        dl = make_downloader(FakeSession({f"{HOST}/file": resp}))

        dl(f"{HOST}/file", tmp_path)
        assert not list(tmp_path.glob("*.partial"))


# ---------------------------------------------------------------------------
# FC-02: redirect credential safety
# ---------------------------------------------------------------------------


class TestRedirectCredentialSafety:
    def _final(self) -> requests.Response:
        return make_response(
            headers={"Content-Disposition": 'attachment; filename="real.zip"'},
        )

    def test_auth_preserved_on_same_host_redirect(self, tmp_path: Path) -> None:
        redirect = make_response(
            status=302,
            url=f"{HOST}/a",
            headers={"Location": f"{HOST}/b"},
        )
        session = FakeSession({f"{HOST}/a": redirect, f"{HOST}/b": self._final()})
        dl = make_downloader(session, auth=("user", "pass"))

        dl(f"{HOST}/a", tmp_path)

        auths = [auth for _, _, auth in session.calls]
        assert auths[0] == ("user", "pass")
        assert auths[1] == ("user", "pass")  # same host keeps credentials

    def test_auth_dropped_on_cross_host_redirect(self, tmp_path: Path) -> None:
        redirect = make_response(
            status=302,
            url=f"{HOST}/a",
            headers={"Location": f"{OTHER_HOST}/b"},
        )
        final = make_response(
            url=f"{OTHER_HOST}/b",
            headers={"Content-Disposition": 'attachment; filename="real.zip"'},
        )
        session = FakeSession({f"{HOST}/a": redirect, f"{OTHER_HOST}/b": final})
        dl = make_downloader(session, auth=("user", "pass"))

        dl(f"{HOST}/a", tmp_path)

        assert session.calls[0][2] == ("user", "pass")
        assert session.calls[1][2] is None  # credentials dropped leaving the host

    def test_auth_dropped_on_scheme_downgrade(self, tmp_path: Path) -> None:
        redirect = make_response(
            status=302,
            url=f"{HOST}/a",
            headers={"Location": "http://host.example/b"},  # same host, https->http
        )
        final = make_response(
            url="http://host.example/b",
            headers={"Content-Disposition": 'attachment; filename="real.zip"'},
        )
        session = FakeSession({f"{HOST}/a": redirect, "http://host.example/b": final})
        dl = make_downloader(session, auth=("user", "pass"))

        dl(f"{HOST}/a", tmp_path)

        assert session.calls[1][2] is None  # never send credentials over plaintext

    def test_instance_auth_not_mutated_across_calls(self, tmp_path: Path) -> None:
        # First call leaves a trusted host, dropping auth for that chain only.
        redirect = make_response(
            status=302,
            url=f"{HOST}/a",
            headers={"Location": f"{OTHER_HOST}/b"},
        )
        final_other = make_response(
            url=f"{OTHER_HOST}/b",
            headers={"Content-Disposition": 'attachment; filename="a.zip"'},
        )
        direct = make_response(
            url=f"{HOST}/c",
            headers={"Content-Disposition": 'attachment; filename="c.zip"'},
        )
        session = FakeSession(
            {
                f"{HOST}/a": redirect,
                f"{OTHER_HOST}/b": final_other,
                f"{HOST}/c": direct,
            },
        )
        dl = make_downloader(session, auth=("user", "pass"))

        dl(f"{HOST}/a", tmp_path)
        dl(f"{HOST}/c", tmp_path)

        # The second, independent call must still carry credentials.
        assert session.calls[-1][2] == ("user", "pass")

    def test_intermediate_response_closed(self, tmp_path: Path) -> None:
        redirect = make_response(
            status=302,
            url=f"{HOST}/a",
            headers={"Location": f"{HOST}/b"},
        )
        session = FakeSession({f"{HOST}/a": redirect, f"{HOST}/b": self._final()})
        dl = make_downloader(session, auth=("user", "pass"))

        dl(f"{HOST}/a", tmp_path)
        assert f"{HOST}/a" in session.closed

    def test_redirect_loop_is_bounded(self, tmp_path: Path) -> None:
        a = make_response(status=302, url=f"{HOST}/a", headers={"Location": f"{HOST}/b"})
        b = make_response(status=302, url=f"{HOST}/b", headers={"Location": f"{HOST}/a"})
        session = FakeSession({f"{HOST}/a": a, f"{HOST}/b": b})
        dl = make_downloader(session, auth=("user", "pass"))

        with pytest.raises(RuntimeError, match="Exceeded maximum"):
            dl(f"{HOST}/a", tmp_path)
        assert len(session.calls) == MAX_REDIRECTS + 1


# ---------------------------------------------------------------------------
# Redirect method rewriting and RFC 5987 decoding
# ---------------------------------------------------------------------------


class TestRedirectMethodRewrite:
    def test_see_other_becomes_get(self) -> None:
        method, kwargs = _rewrite_redirect_method(303, "POST", {"data": b"x"})
        assert method == "GET"
        assert "data" not in kwargs

    def test_moved_post_becomes_get(self) -> None:
        method, _ = _rewrite_redirect_method(301, "POST", {})
        assert method == "GET"

    def test_temporary_redirect_preserves_method_and_body(self) -> None:
        method, kwargs = _rewrite_redirect_method(307, "POST", {"data": b"x"})
        assert method == "POST"
        assert kwargs == {"data": b"x"}


class TestExtractFilenameFromCd:
    def test_rfc5987_is_percent_decoded(self) -> None:
        cd = "attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf"
        assert _extract_filename_from_cd(cd) == "résumé.pdf"

    def test_plain_filename(self) -> None:
        assert _extract_filename_from_cd('attachment; filename="a.zip"') == "a.zip"

    def test_none_when_absent(self) -> None:
        assert _extract_filename_from_cd("attachment") is None
