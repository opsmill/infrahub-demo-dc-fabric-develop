from infrahub_sdk import InfrahubClient, InfrahubNode
from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.protocols import CoreNumberPool

from schema_protocols import (
    InfraVLAN,
    TopologyLayer2NetworkService,
    TopologyLayer3NetworkService,
)

PROVISIONING_STATUS = "provisioning"
ACTIVE_STATUS = "active"
DECOMMISSIONING_STATUS = "decommissioning"
DECOMMISSIONED_STATUS = "decommissioned"
L2_VLAN_POOL = "L2 network service vlan id"
L2_VLAN_NAME_PREFIX = "l2"
L3_VLAN_POOL = "L3 network service vlan id"

# infrahubctl generator generate_network_services network_service_id="17fcb90f-9573-4ddd-2f2b-c51c8e7c9106" --branch main

# FIXME: This is not idempotent
# FIXME: Any way to have debug?
# FIXME: Any way to log something?

# TODO: Implement batch logic in the builder?
# TODO: Proper error handling and return code


class ServiceBuilder:
    def __init__(
        self,
        client: InfrahubClient,
        network_service: TopologyLayer2NetworkService | TopologyLayer3NetworkService,
    ) -> None:
        # Save parameters
        self.client = client
        self.network_service = network_service

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
        network_service: TopologyLayer2NetworkService = await InfrahubNode.from_graphql(
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
            await builder.allocate_vlan(
                ressource_pool_name=L2_VLAN_POOL, vlan_name_prefix="l2"
            )
        else:
            print("we don't support this kind of NetworkService ...")
            return False
