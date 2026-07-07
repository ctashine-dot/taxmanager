import base64
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from semusarang_agent import find_latest_export, serve


def test_find_latest_export_picks_newest_matching_file(tmp_path):
    old = tmp_path / "거래처_old.xlsx"
    old.write_bytes(b"old")
    new = tmp_path / "거래처_new.xlsx"
    new.write_bytes(b"new")
    # make sure mtimes differ and are ordered as expected
    now = time.time()
    import os
    os.utime(old, (now - 5 * 60, now - 5 * 60))
    os.utime(new, (now, now))

    result = find_latest_export(str(tmp_path), "*거래처*.xls*", max_age_minutes=10)
    assert result.name == "거래처_new.xlsx"


def test_find_latest_export_ignores_stale_files(tmp_path):
    stale = tmp_path / "거래처_stale.xlsx"
    stale.write_bytes(b"stale")
    import os
    old_time = time.time() - 60 * 60
    os.utime(stale, (old_time, old_time))

    with pytest.raises(RuntimeError, match="찾지 못했습니다"):
        find_latest_export(str(tmp_path), "*거래처*.xls*", max_age_minutes=10)


def test_find_latest_export_missing_dir():
    with pytest.raises(RuntimeError, match="존재하지 않습니다"):
        find_latest_export("/no/such/dir", "*.xlsx", max_age_minutes=10)


@pytest.fixture
def running_agent(tmp_path):
    sample = tmp_path / "거래처_현황.xlsx"
    sample.write_bytes(b"hello-bytes")

    config = {
        "port": 0,
        "token": "test-token",
        "allowed_origin": "https://example.web.app",
        "mode": "watch",
        "watch_dir": str(tmp_path),
        "file_patterns": {"clients": "*거래처*.xls*"},
        "max_age_minutes": 10,
    }
    from http.server import HTTPServer
    from semusarang_agent import make_handler

    httpd = HTTPServer(("127.0.0.1", 0), make_handler(config))
    port = httpd.server_port
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}", sample
    httpd.shutdown()
    thread.join(timeout=2)


def test_health_endpoint(running_agent):
    base_url, _ = running_agent
    with urllib.request.urlopen(base_url + "/health") as resp:
        body = json.loads(resp.read())
    assert body == {"status": "ok", "mode": "watch"}


def test_fetch_requires_token(running_agent):
    base_url, _ = running_agent
    req = urllib.request.Request(
        base_url + "/fetch",
        data=json.dumps({"type": "clients"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 401


def test_fetch_returns_latest_file(running_agent):
    base_url, sample = running_agent
    req = urllib.request.Request(
        base_url + "/fetch",
        data=json.dumps({"type": "clients"}).encode(),
        headers={"Content-Type": "application/json", "X-Agent-Token": "test-token"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read())
    assert body["filename"] == sample.name
    assert base64.b64decode(body["content_base64"]) == sample.read_bytes()


def test_fetch_unknown_type_rejected(running_agent):
    base_url, _ = running_agent
    req = urllib.request.Request(
        base_url + "/fetch",
        data=json.dumps({"type": "unknown"}).encode(),
        headers={"Content-Type": "application/json", "X-Agent-Token": "test-token"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 400


def test_options_cors_headers(running_agent):
    base_url, _ = running_agent
    req = urllib.request.Request(base_url + "/fetch", method="OPTIONS")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 204
        assert resp.headers.get("Access-Control-Allow-Origin") == "https://example.web.app"
