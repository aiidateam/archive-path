# -*- coding: utf-8 -*-
###########################################################################
# Copyright (c), The AiiDA team. All rights reserved.                     #
#                                                                         #
# The code is hosted at https://github.com/aiidateam/archive-path         #
# For further information on the license, see the LICENSE file            #
###########################################################################
"""A implementation of the ``pathlib.Path`` interface for ``tarfile.TarFile``."""
from contextlib import contextmanager, suppress
import io
import itertools
from pathlib import Path, PurePosixPath
import posixpath
import tarfile
from types import TracebackType
from typing import (
    IO,
    Any,
    Callable,
    Iterable,
    Iterator,
    Optional,
    Set,
    Type,
    Union,
    cast,
)

from .common import _parents, match_glob

__all__ = ("TarPath", "open_file_in_tar", "read_file_in_tar")


class TarPath:
    """A wrapper around ``tarfile.TarPath``,
    to provide an interface equivalent to ``pathlib.Path``

    For reading tar files, you can use it directly::

        path = TarPath('path/to/file.tar.gz', mode='r:gz')
        sub_path = path / 'folder' / 'file.txt'
        assert sub_path.filepath == 'path/to/file.tar.gz'
        assert sub_path.at == 'folder/file.txt'
        assert sub_path.exists() and sub_path.is_file()
        assert sub_path.parent.is_dir()
        content = sub_path.read_text()

    For writing tar files, you should use within a context manager,
    or directly call the ``close`` method::

        with TarPath('path/to/file.tar.gz', mode='w:gz') as path:
            (path / 'new_file.txt').write_text('hallo world')
            # there are also some features equivalent to shutil
            (path / 'other_file.txt').putfile('path/to/external_file.txt')
            (path / 'other_folder').puttree('path/to/external_folder', pattern='**/*')

    Note that ``tarfile`` does not allow to overwrite existing files
    (it will raise a ``FileExistsError``).

    """

    __repr = "{self.__class__.__name__}('{self.filepath!s}', {self.at!r})"

    def __init__(
        self,
        path: Union[str, Path, "TarPath"],
        *,
        mode: str = "r:*",
        at: str = "",  # pylint: disable=invalid-name
        pax_format: int = tarfile.PAX_FORMAT,
        dereference: bool = True,
        **kwargs,
    ):
        """Initialise a tar path item.

        :param path: the path to the tar file, or another instance of a TarPath
        :param at: the path within the tarfile (always use posixpath `/` separators)
        :param mode: the mode with which to open the tarfile,
            see ``tarfile.Tarfile.open`` for available modes
        :param pax_format: The format to use when creating an archive.
        :param dereference: If true, add content of linked file to the tar file, else the link.

        """
        if posixpath.isabs(at):
            raise ValueError(f"'at' cannot be an absolute path: {at}")
        assert not any(
            p == ".." for p in at.split(posixpath.sep)
        ), "'at' should not contain any '..'"

        self._at = at.rstrip("/")

        if isinstance(path, (str, Path)):
            self._filepath = Path(path)
            self._tarfile = tarfile.TarFile.open(
                path, mode=mode, format=pax_format, dereference=dereference, **kwargs
            )
        else:
            self._filepath = path._filepath
            self._tarfile = path._tarfile

    def __str__(self):
        return (
            posixpath.join(self.root.filename, self.at)  # type: ignore[attr-defined]
            if self.root.filename  # type: ignore[attr-defined]
            else self.at
        )

    def __repr__(self):
        return self.__repr.format(self=self)

    def __eq__(self, item: object) -> bool:
        """Return whether the external and internal path are equal"""
        if not isinstance(item, TarPath):
            return False
        if item._at != self._at:
            return False
        return item._filepath.resolve(strict=False) == self._filepath.resolve(
            strict=False
        )

    @property
    def filepath(self) -> Path:
        """Return the path to the tar file."""
        return self._filepath

    @property
    def root(self) -> tarfile.TarFile:
        """Return the root tar file."""
        return self._tarfile

    @property
    def at(self) -> str:  # pylint: disable=invalid-name
        """Return the current internal path within the tar file."""
        return self._at

    def _all_at_set(self) -> Set[str]:
        """Iterate through all file and directory paths in the tar file.

        Note: this is necessary,
        since the tarfile does not strictly store all directories in the namelist.

        It is cached on the tarfile instance if it is in read mode ('r'),
        since then the name list cannot change.

        """
        read_mode = "r" in self._tarfile.mode  # type: ignore
        if read_mode:
            with suppress(AttributeError):
                return self._tarfile.__all_at  # type: ignore
        names = self._tarfile.getnames()
        parents = itertools.chain.from_iterable(map(_parents, names))
        all_set = {p.rstrip("/") for p in itertools.chain([""], names, parents)}
        if read_mode:
            self._tarfile.__all_at = all_set  # type: ignore
        return all_set

    def _has_member(self) -> bool:
        info = None
        with suppress(KeyError):
            info = self._tarfile.getmember(self.at)
        return info is not None

    def close(self):
        """Close the tarfile."""
        self._tarfile.close()

    def __enter__(self):
        """Enter the tarfile for reading/writing."""
        return self

    def __exit__(
        self,
        exctype: Optional[Type[BaseException]],
        excinst: Optional[BaseException],
        exctb: Optional[TracebackType],
    ):
        """Exit the tarfile and close."""
        self.close()

    # pathlib like interface

    @property
    def name(self):
        """Return the basename of the current internal path within the tar file."""
        return posixpath.basename(self.at)

    @property
    def parent(self) -> "TarPath":
        """Return the parent of the current internal path within the tar file."""
        parent_at = posixpath.dirname(self.at)
        return self.__class__(self, at=parent_at)

    def is_dir(self):
        """Whether this path is an existing directory."""
        return self.exists() and not self.is_file()

    def is_file(self):
        """Whether this path is an existing regular file."""
        try:
            info = self._tarfile.getmember(self.at)
        except KeyError:
            return False
        return not info.isdir()

    def exists(self) -> bool:
        """Whether this path exists."""
        if self.at == "":
            return True
        with suppress(KeyError):
            self._tarfile.getmember(self.at)
            return True
        with suppress(KeyError):
            self._tarfile.getmember(self.at + "/")
            return True
        # note, we could just check this, but it can takes time/memory to construct
        return self.at in self._all_at_set()

    def joinpath(self, *paths) -> "TarPath":
        """Combine this path with one or several arguments, and return a new path."""
        return self.__class__(self, at=posixpath.join(self.at, *paths))

    def __truediv__(self, path: str) -> "TarPath":
        """Combine this path with another, and return a new path."""
        return self.__class__(self, at=posixpath.join(self.at, path))

    @contextmanager  # noqa: A003
    def open(self, mode: str = "rb"):  # noqa: A003
        """Open the file pointed by this path and return a file object."""
        # pylint: disable=fixme
        if mode not in {"rb", "wb"}:
            raise ValueError('open() requires mode "rb" or "wb"')
        if mode == "rb":
            handle = None
            with suppress(KeyError):
                handle = self._tarfile.extractfile(self.at)
            if handle is None:
                raise FileNotFoundError(f"No such file: '{self.at}'")
            yield handle
        elif self._has_member():
            raise FileExistsError(f"cannot write to an existing path: '{self.at}'")
        else:
            # TODO this is not as memory performant as the zipfile implementation,
            # which writes directly to the zipfile (issue #1)
            stream = io.BytesIO()
            yield stream
            info = tarfile.TarInfo(name=self.at)
            info.size = stream.getbuffer().nbytes
            stream.seek(0)
            self._tarfile.addfile(tarinfo=info, fileobj=stream)

    def write_bytes(self, content: bytes):
        """Create the file and write bytes to it."""
        if self._has_member():
            raise FileExistsError(f"cannot write to an existing path: '{self.at}'")
        stream = io.BytesIO(content)
        info = tarfile.TarInfo(name=self.at)
        info.size = len(content)
        self._tarfile.addfile(tarinfo=info, fileobj=stream)

    def write_text(self, content: str, encoding="utf8"):
        """Create the file and write text to it."""
        self.write_bytes(content.encode(encoding))

    def read_bytes(self) -> bytes:
        """Read bytes from the file."""
        handle = None
        with suppress(KeyError):
            handle = self._tarfile.extractfile(self.at)
        if handle is None:
            raise FileNotFoundError(f"No such file: '{self.at}'")
        return handle.read()

    def read_text(self, encoding="utf8") -> str:
        """Read text from the file."""
        content = self.read_bytes()
        return content.decode(encoding=encoding)

    def iterdir(self) -> Iterable["TarPath"]:
        """Iterate over the files and folders in this directory (non-recursive)."""
        if self.is_file():
            raise NotADirectoryError(f"Not a directory: '{self.at}'")

        found_name = False
        for name in self._all_at_set():
            if name == self.at:
                found_name = True
            elif posixpath.dirname(name) == self.at:
                yield self.__class__(self, at=name)

        if not found_name:
            raise FileNotFoundError(f"No such file or directory: '{self.at}'")

    def glob(self, pattern: str, include_virtual: bool = True):
        """Iterate over this subtree and yield all existing files (of any
        kind, including directories) matching the given relative pattern.

        :param pattern: the pattern to match (e.g. use ``**/*`` to yield all).
        :param include_virtual: whether to yield paths that are not stored in the tar index.

        """
        iterator = (
            self._all_at_set()
            if include_virtual
            else {name.rstrip("/") for name in self._tarfile.getnames()}
        )
        for name in match_glob(self.at, pattern, iterator):
            yield self.__class__(self, at=name)

    # shutil like interface

    def putfile(self, path: Union[str, Path]):
        """Copy a file's bytes to this path in the tar file."""
        if "r" in self.root.mode:  # type: ignore
            raise IOError("Cannot write a file in read ('r') mode")

        path = cast(Path, Path(path))
        if not path.exists():
            raise FileNotFoundError(f"Source file not found: {path}")
        if not path.is_file():
            raise IOError(f"Source is not a file: {path}")

        if self.exists():
            raise FileExistsError(f"cannot copy to an existing path: '{self.at}'")

        self._tarfile.add(str(path), self.at, recursive=False)

    def puttree(
        self,
        path: Union[str, Path],
        pattern: str = "**/*",
        symlinks: bool = False,
        check_exists: bool = True,
        callback: Optional[Callable[[str, Any], None]] = None,
        cb_descript: str = "Compressing objects",
    ):
        """Recursively copy a directory tree to this path in the tar file.

        Note: only files and directories will be copied.

        :param pattern: the glob pattern used to iterate through the path directory.
            Use this to filter files to copy.
        :param symlinks: whether to copy symbolic links
        :param check_exists: whether to check if the TarPath already exists
            (this can be time consuming for a large tar)
        :param callback: a callback to report on the process, ``callback(action, value)``,
            with the following callback signatures:

            - ``callback('init', {'total': <int>, 'description': <str>})``,
                to signal the start of a process, its total iterations and description
            - ``callback('update', <int>)``,
                to signal an update to the process and the number of iterations to progress

        :param cb_descript: the description to return in the callback

        """
        if "r" in self.root.mode:  # type: ignore
            raise IOError("Cannot write a directory in read ('r') mode")

        path = cast(Path, Path(path))
        if not path.exists():
            raise FileNotFoundError(f"Source file not found: {path}")
        if not path.is_dir():
            raise IOError(f"Source is not a directory: {path}")

        if check_exists and self.exists():
            raise FileExistsError(f"cannot copy to an existing path: '{self.at}'")

        if callback is None:
            callback = lambda action, value: None  # noqa: E731
        else:
            callback(
                "init", {"total": 1, "description": "Counting objects to compress"}
            )
            count = sum(1 for _ in path.glob(pattern))
            callback("init", {"total": count, "description": cb_descript})

        # always write the base folder
        self._tarfile.add(str(path), self.at, recursive=False)

        for subpath in path.glob(pattern):
            callback("update", 1)
            if subpath.is_dir() or (
                subpath.is_file() and (symlinks or not subpath.is_symlink())
            ):
                tarpath = posixpath.normpath(
                    posixpath.join(self.at, subpath.relative_to(path).as_posix())
                )
                self._tarfile.add(str(subpath), tarpath, recursive=False)

    def extract_tree(
        self,
        outpath: Union[str, Path],
        *,
        pattern: str = "**/*",
        allow_dev: bool = False,
        allow_symlink: bool = False,
        callback: Optional[Callable[[str, Any], None]] = None,
        cb_descript: str = "Extracting objects",
    ):
        """Extract the archive path (and recursive children) to an external path.

        :param outpath: The path to output to
        :param pattern: the glob pattern for selecting children to extract
        :param allow_dev: output block devices
        :param allow_symlink: output symlinks

        :param callback: a callback to report on the process, ``callback(action, value)``,
            with the following callback signatures:

            - ``callback('init', {'total': <int>, 'description': <str>})``,
                to signal the start of a process, its total iterations and description
            - ``callback('update', <int>)``,
                to signal an update to the process and the number of iterations to progress

        :param cb_descript: the description to return in the callback

        :raises NotADirectoryError: If the zip path is not a directory

        """
        if not self.is_dir():
            raise NotADirectoryError(f"Source is not a directory: {self.at}")

        if callback is None:
            callback = lambda action, value: None  # noqa: E731
        else:
            callback("init", {"total": 1, "description": "Counting objects to extract"})
            count = sum(1 for _ in self.glob(pattern, include_virtual=False))
            callback("init", {"total": count, "description": cb_descript})

        # always make base directory
        Path(outpath).joinpath(PurePosixPath(self.at)).mkdir(
            parents=True, exist_ok=True
        )

        for path in self.glob(pattern, include_virtual=False):
            callback("update", 1)
            info = self._tarfile.getmember(path.at)
            if (not allow_dev) and info.isdev():
                continue
            if (not allow_symlink) and (info.islnk() or info.issym()):
                continue
            self._tarfile.extract(path=outpath, member=info)


