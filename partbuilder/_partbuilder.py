# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2017-2018 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from collections import ChainMap
import logging
import platform
import os
from typing import TYPE_CHECKING, cast, Type, Union, Dict, List, Set, Any  # noqa: F401

from partbuilder import lifecycle
from partbuilder._schema import Validator
from partbuilder import steps, states
from partbuilder import plugins
from partbuilder import elf, pluginhandler, repo
from partbuilder.pluginhandler._part_environment import (
    get_part_directory_environment,
)
from ._env import build_env, build_env_for_stage, runtime_env
from . import errors, grammar_processing

from partbuilder.pluginhandler._plugin_loader import _custom_plugins

logger = logging.getLogger(__name__)


_ARCH_TRANSLATIONS = {
    "aarch64": {
        "kernel": "arm64",
        "deb": "arm64",
        "uts_machine": "aarch64",
        "cross-compiler-prefix": "aarch64-linux-gnu-",
        "cross-build-packages": ["gcc-aarch64-linux-gnu", "libc6-dev-arm64-cross"],
        "triplet": "aarch64-linux-gnu",
        "core-dynamic-linker": "lib/ld-linux-aarch64.so.1",
    },
    "armv7l": {
        "kernel": "arm",
        "deb": "armhf",
        "uts_machine": "arm",
        "cross-compiler-prefix": "arm-linux-gnueabihf-",
        "cross-build-packages": ["gcc-arm-linux-gnueabihf", "libc6-dev-armhf-cross"],
        "triplet": "arm-linux-gnueabihf",
        "core-dynamic-linker": "lib/ld-linux-armhf.so.3",
    },
    "i686": {
        "kernel": "x86",
        "deb": "i386",
        "uts_machine": "i686",
        "triplet": "i386-linux-gnu",
    },
    "ppc": {
        "kernel": "powerpc",
        "deb": "powerpc",
        "uts_machine": "powerpc",
        "cross-compiler-prefix": "powerpc-linux-gnu-",
        "cross-build-packages": ["gcc-powerpc-linux-gnu", "libc6-dev-powerpc-cross"],
        "triplet": "powerpc-linux-gnu",
    },
    "ppc64le": {
        "kernel": "powerpc",
        "deb": "ppc64el",
        "uts_machine": "ppc64el",
        "cross-compiler-prefix": "powerpc64le-linux-gnu-",
        "cross-build-packages": [
            "gcc-powerpc64le-linux-gnu",
            "libc6-dev-ppc64el-cross",
        ],
        "triplet": "powerpc64le-linux-gnu",
        "core-dynamic-linker": "lib64/ld64.so.2",
    },
    "riscv64": {
        "kernel": "riscv64",
        "deb": "riscv64",
        "uts_machine": "riscv64",
        "cross-compiler-prefix": "riscv64-linux-gnu-",
        "cross-build-packages": ["gcc-riscv64-linux-gnu", "libc6-dev-riscv64-cross"],
        "triplet": "riscv64-linux-gnu",
        "core-dynamic-linker": "lib/ld-linux-riscv64-lp64d.so.1",
    },
    "s390x": {
        "kernel": "s390",
        "deb": "s390x",
        "uts_machine": "s390x",
        "cross-compiler-prefix": "s390x-linux-gnu-",
        "cross-build-packages": ["gcc-s390x-linux-gnu", "libc6-dev-s390x-cross"],
        "triplet": "s390x-linux-gnu",
        "core-dynamic-linker": "lib/ld64.so.1",
    },
    "x86_64": {
        "kernel": "x86",
        "deb": "amd64",
        "uts_machine": "x86_64",
        "triplet": "x86_64-linux-gnu",
        "core-dynamic-linker": "lib64/ld-linux-x86-64.so.2",
    },
}


_pre_hooks = []
_post_hooks = []


