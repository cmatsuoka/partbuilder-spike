# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2016-2018 Canonical Ltd
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

import collections
import contextlib
import shlex
from abc import ABC, abstractmethod
from subprocess import CalledProcessError
from typing import TYPE_CHECKING, Dict, List, Optional, Union

from partbuilder import steps
from partbuilder.utils import formatting_utils

# dict of jsonschema validator -> cause pairs. Wish jsonschema just gave us
# better messages.
_VALIDATION_ERROR_CAUSES = {
    "maxLength": "maximum length is {validator_value}",
    "minLength": "minimum length is {validator_value}",
}


class PartbuilderError(Exception):
    """DEPRECATED: Use PartbuilderException instead."""

    fmt = "Daughter classes should redefine this"

    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __str__(self):
        return self.fmt.format([], **self.__dict__)

    def get_exit_code(self):
        """Exit code to use if this exception causes Snapcraft to exit."""
        return 2


class PartbuilderException(Exception, ABC):
    """Base class for Snapcraft Exceptions."""

    @abstractmethod
    def get_brief(self) -> str:
        """Concise, single-line description of the error."""

    @abstractmethod
    def get_resolution(self) -> str:
        """Concise suggestion for user to resolve error."""

    def get_details(self) -> Optional[str]:
        """Detailed technical information, if required for user to debug issue."""
        return None

    def get_docs_url(self) -> Optional[str]:
        """Link to documentation on docs.snapcraft.io, if applicable."""
        return None

    def get_exit_code(self) -> int:
        """Exit code to use when exiting snapcraft due to this exception."""
        return 2

    def get_reportable(self) -> bool:
        """Defines if error is reportable (an exception trace should be shown)."""
        return False

    def __str__(self) -> str:
        return self.get_brief()


class OsReleaseIdError(PartbuilderError):

    fmt = "Unable to determine host OS ID"


class XAttributeError(PartbuilderException):
    def __init__(self, *, action: str, key: str, path: str) -> None:
        self._action = action
        self._key = key
        self._path = path

    def get_brief(self) -> str:
        return f"Unable to {self._action} extended attribute."

    def get_details(self) -> str:
        return f"Failed to {self._action} attribute {self._key!r} on {self._path!r}."

    def get_resolution(self) -> str:
        return "Check that your filesystem supports extended attributes."


class XAttributeTooLongError(PartbuilderException):
    def __init__(self, *, key: str, value: str, path: str) -> None:
        self._key = key
        self._value = value
        self._path = path

    def get_brief(self) -> str:
        return "Unable to write extended attribute as the key and/or value is too long."

    def get_details(self) -> str:
        return (
            f"Failed to write attribute to {self._path!r}:\n"
            f"key={self._key!r} value={self._value!r}"
        )

    def get_resolution(self) -> str:
        return (
            "This issue is generally resolved by addressing/truncating "
            "the data source of the long data value. In some cases, the "
            "filesystem being used will limit the allowable size."
        )


class MetadataExtractionError(PartbuilderError):
    pass


class MissingMetadataFileError(MetadataExtractionError):

    fmt = (
        "Failed to generate snap metadata: "
        "Part {part_name!r} has a 'parse-info' referring to metadata file "
        "{path!r}, which does not exist."
    )

    def __init__(self, part_name: str, path: str) -> None:
        super().__init__(part_name=part_name, path=path)


class UnhandledMetadataFileTypeError(MetadataExtractionError):

    fmt = (
        "Failed to extract metadata from {path!r}: "
        "This type of file is not supported for supplying metadata."
    )

    def __init__(self, path: str) -> None:
        super().__init__(path=path)


class InvalidExtractorValueError(MetadataExtractionError):

    fmt = (
        "Failed to extract metadata from {path!r}: "
        "Extractor {extractor_name!r} didn't return ExtractedMetadata as "
        "expected."
    )

    def __init__(self, path: str, extractor_name: str) -> None:
        super().__init__(path=path, extractor_name=extractor_name)


class YamlValidationError(PartbuilderError):

    fmt = "Issues while validating {source}: {message}"

    @classmethod
    def from_validation_error(cls, error, *, source="snapcraft.yaml"):
        """Take a jsonschema.ValidationError and create a SnapcraftSchemaError.

        The validation errors coming from jsonschema are a nightmare. This
        class tries to make them a bit more understandable.
        """

        messages = []

        preamble = _determine_preamble(error)
        cause = _determine_cause(error)
        supplement = _determine_supplemental_info(error)

        if preamble:
            messages.append(preamble)

        # If we have a preamble we are not at the root
        if supplement and preamble:
            messages.append(error.message)
            messages.append("({})".format(supplement))
        elif supplement:
            messages.append(supplement)
        elif cause:
            messages.append(cause)
        else:
            messages.append(error.message)

        return cls(" ".join(messages), source)

    def __init__(self, message, source="snapcraft.yaml"):
        super().__init__(message=message, source=source)


class PluginError(PartbuilderError):

    fmt = (
        "Failed to load plugin: "
        "{message}"
        # FIXME include how to fix each of the possible plugin errors.
        # https://bugs.launchpad.net/snapcraft/+bug/1727484
        # --elopio - 2017-10-25
    )

    def __init__(self, message):
        super().__init__(message=message)


class PluginBaseError(PartbuilderError):

    fmt = "The plugin used by part {part_name!r} does not support snaps using base {base!r}."

    def __init__(self, *, part_name, base):
        super().__init__(part_name=part_name, base=base)


