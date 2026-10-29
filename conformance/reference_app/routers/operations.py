from fastapi.routing import APIRoute
from fastapi.utils import generate_unique_id


class MissingOperationId(Exception):
    """A route in the schema doesn't name its operation."""


def require_operation_id(route: APIRoute) -> str:
    """
    Refuse a route in the schema that doesn't name its operation.

    Each adapter generates its typed client from the schema, naming each method by
    its operation's ID, so an ID FastAPI derives from a function's name and path
    would rename every adapter's method whenever either changed. A route out of the
    schema keeps FastAPI's derived ID, which only routing uses.

    Args:
        route: The route, which gives no ``operation_id``.

    Returns:
        The derived ID, for a route out of the schema.

    Raises:
        MissingOperationId: The route is in the schema.
    """
    if route.include_in_schema:
        methods = ", ".join(sorted(route.methods or ()))
        raise MissingOperationId(f"{methods} {route.path} names no operation_id")
    return generate_unique_id(route)
