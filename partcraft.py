#!/usr/bin/env python3

import partbuilder
import yaml
import os
from typing import Dict, List, Set

import partbuilder

def run(name, version, file_name):
    partbuilder.register_plugins({"customv2": CustomPluginV2})
    partbuilder.register_pre_step_callback(set_part_environment)

    with open(file_name) as f:
        parts = yaml.safe_load(f)

    # TODO: change explicit base spec with plugin v1/v2 control?
    lm = partbuilder.LifecycleManager(
        parts=parts,
        base="core20",
        this_project_name=name,
        this_project_grade="whatever",
        this_project_version=version,
        extensions_dir="/my/extensions/dir"
    )
    lm.prime()


def set_part_environment(config: partbuilder.PartData):
    # mimic the part environment set by snapcraft
    env = {
        "SNAPCRAFT_ARCH_TRIPLET": config.arch_triplet,
        "SNAPCRAFT_PARALLEL_BUILD_COUNT": str(config.parallel_build_count),
        "SNAPCRAFT_PROJECT_NAME": config.this_project_name,
        "SNAPCRAFT_PROJECT_VERSION": config.this_project_version,
        "SNAPCRAFT_PROJECT_DIR": config.work_dir,
        "SNAPCRAFT_PROJECT_GRADE": config.this_project_grade,
        "SNAPCRAFT_STAGE": config.stage_dir,
        "SNAPCRAFT_PRIME": config.prime_dir,
        "SNAPCRAFT_EXTENSIONS_DIR": config.extensions_dir,

	"SNAPCRAFT_PART_BUILD": config.part_build_dir,
        "SNAPCRAFT_PART_BUILD_WORK": config.part_build_dir,
        "SNAPCRAFT_PART_INSTALL": config.part_install_dir
    }

    for key, value in env.items():
        os.environ[key] = value


class CustomPluginV2(partbuilder.PluginV2):
    @classmethod
    def get_schema(cls):
        return {
            "$schema": "http://json-schema.org/draft-04/schema#",
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "message": {"type": "string"},
            },
        }

    def get_build_packages(self) -> Set[str]:
        return {"toilet", "toilet-fonts"}

    def get_build_snaps(self) -> Set[str]:
        return set()

    def get_build_environment(self) -> Dict[str, str]:
        return dict()

    def get_build_commands(self) -> List[str]:
        return ["toilet -f smblock --metal '{}'".format(self.options.message)]


if __name__ == "__main__":
    run("mpg123", "1.26.3", "parts-mpg123-v2.yaml")

