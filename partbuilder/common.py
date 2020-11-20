# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2015-2017 Canonical Ltd
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

# Data/methods shared between plugins and snapcraft

import os
import logging
import urllib
import subprocess
import sys
import shlex
import tempfile

from pathlib import Path
from typing import Callable, List, Union

#_DEFAULT_SCHEMADIR = os.path.join(sys.prefix, "share", "snapcraft", "schema")
_DEFAULT_SCHEMADIR = os.path.join("/home", "ubuntu", "partbuilder", "schema")
_schemadir = _DEFAULT_SCHEMADIR

_DOCKERENV_FILE = "/.dockerenv"
_PODMAN_FILE = "/run/.containerenv"

logger = logging.getLogger(__name__)

env = []  # type: List[str]


def assemble_env():
    return "\n".join(["export " + e for e in env])

run_number: int = 0


def _run(cmd: List[str], runner: Callable, **kwargs):
    global run_number
    run_number += 1

    assert isinstance(cmd, list), "run command must be a list"

    lines: List[str] = list()

    # Set shell.
    lines.append("#!/bin/sh")

    # Account for `env` parameter by populating exports.
    # Ordering matters: assembled_env overrides `env` parameter.
    cmd_env = kwargs.pop("env", None)
    if cmd_env:
        lines.append("#############################")
        lines.append("# Exported via `env` parameter:")
        for key in sorted(cmd_env.keys()):
            value = cmd_env.get(key)
            lines.append(f"export {key}={value!r}")

    # Account for assembled_env.
    lines.append("#############################")
    lines.append("# Exported via assembled env:")
    lines.extend(["export " + e for e in env])

    # Account for `cwd` by changing directory.
    cmd_workdir = kwargs.pop("cwd", None)
    if cmd_workdir:
        lines.append("#############################")
        lines.append("# Configured via `cwd` parameter:")
    else:
        cmd_workdir = os.getcwd()
        lines.append("#############################")
        lines.append("# Implicit working directory:")
    lines.append(f"cd {cmd_workdir!r}")

    # Finally, execute desired command.
    lines.append("#############################")
    lines.append("# Execute command:")
    cmd_string = " ".join([shlex.quote(c) for c in cmd])
    lines.append(f"exec {cmd_string}")

    # Save script executed by snapcraft.
    pid = os.getpid()
    temp_dir = Path(tempfile.gettempdir(), f"snapcraft-{pid}")
    temp_dir.mkdir(mode=0o755, parents=True, exist_ok=True)

    script_path = temp_dir / f"run-{run_number}.sh"
    script = "\n".join(lines) + "\n"

    # Write script.
    script_path.write_text(script)
    script_path.chmod(0o755)

    runner_command = ["/bin/sh", str(script_path)]
    runner_command_string = " ".join([shlex.quote(c) for c in runner_command])
    try:
        logger.debug(f"Executing assembled script: {runner_command_string!r}")
        return runner(runner_command, **kwargs)
    except subprocess.CalledProcessError as call_error:
        raise errors.SnapcraftCommandError(
            command=cmd_string, call_error=call_error
        ) from call_error


def run(cmd: List[str], **kwargs) -> None:
    _run(cmd, subprocess.check_call, **kwargs)


def run_output(cmd: List[str], **kwargs) -> str:
    output = _run(cmd, subprocess.check_output, **kwargs)
    try:
        return output.decode(sys.getfilesystemencoding()).strip()
    except UnicodeEncodeError:
        logger.warning("Could not decode output for {!r} correctly".format(cmd))
        return output.decode("latin-1", "surrogateescape").strip()


def get_library_paths(root, arch_triplet, existing_only=True):
    """Returns common library paths for a snap.

    If existing_only is set the paths returned must exist for
    the root that was set.
    """
    paths = [
        os.path.join(root, "lib"),
        os.path.join(root, "usr", "lib"),
        os.path.join(root, "lib", arch_triplet),
        os.path.join(root, "usr", "lib", arch_triplet),
    ]

    if existing_only:
        paths = [p for p in paths if os.path.exists(p)]

    return paths

def get_url_scheme(url):
    return urllib.parse.urlparse(url).scheme


def isurl(url):
    return get_url_scheme(url) != ""

def reset_env():
    global env
    env = []

def get_schemadir():
    return _schemadir

# FIXME:SPIKE: is_snap is snapcraft-specific
def is_snap() -> bool:
    snap_name = os.environ.get("SNAP_NAME", "")
    is_snap = snap_name == "snapcraft"
    logger.debug(
        "snapcraft is running as a snap {!r}, "
        "SNAP_NAME set to {!r}".format(is_snap, snap_name)
    )
    return is_snap

def is_process_container() -> bool:
    logger.debug("snapcraft is running in a docker or podman (OCI) container")
    return any([os.path.exists(p) for p in (_DOCKERENV_FILE, _PODMAN_FILE)])

def get_include_paths(root, arch_triplet):
    paths = [
        os.path.join(root, "include"),
        os.path.join(root, "usr", "include"),
        os.path.join(root, "include", arch_triplet),
        os.path.join(root, "usr", "include", arch_triplet),
    ]

    return [p for p in paths if os.path.exists(p)]


def get_pkg_config_paths(root, arch_triplet):
    paths = [
        os.path.join(root, "lib", "pkgconfig"),
        os.path.join(root, "lib", arch_triplet, "pkgconfig"),
        os.path.join(root, "usr", "lib", "pkgconfig"),
        os.path.join(root, "usr", "lib", arch_triplet, "pkgconfig"),
        os.path.join(root, "usr", "share", "pkgconfig"),
        os.path.join(root, "usr", "local", "lib", "pkgconfig"),
        os.path.join(root, "usr", "local", "lib", arch_triplet, "pkgconfig"),
        os.path.join(root, "usr", "local", "share", "pkgconfig"),
    ]

    return [p for p in paths if os.path.exists(p)]