class PartData:
    def __init__(
        self, *,
        work_dir: str = "",
        target_arch=None,
        base: str = None,        # obtain this information internally
        parallel_build_count: int = 1,
        local_plugins_dir: str = "",
        **xargs
    ):
        self._set_machine(target_arch)

        self.build_base = base
        self._parallel_build_count = parallel_build_count
        self._local_plugins_dir = local_plugins_dir

        self.part = ""   # part name to be filled before calling the hook
        self.step = ""   # step name to be filled before calling the hook

        if work_dir == "":
            work_dir = os.getcwd()

        self.work_dir = work_dir
        self.parts_dir = os.path.join(work_dir, "parts")
        self.stage_dir = os.path.join(work_dir, "stage")
        self.prime_dir = os.path.join(work_dir, "prime")

        for key, value in xargs.items():
            setattr(self, key, value)

    @property
    def arch_triplet(self) -> str:
        return self.__machine_info["triplet"]

    @property
    def is_cross_compiling(self) -> bool:
        return self.__target_machine != self.__platform_arch

    @property
    def parallel_build_count(self) -> int:
        return self._parallel_build_count

    @property
    def local_plugins_dir(self) -> str:
        return self._local_plugins_dir

    @property
    def deb_arch(self) -> str:
        return self.__machine_info["deb"]

    def _set_machine(self, target_arch):
        self.__platform_arch = _get_platform_architecture()
        self.__target_arch = target_arch
        if not target_arch:
            self.__target_machine = self.__platform_arch
        else:
            self.__target_machine = _find_machine(target_arch)
            logger.info("Setting target machine to {!r}".format(target_arch))
        self.__machine_info = _ARCH_TRANSLATIONS[self.__target_machine]


