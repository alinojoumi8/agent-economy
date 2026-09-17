"""The owned production server must close its listener on success and failure."""
from contextlib import asynccontextmanager
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import FastAPI
import pytest

from scripts.city_research_acceptance import _serve


@pytest.mark.parametrize("workflow_fails", [False, True])
def test_owned_server_lifespan_and_socket_close_after_workflow(workflow_fails):
    lifecycle = []

    @asynccontextmanager
    async def lifespan(_app):
        lifecycle.append("started")
        yield
        lifecycle.append("stopped")

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"ok": True}

    try:
        with _serve(app) as url:
            with urlopen(url + "/health", timeout=2) as response:
                assert response.status == 200
            assert lifecycle == ["started"]
            if workflow_fails:
                raise ValueError("browser assertion failed")
    except ValueError as exc:
        assert workflow_fails and str(exc) == "browser assertion failed"
    else:
        assert not workflow_fails
    assert lifecycle == ["started", "stopped"]
    with pytest.raises(URLError):
        urlopen(url + "/health", timeout=2)
