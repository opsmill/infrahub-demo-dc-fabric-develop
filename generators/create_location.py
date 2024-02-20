import logging
import uuid
from collections import defaultdict
from ipaddress import IPv4Network
from typing import Dict, List

from infrahub_sdk import UUIDT, InfrahubClient, InfrahubNode, NodeStore

from utils import group_add_member, populate_local_store, upsert_object

# flake8: noqa
# pylint: skip-file

LOCATIONS = {
    # Name, Type, Parent
    ("north-america", "region", None),
    ("united states", "country",  "north-america"),
    ("atl", "site", "usa"),
    ("atl-rack1", "rack", "atl"),
    ("ord", "site", "usa"),
    ("europe", "region", None),
    ("netherlands", "country", "europe"),
    ("germany", "country", "europe"),
    ("ams", "site", "europe"),
    ("fra", "site", "europe"),
}

# We filter locations to include only those of type 'site'
site_locations = {name: (type, parent) for name, type, parent in LOCATIONS if type == "site"}

# We assigned a /16 per Location for "data" (257 Locations possibles)
INTERNAL_POOL = IPv4Network("10.0.0.0/8").subnets(new_prefix=16)
LOCATION_SUPERNETS = {location: next(INTERNAL_POOL) for location in site_locations}

# We assigned a /24 per Location for "management" (257 Locations possibles)
MANAGEMENT_POOL = IPv4Network("172.16.0.0/16").subnets(new_prefix=24)
LOCATION_MGMTS = {location: next(MANAGEMENT_POOL) for location in site_locations}

# Using RFC5735 TEST-NETs as external networks
EXTERNAL_NETWORKS = [
    IPv4Network("203.0.113.0/24"),
    IPv4Network("192.0.2.0/24"),
    IPv4Network("198.51.100.0/24")
]
# We assigned one /28 per Location (48 Location possibles)
NETWORKS_POOL_EXTERNAL = [subnet for network in EXTERNAL_NETWORKS for subnet in network.subnets(new_prefix=28)]
NETWORKS_POOL_ITER = iter(NETWORKS_POOL_EXTERNAL)
LOCATION_EXTERNAL_NETS = {location: next(NETWORKS_POOL_ITER) for location in site_locations}

VLANS = (
    ("200", "server"),
    ("400", "management"),
)

# Mapping Dropdown Role and Status here
ACTIVE_STATUS = "active"

store = NodeStore()

