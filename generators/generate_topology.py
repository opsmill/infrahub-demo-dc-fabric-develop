import logging
import uuid
from collections import defaultdict
from ipaddress import IPv4Network
from typing import Any, Dict, List, Optional

from infrahub_sdk import UUIDT, InfrahubClient, InfrahubNode, NodeStore

from create_location import LOCATION_SUPERNETS, LOCATION_MGMTS, EXTERNAL_NETWORKS
from utils import add_relationships, group_add_member, populate_local_store, upsert_object


# flake8: noqa
# pylint: skip-file

INTERFACE_MGMT_NAME = {
    "QFX5110-48S-S": "fxp0",
    "CCS-720DP-48S-2F": "Management1",
    "NCS-5501-SE": "MgmtEth0/RP0/CPU0/0",
    "ASR1002-HX": "GigabitEthernet0",
    "linux": "Eth0"
}

INTERFACE_LOOP_NAME = {
    "QFX5110-48S-S": "lo0",
    "CCS-720DP-48S-2F": "loopback 1",
    "NCS-5501-SE": "Loopback 1",
    "ASR1002-HX": "Loopback 1",
    "linux": "lo"
}

# TODO replace name by real name
DEVICES_INTERFACES = {
    # Device Type [ Interfaces ]
    "QFX5110-48S-S": [
        "Ethernet1",
        "Ethernet2",
        "Ethernet3",
        "Ethernet4",
        "Ethernet5",
        "Ethernet6",
        "Ethernet7",
        "Ethernet8",
        "Ethernet9",
        "Ethernet10",
        "Ethernet11",
        "Ethernet12",
    ],
    "CCS-720DP-48S-2F": [
        "Ethernet1",
        "Ethernet2",
        "Ethernet3",
        "Ethernet4",
        "Ethernet5",
        "Ethernet6",
        "Ethernet7",
        "Ethernet8",
        "Ethernet9",
        "Ethernet10",
        "Ethernet11",
        "Ethernet12",
    ],
    "NCS-5501-SE": [
        "Ethernet1",
        "Ethernet2",
        "Ethernet3",
        "Ethernet4",
        "Ethernet5",
        "Ethernet6",
        "Ethernet7",
        "Ethernet8",
        "Ethernet9",
        "Ethernet10",
        "Ethernet11",
        "Ethernet12",
    ],
    "ASR1002-HX": [
        "Ethernet1",
        "Ethernet2",
        "Ethernet3",
        "Ethernet4",
        "Ethernet5",
        "Ethernet6",
        "Ethernet7",
        "Ethernet8",
        "Ethernet9",
        "Ethernet10",
        "Ethernet11",
        "Ethernet12",
    ]
}

# 12 Interfaces to fit DEVICES_INTERFACES
INTERFACE_ROLES_MAPPING = {
    "spine": [
        "leaf",     # Ethernet1  - leaf1 (L3)
        "leaf",     # Ethernet2  - leaf2 (L3)
        "leaf",     # Ethernet3  - leaf3 (L3)
        "leaf",     # Ethernet4  - leaf4 (L3)
        "leaf",     # Ethernet5  - leaf5 (L3)
        "leaf",     # Ethernet6  - leaf6 (L3)
        "spare",    # Ethernet7
        "spare",    # Ethernet8
        "peer",     # Ethernet9  - spine (L2)
        "peer",     # Ethernet10 - spine (L2)
        "transit",  # Ethernet11
        "transit",  # Ethernet12
    ],
    "leaf": [
        "server",   # Ethernet1
        "server",   # Ethernet2
        "server",   # Ethernet3
        "server",   # Ethernet4
        "spare",    # Ethernet5
        "spare",    # Ethernet6
        "peer",     # Ethernet7  - leaf (L2)
        "peer",     # Ethernet8  - leaf (L2)
        "uplink",   # Ethernet9  - spine1 (L3)
        "uplink",   # Ethernet10 - spine2 (L3)
        "uplink",   # Ethernet11 - spine3 (L3)
        "uplink",   # Ethernet12 - spine4 (L3)
    ]
}

