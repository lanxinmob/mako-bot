"""Exercise real Dashboard routes with synthetic settings/service, without booting the bot."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import Mock


def deny_external(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        name = Path(str(args[0])).name
        assert name != ".env" and not name.startswith(".env."), "env read denied"
    assert event not in {"socket.connect", "socket.getaddrinfo"}, "network denied"


# Windows creates a loopback socketpair for the event loop's own wakeup pipe.
# Create only that loop before installing the network denial, before app imports.
loop = asyncio.new_event_loop()
sys.addaudithook(deny_external)
root = Path.cwd().resolve()
assert (root / "pyproject.toml").is_file()
sys.path.insert(0, str(root))
from fastapi import FastAPI
import httpx

app = FastAPI()
driver = types.SimpleNamespace(server_app=app, on_startup=lambda fn: fn)
settings = types.SimpleNamespace(dashboard_token="synthetic-dashboard-token")
payload = {"ok": True, "data": {"synthetic": True}}
service = Mock()
service.get_frontend_summary.return_value = payload
for name, attrs in {
    "nonebot": {"get_driver": lambda: driver},
    "nonebot.log": {"logger": Mock()},
    "src.core.config": {"get_settings": lambda: settings},
    "src.web.dashboard.service": {"DashboardService": Mock(return_value=service)},
}.items():
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module

path = root / "src/plugins/dashboard/__init__.py"
spec = importlib.util.spec_from_file_location("dashboard_routes_under_test", path)
routes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routes)


async def verify():
    await routes.mount_dashboard_routes()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://dashboard.test"
    ) as client:
        page = await client.get("/mako/dashboard")
        assert page.status_code == 200
        for key, value in routes.SECURITY_HEADERS.items():
            assert page.headers[key] == value
        assert "synthetic-dashboard-token" not in page.text
        assert "script-src 'self'" in page.headers["Content-Security-Policy"]
        assert "unsafe-inline" not in page.headers["Content-Security-Policy"]
        for url in ("/mako/dashboard/assets/dashboard.js", "/mako/dashboard/assets/dashboard.css"):
            response = await client.get(url)
            assert response.status_code == 200
        # Every nested asset must be served with an ES-module/CSS-compatible MIME type.
        assets = root / "src/web/dashboard/static/assets"
        for asset in assets.rglob("*"):
            if not asset.is_file() or asset.suffix not in {".js", ".css"}:
                continue
            response = await client.get("/mako/dashboard/assets/" + asset.relative_to(assets).as_posix())
            assert response.status_code == 200, asset
            expected = ("text/javascript", "application/javascript") if asset.suffix == ".js" else ("text/css",)
            assert response.headers["content-type"].split(";")[0] in expected, asset
        endpoint = "/mako/dashboard/api/summary"
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            assert (await client.get(endpoint, headers=headers)).status_code == 401
        service.get_frontend_summary.assert_not_called()
        for headers in (
            {"Authorization": "Bearer synthetic-dashboard-token"},
            {"X-Dashboard-Token": "synthetic-dashboard-token"},
        ):
            response = await client.get(endpoint + "?limit=7", headers=headers)
            assert response.status_code == 200 and response.json() == payload
            service.get_frontend_summary.assert_called_with(limit=7)
            for key, value in routes.SECURITY_HEADERS.items():
                assert response.headers[key] == value
        for limit in (0, 201):
            assert (await client.get(endpoint + f"?limit={limit}")).status_code == 422
        settings.dashboard_token = ""
        assert (await client.get(endpoint)).status_code == 503
    print("PASS real routes: public shell, auth 401/503/Bearer/X-Dashboard-Token, limits, JSON, security headers, asset MIME")


try:
    loop.run_until_complete(verify())
finally:
    loop.close()