async def create_location(client: InfrahubClient, log: logging.Logger, branch: str):
    # --------------------------------------------------
    # Preparating some variables for the Location
    # --------------------------------------------------
    account_pop = store.get(key="pop-builder", kind="CoreAccount")
    account_crm = store.get(key="CRM Synchronization", kind="CoreAccount")
    account_eng = store.get(key="Engineering Team", kind="CoreAccount")
    account_ops = store.get(key="Operation Team", kind="CoreAccount")

    orga_duff = store.get(key="Duff", kind="CoreOrganization")

    for location in LOCATIONS:
        location_name = location[0]
        location_type = location[1]

        location_description = f"{location_type.title()} {location_name.upper()}"
        location_kind = f"Location{location_type.title()}"

        # --------------------------------------------------
        # Create Location
        # --------------------------------------------------
        data={
            "name": {"value": location_name, "is_protected": True, "source": account_crm.id},
            "description": {"value": location_description},
        }
        await upsert_object(
            client=client,
            log=log,
            branch=branch,
            object_name=location_name,
            kind_name=location_kind,
            data=data,
            store=store,
            retrived_on_failure=True
            )

    for location in LOCATIONS:
        location_name = location[0]
        location_type = location[1]
        location_parent_name = location[2]

        location_description = f"{location_type.title()} {location_name.upper()}"
        location_kind = f"Location{location_type.title()}"

        # Set the parent
        if location_parent_name:
            # Find the parent in the LOCATIONS set and get its type
            for loc in LOCATIONS:
                if loc[0] == location_parent_name:
                    parent_kind = f"Location{loc[1].title()}"
                    break
            location_object = store.get(key=location_name, kind=location_kind)
            parent_object = store.get(key=location_parent_name, kind=parent_kind)
            # if parent_object:
            #     location_object.parent = parent_object
            #     await location_object.save()
            log.info(f"- Add {location_name} to {location_parent_name}")

        # if it's not a site, we don't create anything else
        if location_type != "site":
            continue

        # We cut the prefixes attribued to the Location
        location_supernet = LOCATION_SUPERNETS[location_name]
        location_loopback_pool = list(location_supernet.subnets(new_prefix=24))[-1]
        location_p2p_pool = list(location_supernet.subnets(new_prefix=24))[-2]

        location_mgmt_pool = LOCATION_MGMTS[location_name]
        # mgmt_address_pool = location_mgmt.hosts()

        location_external_net = LOCATION_EXTERNAL_NETS[location_name]
        location_prefixes = [
            location_external_net,
            location_loopback_pool,
            location_p2p_pool,
            location_mgmt_pool
            ]
        # --------------------------------------------------
        # Create VLANs
        # --------------------------------------------------
        batch = await client.create_batch()
        location_id = location_object.id
        for vlan in VLANS:
            role = vlan[1]
            vlan_name = f"{location_name}_{vlan[1]}"

            data={
                "name": {"value": f"{location_name}_{vlan[1]}", "is_protected": True, "source": account_pop.id},
                "vlan_id": {"value": int(vlan[0]), "is_protected": True, "owner": account_eng.id, "source": account_pop.id},
                "description": {"value": f"{location_name.upper()} {vlan[1].title()} VLAN" },
                "status": {"value": ACTIVE_STATUS, "owner": account_ops.id},
                "role": {"value": role, "source": account_pop.id, "is_protected": True, "owner": account_eng.id},
                "location": {"id": location_id},
            }
            await upsert_object(
                client=client,
                log=log,
                branch=branch,
                object_name=vlan_name,
                kind_name="InfraVLAN",
                data=data,
                store=store,
                batch=batch
                )
        async for node, _ in batch.execute():
            log.info(f"- Created {node._schema.kind} - {node.name.value}")

        mgmt_vlan= store.get(key=f"{location_name}_management", kind="InfraVLAN")

        # --------------------------------------------------
        # Create Prefix
        # --------------------------------------------------
        batch = await client.create_batch()
        # Create Supernet
        supernet_description = f"{location_name.upper()}-supernet-{IPv4Network(location_supernet).network_address}"
        data = {
            "prefix":  {"value": location_supernet },
            "description": {"value": supernet_description},
            "organization": {"id": orga_duff.id },
            "location": {"id": location_id },
            "status": {"value": "active"},
            "role": {"value": "supernet"},
        }
        prefix_obj = await upsert_object(
            client=client,
            log=log,
            branch=branch,
            object_name=location_supernet,
            kind_name="InfraPrefix",
            data=data,
            store=store,
            batch=batch
        )
        # Create /24 specifics subnets Pool
        for prefix in location_prefixes:
            vlan_id = None
            if any(prefix.subnet_of(external_net) for external_net in EXTERNAL_NETWORKS):
                prefix_status = "active"
                prefix_description = f"{location_name.upper()}-ext-{IPv4Network(prefix).network_address}"
                prefix_role = "public"
            elif prefix.subnet_of(location_mgmt_pool):
                prefix_status = "active"
                prefix_description = f"{location_name.upper()}-mgmt-{IPv4Network(prefix).network_address}"
                prefix_role = "management"
                vlan_id = mgmt_vlan.id
            else:
                prefix_status = "reserved"
                prefix_description = f"{location_name.upper()}-int-{IPv4Network(prefix).network_address}"
                if prefix.subnet_of(location_loopback_pool):
                    prefix_role = "loopback"
                else:
                    prefix_role = "technical"
            data = {
                "prefix":  {"value": prefix },
                "description": {"value": prefix_description},
                "organization": {"id": orga_duff.id },
                "location": {"id": location_id },
                "status": {"value": prefix_status},
                "role": {"value": prefix_role},
                "vlan": {"id": vlan_id},
            }
            prefix_obj = await upsert_object(
                client=client,
                log=log,
                branch=branch,
                object_name=prefix,
                kind_name="InfraPrefix",
                data=data,
                store=store,
                batch=batch
                )
        async for node, _ in batch.execute():
            log.info(f"- Created {node._schema.kind} - {node.prefix.value}")

# ---------------------------------------------------------------
# Use the `infrahubctl run` command line to execute this script
#
#   infrahubctl run models/infrastructure_edge.py
#
# ---------------------------------------------------------------
async def run(client: InfrahubClient, log: logging.Logger, branch: str, **kwargs) -> None:

    # ------------------------------------------
    # Create Sites
    # ------------------------------------------
    log.info("Retrieving objects from Infrahub")
    try:
        accounts=await client.all("CoreAccount")
        populate_local_store(objects=accounts, key_type="name", store=store)
        organizations=await client.all("CoreOrganization")
        populate_local_store(objects=organizations, key_type="name", store=store)
        autonomous_systems=await client.all("InfraAutonomousSystem")
        populate_local_store(objects=autonomous_systems, key_type="name", store=store)
        platforms=await client.all("InfraPlatform")
        populate_local_store(objects=platforms, key_type="name", store=store)
        groups=await client.all("CoreStandardGroup")
        populate_local_store(objects=groups, key_type="name", store=store)
        device_types=await client.all("InfraDeviceType")
        populate_local_store(objects=device_types, key_type="name", store=store)
        devices=await client.all("InfraDevice")
        populate_local_store(objects=devices, key_type="name", store=store)
        topologies=await client.all("TopologyTopology")
        populate_local_store(objects=topologies, key_type="name", store=store)

    except Exception as e:
        log.info(f"Fail to populate due to {e}")
        exit(1)

    log.info("Generation Location")
    await create_location(client=client, branch=branch, log=log)
