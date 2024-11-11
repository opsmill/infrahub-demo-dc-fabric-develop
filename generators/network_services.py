from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from infrahub_sdk import InfrahubClient
from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.node import InfrahubNode
from infrahub_sdk.protocols import CoreIPPrefixPool, CoreNumberPool

from infrahub_sdk.protocols import CoreNode
if TYPE_CHECKING:
    from infrahub_sdk.node import RelatedNode, RelationshipManager

class InfraVLAN(CoreNode):
    name: str
    description: Optional[str]
    vlan_id: int
    status: str
    role: str
    location: RelatedNode
    network_service: RelatedNode
    profiles: RelationshipManager
    member_of_groups: RelationshipManager
    subscriber_of_groups: RelationshipManager

class TopologyNetworkService(CoreNode):
    name: Optional[str]
    description: Optional[str]
    status: str
    identifier: RelatedNode
    topology: RelatedNode
    profiles: RelationshipManager
    member_of_groups: RelationshipManager
    subscriber_of_groups: RelationshipManager

class TopologyLayer2NetworkService(TopologyNetworkService):
    name: Optional[str]
    description: Optional[str]
    status: str
    vlan: RelatedNode
    identifier: RelatedNode
    topology: RelatedNode
    profiles: RelationshipManager
    member_of_groups: RelationshipManager
    subscriber_of_groups: RelationshipManager

class TopologyLayer3NetworkService(TopologyNetworkService):
    name: Optional[str]
    description: Optional[str]
    status: str
    prefix: RelatedNode
    vlan: RelatedNode
    identifier: RelatedNode
    topology: RelatedNode
    profiles: RelationshipManager
    member_of_groups: RelationshipManager
    subscriber_of_groups: RelationshipManager


PROVISIONING_STATUS = "provisioning"
ACTIVE_STATUS = "active"
DECOMMISSIONING_STATUS = "decommissioning"
DECOMMISSIONED_STATUS = "decommissioned"

L2_VLAN_POOL = "L2 network service vlan id"
L2_VLAN_NAME_PREFIX = "l2"

L3_VLAN_POOL = "L3 network service vlan id"
L3_PREFIX_POOL = "testl3pool"
L3_VLAN_NAME_PREFIX = "l3"

# infrahubctl generator generate_network_services network_service_name="aabbcc" --branch main
# FIXME: This is not idempotent
# FIXME: Any way to have debug?
# FIXME: Any way to log something?

# TODO: Implement batch logic in the builder?
# TODO: Proper error handling and return code
# TODO: What about branches?
# TODO: Manage location
# TODO: Manage vrf
# TODO: Manage org
# Create a pull
# Create a group
# Get generator going


class ServiceBuilder:
    def __init__(
        self,
        client: InfrahubClient,
        network_service: TopologyLayer2NetworkService | TopologyLayer3NetworkService,
    ) -> None:
        # Save parameters
        self.client = client
        self.network_service = network_service

    async def allocate_prefix(self) -> None:
        """Allocate a prefix coming from a resource pool to the service."""

        # Get resource pool
        resource_pool = await self.client.get(
            kind=CoreIPPrefixPool,
            name__value=L3_PREFIX_POOL,
        )

        # Craft the data dict for prefix
        prefix_data: dict = {
            "status": "active",
            "description": f"Prefix allocated to l3 service {self.network_service.display_label}",
            "network_service": self.network_service.id,
            "role": "server",
        }

        # Create resource from the pool
        await self.client.allocate_next_ip_prefix(resource_pool, data=prefix_data)

    async def allocate_vlan(
        self, ressource_pool_name: str, vlan_name_prefix: str
    ) -> None:
        """Create a VLAN with ID coming from the pool provided and assign this VLAN to the service."""

        # Get resource pool
        resource_pool = await self.client.get(
            kind=CoreNumberPool,
            name__value=ressource_pool_name,
        )

        # Craft and save the vlan
        vlan: InfraVLAN = await self.client.create(
            kind=InfraVLAN,
            name=f"vlan_{vlan_name_prefix}_{self.network_service.name.value.lower()}",
            vlan_id=resource_pool,
            description="VLAN dedicated to a Network Service",
            status=ACTIVE_STATUS,
            network_service=self.network_service,
            role="server",
            location=self.network_service.topology.get().location,
        )
        await vlan.save()

        # Attach service -> vlan
        self.network_service.vlan = vlan
        await self.network_service.save(allow_upsert=True)


class NetworkServicesGenerator(InfrahubGenerator):
    async def generate(self, data: dict) -> None:
        # Here we just get the id from the dict
        # TODO: support IndexError: list index out of range
        network_service_node: dict = data["TopologyNetworkService"]["edges"][0]["node"]

        # Translate the dict to proper object
        network_service = await InfrahubNode.from_graphql(
            client=self.client, data=network_service_node, branch=self.branch
        )

        # Here we populate relationships of the network service
        await network_service.topology.fetch()
        await network_service.topology.get().location.fetch()

        # Create a builder object
        builder: ServiceBuilder = ServiceBuilder(
            client=self.client, network_service=network_service
        )

        # Now we build service depending on the flavour we want
        if network_service.get_kind() == "TopologyLayer2NetworkService":  # FIXME
            # Allocate a VLAN
            await builder.allocate_vlan(
                ressource_pool_name=L2_VLAN_POOL, vlan_name_prefix="l2"
            )
        elif network_service.get_kind() == "TopologyLayer3NetworkService":  # FIXME
            # Allocate a VLAN ...
            await builder.allocate_vlan(
                ressource_pool_name=L3_VLAN_POOL, vlan_name_prefix="l3"
            )
            # and a prefix
            await builder.allocate_prefix()
        else:
            print("we don't support this kind of NetworkService ...")
            return False
