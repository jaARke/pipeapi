from reference_app.routers.requests import Seen
from runner.case_run import CaseRun
from runner.listeners import RecordingListener
from runner.registry import implements

PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
BYPASS_VARIABLES = ("NO_PROXY",)


@implements("host.proxies-ignored")
def requests_never_go_through_a_proxy(run: CaseRun) -> None:
    """
    Check that proxy variables naming a listener leave every request direct.

    Raises:
        AssertionError: A request failed, with the connections the proxy recorded.
    """
    app = run.app()
    with RecordingListener() as proxy:
        changes: dict[str, str | None] = {}
        for variable in PROXY_VARIABLES:
            changes |= {variable: proxy.url, variable.lower(): proxy.url}
        for variable in BYPASS_VARIABLES:
            changes |= {variable: None, variable.lower(): None}
        client = run.client(changes)
        backend = run.connect(client, app)
        server_pid = app.observations()[0]["pid"]
        try:
            seen = client.request(backend, "GET", "/seen", via=run.via).answer(Seen)
        except AssertionError as failure:
            connections = len(proxy.connections())
            failure.add_note(f"the proxy recorded {connections} connections")
            raise
        assert seen.pid == server_pid
        assert proxy.connections() == []