@contextmanager
def open_file_in_tar(
    filepath: str, path: str, *, mode: str = "r:*"
) -> Iterator[IO[bytes]]:
    """Open a file from inside a tar file.

    This function is optimised for cpu/memory performance,
    since it returns the file as soon as its index is found in the tar registry,
    and does not construct the full index in memory.

    For best performance, the path should have been stored near the start of the index.

    :param filepath: the path to the zip file
    :param path: the relative path within the zip file

    :raises IOError: If the zip file cannot be read
    :raises FileNotFoundError: If the path in the zip file does not exist
    """
    assert mode.startswith("r")
    try:
        with tarfile.open(filepath, mode, format=tarfile.PAX_FORMAT) as tar_handle:
            tarinfo = None
            while True:
                tarinfo = tar_handle.next()  # noqa: B305
                if tarinfo is None or tarinfo.name == path:
                    break
                # flush stored members
                tar_handle.members = []  # type: ignore
            if tarinfo is None:
                raise FileNotFoundError(f"required file `{path}` is not included")
            handle = tar_handle.extractfile(tarinfo)
            if handle is None:
                raise FileNotFoundError(f"required file `{path}` is not included")
            yield handle
    except tarfile.ReadError:
        raise IOError("The input file format is not valid (not a tar file)")
    except (KeyError, AttributeError):
        raise FileNotFoundError(f"required file `{path}` is not included")


def read_file_in_tar(
    filepath: str, path: str, encoding: Optional[str] = "utf8", mode="r:*"
) -> Union[bytes, str]:
    """Read a text based file from inside a tar file and return its content.

    This function is optimised for cpu/memory performance,
    since it returns the file as soon as its index is found in the tar registry,
    and does not construct the full index in memory.

    For best performance, the path should have been stored near the start of the index.

    :param filepath: the path to the tar file
    :param path: the relative path within the tar file
    :param encoding: If not None, decode the bytes with this encoding

    :raises IOError: If the zip file cannot be read
    :raises FileNotFoundError: If the path in the zip file does not exist

    """
    with open_file_in_tar(filepath, path, mode=mode) as handle:
        output = handle.read()
    if encoding is not None:
        return output.decode(encoding)
    return output
