"""The PWA shell: self-contained (CSP blocks anything external), cached by a versioned service
worker that never touches /api, and every /api route behind the cookie."""
from __future__ import annotations

import re
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
    root = Path(settings.base_dir).parent
    for f in root.rglob("*"):
        if f.is_dir() or ".git" in f.parts or ".venv" in f.parts or ".claude" in f.parts or "__pycache__" in f.parts:
            continue
        if f.suffix in {".png", ".db", ".mp3", ".pyc"}:
            continue
        text = f.read_text(errors="ignore")
        # Real keys have a long random tail; the bare prefixes (as in this test) are fine.
        assert not re.search(r"AIza[0-9A-Za-z_\-]{30,}|gsk_[0-9A-Za-z]{40,}", text), f"looks like an API key in {f}"
