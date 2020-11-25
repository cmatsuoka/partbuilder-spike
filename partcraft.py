#!/usr/bin/env python3

import partbuilder
import yaml
import os

from partbuilder import PluginV1

def run(name, version, file_name):
    with open(file_name) as f:
        parts = yaml.safe_load(f)

    # TODO: change explicit base spec with plugin v1/v2 control?
    builder = partbuilder.PartBuilder(
        parts=parts,
        base="core18",
        this_project_name=name,
        this_project_grade="whatever",
        this_project_version=version,
        extensions_dir="/my/extensions/dir"
    )
    builder.prime()


@partbuilder.pre_step
def set_part_environment(config: partbuilder.BuildConfig):
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


@partbuilder.plugin(name="custom")
class CustomPlugin(PluginV1):
    @classmethod
    def schema(cls):
        schema = super().schema()
        schema["properties"]["message"] = {"type": "string"}
        schema["required"] = ["message"]
        return schema

    @classmethod
    def get_build_properties(cls):
        # Inform Snapcraft of the properties associated with building. If these
        # change in the YAML Snapcraft will consider the build step dirty.
        return ["message"]

    def __init__(self, name, options, config):
        super().__init__(name, options, config)
        self.build_packages.append("figlet")

    def build(self):
        super().build()
        command = ["figlet", self.options.message]
        self.run(command)


if __name__ == "__main__":
    run("mpg123", "1.26.3", "parts-mpg123.yaml")

