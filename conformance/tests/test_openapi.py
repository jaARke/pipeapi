from reference_app.app import create_app
from reference_app.environment import Settings


def test_the_schema_holds_the_typed_api_and_leaves_out_the_mirror() -> None:
    paths = create_app(Settings()).openapi()["paths"]
    assert set(paths["/items"]) == {"get", "head", "post"}
    assert set(paths["/items/form"]) == {"post"}
    assert set(paths["/items/{item_id}"]) == {"delete"}
    assert not any(path.startswith("/seen") for path in paths)