class PartbuilderCommandError(PartbuilderError, CalledProcessError):
    """Exception for generic command errors.

    Processes should capture this error for specific messaging.
    This exception carries the signature of CalledProcessError for backwards
    compatibility.
    """

    fmt = "Failed to run {command!r}: Exited with code {exit_code}."

    def __init__(self, *, command: str, call_error: CalledProcessError) -> None:
        super().__init__(command=command, exit_code=call_error.returncode)
        CalledProcessError.__init__(
            self,
            returncode=call_error.returncode,
            cmd=call_error.cmd,
            output=call_error.output,
            stderr=call_error.stderr,
        )


class PartbuilderPluginCommandError(PartbuilderError):
    """Command executed by a plugin fails."""

    fmt = (
        "Failed to run {command!r} for {part_name!r}: "
        "Exited with code {exit_code}.\n"
        "Verify that the part is using the correct parameters and try again."
    )

    def __init__(
        self, *, command: Union[List, str], part_name: str, exit_code: int
    ) -> None:
        if isinstance(command, list):
            command = " ".join([shlex.quote(c) for c in command])
        super().__init__(command=command, part_name=part_name, exit_code=exit_code)


class PartbuilderPluginBuildError(PartbuilderException):
    """An exception to raise when the PluginV2 build fails at runtime."""

    def __init__(self, *, part_name: str) -> None:
        self._part_name = part_name

    def get_brief(self) -> str:
        return f"Failed to build {self._part_name!r}."

    def get_resolution(self) -> str:
        return "Check the build logs and ensure the part's configuration and sources are correct."


class PartbuilderEnvironmentError(PartbuilderException):
    """DEPRECATED: Too generic, create (or re-use) a tailored one."""

    # FIXME This exception is too generic.
    # https://bugs.launchpad.net/snapcraft/+bug/1734231
    # --elopio - 20171123

    def __init__(self, message: str) -> None:
        self.message = message

    def get_brief(self) -> str:
        return self.message

    def get_resolution(self) -> str:
        return ""


class StepHasNotRunError(PartbuilderError):
    fmt = "The {part_name!r} part has not yet run the {step.name!r} step"

    def __init__(self, part_name, step):
        super().__init__(part_name=part_name, step=step)


class NoLatestStepError(PartbuilderError):
    fmt = "The {part_name!r} part hasn't run any steps"

    def __init__(self, part_name):
        super().__init__(part_name=part_name)


class ScriptletBaseError(PartbuilderError):
    """Base class for all scriptlet-related exceptions.

    :cvar fmt: A format string that daughter classes override

    """


class ScriptletRunError(ScriptletBaseError):
    fmt = "Failed to run {scriptlet_name!r}: Exit code was {code}."

    def __init__(self, scriptlet_name: str, code: int) -> None:
        super().__init__(scriptlet_name=scriptlet_name, code=code)


class MissingStateCleanError(PartbuilderException):
    def __init__(self, step: steps.Step) -> None:
        self.step = step

    def get_brief(self) -> str:
        return f"Failed to clean for step {self.step.name!r}."

    def get_resolution(self) -> str:
        return CLEAN_RESOLUTION


def _determine_preamble(error):
    messages = []
    path = _determine_property_path(error)
    if path:
        messages.append(
            "The '{}' property does not match the required schema:".format(
                "/".join(path)
            )
        )
    return " ".join(messages)


def _determine_cause(error):
    messages = []

    # error.validator_value may contain a custom validation error message.
    # If so, use it instead of the garbage message jsonschema gives us.
    with contextlib.suppress(TypeError, KeyError):
        messages.append(error.validator_value["validation-failure"].format(error))

    # The schema itself may have a custom validation error message. If so,
    # use it as well.
    with contextlib.suppress(AttributeError, TypeError, KeyError):
        key = error
        if (
            error.schema.get("type") == "object"
            and error.validator == "additionalProperties"
        ):
            key = list(error.instance.keys())[0]

        messages.append(error.schema["validation-failure"].format(key))

    # anyOf failures might have usable context... try to improve them a bit
    if error.validator == "anyOf":
        contextual_messages: Dict[str, str] = collections.OrderedDict()
        for contextual_error in error.context:
            key = contextual_error.schema_path.popleft()
            if key not in contextual_messages:
                contextual_messages[key] = []
            message = contextual_error.message
            if message:
                # Sure it starts lower-case (not all messages do)
                contextual_messages[key].append(message[0].lower() + message[1:])

        oneOf_messages: List[str] = []
        for key, value in contextual_messages.items():
            oneOf_messages.append(formatting_utils.humanize_list(value, "and", "{}"))

        messages.append(formatting_utils.humanize_list(oneOf_messages, "or", "{}"))

    return " ".join(messages)


def _determine_supplemental_info(error):
    message = _VALIDATION_ERROR_CAUSES.get(error.validator, "").format(
        validator_value=error.validator_value
    )

    if not message and error.validator == "anyOf":
        message = _interpret_anyOf(error)

    if not message and error.cause:
        message = error.cause

    return message


def _determine_property_path(error):
    path = []
    while error.absolute_path:
        element = error.absolute_path.popleft()
        # assume numbers are indices and use 'xxx[123]' notation.
        if isinstance(element, int):
            path[-1] = "{}[{}]".format(path[-1], element)
        else:
            path.append(str(element))

    return path
