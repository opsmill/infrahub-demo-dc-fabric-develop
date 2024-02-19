#!/bin/bash

# Load infra-schema + infra-topology
poetry run infrahubctl schema load models

# Load infra-data
poetry run infrahubctl run generator/create_basic.py
poetry run infrahubctl run generator/create_location.py
poetry run infrahubctl run generator/create_topology.py
