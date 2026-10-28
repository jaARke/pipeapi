from fastapi.testclient import TestClient

from reference_app.app import create_app
from reference_app.environment import Settings
from tests.support.targets import Target

MULTIPART_BOUNDARY = "reference-app-boundary"


def test_a_created_item_is_listed(target: Target) -> None:
    created = target.client.post("/items", json={"name": "first", "tags": ["a"]})
    assert created.status_code == 201
    item = created.json()
    assert (item["name"], item["tags"]) == ("first", ["a"])
    assert item in target.client.get("/items").json()


def test_a_url_encoded_form_creates_an_item_with_its_repeated_fields(
    target: Target,
) -> None:
    response = target.client.post(
        "/items/form", data={"name": "encoded", "tags": ["x", "y"]}
    )
    assert response.status_code == 201
    assert (response.json()["name"], response.json()["tags"]) == ("encoded", ["x", "y"])


def test_a_multipart_form_creates_an_item(target: Target) -> None:
    body = (
        f"--{MULTIPART_BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="name"\r\n\r\n'
        "parted\r\n"
        f"--{MULTIPART_BOUNDARY}--\r\n"
    )
    response = target.client.post(
        "/items/form",
        content=body.encode(),
        headers={"content-type": f"multipart/form-data; boundary={MULTIPART_BOUNDARY}"},
    )
    assert response.status_code == 201
    assert (response.json()["name"], response.json()["tags"]) == ("parted", [])


def test_deleting_an_item_answers_204_with_no_body(target: Target) -> None:
    item = target.client.post("/items", json={"name": "doomed"}).json()
    deleted = target.client.delete(f"/items/{item['id']}")
    assert (deleted.status_code, deleted.content) == (204, b"")
    assert deleted.headers.get("content-length", "0") == "0"
    assert item not in target.client.get("/items").json()


def test_deleting_an_item_the_store_lacks_answers_404(target: Target) -> None:
    assert target.client.delete("/items/999999").status_code == 404


def test_head_answers_the_lists_headers_without_its_body(target: Target) -> None:
    target.client.post("/items", json={"name": "headed"})
    listed = target.client.get("/items")
    head = target.client.head("/items")
    assert (head.status_code, head.content) == (200, b"")
    assert head.headers["content-length"] == str(len(listed.content))


def test_an_invalid_item_is_refused(target: Target) -> None:
    assert target.client.post("/items", json={"tags": ["no name"]}).status_code == 422


def test_each_app_holds_items_of_its_own() -> None:
    with TestClient(create_app(Settings())) as first:
        first.post("/items", json={"name": "only in the first"})
    with TestClient(create_app(Settings())) as second:
        assert second.get("/items").json() == []
