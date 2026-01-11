from __future__ import annotations

import re
from typing import TYPE_CHECKING

from packaging.requirements import Requirement

from .req.file import ParsedRequirement, ReqFileLines, RequirementsFile

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace
    from pathlib import Path
    from typing import Final


def _is_pylock_file(path_str: str) -> bool:
    """Check if a path refers to a PEP 751 pylock.toml file."""
    path_lower = path_str.lower()
    # Match pylock.toml or pylock.<name>.toml
    return path_lower == "pylock.toml" or (path_lower.startswith("pylock.") and path_lower.endswith(".toml"))


class PythonDeps(RequirementsFile):
    # these options are valid in requirements.txt, but not via pip cli and
    # thus cannot be used in the testenv `deps` list
    _illegal_options: Final[list[str]] = ["hash"]

    def __init__(self, raw: str | list[str] | list[Requirement], root: Path) -> None:
        super().__init__(root / "tox.ini", constraint=False)
        got = raw if isinstance(raw, str) else "\n".join(str(i) for i in raw)
        self._raw = self._normalize_raw(got)
        self._unroll: tuple[list[str], list[str]] | None = None
        self._req_parser_: RequirementsFile | None = None

    def _extend_parser(self, parser: ArgumentParser) -> None:  # noqa: PLR6301
        parser.add_argument("--no-deps", action="store_true", dest="no_deps", default=False)

    def _merge_option_line(self, base_opt: Namespace, opt: Namespace, filename: str) -> None:
        super()._merge_option_line(base_opt, opt, filename)
        if getattr(opt, "no_deps", False):  # if the option comes from a requirements file this flag is missing there
            base_opt.no_deps = True

    def _option_to_args(self, opt: Namespace) -> list[str]:
        result = super()._option_to_args(opt)
        if getattr(opt, "no_deps", False):
            result.append("--no-deps")
        return result

    @property
    def _req_parser(self) -> RequirementsFile:
        if self._req_parser_ is None:
            # Create a custom RequirementsFile that can handle pylock files
            self._req_parser_ = _PylockAwareRequirementsFile(path=self._path, constraint=False)
        return self._req_parser_

    def _get_file_content(self, url: str) -> str:
        # Check if this is a pylock.toml file
        from pathlib import Path as PathLib  # noqa: PLC0415
        
        url_path = PathLib(url) if not url.startswith(("http://", "https://", "file://")) else None
        if url_path and _is_pylock_file(url_path.name):
            # This is a pylock.toml file - convert it to requirements format
            from .pylock import PylockFile  # noqa: PLC0415
            
            try:
                pylock = PylockFile(url_path)
                lock_requirements = pylock.get_requirements()
                # Convert to requirements.txt format (one requirement per line)
                return "\n".join(str(req) for req in lock_requirements)
            except Exception:  # noqa: BLE001
                # If parsing fails, fall through to normal file handling
                pass
        
        if self._is_url_self(url):
            return self._raw
        return super()._get_file_content(url)

    def _is_url_self(self, url: str) -> bool:
        return url == str(self._path)

    def _pre_process(self, content: str) -> ReqFileLines:
        for at, line in super()._pre_process(content):
            if line.startswith("-r") or (line.startswith("-c") and line[2].isalpha()):
                found_line = f"{line[0:2]} {line[2:]}"  # normalize
            else:
                found_line = line
            yield at, found_line

    def lines(self) -> list[str]:
        return self._raw.splitlines()

    @classmethod
    def _normalize_raw(cls, raw: str) -> str:
        # a line ending in an unescaped \ is treated as a line continuation and the newline following it is effectively
        # ignored
        raw = "".join(raw.replace("\r", "").split("\\\n"))
        # for tox<4 supporting requirement/constraint files via -rreq.txt/-creq.txt
        lines: list[str] = [cls._normalize_line(line) for line in raw.splitlines()]
        adjusted = "\n".join(lines)
        return f"{adjusted}\n" if raw.endswith("\\\n") else adjusted  # preserve trailing newline if input has it

    @classmethod
    def _normalize_line(cls, line: str) -> str:
        arg_match = next(
            (
                arg
                for arg in ONE_ARG
                if line.startswith(arg)
                and len(line) > len(arg)
                and not (line[len(arg)].isspace() or line[len(arg)] == "=")
            ),
            None,
        )
        if arg_match is not None:
            values = line[len(arg_match) :]
            line = f"{arg_match} {values}"
        # escape spaces
        escape_match = next((e for e in ONE_ARG_ESCAPE if line.startswith(e) and line[len(e)].isspace()), None)
        if escape_match is not None:
            # escape not already escaped spaces
            escaped = re.sub(r"(?<!\\)(\s)", r"\\\1", line[len(escape_match) + 1 :])
            line = f"{line[: len(escape_match)]} {escaped}"
        return line

    def _parse_requirements(self, opt: Namespace, recurse: bool) -> list[ParsedRequirement]:  # noqa: FBT001
        # check for any invalid options in the deps list
        # (requirements recursively included from other files are not checked)
        requirements = super()._parse_requirements(opt, recurse)
        for req in requirements:
            if req.from_file != str(self.path):
                continue
            for illegal_option in self._illegal_options:
                if req.options.get(illegal_option):
                    msg = f"Cannot use --{illegal_option} in deps list, it must be in requirements file. ({req})"
                    raise ValueError(msg)
        return requirements

    @property
    def as_root_args(self) -> list[str]:
        """
        Override to handle pylock.toml files properly.
        
        Instead of returning -r pylock.toml, we expand it to individual requirements.
        """
        from argparse import Namespace  # noqa: PLC0415
        
        # Use recurse=True to actually parse the files
        opt = Namespace()
        result: list[str] = []
        
        # Parse requirements with recursion to expand pylock files
        for req in self._parse_requirements(opt=opt, recurse=True):
            result.extend(req.as_args())
        
        # Process options but filter out pylock.toml references
        option_args = self._option_to_args_filtered(opt)
        result.extend(option_args)
        
        return result
    
    def _option_to_args_filtered(self, opt: Namespace) -> list[str]:
        """Like _option_to_args but filters out pylock.toml files (already expanded)."""
        result: list[str] = []
        from pathlib import Path as PathLib  # noqa: PLC0415
        
        # Filter requirements - exclude pylock files as they're already expanded
        for req in getattr(opt, "requirements", []):
            req_path = PathLib(req)
            if not _is_pylock_file(req_path.name):
                result.extend(("-r", req))
        
        # Constraints are passed as-is (pylock files won't be in constraints)
        for req in getattr(opt, "constraints", []):
            result.extend(("-c", req))
        
        # Other options from parent
        parent_args = self._req_parser._option_to_args(opt)  # noqa: SLF001
        # Filter out any -r/-c we already handled
        i = 0
        while i < len(parent_args):
            arg = parent_args[i]
            if arg in ("-r", "-c") and i + 1 < len(parent_args):
                # Skip this pair, we already handled it
                i += 2
            else:
                result.append(arg)
                i += 1
        
        return result

    def unroll(self) -> tuple[list[str], list[str]]:
        if self._unroll is None:
            opts_dict = vars(self.options)
            if not self.requirements and opts_dict:
                msg = "no dependencies"
                raise ValueError(msg)
            result_opts: list[str] = [f"{key}={value}" for key, value in opts_dict.items()]
            result_req = [str(req) for req in self.requirements]
            self._unroll = result_opts, result_req
        return self._unroll

    def __iadd__(self, other: PythonDeps) -> PythonDeps:  # noqa: PYI034
        self._raw += "\n" + other._raw
        return self

    @classmethod
    def factory(cls, root: Path, raw: object) -> PythonDeps:
        if not (
            isinstance(raw, str)
            or (
                isinstance(raw, list)
                and (all(isinstance(i, str) for i in raw) or all(isinstance(i, Requirement) for i in raw))
            )
        ):
            raise TypeError(raw)
        return cls(raw, root)


