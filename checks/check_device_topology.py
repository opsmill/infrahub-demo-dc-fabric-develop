from collections import Counter, defaultdict

from infrahub_sdk.checks import InfrahubCheck


class InfrahubCheckDeviceTopology(InfrahubCheck):

    query = "check_device_topology"

    def validate(self):

        site_device_roles = defaultdict(list)
        site_expected_device_roles = defaultdict(dict) 

        for device in self.data["data"]["InfraDevice"]["edges"]:
            role = device["node"]["role"]["value"]
            site = device["node"]["site"]["node"]["name"]["value"]
            site_device_roles[site].append(role)

        for site in site_device_roles.keys(): 
            site_device_roles[site] = Counter(site_device_roles[site])

        for topology in self.data["data"]["TopologyTopology"]["edges"]:
            if not topology["node"]["location"]["node"]:
                continue
            site = topology["node"]["location"]["node"]["name"]["value"]
            for element in topology["node"]["elements"]["edges"]:
                role = element["node"]["device_role"]["value"]
                quantity = element["node"]["quantity"]["value"]
                site_expect_device_roles[site][role] = quantity
                
        for site, roles in site_expected_device_roles.items():
            for role, quantity in roles.items():
                if quantity != site_device_roles.get(site, {}).get(role, 0):
                    self.log_error(
                        message=f"{site} does not have expected amount of devices with role {role}",
                        object_id=role,
                        object_type="role",
                    )
