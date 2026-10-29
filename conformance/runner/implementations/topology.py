import secrets

from reference_app.routers.requests import BarrierOutcome
from runner.case_run import CaseRun
from runner.registry import implements

CLIENTS = 2


@implements("topology.concurrent-clients")
def two_clients_requests_run_together(run: CaseRun) -> None:
    """Check that two clients' requests to one backend are in flight together."""
    app = run.app()
    clients = [run.client() for _ in range(CLIENTS)]
    backends = [run.connect(client, app) for client in clients]
    target = f"/barrier/{secrets.token_hex(8)}?parties={CLIENTS}"
    requests = [
        client.send_request(backend, "GET", target, via=run.via)
        for client, backend in zip(clients, backends, strict=True)
    ]
    outcomes = [
        client.finish(request).answer(BarrierOutcome)
        for client, request in zip(clients, requests, strict=True)
    ]
    assert all(outcome.filled for outcome in outcomes), outcomes
    assert len({client.hello.pid for client in clients}) == CLIENTS
