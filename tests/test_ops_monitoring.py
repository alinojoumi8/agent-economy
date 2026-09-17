import json
import threading
import time
from urllib.request import urlopen

import pytest

from tests.test_catalog_backup_retention import backup_module
from scripts import docker_preflight


def test_backup_metrics_fail_closed_and_serve_real_http(tmp_path, monkeypatch):
    module = backup_module()
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(module, "STATE", receipt)
    for payload in (None, "broken", "{}", '{"completed_at": "secret"}',
                    json.dumps({"completed_at": time.time() + 1000})):
        if payload is not None:
            receipt.write_text(payload)
        assert module.last_success() == 0
    completed = time.time() - 1
    receipt.write_text(json.dumps({"completed_at": completed, "name": "private"}))
    server = module.MetricsServer(("127.0.0.1", 0), module.MetricsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/metrics", timeout=5) as response:
            text = response.read().decode()
            assert str(completed) in text
            assert "private" not in text
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_docker_preflight_leaves_healthy_engine_untouched(monkeypatch):
    monkeypatch.setattr(docker_preflight, "probe", lambda _: "test-version")
    monkeypatch.setattr(docker_preflight, "desktop_running", lambda: pytest.fail("unnecessary startup check"))
    monkeypatch.setattr(docker_preflight.subprocess, "Popen", lambda *a, **k: pytest.fail("unexpected process start"))
    assert docker_preflight.ensure_ready("docker", start=True)["desktop_started"] is False


def test_docker_preflight_exits_on_failure_without_restart(monkeypatch):
    monkeypatch.setattr(docker_preflight, "probe", lambda _: None)
    monkeypatch.setattr(docker_preflight.subprocess, "Popen", lambda *a, **k: pytest.fail("unexpected process start"))
    result = docker_preflight.ensure_ready("docker", wait_seconds=0)
    assert result["status"] == "unavailable"
    assert result["desktop_started"] is False
