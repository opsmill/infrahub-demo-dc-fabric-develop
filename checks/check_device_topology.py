from collections import Counter, defaultdict

from infrahub_sdk.checks import InfrahubCheck


class InfrahubCheckDeviceTopology(InfrahubCheck):

    query = "check_device_topology"

    def validate(self, data):
        location_device_roles = defaultdict(lambda: defaultdict(list))
        location_expected_device_roles = defaultdict(lambda: defaultdict(dict))
        location_role_count = defaultdict(lambda: defaultdict(int))

        # Collect actual roles and device types in locations
        for device in data["data"]["InfraDevice"]["edges"]:
            role = device["node"]["role"]["value"]
            location = device["node"]["location"]["node"]["name"]["value"]
            device_type = device["node"]["device_type"]["node"]["name"]["value"]
            location_device_roles[location][role].append(device_type)
            location_role_count[location][role] += 1

        # Transform lists into counts of device types
        for location, roles in location_device_roles.items():
            for role, device_types in roles.items():
                location_device_roles[location][role] = Counter(device_types)

        # Collect expected roles and device types in locations
        for topology in data["data"]["TopologyTopology"]["edges"]:
            if not topology["node"]["location"]["node"]:
                continue
            location = topology["node"]["location"]["node"]["name"]["value"]
            for element in topology["node"]["elements"]["edges"]:
                role = element["node"]["device_role"]["value"]
                device_type = element["node"]["device_type"]["value"]  # Assuming this is how you get device type
                quantity = element["node"]["quantity"]["value"]
                location_expected_device_roles[location][role][device_type] = quantity

        # Compare expected roles and device types with actual ones
        for location, roles in location_expected_device_roles.items():
            for role, device_types in roles.items():
                # Check role quantity mismatch
                expected_role_quantity = sum(device_types.values())
                actual_role_quantity = location_role_count[location].get(role, 0)
                if expected_role_quantity != actual_role_quantity:
                    self.log_error(
                        message=f"{location} does not have expected total quantity of devices with role {role}",
                        object_id=role,
                        object_type="role",
                    )

                # Check device type quantity mismatch per role
                for device_type, quantity in device_types.items():
                    actual_quantity = location_device_roles.get(location, {}).get(role, {}).get(device_type, 0)
                    if quantity != actual_quantity:
                        self.log_error(
                            message=f"{location} does not have expected quantity of {device_type} devices with role {role}",
                            object_id=f"{role}_{device_type}",
                            object_type="role_device_type",
                        )
