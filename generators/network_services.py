from infrahub_sdk import InfrahubClient, InfrahubNode
from infrahub_sdk.batch import InfrahubBatch
from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.protocols import CoreNumberPool

from schema_protocols import (
    InfraVLAN,
    TopologyLayer2NetworkService,
    TopologyLayer3NetworkService,
    TopologyNetworkService,
)

PROVISIONING_STATUS = "provisioning"
ACTIVE_STATUS = "active"
DECOMMISSIONING_STATUS = "decommissioning"
DECOMMISSIONED_STATUS = "decommissioned"
L2_VLAN_POOL = "L2 network service vlan id"
L3_VLAN_POOL = "L3 network service vlan id"

# infrahubctl generator generate_network_services network_service_id="17fcb90f-9573-4ddd-2f2b-c51c8e7c9106" --branch main

# FIXME: Any way to have debug?
# FIXME: Any way to log something?


class ServiceBuilder:
    # TODO: Implement batch logic in the builder?
    def __init__(
        self,
        client: InfrahubClient,
        network_service: dict,
    ) -> None:
        # Save parameters
        self.client = client
        self.network_service = network_service

    async def allocate_vlan(self, ressource_pool_name: str) -> None:
        """Create a VLAN with ID coming from the pool provided and assign this VLAN to the service."""

        # Get resource pool
        resource_pool: CoreNumberPool = await self.client.get(
            kind="CoreNumberPool", name__value=ressource_pool_name
        )

        # Craft VLAN object
        # FIXME: Here we must put a placeholder name to create the vlan,
        # so then we can get a vlan ID from the resource pool
        # and then we can update the name
        vlan_data: dict = {
            "name": {"value": "PLACEHOLDER"},
            "vlan_id": resource_pool,
            "description": {"value": "VLAN dedicated to a Network Service"},
            "status": {"value": ACTIVE_STATUS},
            "role": {"value": "server"},
            "location": self.network_service["topology"]["node"]["location"]["node"],
            "network_service": self.network_service,
        }

        # Save vlan
        vlan_obj: InfraVLAN = await self.client.create(kind="InfraVLAN", data=vlan_data)
        # FIXME: Here I need to save a first time my vlan to get vlan_id generated
        await vlan_obj.save()

        # FIXME: Here somehow (guess it's because resource manager is involved ...)
        # vlan_obj.vlan_id.value => {'value': 2002}
        # thus is need to do `vlan_obj.vlan_id.value["value"]` to get vlan id .....
        # FIXME: That's the worst piece of code
        vlan_obj.name.value = f"{self.network_service["topology"]["node"]["location"]["node"]["shortname"]["value"].lower()}_{str(vlan_obj.vlan_id.value["value"])}"

        # FIXME: AAAAAAAAAAAHHHHH
        # {'message': "Expected value of type 'BigInt', found {value: 2007}.", 'locations': [{'line': 9, 'column': 24}]}
        vlan_obj.vlan_id.value = vlan_obj.vlan_id.value["value"]

        # Then save the vlan a second time ...
        await vlan_obj.save()

        # Query the actual network service object
        # FIXME: Here I need to query the network service
        self.network_service_obj = await self.client.get(
            kind=self.network_service["__typename"],
            id=self.network_service["id"],
        )

        # Attach service -> vlan
        self.network_service_obj.vlan = vlan_obj
        await self.network_service_obj.save()

    async def set_service_name_and_description(self, name_prefix: str) -> None:
        """Set a proper name and description for the service."""

        # Compute the name string
        service_name: str = f"{name_prefix}_server_{str(self.network_service_obj.vlan.get().vlan_id.value)}"  # FIXME: Here I need to .get() the vlan?
        service_description: str = f"Network service running on topology {str(self.network_service["topology"]["node"]["name"]["value"])}"

        # Save network service object
        self.network_service_obj.name.value = service_name
        self.network_service_obj.description.value = service_description

        await self.network_service_obj.save()

    async def build(
        self,
    ) -> None:
        # Move the status to active
        self.network_service_obj.status.value = ACTIVE_STATUS

        # We save that service for good
        await self.network_service_obj.save()


class NetworkServicesGenerator(InfrahubGenerator):
    async def activate_service(
        self,
        network_service: dict,
    ) -> bool:
        # Create a builder object
        builder: ServiceBuilder = ServiceBuilder(
            client=self.client, network_service=network_service
        )

        # Now we build service depending on the flavour we want
        if network_service["__typename"] == "TopologyLayer2NetworkService":  # FIXME
            await builder.allocate_vlan(ressource_pool_name=L2_VLAN_POOL)
            await builder.set_service_name_and_description(name_prefix="l2")
        else:
            print("we don't support this kind of NetworkService ...")
            # TODO: Proper return code ...
            return False

        # We have our builder set, now time to get the object built
        await builder.build()

        return True

    async def decommission_service(self, service: dict) -> bool:
        print(f"THIS SERVICE: {service["id"]} NEEDS TO BE DECOMMISSIONED")

    async def generate(self, data: dict) -> None:
        # Here we just get the id from the dict
        # TODO: support IndexError: list index out of range
        service_node: dict = data["TopologyNetworkService"]["edges"][0]["node"]

        # FIXME: Here I have a dict and not an actual object.
        # I have all the data I need and I don't want to query it again to have proper obj ...

        # If the status is "provisioning" then we do the provisioning
        if service_node["status"]["value"] == PROVISIONING_STATUS:
            await self.activate_service(service_node)
            # ... at the end the service will be moved to "active"
        # If the status is "decommissioning" then we do the decommissioning
        elif service_node["status"]["value"] == DECOMMISSIONING_STATUS:
            await self.decommission_service(service_node)
            # ... at the end the service will be moved to "decommissioned"
        elif service_node["status"]["value"] == ACTIVE_STATUS:
            print(f"{service_node["status"]["value"]} is ACTIVE => Nothing to do")
            pass
        # TODO: Cover all status or add default
