from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, status
from pydantic import BaseModel, Field

from reference_app.routers.operations import require_operation_id


class NewItem(BaseModel):
    """An item to create."""

    name: str
    tags: list[str] = Field(default_factory=list)


class Item(BaseModel):
    """A created item."""

    id: int
    name: str
    tags: list[str]


class ItemStore:
    """The items one app instance holds, in memory, so a new backend starts empty."""

    def __init__(self) -> None:
        self._items: dict[int, Item] = {}
        self._next_id = 1

    def add(self, new: NewItem) -> Item:
        """
        Store an item under the next ID.

        Args:
            new: The item.

        Returns:
            The stored item.
        """
        item = Item(id=self._next_id, name=new.name, tags=list(new.tags))
        self._items[item.id] = item
        self._next_id += 1
        return item

    def all(self) -> list[Item]:
        """
        List the items.

        Returns:
            The items, in the order they were created.
        """
        return list(self._items.values())

    def remove(self, item_id: int) -> bool:
        """
        Remove an item.

        Args:
            item_id: The item's ID.

        Returns:
            Whether the store held it.
        """
        return self._items.pop(item_id, None) is not None


def create_router() -> APIRouter:
    """
    Create the items routes, over a store of their own.

    Returns:
        The router.
    """
    store = ItemStore()
    router = APIRouter(
        prefix="/items",
        tags=["items"],
        generate_unique_id_function=require_operation_id,
    )

    async def list_items() -> list[Item]:
        """
        List the items.

        Returns:
            The items, in the order they were created.
        """
        return store.all()

    # HEAD apart from GET, since a route that names both has one operation ID for two
    # operations in the schema.
    router.add_api_route("", list_items, methods=["GET"], operation_id="list_items")
    router.add_api_route("", list_items, methods=["HEAD"], operation_id="head_items")

    @router.post("", status_code=status.HTTP_201_CREATED, operation_id="create_item")
    async def create_item(new: NewItem) -> Item:
        """
        Create an item from a JSON body.

        Returns:
            The created item.
        """
        return store.add(new)

    @router.post(
        "/form",
        status_code=status.HTTP_201_CREATED,
        operation_id="create_item_from_form",
    )
    async def create_item_from_form(
        name: Annotated[str, Form()],
        tags: Annotated[list[str], Form(default_factory=list)],
    ) -> Item:
        """
        Create an item from a form, URL-encoded or multipart, which may repeat `tags`.

        Returns:
            The created item.
        """
        return store.add(NewItem(name=name, tags=tags))

    @router.delete(
        "/{item_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        operation_id="delete_item",
    )
    async def delete_item(item_id: int) -> None:
        """
        Delete an item, answering with no content.

        Raises:
            HTTPException: 404, for an item the store does not hold.
        """
        if not store.remove(item_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such item")

    return router
