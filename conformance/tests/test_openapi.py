import pytest
from fastapi import APIRouter, FastAPI

from reference_app.app import create_app
from reference_app.environment import Settings
from reference_app.routers.operations import MissingOperationId, require_operation_id


def test_the_schema_holds_the_typed_api_and_leaves_out_the_mirror() -> None:
    paths = create_app(Settings()).openapi()["paths"]
    assert set(paths["/items"]) == {"get", "head", "post"}
    assert set(paths["/items/form"]) == {"post"}
    assert set(paths["/items/{item_id}"]) == {"delete"}
    assert not any(path.startswith("/seen") for path in paths)


def test_each_operation_keeps_the_id_adapters_name_its_method_by() -> None:
    paths = create_app(Settings()).openapi()["paths"]
    operations = {
        (method.upper(), path): operation["operationId"]
        for path, methods in paths.items()
        for method, operation in methods.items()
    }
    assert operations == {
        ("GET", "/items"): "list_items",
        ("HEAD", "/items"): "head_items",
        ("POST", "/items"): "create_item",
        ("POST", "/items/form"): "create_item_from_form",
        ("DELETE", "/items/{item_id}"): "delete_item",
        ("POST", "/echo"): "echo",
        ("GET", "/headers"): "headers",
        ("GET", "/status/{code}"): "get_status",
        ("POST", "/status/{code}"): "post_status",
        ("GET", "/barrier/{name}"): "barrier",
        ("GET", "/events"): "events",
        ("POST", "/environment"): "probe_environment",
        ("POST", "/input"): "read_input",
        ("POST", "/output"): "write_output",
    }


def test_a_route_in_the_schema_without_an_operation_id_is_refused() -> None:
    router = APIRouter(generate_unique_id_function=require_operation_id)

    async def unnamed() -> None:
        pass

    with pytest.raises(MissingOperationId, match="GET /unnamed"):
        router.add_api_route("/unnamed", unnamed, methods=["GET"])


def test_a_route_out_of_the_schema_keeps_fastapis_id() -> None:
    app = FastAPI(generate_unique_id_function=require_operation_id)

    async def hidden() -> None:
        pass

    app.add_api_route("/hidden", hidden, methods=["GET"], include_in_schema=False)
    assert "/hidden" not in app.openapi()["paths"]
