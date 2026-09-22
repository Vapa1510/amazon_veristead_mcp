from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient

from veristead.server import StripWWWAuthenticateMiddleware, _build_auth


def _make_app(status_code, headers=None):
    async def endpoint(request):
        return Response(status_code=status_code, headers=headers or {})

    app = Starlette(routes=[Route("/", endpoint)])
    app.add_middleware(StripWWWAuthenticateMiddleware)
    return app


def test_strips_www_authenticate_on_401():
    app = _make_app(401, headers={"WWW-Authenticate": "Bearer"})
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 401
    assert "www-authenticate" not in {k.lower() for k in response.headers.keys()}


def test_leaves_other_headers_on_401():
    app = _make_app(401, headers={"WWW-Authenticate": "Bearer", "X-Custom": "value"})
    client = TestClient(app)
    response = client.get("/")

    assert response.headers.get("x-custom") == "value"


def test_does_not_touch_200_headers():
    """Regression guard: the middleware must only ever act on 401 responses,
    never strip headers from anything else."""
    app = _make_app(200, headers={"WWW-Authenticate": "Bearer"})
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers.get("www-authenticate") == "Bearer"


def test_build_auth_returns_none_without_credentials(monkeypatch):
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("OAUTH_BASE_URL", raising=False)

    assert _build_auth() is None


def test_build_auth_returns_provider_with_credentials(monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test_id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("OAUTH_BASE_URL", "http://localhost:8000")

    assert _build_auth() is not None
