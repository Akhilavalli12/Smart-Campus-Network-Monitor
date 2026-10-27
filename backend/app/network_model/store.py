"""Persistence boundary for the network model.

`NetworkStore` is the interface the service layer depends on. `MongoNetworkStore`
is the real implementation. Tests also run the same contract against an
in-memory implementation.
"""
from typing import Protocol

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.network_model.errors import ConflictError
from app.network_model.models import Device, Link, Subnet


class NetworkStore(Protocol):
    async def list_subnets(self) -> list[Subnet]: ...
    async def get_subnet(self, subnet_id: str) -> Subnet | None: ...
    async def insert_subnet(self, subnet: Subnet) -> None: ...
    async def list_devices(self, *, block: str | None = None, type: str | None = None, subnet_id: str | None = None) -> list[Device]: ...
    async def get_device(self, device_id: str) -> Device | None: ...
    async def insert_device(self, device: Device) -> None: ...
    async def delete_device(self, device_id: str) -> bool: ...
    async def update_device_fields(self, device_id: str, fields: dict) -> bool: ...
    async def list_links(self) -> list[Link]: ...
    async def insert_link(self, link: Link) -> None: ...
    async def update_link_fields(self, link_id: str, fields: dict) -> bool:
        check_link_updatable(fields)
        result = await self._links.update_one({"_id": link_id}, {"$set": fields})
        return result.matched_count == 1

    async def delete_links_of_device(self, device_id: str) -> int: ...
    async def update_link_fields(self, link_id: str, fields: dict) -> bool: ...
    async def clear_network(self) -> None: ...


# Fields other components may write on a device document. Anything else is refused,
# so a bug cannot overwrite identity or addressing data.
UPDATABLE_DEVICE_FIELDS = frozenset(
    {"status", "last_seen", "up_since", "consecutive_failures", "caused_by", "monitoring_error", "latest", "sim_state"}
)


UPDATABLE_LINK_FIELDS = frozenset({"latest"})


def check_link_updatable(fields: dict) -> None:
    unknown = set(fields) - UPDATABLE_LINK_FIELDS
    if unknown:
        raise ValueError(f"Fields not updatable on a link: {sorted(unknown)}")


def check_updatable(fields: dict) -> None:
    unknown = set(fields) - UPDATABLE_DEVICE_FIELDS
    if unknown:
        raise ValueError(f"Fields not updatable on a device: {sorted(unknown)}")


def _to_doc(model) -> dict:
    document = model.model_dump()
    document["_id"] = document.pop("id")
    return document


def _from_doc(model_class, document: dict):
    data = dict(document)
    data["id"] = data.pop("_id")
    return model_class.model_validate(data)


class MongoNetworkStore:
    def __init__(self, db: AsyncDatabase) -> None:
        self._subnets = db["subnets"]
        self._devices = db["devices"]
        self._links = db["links"]

    async def ensure_indexes(self) -> None:
        """Idempotent. Unique indexes enforce IP/CIDR uniqueness even under concurrent writes."""
        await self._devices.create_index("ip", unique=True, name="uniq_device_ip")
        await self._devices.create_index([("block", 1), ("type", 1)], name="block_type")
        await self._subnets.create_index("cidr", unique=True, name="uniq_subnet_cidr")
        await self._links.create_index([("a_id", 1), ("b_id", 1)], unique=True, name="uniq_link_pair")

    # --- subnets ---
    async def list_subnets(self) -> list[Subnet]:
        docs = await self._subnets.find({}).sort("_id", 1).to_list(length=None)
        return [_from_doc(Subnet, d) for d in docs]

    async def get_subnet(self, subnet_id: str) -> Subnet | None:
        doc = await self._subnets.find_one({"_id": subnet_id})
        return _from_doc(Subnet, doc) if doc else None

    async def insert_subnet(self, subnet: Subnet) -> None:
        try:
            await self._subnets.insert_one(_to_doc(subnet))
        except DuplicateKeyError:
            raise ConflictError("A subnet with this id or CIDR already exists") from None

    # --- devices ---
    async def list_devices(self, *, block: str | None = None, type: str | None = None, subnet_id: str | None = None) -> list[Device]:
        query = {k: v for k, v in {"block": block, "type": type, "subnet_id": subnet_id}.items() if v is not None}
        docs = await self._devices.find(query).sort("_id", 1).to_list(length=None)
        return [_from_doc(Device, d) for d in docs]

    async def get_device(self, device_id: str) -> Device | None:
        doc = await self._devices.find_one({"_id": device_id})
        return _from_doc(Device, doc) if doc else None

    async def insert_device(self, device: Device) -> None:
        try:
            await self._devices.insert_one(_to_doc(device))
        except DuplicateKeyError:
            raise ConflictError("A device with this id or IP address already exists") from None

    async def delete_device(self, device_id: str) -> bool:
        result = await self._devices.delete_one({"_id": device_id})
        return result.deleted_count == 1

    async def update_device_fields(self, device_id: str, fields: dict) -> bool:
        check_updatable(fields)
        result = await self._devices.update_one({"_id": device_id}, {"$set": fields})
        return result.matched_count == 1

    # --- links ---
    async def list_links(self) -> list[Link]:
        docs = await self._links.find({}).sort("_id", 1).to_list(length=None)
        return [_from_doc(Link, d) for d in docs]

    async def insert_link(self, link: Link) -> None:
        try:
            await self._links.insert_one(_to_doc(link))
        except DuplicateKeyError:
            raise ConflictError("This link already exists") from None

    async def update_link_fields(self, link_id: str, fields: dict) -> bool:
        check_link_updatable(fields)
        result = await self._links.update_one({"_id": link_id}, {"$set": fields})
        return result.matched_count == 1

    async def delete_links_of_device(self, device_id: str) -> int:
        result = await self._links.delete_many({"$or": [{"a_id": device_id}, {"b_id": device_id}]})
        return result.deleted_count

    async def clear_network(self) -> None:
        for collection in (self._links, self._devices, self._subnets):
            await collection.delete_many({})