L3_ROLE_MAPPING = [
    "backbone",
    "transit",
    "peering",
    "uplink",
    "leaf"
]
L2_ROLE_MAPPING = [
    "peer",
    "server",
    "spare"
]

DEVICE_INTERFACE_OBJS: Dict[str, List[InfrahubNode]] = defaultdict(list)

# Mapping Dropdown Role and Status here
ACTIVE_STATUS = "active"
PROVISIONING_STATUS = "provisionning"
LOOPBACK_ROLE = "loopback"
MGMT_ROLE = "management"

store = NodeStore()

def get_interface_names(device_type: str, device_role: str, interface_role: str) -> Optional[List]:
    if device_type not in DEVICES_INTERFACES:
        return None
    if device_role not in INTERFACE_ROLES_MAPPING:
        return None

    # Mapping of roles to interface indices
    role_indices = [i for i, r in enumerate(INTERFACE_ROLES_MAPPING[device_role]) if r == interface_role]

    # Get the interface names based on the indices for the specific device model
    interface_names = [DEVICES_INTERFACES[device_type][i] for i in role_indices]

    return interface_names

async def upsert_interface(
        client: InfrahubClient,
        log: logging.Logger,
        branch: str,
        device_name: str,
        intf_name: str,
        data: Dict[str, Any],
        store: NodeStore
        )-> InfrahubNode:

    kind_name = data['kind_name']
    data.pop('kind_name')
    found_iface = None
    for tmp_iface in DEVICE_INTERFACE_OBJS[device_name]:
        if tmp_iface.name.value == intf_name:
            found_iface = tmp_iface
            break
    if found_iface is not None:
        data["id"] = found_iface.id

    interface_obj = await upsert_object(
        client=client,
        log=log,
        branch=branch,
        object_name=f"{device_name}-{intf_name}",
        kind_name=kind_name,
        data=data,
        store=store,
    )
    return interface_obj

async def upsert_ip_address(
        client: InfrahubClient,
        log: logging.Logger,
        branch: str,
        interface_obj: InfrahubNode,
        description: str,
        account_pop_id: str,
        address: str,
        store: NodeStore
        ) -> None:
    data = {
        "interface": {"id": interface_obj.id, "source": account_pop_id},
        "description": {"value": description},
        "address": {"value": address, "source": account_pop_id},
    }
    ip_obj = await upsert_object(
        client=client,
        log=log,
        branch=branch,
        object_name=f"{interface_obj.name.value}-address",
        kind_name="InfraIPAddress",
        data=data,
        store=store,
    )
    return ip_obj

def prepare_interface_data(
        device_obj_id: str,
        intf_name: str,
        intf_role: str,
        intf_status: str,
        description: str,
        account_pop_id: str,
        account_ops_id: str,
        speed: int = 1000,
        l2_mode: str = None,
        untagged_vlan: InfrahubNode = None
        ) -> Dict[str, Any]:
    data = {
        "device": {"id": device_obj_id, "is_protected": True},
        "name": {"value": intf_name, "source": account_pop_id, "is_protected": True},
        "description": {"value": description},
        "enabled": True,
        "status": {"value": intf_status, "owner": account_ops_id},
        "role": {"value": intf_role, "source": account_pop_id, "is_protected": True},
        "speed": speed,
        "kind_name": "InfraInterfaceL3" if intf_role in L3_ROLE_MAPPING or intf_role in (LOOPBACK_ROLE, MGMT_ROLE) else  "InfraInterfaceL2",
    }
    if l2_mode:
        data["l2_mode"] = l2_mode
        if untagged_vlan:
            data["untagged_vlan"] = untagged_vlan
    return data

