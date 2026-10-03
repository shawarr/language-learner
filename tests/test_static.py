"""The PWA shell: self-contained (CSP blocks anything external), cached by a versioned service
worker that never touches /api, and every /api route behind the cookie."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from app.config import settings

STATIC = settings.static_dir


def _sw_shell_list() -> list[str]:
    sw = (STATIC / "sw.js").read_text()
    m = re.search(r"const SHELL = \[(.*?)\];", sw, re.S)
    assert m, "sw.js must declare a SHELL list"
    return re.findall(r"'([^']+)'", m.group(1))


def test_every_precached_file_exists_and_api_is_never_cached():
    shell = _sw_shell_list()
    for path in shell:
        if path == "/":
            continue
        assert (STATIC / path.lstrip("/")).exists(), f"sw.js precaches {path} but it is missing"
    sw = (STATIC / "sw.js").read_text()
    assert "CACHE_VERSION" in sw
    assert "url.pathname.startsWith('/api/')" in sw and "'/sw.js'" in sw
    assert not any(p.startswith("/api") for p in shell)


def test_every_module_the_shell_imports_is_precached():
    shell = set(_sw_shell_list())
    for js in list(STATIC.glob("*.js")) + list((STATIC / "js").glob("*.js")):
        if js.name == "sw.js":
            continue
        rel = "/" + js.relative_to(STATIC).as_posix()
        assert rel in shell, f"{rel} is not in the service worker's SHELL list (offline start-up would break)"
        for imp in re.findall(r"from '\./([^']+)'", js.read_text()):
            target = "/" + (js.parent / imp).relative_to(STATIC).as_posix()
            assert target in shell, f"{rel} imports {target} which is not precached"


def test_no_external_resources_in_the_shell():
    for f in list(STATIC.glob("*.html")) + list(STATIC.glob("*.css")) + list(STATIC.glob("*.js")) + list((STATIC / "js").glob("*.js")):
        text = f.read_text()
        assert "https://" not in text and "http://" not in text, f"{f.name} references an external URL; the CSP blocks it"
    html = (STATIC / "index.html").read_text()
    assert "<script" not in html.replace('<script type="module" src="/app.js"></script>', ""), "inline scripts are blocked by the CSP"
    assert 'rel="manifest"' in html and "apple-touch-icon" in html
    assert "viewport-fit=cover" in html


def test_manifest_and_icons():
    import json

    m = json.loads((STATIC / "manifest.webmanifest").read_text())
    assert m["display"] == "standalone" and m["orientation"] == "portrait" and m["theme_color"]
    for icon in m["icons"]:
        p = STATIC / icon["src"].lstrip("/")
        assert p.exists() and p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_every_api_route_requires_auth():
    from app import auth
    from app.main import app

    public = {"/api/health", "/api/auth/login", "/api/auth/logout"}
    missing = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api") or path in public:
            continue
        calls = {d.call for d in route.dependant.dependencies}
        if auth.require_auth not in calls:
            missing.append(path)
    assert not missing, f"routes without Depends(auth.require_auth): {missing}"


def test_no_secret_in_the_repo_tree():
    """No key material in anything git tracks.

    Scoped to tracked files on purpose. The risk is *committing* a secret; a real deployment has a
    gitignored .env holding live keys, and scanning the working tree would fail there every time —
    a test that always fails on the server gets disabled, and then it protects nothing.
    """
    root = Path(settings.base_dir).parent
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                             capture_output=True, text=True, check=True).stdout.split("\0")
    checked = 0
    for name in filter(None, tracked):
        f = root / name
        if not f.is_file() or f.suffix in {".png", ".db", ".mp3", ".pyc", ".m4a", ".webm"}:
            continue
        checked += 1
        # Real keys have a long random tail; the bare prefixes (as in this test) are fine.
        assert not re.search(r"AIza[0-9A-Za-z_\-]{30,}|gsk_[0-9A-Za-z]{40,}", f.read_text(errors="ignore")), \
            f"looks like an API key in {name}"
    assert checked > 50, f"only scanned {checked} tracked files — is git ls-files working?"


def test_the_hold_gesture_cannot_select_text():
    """Holding the mic is a gesture. Without these, dragging the thumb over the chat selects the
    bubbles and iOS raises its "Copy / Look Up" callout, which is what makes hold-to-talk feel broken.
    """
    css = (Path(settings.static_dir) / "styles.css").read_text()
    assert "html.recording" in css, "no document-wide clamp while recording"
    clamp = css[css.index("html.recording"):][:500]
    assert "user-select: none !important" in clamp
    assert "-webkit-touch-callout: none !important" in clamp
    # A tapped word is a control, so it must not offer the native long-press menu either.
    word_rule = css[css.index(".word {"):][:260]
    assert "-webkit-touch-callout: none" in word_rule

    mic = (Path(settings.static_dir) / "js" / "mic.js").read_text()
    assert mic.count("setRecordingGesture(false)") >= 3, "the clamp must be released on every exit path"
    assert "selectstart" in mic


def test_every_tutor_reply_can_be_understood():
    """The tutor speaks German; a beginner needs to know what it means without a second call.

    `meaning_en` is required by the turn schema, stored on the message, returned by the API and
    rendered under the bubble — defaulting to visible at A1, where German-only is not comprehensible
    input but noise.
    """
    from app.services.tutor import TUTOR_TURN_SCHEMA, MESSAGE_FIELDS

    assert "meaning_en" in TUTOR_TURN_SCHEMA["required"]
    assert "meaning_en" in MESSAGE_FIELDS

    from app.db import MIGRATIONS
    assert ("messages", "meaning_en", "TEXT") in MIGRATIONS

    talk = (Path(settings.static_dir) / "js" / "talk.js").read_text()
    assert "bubble-meaning" in talk
    assert "defaultEnglishFor" in talk and "startsWith('A1')" in talk
    css = (Path(settings.static_dir) / "styles.css").read_text()
    assert ".bubble-meaning" in css


def test_the_app_teaches_before_it_tests():
    """Practice assumes you were taught. Learn is the first tab, is precached, and a unit with an
    unfinished lesson wins the landing screen over whatever tab was last open."""
    html = (Path(settings.static_dir) / "index.html").read_text()
    tabs = re.findall(r'data-tab="(\w+)"', html)
    assert tabs[0] == "learn", f"Learn must be the first tab, got {tabs}"
    assert len(tabs) == 6

    sw = (Path(settings.static_dir) / "sw.js").read_text()
    assert "/js/learn.js" in sw, "the Learn screen must work offline like the rest of the shell"

    app = (Path(settings.static_dir) / "app.js").read_text()
    assert "firstTab" in app and "'learn'" in app

    css = (Path(settings.static_dir) / "styles.css").read_text()
    tabs_rule = css[css.index("#tabs {"):][:400]
    assert "repeat(5" not in tabs_rule, "a hardcoded column count drops the last tab off-screen"