class LifecycleManager:
    # TODO: also specify part environment replacements
    def __init__(
        self, *,
        parts: Dict[str, Any],
        package_repositories: List[str] = [],
        build_packages: List[str] = [],

        # PartData parameters
        **kwargs

    ):
        self._parts = parts
        self._soname_cache = elf.SonameCache()
        self._parts_data = parts.get("parts", {})

        self._config = PartData(**kwargs)

        # FIXME:SPIKE: deal with managed host
        self._is_managed_host = False

        self._package_repositories = package_repositories
        self._build_packages = build_packages

        self._validator = Validator(parts)
        self._validator.validate()

        self.all_parts = []
        self._part_names = []
        self.after_requests = {}

        self._process_parts()

    @property
    def part_names(self):
        return self._part_names

    @property
    def additional_build_packages(self):
        packages = self._build_packages
        if self._is_cross_compiling:
            packages.extend(self.__machine_info.get("cross-build-packages", []))
        return packages

    def clean(self):
        lifecycle.execute(steps.CLEAN, self, _pre_hooks, _post_hooks)

    def pull(self):
        lifecycle.execute(steps.PULL, self, _pre_hooks, _post_hooks)

    def build(self):
        lifecycle.execute(steps.BUILD, self, _pre_hooks, _post_hooks)

    def stage(self):
        lifecycle.execute(steps.STAGE, self, _pre_hooks, _post_hooks)

    def prime(self):
        lifecycle.execute(steps.PRIME, self, _pre_hooks, _post_hooks)

    def _process_parts(self):
        for part_name in self._parts_data:
            self._part_names.append(part_name)
            properties = self._parts_data[part_name] or {}

            plugin_name = properties.get("plugin")

            if "after" in properties:
                self.after_requests[part_name] = properties.pop("after")

            if "filesets" in properties:
                del properties["filesets"]

            self.load_part(part_name, plugin_name, properties)

        self._compute_dependencies()
        self.all_parts = self._sort_parts()

    def _compute_dependencies(self):
        """Gather the lists of dependencies and adds to all_parts."""

        for part in self.all_parts:
            dep_names = self.after_requests.get(part.name, [])
            for dep_name in dep_names:
                dep = self.get_part(dep_name)
                if not dep:
                    raise errors.SnapcraftAfterPartMissingError(part.name, dep_name)

                part.deps.append(dep)

    def _sort_parts(self):
        """Performs an inneficient but easy to follow sorting of parts."""
        sorted_parts = []

        # We want to process parts in a consistent order between runs. The
        # simplest way to do this is to sort them by name.
        self.all_parts = sorted(
            self.all_parts, key=lambda part: part.name, reverse=True
        )

        while self.all_parts:
            top_part = None
            for part in self.all_parts:
                mentioned = False
                for other in self.all_parts:
                    if part in other.deps:
                        mentioned = True
                        break
                if not mentioned:
                    top_part = part
                    break
            if not top_part:
                raise errors.SnapcraftLogicError(
                    "circular dependency chain found in parts definition"
                )
            sorted_parts = [top_part] + sorted_parts
            self.all_parts.remove(top_part)

        return sorted_parts

    def get_dependencies(
        self, part_name: str, *, recursive: bool = False
    ) -> Set[pluginhandler.PluginHandler]:
        """Returns a set of all the parts upon which part_name depends."""

        dependency_names = set(self.after_requests.get(part_name, []))
        dependencies = {p for p in self.all_parts if p.name in dependency_names}

        if recursive:
            # No need to worry about infinite recursion due to circular
            # dependencies since the YAML validation won't allow it.
            for dependency_name in dependency_names:
                dependencies |= self.get_dependencies(
                    dependency_name, recursive=recursive
                )

        return dependencies

    def get_reverse_dependencies(
        self, part_name: str, *, recursive: bool = False
    ) -> Set[pluginhandler.PluginHandler]:
        """Returns a set of all the parts that depend upon part_name."""

        reverse_dependency_names = set()
        for part, dependencies in self.after_requests.items():
            if part_name in dependencies:
                reverse_dependency_names.add(part)

        reverse_dependencies = {
            p for p in self.all_parts if p.name in reverse_dependency_names
        }

        if recursive:
            # No need to worry about infinite recursion due to circular
            # dependencies since the YAML validation won't allow it.
            for reverse_dependency_name in reverse_dependency_names:
                reverse_dependencies |= self.get_reverse_dependencies(
                    reverse_dependency_name, recursive=recursive
                )

        return reverse_dependencies

    def get_part(self, part_name):
        for part in self.all_parts:
            if part.name == part_name:
                return part

        return None

    def clean_part(self, part_name, staged_state, primed_state, step):
        part = self.get_part(part_name)
        part.clean(staged_state, primed_state, step)

    def validate(self, part_names):
        for part_name in part_names:
            if part_name not in self._part_names:
                raise errors.SnapcraftEnvironmentError(
                    f"The part named {part_name!r} is not defined"
                )

    def load_part(self, part_name, plugin_name, part_properties):
        plugin = pluginhandler.load_plugin(
            plugin_name=plugin_name,
            part_name=part_name,
            properties=part_properties,
            config=self._config,
            part_schema=self._validator.part_schema,
            definitions_schema=self._validator.definitions_schema,
        )

        logger.debug(
            "Setting up part {!r} with plugin {!r} and "
            "properties {!r}.".format(part_name, plugin_name, part_properties)
        )

        stage_packages_repo = repo.Repo

        grammar_processor = grammar_processing.PartGrammarProcessor(
            plugin=plugin,
            properties=part_properties,
            config=self,
            repo=stage_packages_repo,
        )

        part = pluginhandler.PluginHandler(
            plugin=plugin,
            part_properties=part_properties,
            config=self._config,
            builder=self,
            part_schema=self._validator.part_schema,
            definitions_schema=self._validator.definitions_schema,
            stage_packages_repo=stage_packages_repo,
            grammar_processor=grammar_processor,
            soname_cache=self._soname_cache,
        )

        self.all_parts.append(part)

        return part

    def build_env_for_part(self, part, root_part=True) -> List[str]:
        """Return a build env of all the part's dependencies."""

        env = []  # type: List[str]
        stagedir = self._config.stage_dir

        if root_part:
            # this has to come before any {}/usr/bin
            env += part.env(part.part_install_dir)
            env += runtime_env(part.part_install_dir, self._config.arch_triplet)
            env += runtime_env(stagedir, self._config.arch_triplet)
            env += build_env(
                part.part_install_dir,
                self._config.arch_triplet,
            )
            env += build_env_for_stage(
                stagedir, self._config.arch_triplet
            )

            part_env = get_part_directory_environment(part)

            for variable, value in part_env.items():
                env.append('{}="{}"'.format(variable, value))

            # Finally, add the declared environment from the part.
            # This is done only for the "root" part.
            env += part.build_environment
        else:
            env += part.env(stagedir)
            env += runtime_env(stagedir, self._config.arch_triplet)

        for dep_part in part.deps:
            env += dep_part.env(stagedir)
            env += self.build_env_for_part(dep_part, root_part=False)

        # LP: #1767625
        # Remove duplicates from using the same plugin in dependent parts.
        seen = set()  # type: Set[str]
        deduped_env = list()  # type: List[str]
        for e in env:
            if e not in seen:
                deduped_env.append(e)
                seen.add(e)

        return deduped_env

    def install_package_repositories(self) -> None:
        package_repos = self._package_repositories
        if not package_repos:
            return

        # Install pre-requisite packages for apt-key, if not installed.
        repo.Repo.install_build_packages(package_names=["gnupg", "dirmngr"])

        keys_path = self.project._get_keys_path()
        changes = [
            package_repo.install(keys_path=keys_path) for package_repo in package_repos
        ]
        if any(changes):
            repo.Repo.refresh_build_packages()

    def get_build_packages(self) -> Set[str]:
        # Install/update configured package repositories.
        self.install_package_repositories()

        # FIXME:SPIKE: re-add global and additional build packages
        # build_packages = self._global_grammar_processor.get_build_packages()
        # build_packages |= set(self.additional_build_packages)
        build_packages = set()

        # FIXME:SPIKE: allow the application to specificy extra packages
        #if self._config.is_git_version:
        #    build_packages.add("git")

        for part in self.all_parts:
            build_packages |= part._grammar_processor.get_build_packages()

            # TODO: this should not pass in command but the required package,
            #       where the required package is to be determined by the
            #       source handler.
            if part.source_handler and part.source_handler.command:
                # TODO get_packages_for_source_type should not be a thing.
                build_packages |= repo.Repo.get_packages_for_source_type(
                    part.source_handler.command
                )

            if not isinstance(part.plugin, plugins.v1.PluginV1):
                build_packages |= part.plugin.get_build_packages()

        return build_packages

    # FIXME:SPIKE: implement get_build_snaps
    def get_build_snaps(self) -> Set[str]:
        print("TODO: get build snaps")
        return set()

    # FIXME:SPIKE: implement get_content_snaps
    def get_content_snaps(self) -> Set[str]:
        print("TODO: get content snaps")
        return set()

    def _get_global_state_file_path(self) -> str:
        if self._is_managed_host:
            state_file_path = os.path.join(self._work_dir, "state")
        else:
            state_file_path = os.path.join(self._config.parts_dir, ".snapcraft_global_state")

        return state_file_path

    def get_project_state(self, step: steps.Step):
        """Returns a dict of states for the given step of each part."""

        state = {}
        for part in self.all_parts:
            state[part.name] = states.get_state(part.part_state_dir, step)

        return state