async def generate_topology(client: InfrahubClient, log: logging.Logger, branch: str, topology: InfrahubNode) -> Optional[str]:
    topology_name = topology.name.value

    if not topology.location.peer:
        log.info(f"{topology_name} is not associated with a site.")
        return None

    location_id = topology.location.peer.id
    location_name = topology.location.peer.name.value

    log.info(f"{topology_name} is assigned to {location_name}.")



    # --------------------------------------------------
    # Preparating some variables for the Location
    # --------------------------------------------------
    account_pop = store.get(key="pop-builder", kind="CoreAccount")
    account_eng = store.get(key="Engineering Team", kind="CoreAccount")
    account_ops = store.get(key="Operation Team", kind="CoreAccount")

    # We are using DUFF Oragnization ASN as "internal" (AS64496)
    internal_as = store.get(key="AS64496", kind="InfraAutonomousSystem")

    locations_vlans = await client.filters(kind="InfraVLAN", location__name__value=location_name, branch=branch)
    populate_local_store(objects=locations_vlans, key_type="name", store=store)
    vlan_server = store.get(key=f"{location_name}_server", kind="InfraVLAN")

    # Using Prefix role to knwow which network to use. Role to Prefix should help avoid doing this
    locations_subnets = await client.filters(kind="InfraPrefix", location__name__value=location_name, branch=branch)
    location_external_net = []
    location_technical_net_pool = []
    location_loopback_net_pool = []
    location_mgmt_net_pool = []

    if not locations_subnets:
        # Will not be able to set the loopback, so we are skipping the device creation completely
        return None

    for prefix in locations_subnets:
        if prefix.role.value == "management":
            location_mgmt_net_pool.append(prefix.prefix.value)
        elif prefix.role.value == "technical":
            location_technical_net_pool.append(prefix.prefix.value)
        elif prefix.role.value == "loopback":
            location_loopback_net_pool.append(prefix.prefix.value)
        elif prefix.role.value == "public":
            location_external_net.append(prefix.prefix.value)

    # --------------------------------------------------
    # Generate the topology
    #   - Create Devices
    #   - Create Devices Interfaces
    #   - Add IP to external facing L3 Interfaces
    #   - Add Cable between Topology Elements
    # --------------------------------------------------
    # Generate the Devices From the topology

    loopback_address_pool = location_loopback_net_pool[0].hosts()
    mgmt_address_pool = location_mgmt_net_pool[0].hosts()
    location_external_net_pool_iter = iter(list(location_external_net[0].subnets(new_prefix=31)))
    topology_elements = await client.filters(kind="TopologyPhysicalElement", topology__ids=topology.id, populate_store=True, prefetch_relationships=True)

    for topology_element in topology_elements:
        if not topology_element.device_type:
            log.info(f"No device_type for {topology_element.name.value} - Ignored")
            continue
        device_type = await client.get(ids=topology_element.device_type.id, kind="InfraDeviceType")
        if not device_type.platform.id:
            log.info(f"No platform for {device_type.name.value} - Ignored")
            continue
        platform = await client.get(ids=device_type.platform.id, kind="InfraPlatform")
        platform_id = platform.id
        device_role_name = topology_element.device_role.value
        device_type_name = device_type.name.value

        for id in range(1, int(topology_element.quantity.value)+1):
            device_name = f"{location_name}-{topology_name}-{device_role_name}{id}"
            data={
                "name": {"value": device_name, "source": account_pop.id, "is_protected": True},
                "site": {"id": location_id, "source": account_pop.id, "is_protected": True},
                "status": {"value": ACTIVE_STATUS, "owner": account_ops.id},
                "type": {"value": device_type_name, "source": account_pop.id},
                "role": {"value": device_role_name, "source": account_pop.id, "is_protected": True, "owner": account_eng.id},
                "asn": {"id": internal_as.id, "source": account_pop.id, "is_protected": True, "owner": account_eng.id},
                "platform": {"id": platform_id, "source": account_pop.id, "is_protected": True}
            }
            device_obj = await upsert_object(
                client=client,
                log=log,
                branch=branch,
                object_name=device_name,
                kind_name="InfraDevice",
                data=data,
                store=store
                )

            # Add device to groups
            platform_group_name = f"{platform.name.value.lower().split(' ', 1)[0]}_devices"
            platform_group = store.get(key=platform_group_name, kind="CoreStandardGroup")
            await group_add_member(
                client=client,
                group=platform_group,
                members=[device_obj],
                branch=branch
                )
            log.info(f"- Add {device_name} to {platform_group_name} CoreStandardGroup")

            # FIXME  Interface name is not unique, upsert() is not good enough for indempotency. Need constraints
            DEVICE_INTERFACE_OBJS[device_name] = await client.filters(kind="InfraInterfaceL3", device__name__value=device_name, branch=branch)
            DEVICE_INTERFACE_OBJS[device_name] += await client.filters(kind="InfraInterfaceL2", device__name__value=device_name, branch=branch)

            # Loopback Interface
            loopback_name = INTERFACE_LOOP_NAME[device_type_name]
            loopback_description = f"Loopback: {loopback_name.lower().replace(' ', '')}.{device_name.lower()}"
            loopback_data = prepare_interface_data(
                device_obj_id=device_obj.id,
                intf_name=loopback_name,
                intf_role=LOOPBACK_ROLE,
                intf_status=ACTIVE_STATUS,
                description=loopback_description,
                account_pop_id=account_pop.id,
                account_ops_id=account_ops.id
                )
            loopback_obj = await upsert_interface(
                client=client,
                log=log,
                branch=branch,
                device_name=device_name,
                intf_name=loopback_name,
                data=loopback_data,
                store=store
                )
            ip_loop = f"{str(next(loopback_address_pool))}/32"
            await upsert_ip_address(
                client=client,
                log=log,
                branch=branch,
                interface_obj=loopback_obj,
                description=loopback_description,
                account_pop_id=account_pop.id,
                address=ip_loop,
                store=store
                )

            # Management Interface
            mgmt_name = INTERFACE_MGMT_NAME[device_type_name]
            mgmt_description = f"Mgmt: {mgmt_name.lower().replace(' ', '')}.{device_name.lower()}"
            mgmt_data = prepare_interface_data(
                device_obj_id=device_obj.id,
                intf_name=mgmt_name,
                intf_role=MGMT_ROLE,
                intf_status=ACTIVE_STATUS,
                description=mgmt_description,
                account_pop_id=account_pop.id,
                account_ops_id=account_eng.id
                )
            mgmt_obj = await upsert_interface(
                client=client,
                log=log,
                branch=branch,
                device_name=device_name,
                intf_name=mgmt_name,
                data=mgmt_data,
                store=store
                )
            ip_mgmt = f"{str(next(mgmt_address_pool))}/24"
            ip_mgmt_obj = await upsert_ip_address(
                client=client,
                log=log,
                branch=branch,
                interface_obj=mgmt_obj,
                description=mgmt_description,
                account_pop_id=account_pop.id,
                address=ip_mgmt,
                store=store
                )

            # Set Mgmt IP as Primary IP
            device_obj.primary_address = ip_mgmt_obj
            await device_obj.save()
            store.set(key="device_name", node=device_obj)
            log.info(f"- Set {ip_mgmt} as {device_name} Primary IP")

            if device_role_name.lower() not in ["spine", "leaf"]:
                continue

            for intf_idx, intf_name in enumerate(DEVICES_INTERFACES[device_type_name]):
                intf_role = INTERFACE_ROLES_MAPPING[device_role_name.lower()][intf_idx]
                interface_description = f"{intf_role.title()}: {intf_name.lower().replace(' ', '')}.{device_name.lower()}"

                # L3 Interfaces
                if intf_role in L3_ROLE_MAPPING:
                    interface_data = prepare_interface_data(
                        device_obj_id=device_obj.id,
                        intf_name=intf_name,
                        intf_role=intf_role,
                        intf_status=PROVISIONING_STATUS,
                        description=interface_description,
                        account_pop_id=account_pop.id,
                        account_ops_id=account_ops.id
                        )
                # L2 Interfaces
                elif intf_role in L2_ROLE_MAPPING:
                    interface_data = prepare_interface_data(
                        device_obj_id=device_obj.id,
                        intf_name=intf_name,
                        intf_role=intf_role,
                        intf_status=PROVISIONING_STATUS,
                        description=interface_description,
                        account_pop_id=account_pop.id,
                        account_ops_id=account_ops.id,
                        l2_mode="Access",
                        untagged_vlan=vlan_server
                    )
                interface_obj = await upsert_interface(
                    client=client,
                    log=log,
                    branch=branch,
                    device_name=device_name,
                    intf_name=intf_name,
                    data=interface_data,
                    store=store
                )

                # Creation IP for some L3 Interface
                if intf_role in ["upstream", "transit"]:
                    ico_hosts = list(next(location_external_net_pool_iter).hosts())
                    address = f"{str(ico_hosts[0])}/31"
                    # peer_address = f"{str(ico_hosts[1])}/31"
                    if not address:
                        continue
                    ip_mgmt = f"{str(next(mgmt_address_pool))}/24"
                    await upsert_ip_address(
                        client=client,
                        log=log,
                        branch=branch,
                        interface_obj=interface_obj,
                        description=interface_description,
                        account_pop_id=account_pop.id,
                        address=address,
                        store=store
                        )

    # Connect Spine <-> Leaf
    spine_quantity = 0
    leaf_quantity = 0
    spine_leaf_interfaces = {}
    leaf_uplink_interfaces = {}
    spine_peer_interfaces = {}
    leaf_peer_interfaces = {}
    for topology_element in topology_elements:
        if not topology_element.device_type:
            log.info(f"No device_type for {topology_element.name.value} - Ignored")
            continue
        device_type = await client.get(id=topology_element.device_type.id, kind="InfraDeviceType", populate_store=True)
        device_role_name = topology_element.device_role.value
        device_type_name = device_type.name.value

        if device_role_name == "spine":
            spine_quantity = topology_element.quantity.value
            spine_leaf_interfaces = get_interface_names(device_type=device_type_name, device_role="spine", interface_role="leaf")
            spine_peer_interfaces = get_interface_names(device_type=device_type_name, device_role="spine", interface_role="peer")
        elif device_role_name == "leaf":
            leaf_quantity = topology_element.quantity.value
            leaf_uplink_interfaces = get_interface_names(device_type=device_type_name, device_role="leaf", interface_role="uplink")
            leaf_peer_interfaces = get_interface_names(device_type=device_type_name, device_role="leaf", interface_role="peer")

    #   ---------- Cabling Logic    ----------
    #   odd number lf1 uplink port <-> sp1 odd number leaf port
    #   even number lf1 uplink port <-> sp2 odd number leaf port
    #   odd number lf2 uplink port <-> sp1 even number leaf port
    #   even number lf2 uplink port <-> sp2 even number leaf port
    #   odd number lf1 peer port <-> lf2 odd number peer port
    #   even number lf1 peer port <-> lf2 even number peer port

    # Cabling Spines <-> Leaf
    if not spine_leaf_interfaces or not leaf_uplink_interfaces:
        log.error("No 'uplink' interfaces found on leaf or no 'leaf' interfaces on spines")
        return None

    for leaf_idx in range(1, leaf_quantity + 1):
        if leaf_idx > len(spine_leaf_interfaces):
            log.error(f"The quantity of leaf requested ({leaf_quantity}) is superior to the number of interfaces flagged as 'leaf' ({len(spine_leaf_interfaces)})")
            break
        # Calculate the good interfaces based on the Cabling Logic above
        leaf_pair_num = (leaf_idx + 1) // 2
        if leaf_pair_num == 1:
            if len(spine_leaf_interfaces) < 2:
                continue
            spine_port = spine_leaf_interfaces[0] if leaf_idx % 2 != 0 else spine_leaf_interfaces[1]
        else:
            offset = (leaf_pair_num - 1) * 2
            if len(spine_leaf_interfaces) < offset + 1 :
                continue
            spine_port = spine_leaf_interfaces[offset] if leaf_idx % 2 != 0 else spine_leaf_interfaces[offset + 1]

        for spine_idx in range(1, spine_quantity + 1):
            if spine_idx > len(leaf_uplink_interfaces):
                log.error(f"The quantity of spines requested ({spine_quantity}) is superior to the number of interfaces flagged as 'uplink' ({len(leaf_uplink_interfaces)})")
                break

            spine_pair_num = (spine_idx + 1) // 2
            if spine_pair_num == 1:
                if len(leaf_uplink_interfaces) < 2:
                    continue
                uplink_port = leaf_uplink_interfaces[0] if spine_idx % 2 != 0 else leaf_uplink_interfaces[1]
            else:
                offset = (spine_pair_num - 1) * 2
                if len(leaf_uplink_interfaces) < offset + 1 :
                    continue
                if spine_idx % 2 != 0:
                    uplink_port = leaf_uplink_interfaces[offset]
                else:
                    uplink_port = leaf_uplink_interfaces[offset + 1]

            # Retrieve interfaces from store (as we create them above) #{location_name}-{topology_name}-{device_role_name}
            intf_spine_obj = store.get(kind="InfraInterfaceL3", key=f"{location_name}-{topology_name}-spine{spine_idx}-{spine_port}")
            intf_leaf_obj = store.get(kind="InfraInterfaceL3", key=f"{location_name}-{topology_name}-leaf{leaf_idx}-{uplink_port}")

            new_spine_intf_description = intf_spine_obj.description.value + f" to {intf_leaf_obj.description.value.split(':', 1)[1].strip()}"
            spine_ico_ip_description = intf_spine_obj.description.value
            new_leaf_intf_description = intf_leaf_obj.description.value + f" to {intf_spine_obj.description.value.split(':', 1)[1].strip()}"
            leaf_ico_ip_description = intf_leaf_obj.description.value

            interconnection = list(next(location_technical_net_pool).hosts())
            spine_ip = f"{str(interconnection[0])}/31"
            leaf_ip = f"{str(interconnection[1])}/31"
            await upsert_ip_address(
                        client=client,
                        log=log,
                        branch=branch,
                        interface_obj=intf_spine_obj,
                        description=spine_ico_ip_description,
                        account_pop_id=account_pop.id,
                        address=spine_ip,
                        store=store
                        )
            await upsert_ip_address(
                        client=client,
                        log=log,
                        branch=branch,
                        interface_obj=intf_leaf_obj,
                        description=leaf_ico_ip_description,
                        account_pop_id=account_pop.id,
                        address=leaf_ip,
                        store=store
                        )
            # Update Spine interface (description, endpoints, status)
            intf_spine_obj.description.value = new_spine_intf_description
            intf_spine_obj.status.value = ACTIVE_STATUS
            intf_spine_obj.connected_endpoint = intf_leaf_obj
            await intf_spine_obj.save()

            # Update Leaf interface (description, endpoints, status)
            intf_leaf_obj.description.value = new_leaf_intf_description
            intf_leaf_obj.status.value  = ACTIVE_STATUS
            intf_leaf_obj.connected_endpoint = intf_spine_obj
            await intf_leaf_obj.save()
            log.info(f"- Connected {location_name}-{topology_name}-leaf{leaf_idx}-{uplink_port} to {location_name}-{topology_name}-spine{spine_idx}-{spine_port}")

    # Cabling Spines <-> Spines & Leaf <-> Leaf
    if not spine_peer_interfaces or not leaf_peer_interfaces:
        log.error("No 'peer' interfaces found on Leaf or Spines")
        return None

    if leaf_quantity % 2 != 0 or spine_quantity % 2 != 0:
        log.error("The number of devices must be even to form pairs")
        return None

    for leaf_idx in range(1, leaf_quantity + 1, 2):
        leaf1_name = f"{location_name}-{topology_name}-leaf{leaf_idx}"
        leaf2_name = f"{location_name}-{topology_name}-leaf{leaf_idx + 1}"
        for leaf_peer_interface in leaf_peer_interfaces:
            intf_leaf1_obj = store.get(kind="InfraInterfaceL3", key=f"{leaf1_name}-{leaf_peer_interface}")
            intf_leaf2_obj = store.get(kind="InfraInterfaceL3", key=f"{leaf2_name}-{leaf_peer_interface}")

            new_leaf1_intf_description = intf_leaf1_obj.description.value + f" to {intf_leaf2_obj.description.value.split(':', 1)[1].strip()}"
            new_leaf2_intf_description = intf_leaf2_obj.description.value + f" to {intf_leaf1_obj.description.value.split(':', 1)[1].strip()}"

            # Update Leaf1 interface (description, endpoints, status)
            intf_leaf1_obj.description.value = new_leaf1_intf_description
            intf_leaf1_obj.status.value = ACTIVE_STATUS
            intf_leaf1_obj.connected_endpoint = intf_leaf2_obj
            await intf_leaf1_obj.save()
            # Update Leaf2 interface (description, endpoints, status)
            intf_leaf2_obj.description.value = new_leaf2_intf_description
            intf_leaf2_obj.status.value = ACTIVE_STATUS
            intf_leaf2_obj.connected_endpoint = intf_leaf1_obj
            await intf_leaf2_obj.save()

    for spine_idx in range(1, spine_quantity + 1, 2):
        spine1_name = f"{location_name}-{topology_name}-spine{spine_idx}"
        spine2_name = f"{location_name}-{topology_name}-spine{spine_idx + 1}"
        for spine_peer_interface in spine_peer_interfaces:
            intf_spine1_obj = store.get(kind="InfraInterfaceL3", key=f"{spine1_name}-{spine_peer_interface}")
            intf_spine2_obj = store.get(kind="InfraInterfaceL3", key=f"{spine2_name}-{spine_peer_interface}")

            new_spine1_intf_description = intf_spine1_obj.description.value + f" to {intf_spine2_obj.description.value.split(':', 1)[1].strip()}"
            new_spine2_intf_description = intf_spine2_obj.description.value + f" to {intf_spine1_obj.description.value.split(':', 1)[1].strip()}"

            # Update Spine1 interface (description, endpoints, status)
            intf_spine1_obj.description.value = new_spine1_intf_description
            intf_spine1_obj.status.value = ACTIVE_STATUS
            intf_spine1_obj.connected_endpoint = intf_spine2_obj
            await intf_spine1_obj.save()
            # Update Spine2 interface (description, endpoints, status)
            intf_spine2_obj.description.value = new_spine2_intf_description
            intf_spine2_obj.status.value = ACTIVE_STATUS
            intf_spine2_obj.connected_endpoint = intf_spine1_obj
            await intf_spine2_obj.save()

    #   ---------- iBGP Logic    ----------
    # Create iBGP Sessions within the Site
    # TODO

    #   ---------- Network Services    ----------
    # Create Network Services for the topology
    # TODO

    return location_name

