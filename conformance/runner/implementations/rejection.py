from runner.case_run import CaseRun
from runner.registry import implements

TARGET = "/status/401"
# Sent once the first response has returned; once it answers, a resend or an event the
# first caused would have shown.
CONTROL_TARGET = "/status/204"


@implements("rejection.app-401")
def the_apps_own_401_is_the_apps(run: CaseRun) -> None:
    """Check that the app's own 401 comes back as it is, sent once, with no event."""
    app = run.app()
    client = run.client()
    backend = run.connect(client, app)
    before = len(app.observations())
    response = client.request(backend, "GET", TARGET, via=run.via)
    assert response.status == 401
    assert response.values("www-authenticate") == ["Bearer"]
    assert response.values("x-pipeapi-rejected") == []
    control = client.request(backend, "GET", CONTROL_TARGET, via=run.via)
    assert control.status == 204
    requests = [
        each
        for each in app.observations()[before:]
        if each["event"] == "request" and each["path"] == TARGET
    ]
    assert len(requests) == 1
    assert client.events(lambda each: each["event"] == "lifecycle") == []