# We only have V2 now, will be Union[] later
Plugin = Type[plugins.v2.PluginV2]

# FIXME:SPIKE: handle steps list
def register_pre_step_callback(func, steps: List[str]=[]):
    _pre_hooks.append(func)
    return func


# FIXME:SPIKE: handle steps list
def register_post_step_callback(func, steps: List[str]=[]):
    _post_hooks.append(func)
    return func


def register_plugins(plugins: Dict[str, Plugin]):
    _custom_plugins.update(plugins)


def _get_platform_architecture():
    architecture = platform.machine()

    # FIXME:SPIKE: handle windows case
    # Translate the windows architectures we know of to architectures
    # we can work with.
    # if sys.platform == "win32":
    #     architecture = _WINDOWS_TRANSLATIONS.get(architecture)
    # if platform.architecture()[0] == "32bit":
    #     userspace = _32BIT_USERSPACE_ARCHITECTURE.get(architecture)
    #     if userspace:
    #         architecture = userspace

    return architecture


# FIXME:SPIKE: find a better place for this
def replace_attr(
    attr: Union[List[str], Dict[str, str], str], replacements: Dict[str, str]
) -> Union[List[str], Dict[str, str], str]:
    if isinstance(attr, str):
        for replacement, value in replacements.items():
            attr = attr.replace(replacement, str(value))
        return attr
    elif isinstance(attr, list) or isinstance(attr, tuple):
        return [cast(str, replace_attr(i, replacements)) for i in attr]
    elif isinstance(attr, dict):
        result = dict()  # type: Dict[str, str]
        for key, value in attr.items():
            # Run replacements on both the key and value
            key = cast(str, replace_attr(key, replacements))
            value = cast(str, replace_attr(value, replacements))
            result[key] = value
        return result

    return attr
