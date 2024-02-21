from collections import Counter, defaultdict

from infrahub_sdk.checks import InfrahubCheck


class InfrahubCheckDeviceTopology(InfrahubCheck):

    query = "check_device_topology"

    # def validate(self, data):
    #     location_device_roles = defaultdict(lambda: defaultdict(list))
    #     location_expected_device_roles = defaultdict(lambda: defaultdict(dict))
    #     location_role_count = defaultdict(lambda: defaultdict(int))

    #     # Collect actual roles and device types in locations
    #     for device in data["data"]["InfraDevice"]["edges"]:
    #         role = device["node"]["role"]["value"]
    #         location = device["node"]["location"]["node"]["name"]["value"]
    #         device_type = device["node"]["device_type"]["node"]["name"]["value"]
    #         location_device_roles[location][role].append(device_type)
    #         location_role_count[location][role] += 1

    #     # Transform lists into counts of device types
    #     for location, roles in location_device_roles.items():
    #         for role, device_types in roles.items():
    #             location_device_roles[location][role] = Counter(device_types)

    #     # Collect expected roles and device types in locations
    #     for topology in data["data"]["TopologyTopology"]["edges"]:
    #         if not topology["node"]["location"]["node"]:
    #             continue
    #         location = topology["node"]["location"]["node"]["name"]["value"]
    #         for element in topology["node"]["elements"]["edges"]:
    #             role = element["node"]["device_role"]["value"]
    #             device_type = element["node"]["device_type"]["node"]["name"]["value"]
    #             quantity = element["node"]["quantity"]["value"]
    #             location_expected_device_roles[location][role][device_type] = quantity

    #     # Compare expected roles and device types with actual ones
    #     for location, roles in location_expected_device_roles.items():
    #         for role, device_types in roles.items():
    #             # Check role quantity mismatch
    #             expected_role_quantity = sum(device_types.values())
    #             actual_role_quantity = location_role_count[location].get(role, 0)
    #             if expected_role_quantity != actual_role_quantity:
    #                 self.log_error(
    #                     message=f"{location} does not have expected total quantity of devices with role {role}",
    #                     object_id=role,
    #                     object_type="role",
    #                 )

    #             # Check device type quantity mismatch per role
    #             for device_type, quantity in device_types.items():
    #                 actual_quantity = location_device_roles.get(location, {}).get(role, {}).get(device_type, 0)
    #                 if quantity != actual_quantity:
                        # self.log_error(
                        #     message=f"{location} does not have expected quantity of {device_type} devices with role {role}",
                        #     object_id=f"{role}_{device_type}",
                        #     object_type="role_device_type",
                        # )
    def validate(self, data):
        # Extract Topology and Group data
        topologies = data["data"]["TopologyTopology"]["edges"]
        groups = data["data"]["CoreStandardGroup"]["edges"]
        group_devices = {group["node"]["name"]["value"]: {edge["node"]["id"] for edge in group["node"]["members"]["edges"] if edge["node"]} for group in groups}
        device_map = {edge["node"]["id"]: edge["node"] for edge in data["data"]["InfraDevice"]["edges"]}

        for topology_edge in topologies:
            topology_node = topology_edge["node"]
            topology_name = topology_node["location"]["node"]["name"]["value"] + "_topology"
            topology_elements = topology_node["elements"]["edges"]

            if topology_name in group_devices:
                group_device_ids = group_devices[topology_name]

                expected_role_device_counts = {}

                # Collect expected role and device types from topology
                for element_edge in topology_elements:
                    element_node = element_edge["node"]
                    role = element_node["device_role"]["value"]
                    device_type = element_node["device_type"]["node"]["name"]["value"]
                    quantity = element_node["quantity"]["value"]

                    if role not in expected_role_device_counts:
                        expected_role_device_counts[role] = {}
                    expected_role_device_counts[role][device_type] = expected_role_device_counts[role].get(device_type, 0) + quantity

                    if quantity % 2 != 0:
                        self.log_error(
                            message=f"{topology_name} has an odd number of devices for role {role}",
                            object_id=f"{role}",
                            object_type="role_count"
                        )

                # Validate actual devices in group against expected role/device type counts
                actual_role_device_counts = {}
                for device_id in group_device_ids:
                    if device_id in device_map:
                        device = device_map[device_id]
                        role = device["role"]["value"]
                        device_type = device["device_type"]["node"]["name"]["value"]

                        if role not in actual_role_device_counts:
                            actual_role_device_counts[role] = {}
                        actual_role_device_counts[role][device_type] = actual_role_device_counts[role].get(device_type, 0) + 1

                # Compare expected vs actual
                for role, device_types in expected_role_device_counts.items():
                    for device_type, expected_count in device_types.items():
                        actual_count = actual_role_device_counts.get(role, {}).get(device_type, 0)
                        if actual_count != expected_count:
                            self.log_error(
                                message=f"{topology_name} does not have expected quantity of {device_type} devices with role {role}. Expected: {expected_count}, Actual: {actual_count}",
                                object_id=f"{role}_{device_type}",
                                object_type="role_device_type"
                            )
