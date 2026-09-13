"""An exception escaping a route is written to ppxai's OWN log, traceback included.

v1.19.2. The Windows `/preview` 500 (a backslash path handed to
`FileResponse`) left NOTHING in ~/.ppxai/logs: the debug log showed the
request line, then silence, because the traceback went to uvicorn's stderr
only. It was diagnosed from the browser console instead of the log this
project keeps for exactly that.

`log_unhandled_route_error` in `ppxai/server/http.py` closes the gap. Pinned
here: the traceback reaches the module logger (with `exc_info`), the client
gets a JSON body with a stable `error` key, and the exception's own text
stays OUT of that body (a gateway deployment must not leak internals).
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

import ppxai.server.http as http_module

BOOM_PATH = "/__test_unhandled_route_error"


def _ensure_boom_route() -> None:
    """Register a route that raises, once; the module app is shared across tests."""
    if any(getattr(r, "path", None) == BOOM_PATH for r in http_module.app.routes):
        return

    @http_module.app.get(BOOM_PATH)
    async def _boom():
        raise RuntimeError("kaboom from a route")


class TestUnhandledRouteErrorsAreLogged:

    def test_the_traceback_reaches_the_ppxai_logger(self):
        _ensure_boom_route()

        with patch.object(http_module, "logger") as log:
            client = TestClient(http_module.app, raise_server_exceptions=False)
            resp = client.get(BOOM_PATH)

        assert resp.status_code == 500
        log.error.assert_called_once()
        msg = log.error.call_args.args[0]
        assert "RuntimeError" in msg
        assert BOOM_PATH in msg
        assert "kaboom" in msg, "the exception text belongs in the log"
        assert log.error.call_args.kwargs.get("exc_info") is True, (
            "without exc_info the log has the message but not the traceback"
        )

    def test_the_client_gets_a_generic_json_body(self):
        _ensure_boom_route()

        with patch.object(http_module, "logger"):
            client = TestClient(http_module.app, raise_server_exceptions=False)
            resp = client.get(BOOM_PATH)

        body = resp.json()
        assert body["error"] == "internal_error"
        assert "kaboom" not in body["detail"], "internals must not reach the wire"
        assert "log" in body["detail"], "the body must point the user at the log"
