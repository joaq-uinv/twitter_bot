"""The status page renders data as plain text only (spec 002 FR-17, E-14; plan DD-9).

FR-16 already keeps third-party text out of status.json. These checks are the second
guard: even if something slipped through, the page could not interpret it as markup
or script, and it loads nothing from anywhere else.
"""
import re
from pathlib import Path

import pytest

import tweet_relay

SITE = Path(tweet_relay.__file__).parent / "site"
FILES = ("index.html", "app.js", "style.css")


@pytest.mark.parametrize("name", FILES)
def test_site_file_exists(name):
    assert (SITE / name).is_file()


@pytest.mark.parametrize("sink", ["innerHTML", "outerHTML", "insertAdjacentHTML",
                                  "document.write", "eval(", "new Function", "setTimeout(\"",
                                  "srcdoc"])
def test_script_has_no_markup_or_code_sinks(sink):
    assert sink not in (SITE / "app.js").read_text()


def test_page_declares_a_strict_content_security_policy():
    html = (SITE / "index.html").read_text()
    meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"', html)
    assert meta, "CSP meta tag missing"
    policy = meta.group(1)
    assert "default-src 'self'" in policy and "script-src 'self'" in policy
    assert "'unsafe-inline'" not in policy and "'unsafe-eval'" not in policy


def test_page_loads_nothing_from_elsewhere():
    for name in FILES:
        text = (SITE / name).read_text()
        assert not re.search(r'(src|href)\s*=\s*["\']?(https?:)?//', text), name
        assert "@import" not in text and "url(http" not in text, name


def test_no_inline_script_or_handlers():
    html = (SITE / "index.html").read_text()
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    assert not re.search(r"\son[a-z]+\s*=", html)


def test_probe_mirrors_writes_the_complete_site(monkeypatch, tmp_path):
    """P-1: one directory holds the page and its data."""
    from tests.unit.test_cli import _outcome, _probe_env
    from tweet_relay import cli
    argv, site = _probe_env(monkeypatch, tmp_path, {"a.example": _outcome(True),
                                                    "b.example": _outcome(True)})
    assert cli.main(argv) == 0
    assert sorted(p.name for p in site.iterdir()) == ["app.js", "index.html", "status.json",
                                                      "style.css"]