class PythonConstraints(RequirementsFile):
    def __init__(self, raw: str | list[str] | list[Requirement], root: Path) -> None:
        super().__init__(root / "tox.ini", constraint=True)
        got = raw if isinstance(raw, str) else "\n".join(str(i) for i in raw)
        self._raw = self._normalize_raw(got)
        self._unroll: tuple[list[str], list[str]] | None = None
        self._req_parser_: RequirementsFile | None = None

    @property
    def _req_parser(self) -> RequirementsFile:
        if self._req_parser_ is None:
            self._req_parser_ = RequirementsFile(path=self._path, constraint=True)
        return self._req_parser_

    def _get_file_content(self, url: str) -> str:
        if self._is_url_self(url):
            return self._raw
        return super()._get_file_content(url)

    def _is_url_self(self, url: str) -> bool:
        return url == str(self._path)

    def _pre_process(self, content: str) -> ReqFileLines:
        for at, line in super()._pre_process(content):
            if line.startswith("-r") or (line.startswith("-c") and line[2].isalpha()):
                found_line = f"{line[0:2]} {line[2:]}"  # normalize
            else:
                found_line = line
            yield at, found_line

    def lines(self) -> list[str]:
        return self._raw.splitlines()

    @classmethod
    def _normalize_raw(cls, raw: str) -> str:
        # a line ending in an unescaped \ is treated as a line continuation and the newline following it is effectively
        # ignored
        raw = "".join(raw.replace("\r", "").split("\\\n"))
        # for tox<4 supporting requirement/constraint files via -rreq.txt/-creq.txt
        lines: list[str] = [cls._normalize_line(line) for line in raw.splitlines()]

        if any(line.startswith("-") for line in lines):
            msg = "only constraints files or URLs can be provided"
            raise ValueError(msg)

        adjusted = "\n".join([f"-c {line}" for line in lines])
        return f"{adjusted}\n" if raw.endswith("\\\n") else adjusted  # preserve trailing newline if input has it

    @classmethod
    def _normalize_line(cls, line: str) -> str:
        arg_match = next(
            (
                arg
                for arg in ONE_ARG
                if line.startswith(arg)
                and len(line) > len(arg)
                and not (line[len(arg)].isspace() or line[len(arg)] == "=")
            ),
            None,
        )
        if arg_match is not None:
            values = line[len(arg_match) :]
            line = f"{arg_match} {values}"
        # escape spaces
        escape_match = next((e for e in ONE_ARG_ESCAPE if line.startswith(e) and line[len(e)].isspace()), None)
        if escape_match is not None:
            # escape not already escaped spaces
            escaped = re.sub(r"(?<!\\)(\s)", r"\\\1", line[len(escape_match) + 1 :])
            line = f"{line[: len(escape_match)]} {escaped}"
        return line

    def _parse_requirements(self, opt: Namespace, recurse: bool) -> list[ParsedRequirement]:  # noqa: FBT001
        # check for any invalid options in the deps list
        # (requirements recursively included from other files are not checked)
        requirements = super()._parse_requirements(opt, recurse)
        for req in requirements:
            if req.from_file != str(self.path):
                continue
            if req.options:
                msg = f"Cannot provide options in constraints list, only paths or URL can be provided. ({req})"
                raise ValueError(msg)
        return requirements

    def unroll(self) -> tuple[list[str], list[str]]:
        if self._unroll is None:
            opts_dict = vars(self.options)
            if not self.requirements and opts_dict:
                msg = "no dependencies"
                raise ValueError(msg)
            result_opts: list[str] = [f"{key}={value}" for key, value in opts_dict.items()]
            result_req = [str(req) for req in self.requirements]
            self._unroll = result_opts, result_req
        return self._unroll

    @classmethod
    def factory(cls, root: Path, raw: object) -> PythonConstraints:
        if not (
            isinstance(raw, str)
            or (
                isinstance(raw, list)
                and (all(isinstance(i, str) for i in raw) or all(isinstance(i, Requirement) for i in raw))
            )
        ):
            raise TypeError(raw)
        return cls(raw, root)


