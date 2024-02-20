import logging
import uuid
import random
from collections import defaultdict
from ipaddress import IPv4Network
from typing import Dict, List

from infrahub_sdk import UUIDT, InfrahubClient, InfrahubNode, NodeStore

from utils import add_relationships, group_add_member, populate_local_store, upsert_object

# flake8: noqa
# pylint: skip-file

LOCATIONS = {
    # Name, Short-name, Type, Parent, Timezone
    ("North America", "nam", "region", None, None),
    ("United States", "us", "country",  "North America", None),
    ("Atlanta 01", "atl01", "site", "United States", "GMT-5" ),
    ("O'Hare 01", "ord01", "site", "United States", "GMT-6"),
    ("Europe", "eu", "region", None, None),
    ("Netherlands", "nl", "country", "Europe", "GMT+1"),
    ("Germany", "de", "country", "Europe", "GMT+1"),
    ("Amsterdam 09", "ams09", "site", "Netherlands", None),
    ("Frankfurt 02", "fra02", "site", "Germany", None),
}

MGMT_SERVERS = {
    # Name, Description, Type
    ("8.8.8.8", "Google-8.8.8.8", "Name"),
    ("8.8.4.4", "Google-8.8.4.4", "Name"),
    ("1.1.1.1", "Cloudflare-1.1.1.1", "Name"),
    ("time1.google.com", "Google time1", "NTP"),
    ("time.cloudflare.com", "Cloudflare time", "NTP"),
}

# We filter locations to include only those of type 'site'
site_locations = {name: (shortname, type, parent, timezone) for name, shortname, type, parent, timezone in LOCATIONS if type == "site"}

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

    for mgmt_server in MGMT_SERVERS:
        mgmt_server_name = mgmt_server[0]
        mgmt_server_desc = mgmt_server[1]
        mgmt_server_type = mgmt_server[2]
        mgmt_server_kind = f"Network{mgmt_server_type}Server"
        # --------------------------------------------------
        # Create Mgmt Servers
        # --------------------------------------------------
        data={
            "name": {"value": mgmt_server_name, "is_protected": True, "source": account_eng.id},
            "description": {"value": mgmt_server_desc, "is_protected": True, "source": account_eng.id},
            "status": {"value": ACTIVE_STATUS, "is_protected": True, "source": account_eng.id},
        }
        await upsert_object(
            client=client,
            log=log,
            branch=branch,
            object_name=mgmt_server_name,
            kind_name=mgmt_server_kind,
            data=data,
            store=store,
            retrived_on_failure=True
            )

    parent_to_children = {}
    for location in LOCATIONS:
        location_name = location[0]
        location_short = location[1]
        location_type = location[2]
        location_parent_name = location[3]
        location_timezone = location[4]

        location_description = f"{location_type.title()} {location_name.title()} ({location_short.upper()})"
        location_kind = f"Location{location_type.title()}"

        # --------------------------------------------------
        # Create Location
        # --------------------------------------------------
        mgmt_servers_obj = []
        data={
            "name": {"value": location_name, "is_protected": True, "source": account_crm.id},
            "description": {"value": location_description, "is_protected": True, "source": account_crm.id},
            "shortname": {"value": location_short, "is_protected": True, "source": account_crm.id},
            "timezone": {"value": location_timezone, "is_protected": True, "source": account_crm.id},
        }
        if not location_timezone:
            name_servers = [server[0] for server in MGMT_SERVERS if server[2] == "Name"]
            random_name_server = random.choice(name_servers)

            ntp_servers = [server[0] for server in MGMT_SERVERS if server[2] == "NTP"]
            random_ntp_server = random.choice(ntp_servers)

            time_server_obj = store.get(key=random_ntp_server, kind="NetworkNTPServer")
            name_server_obj = store.get(key=random_name_server, kind="NetworkNameServer")

            mgmt_servers_obj = [name_server_obj, time_server_obj]

        location_obj = await upsert_object(
            client=client,
            log=log,
            branch=branch,
            object_name=location_name,
            kind_name=location_kind,
            data=data,
            store=store,
            retrived_on_failure=True
            )

        await add_relationships(
            client=client,
            node_to_update=location_obj,
            relation_to_update="network_management_servers",
            related_nodes=mgmt_servers_obj,
            branch=branch,
            )
        for mgmt_server_obj in mgmt_servers_obj:
            log.info(f"- Add {mgmt_server_obj.name.value.title()} to {location_name.title()}")
        if location_parent_name:
            if location_parent_name not in parent_to_children:
                parent_to_children[location_parent_name] = []

            parent_to_children[location_parent_name].append(location_name)

    for parent, children in parent_to_children.items():
        parent_object = store.get(key=parent, kind=f"Location{[loc[2].title() for loc in LOCATIONS if loc[0] == parent][0]}")
        if parent_object:
            childs = []
            for child_name in children:
                child_kind = f"Location{[loc[2].title() for loc in LOCATIONS if loc[0] == child_name][0]}"
                child_object = store.get(key=child_name, kind=child_kind)
                if child_object:
                    childs.append(child_object)
            await add_relationships(
                client=client,
                node_to_update=parent_object,
                relation_to_update="children",
                related_nodes=childs,
                branch=branch,
            )
            log.info(f"- Add {', '.join(children).title()} to {parent.title()}")

    for location in LOCATIONS:
        location_name = location[0]
        location_short = location[1]
        location_type = location[2]
        location_parent_name = location[3]
        location_timezone = location[4]
        location_obj = store.get(key=location_name, kind=location_kind)

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
        location_id = location_obj.id
        for vlan in VLANS:
            role = vlan[1]
            vlan_name = f"{location_short.lower()}_{vlan[1]}"

            data={
                "name": {"value": vlan_name, "is_protected": True, "source": account_pop.id},
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

        mgmt_vlan = store.get(key=f"{location_short.lower()}_management", kind="InfraVLAN")

        # --------------------------------------------------
        # Create Prefix
        # --------------------------------------------------
        batch = await client.create_batch()
        # Create Supernet
        supernet_description = f"{location_short.lower()}-supernet-{IPv4Network(location_supernet).network_address}"
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
                prefix_description = f"{location_short.lower()}-ext-{IPv4Network(prefix).network_address}"
                prefix_role = "public"
            elif prefix.subnet_of(location_mgmt_pool):
                prefix_status = "active"
                prefix_description = f"{location_short.lower()}-mgmt-{IPv4Network(prefix).network_address}"
                prefix_role = "management"
                vlan_id = mgmt_vlan.id
            else:
                prefix_status = "reserved"
                prefix_description = f"{location_short.lower()}-int-{IPv4Network(prefix).network_address}"
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