# ---------------------------------------------------------------
# Use the `infrahubctl run` command line to execute this script
#
#   infrahubctl run models/infrastructure_edge.py
#
# ---------------------------------------------------------------
async def run(client: InfrahubClient, log: logging.Logger, branch: str, **kwargs) -> None:
    # ------------------------------------------
    # Retrieving objects from Infrahub
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

        prefixes=await client.all("InfraPrefix")
        populate_local_store(objects=prefixes, key_type="prefix", store=store)

        topologies=await client.all("TopologyTopology")
        populate_local_store(objects=topologies, key_type="name", store=store)

        # topology_elements=await client.all("TopologyGenericElement")
        # populate_local_store(objects=topology_elements, key_type="name", store=store)

        locations=await client.all("LocationGeneric", populate_store=True)
        populate_local_store(objects=locations, key_type="name", store=store)

    except Exception as e:
        log.error(f"Fail to populate due to {e}")
        exit(1)

    log.info("Adding a new Device Role (client) via the SDK")
    try:
        await client.schema.add_dropdown_option(
            kind="InfraDevice",
            attribute="role",
            option="client",
            color="#c5a3ff",
            description="Server & Client endpoints."
        )
    except Exception as e:
        log.debug(f"Fail to add Client dropdown option due to {e}")

    # ------------------------------------------
    # Create Topology
    # ------------------------------------------
    log.info("Generation Topology")
    batch = await client.create_batch()
    for topology in topologies:
        if not topology.location.peer:
            continue
        batch.add(
            task=generate_topology,
            topology=topology,
            client=client,
            branch=branch,
            log=log
            )

    async for _, response in batch.execute():
        log.debug(f"Topology {response} Creation Completed")
