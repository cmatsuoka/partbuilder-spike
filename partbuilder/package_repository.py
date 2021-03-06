# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2019 Canonical Ltd
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

import abc
import logging
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from partbuilder import repo

from . import errors

logger = logging.getLogger(__name__)


class PackageRepository(abc.ABC):
    @abc.abstractmethod
    def install(self, *, keys_path: Path) -> bool:
        ...

    @abc.abstractmethod
    def marshal(self) -> Dict[str, Any]:
        ...

    @classmethod
    def unmarshal(cls, data: Dict[str, str]) -> "PackageRepository":
        if not isinstance(data, dict):
            raise RuntimeError(f"invalid repository object: {data!r}")

        if "ppa" in data:
            return PackageRepositoryAptPpa.unmarshal(data)

        return PackageRepositoryApt.unmarshal(data)

    @classmethod
    def unmarshal_package_repositories(cls, data: Any) -> List["PackageRepository"]:
        repositories = list()

        if data is not None:
            if not isinstance(data, list):
                raise RuntimeError(f"invalid package-repositories: {data!r}")

            for repository in data:
                package_repo = cls.unmarshal(repository)
                repositories.append(package_repo)

        return repositories


class PackageRepositoryAptPpa(PackageRepository):
    def __init__(self, *, ppa: str) -> None:
        self.type = "apt"
        self.ppa = ppa

    def install(self, *, keys_path: Path) -> bool:
        return repo.Ubuntu.install_ppa(keys_path=keys_path, ppa=self.ppa)

    def marshal(self) -> Dict[str, Any]:
        data = dict(type="apt")
        data["ppa"] = self.ppa
        return data

    @classmethod
    def unmarshal(cls, data: Dict[str, str]) -> "PackageRepositoryAptPpa":
        if not isinstance(data, dict):
            raise errors.PackageRepositoryValidationError(
                url=str(data), brief=f"Invalid PPA object {data!r}.",
            )

        if not isinstance(data, dict):
            raise RuntimeError(f"invalid ppa repository object: {data!r}")

        data_copy = deepcopy(data)

        ppa = data_copy.pop("ppa", "")
        repo_type = data_copy.pop("type", None)

        if repo_type != "apt":
            raise errors.PackageRepositoryValidationError(
                url=ppa,
                brief=f"Unsupported type {repo_type!r}.",
                resolution="You can use type 'apt'.",
            )

        if not ppa:
            raise errors.PackageRepositoryValidationError(
                url=ppa,
                brief=f"Invalid PPA {ppa!r}.",
                resolution="You can update 'ppa' to a non-empty string.",
            )

        if data_copy:
            keys = ", ".join([repr(k) for k in data_copy.keys()])
            raise errors.PackageRepositoryValidationError(
                url=ppa,
                brief=f"Invalid keys present ({keys}).",
                resolution="You can remove the unsupported keys.",
            )

        return cls(ppa=ppa)