class _PylockAwareRequirementsFile(RequirementsFile):
    """A RequirementsFile subclass that can intercept and convert pylock.toml files."""
    
    def _get_file_content(self, url: str) -> str:
        # Check if this is a pylock.toml file
        from pathlib import Path as PathLib  # noqa: PLC0415
        
        url_path = PathLib(url) if not url.startswith(("http://", "https://", "file://")) else None
        if url_path and _is_pylock_file(url_path.name):
            # This is a pylock.toml file - convert it to requirements format
            from .pylock import PylockFile  # noqa: PLC0415
            
            try:
                pylock = PylockFile(url_path)
                lock_requirements = pylock.get_requirements()
                # Convert to requirements.txt format (one requirement per line)
                return "\n".join(str(req) for req in lock_requirements)
            except Exception:  # noqa: BLE001
                # If parsing fails, fall through to normal file handling
                pass
        
        return super()._get_file_content(url)


ONE_ARG = {
    "-i",
    "--index-url",
    "--extra-index-url",
    "-e",
    "--editable",
    "-c",
    "--constraint",
    "-r",
    "--requirement",
    "-f",
    "--find-links",
    "--trusted-host",
    "--use-feature",
    "--no-binary",
    "--only-binary",
}
ONE_ARG_ESCAPE = {
    "-c",
    "--constraint",
    "-r",
    "--requirement",
    "-f",
    "--find-links",
    "-e",
    "--editable",
}

__all__ = (
    "ONE_ARG",
    "PythonDeps",
)
