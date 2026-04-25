"""v1.18.1 hotfix: Rich TUI rewrites relative md links to file:// URIs.

The Rich TUI renders markdown via `Markdown(content)` which emits
OSC 8 terminal hyperlinks. Terminals (WezTerm, iTerm2) hand the raw
target to the OS — relative paths like `docs/foo.png` can't be
resolved without "the markdown file's directory" context, so the
user sees a "this link is invalid" popup.

The renderer now rewrites relative `![alt](path)` and `[text](path)`
to absolute `file:///abs/path/...` URIs using the source file's
parent directory as the base.

Tests pin the contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _get_rewriter():
    # Helper lives in ppxai/common/ — leaf module, no rendering chain.
    from ppxai.common.markdown_links import rewrite_relative_links
    return rewrite_relative_links


# ---------------------------------------------------------------------------
# Path rewriting
# ---------------------------------------------------------------------------

class TestRewriteRelativeLinks:
    def test_image_with_relative_path_rewritten(self, tmp_path):
        source = tmp_path / "README.md"
        content = "![logo](docs/logo.png)"
        out = _get_rewriter()(content, str(source))
        # docs/logo.png becomes file:///{tmp_path}/docs/logo.png
        expected = (tmp_path / "docs" / "logo.png").resolve().as_uri()
        assert out == f"![logo]({expected})"

    def test_link_with_relative_path_rewritten(self, tmp_path):
        source = tmp_path / "README.md"
        content = "See [the docs](docs/install.md) for details."
        out = _get_rewriter()(content, str(source))
        expected = (tmp_path / "docs" / "install.md").resolve().as_uri()
        assert f"[the docs]({expected})" in out

    def test_absolute_url_not_rewritten(self, tmp_path):
        source = tmp_path / "README.md"
        content = "[GitHub](https://github.com/foo/bar)"
        assert (
            _get_rewriter()(content, str(source))
            == content
        )

    def test_mailto_not_rewritten(self, tmp_path):
        source = tmp_path / "README.md"
        content = "[contact](mailto:hi@example.com)"
        assert (
            _get_rewriter()(content, str(source))
            == content
        )

    def test_fragment_not_rewritten(self, tmp_path):
        source = tmp_path / "README.md"
        content = "[top](#top-of-page)"
        assert (
            _get_rewriter()(content, str(source))
            == content
        )

    def test_absolute_unix_path_not_rewritten(self, tmp_path):
        source = tmp_path / "README.md"
        content = "![pic](/tmp/already-absolute.png)"
        assert (
            _get_rewriter()(content, str(source))
            == content
        )

    def test_windows_drive_letter_not_rewritten(self, tmp_path):
        source = tmp_path / "README.md"
        content = "![pic](C:/already-absolute.png)"
        assert (
            _get_rewriter()(content, str(source))
            == content
        )

    def test_data_url_not_rewritten(self, tmp_path):
        source = tmp_path / "README.md"
        content = "![tiny](data:image/png;base64,iVBORw0KGgo=)"
        assert (
            _get_rewriter()(content, str(source))
            == content
        )

    def test_no_source_path_returns_unchanged(self):
        content = "![logo](docs/logo.png)"
        assert _get_rewriter()(content, "") == content

    def test_link_title_preserved(self, tmp_path):
        source = tmp_path / "README.md"
        content = '[doc](docs/x.md "Title")'
        out = _get_rewriter()(content, str(source))
        expected = (tmp_path / "docs" / "x.md").resolve().as_uri()
        assert f'[doc]({expected} "Title")' in out

    def test_multiple_links_in_one_doc(self, tmp_path):
        source = tmp_path / "README.md"
        content = (
            "Multi:\n"
            "![a](docs/a.png)\n"
            "[external](https://x.com)\n"
            "![b](docs/b.png)\n"
        )
        out = _get_rewriter()(content, str(source))
        # a.png and b.png rewritten, external unchanged
        assert (tmp_path / "docs" / "a.png").resolve().as_uri() in out
        assert (tmp_path / "docs" / "b.png").resolve().as_uri() in out
        assert "https://x.com" in out