class PackageRepositoryApt(PackageRepository):
    def __init__(
        self,
        *,
        architectures: Optional[List[str]] = None,
        components: List[str],
        formats: Optional[List[str]] = None,
        key_id: str,
        key_server: Optional[str] = None,
        name: Optional[str] = None,
        suites: List[str],
        url: str,
    ) -> None:
        self.type = "apt"
        self.architectures = architectures
        self.components = components
        self.formats = formats
        self.key_id = key_id
        self.key_server = key_server

        if name is None:
            # Default name is URL, stripping non-alphanumeric characters.
            self.name: str = re.sub(r"\W+", "_", url)
        else:
            self.name = name

        self.suites = suites
        self.url = url

        self.validate()

    def install(self, keys_path: Path) -> bool:
        # First install associated GPG key.
        new_key: bool = repo.Ubuntu.install_gpg_key_id(
            keys_path=keys_path, key_id=self.key_id, key_server=self.key_server
        )

        # Now install sources file.
        new_sources: bool = repo.Ubuntu.install_sources(
            architectures=self.architectures,
            components=self.components,
            formats=self.formats,
            name=self.name,
            suites=self.suites,
            url=self.url,
        )

        return new_key or new_sources

    def marshal(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"type": "apt"}

        if self.architectures:
            data["architectures"] = self.architectures

        data["components"] = self.components

        if self.formats:
            data["formats"] = self.formats

        data["key-id"] = self.key_id

        if self.key_server:
            data["key-server"] = self.key_server

        data["name"] = self.name
        data["suites"] = self.suites
        data["url"] = self.url

        return data

    def validate(self) -> None:
        if self.formats is not None and any(
            f not in ["deb", "deb-src"] for f in self.formats
        ):
            raise errors.PackageRepositoryValidationError(
                url=self.url,
                brief=f"Invalid formats {self.formats!r}.",
                resolution="You can specify a list of formats including 'deb' and/or 'deb-src'.",
            )

        if not self.key_id:
            raise errors.PackageRepositoryValidationError(
                url=self.url,
                brief=f"Invalid Key Identifier {self.key_id!r}.",
                resolution="You can verify that the key specifies a valid key identifier.",
            )

        if not self.url:
            raise errors.PackageRepositoryValidationError(
                url=self.url,
                brief=f"Invalid URL {self.url!r}.",
                resolution="You can update 'url' to a non-empty string.",
            )

    @classmethod  # noqa: C901
    def unmarshal(cls, data: Dict[str, Any]) -> "PackageRepositoryApt":
        if not isinstance(data, dict):
            raise errors.PackageRepositoryValidationError(
                url=str(data), brief=f"Invalid object {data!r}.",
            )

        data_copy = deepcopy(data)

        architectures = data_copy.pop("architectures", None)
        components = data_copy.pop("components", None)
        formats = data_copy.pop("formats", None)
        key_id = data_copy.pop("key-id", None)
        key_server = data_copy.pop("key-server", None)
        name = data_copy.pop("name", None)
        suites = data_copy.pop("suites", None)
        url = data_copy.pop("url", "")
        repo_type = data_copy.pop("type", None)

        if repo_type != "apt":
            raise errors.PackageRepositoryValidationError(
                url=url,
                brief=f"Unsupported type {repo_type!r}.",
                resolution="You can use type 'apt'.",
            )

        if architectures is not None and (
            not isinstance(architectures, list)
            or not all(isinstance(x, str) for x in architectures)
        ):
            raise errors.PackageRepositoryValidationError(
                url=url, brief=f"Invalid architectures {architectures!r}.",
            )

        if (
            not isinstance(components, list)
            or not all(isinstance(x, str) for x in components)
            or not components
        ):
            raise errors.PackageRepositoryValidationError(
                url=url, brief=f"Invalid components {components!r}.",
            )

        if formats is not None and (
            not isinstance(formats, list)
            or not all(isinstance(x, str) for x in formats)
        ):
            raise errors.PackageRepositoryValidationError(
                url=url, brief=f"Invalid formats {formats!r}.",
            )

        if not isinstance(key_id, str):
            raise errors.PackageRepositoryValidationError(
                url=url, brief=f"Invalid key identifier {key_id!r}.",
            )

        if key_server is not None and not isinstance(key_server, str):
            raise errors.PackageRepositoryValidationError(
                url=url, brief=f"Invalid key server {key_server!r}.",
            )

        if name is not None and not isinstance(name, str):
            raise errors.PackageRepositoryValidationError(
                url=url, brief=f"Invalid name {name!r}.",
            )

        if (
            not isinstance(suites, list)
            or not all(isinstance(x, str) for x in suites)
            or not suites
        ):
            raise errors.PackageRepositoryValidationError(
                url=url, brief=f"Suites must be a list of strings.",
            )

        if not isinstance(url, str):
            raise errors.PackageRepositoryValidationError(
                url=url, brief=f"Invalid URL {url!r}.",
            )

        if data_copy:
            keys = ", ".join([repr(k) for k in data_copy.keys()])
            raise errors.PackageRepositoryValidationError(
                url=url, brief=f"Invalid keys present ({keys}).",
            )

        return cls(
            architectures=architectures,
            components=components,
            formats=formats,
            key_id=key_id,
            key_server=key_server,
            name=name,
            suites=suites,
            url=url,
        )
