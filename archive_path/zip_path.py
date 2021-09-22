# -*- coding: utf-8 -*-
###########################################################################
# Copyright (c), The AiiDA team. All rights reserved.                     #
#                                                                         #
# The code is hosted at https://github.com/aiidateam/archive-path         #
# For further information on the license, see the LICENSE file            #
###########################################################################
"""A implementation of the ``pathlib.Path`` interface for ``zipfile.ZipFile``.

The implementation is partially based on back-porting ``zipfile.Path`` (new in python 3.8)
"""
from collections import abc
from contextlib import contextmanager, suppress
import io
import itertools
import os
from pathlib import Path, PurePosixPath
import posixpath
import shutil
import threading
from types import TracebackType
from typing import (
    IO,
    Any,
    BinaryIO,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Type,
    Union,
    cast,
)
import zipfile

from .common import _parents, match_glob

__all__ = (
    "ZipPath",
    "ZipFileExtra",
    "FilteredZipInfo",
    "StopZipIndexRead",
    "open_file_in_zip",
    "read_file_in_zip",
    "extract_file_in_zip",
    "NOTSET",
)

NOTSET = ()


class ZipPath:
    """A wrapper around ``zipfile.ZipFile``,
    to provide an interface equivalent to ``pathlib.Path``

    For reading zip files, you can use it directly::

        path = ZipPath('path/to/file.zip', mode='r')
        sub_path = path / 'folder' / 'file.txt'
        assert sub_path.filepath == 'path/to/file.zip'
        assert sub_path.at == 'folder/file.txt'
        assert sub_path.exists() and sub_path.is_file()
        assert sub_path.parent.is_dir()
        content = sub_path.read_text()

    For writing zip files, you should use within a context manager,
    or directly call the ``close`` method::

        with ZipPath('path/to/file.zip', mode='w', compression=zipfile.ZIP_DEFLATED) as path:
            (path / 'new_file.txt').write_text('hallo world')
            # there are also some features equivalent to shutil
            (path / 'other_file.txt').putfile('path/to/external_file.txt')
            (path / 'other_folder').puttree('path/to/external_folder', pattern='**/*')

    Note that ``zipfile`` does not allow to overwrite existing files
    (it will raise a ``FileExistsError``).

    """

    __repr = "{self.__class__.__name__}({self.root.filename!r}, {self.at!r})"

    def __init__(
        self,
        path: Union[str, Path, "ZipPath"],
        *,
        mode: str = "r",
        at: str = "",  # pylint: disable=invalid-name
        allow_zip64: bool = True,
        compression: int = zipfile.ZIP_DEFLATED,
        compresslevel: Optional[int] = None,
        name_to_info: Optional[Dict[str, zipfile.ZipInfo]] = None,
        info_order: Sequence[str] = (),
    ):
        """Initialise a zip path item.

        :param path: the path to the zip file, or another instance of a ZipPath
        :param at: the path within the zipfile (always use posixpath `/` separators)
        :param mode: the mode with which to open the zipfile,
            either read 'r', write 'w', exclusive create 'x', or append 'a'

        write only options:

        :param allow_zip64: if True, the ZipFile will create files with ZIP64 extensions when needed
        :param compression: compression type
            ``zipfile.ZIP_STORED`` (no compression), ``zipfile.ZIP_DEFLATED`` (requires zlib),
            ``zipfile.ZIP_BZIP2`` (requires bz2) or ``zipfile.ZIP_LZMA`` (requires lzma)
        :param name_to_info: The dictionary for storing mappings of filename -> ``ZipInfo``,
            if ``None``, defaults to ``{}``.
            This can be used to implement on-disk storage of the zip central directory
        :param info_order: ``ZipInfo`` for these file names will be written first
            to the zip central directory.
            These allows for faster reading of key files, in a zip that contains
            many 1000s of files (see ``FilteredZipInfo``).

        """
        if posixpath.isabs(at):
            raise ValueError(f"'at' cannot be an absolute path: {at}")
        assert not any(
            p == ".." for p in at.split(posixpath.sep)
        ), "'at' should not contain any '..'"

        # Note ``zipfile.ZipInfo.filename`` of directories always end `/`
        # but we store without, to e.g. correctly compute parent/file names
        self._at = at.rstrip("/")

        if isinstance(path, (str, Path)):
            self._filepath = Path(path)
            self._zipfile = ZipFileExtra(
                path,
                mode=mode,
                compression=compression,
                compresslevel=compresslevel,
                allowZip64=allow_zip64,
                name_to_info=name_to_info,
                info_order=info_order,
            )
        else:
            self._filepath = path._filepath
            self._zipfile = path._zipfile

    def __str__(self):
        return (
            posixpath.join(self.root.filename, self.at)  # type: ignore[attr-defined]
            if self.root.filename
            else self.at
        )

    def __repr__(self):
        return self.__repr.format(self=self)

    def __eq__(self, item: object) -> bool:
        """Return whether the external and internal path are equal"""
        if not isinstance(item, ZipPath):
            return False
        if item._at != self._at:
            return False
        return item._filepath.resolve(strict=False) == self._filepath.resolve(
            strict=False
        )

    @property
    def filepath(self) -> Path:
        """Return the path to the zip file."""
        return self._filepath

    @property
    def root(self) -> zipfile.ZipFile:
        """Return the root zip file."""
        return self._zipfile

    @property
    def at(self) -> str:  # pylint: disable=invalid-name
        """Return the current internal path within the zip file."""
        return self._at

    def _all_at_set(self) -> Set[str]:
        """Iterate through all file and directory paths in the zip file.

        Note: this is necessary,
        since the zipfile does not strictly store all directories in the namelist.

        It is cached on the zipfile instance if it is in read mode ('r'),
        since then the name list cannot change.

        """
        read_mode = self._zipfile.mode == "r"  # type: ignore
        if read_mode:
            with suppress(AttributeError):
                return self._zipfile.__all_at  # type: ignore
        names = self._zipfile.namelist()
        parents = itertools.chain.from_iterable(map(_parents, names))
        all_set = {p.rstrip("/") for p in itertools.chain([""], names, parents)}
        if read_mode:
            self._zipfile.__all_at = all_set  # type: ignore
        return all_set

    def close(self):
        """Close the zipfile."""
        self._zipfile.close()

    def __enter__(self):
        """Enter the zipfile for reading/writing."""
        return self

    def __exit__(
        self,
        exctype: Optional[Type[BaseException]],
        excinst: Optional[BaseException],
        exctb: Optional[TracebackType],
    ):
        """Exit the zipfile and close."""
        self.close()

    # pathlib like interface

    @property
    def name(self):
        """Return the basename of the current internal path within the zip file."""
        return posixpath.basename(self.at)

    @property
    def parent(self) -> "ZipPath":
        """Return the parent of the current internal path within the zip file."""
        parent_at = posixpath.dirname(self.at)
        return self.__class__(self, at=parent_at)

    def is_dir(self):
        """Whether this path is an existing directory."""
        return self.exists() and not self.is_file()

    def is_file(self):
        """Whether this path is an existing regular file."""
        try:
            info = self._zipfile.getinfo(self.at)
        except KeyError:
            return False
        return not info.is_dir()

    def exists(self) -> bool:
        """Whether this path exists."""
        if self.at == "":
            return True
        with suppress(KeyError):
            self._zipfile.getinfo(self.at)
            return True
        with suppress(KeyError):
            self._zipfile.getinfo(self.at + "/")
            return True
        # note, we could just check this, but it can takes time/memory to construct
        return self.at in self._all_at_set()

    def joinpath(self, *paths) -> "ZipPath":
        """Combine this path with one or several arguments, and return a new path."""
        return self.__class__(self, at=posixpath.join(self.at, *paths))

    def __truediv__(self, path: str) -> "ZipPath":
        """Combine this path with another, and return a new path."""
        return self.__class__(self, at=posixpath.join(self.at, path))

    @contextmanager  # noqa: A003
    def open(  # noqa: A003
        self, mode: str = "rb", *, compression=NOTSET, level=NOTSET, comment=NOTSET
    ):
        """Open the file pointed by this path and return a file object.

        write only parameters:

        :param compression: the ZIP compression method to use when writing the archive,
                if not set use default value,
                ZIP_STORED (no compression), ZIP_DEFLATED (requires zlib),
                ZIP_BZIP2 (requires bz2) or ZIP_LZMA (requires lzma).
        :param level: control the compression level to use when writing files to the archive
                When using ZIP_DEFLATED integers 0 through 9 are accepted.
                When using ZIP_BZIP2 integers 1 through 9 are accepted.
        :param comment: A binary comment, stored in the central directory
        """
        # zip file open misleading signals 'r', 'w', when actually they are byte mode
        zinfo: Union[str, zipfile.ZipInfo]
        if mode == "wb":
            zinfo = zipfile.ZipInfo(self.at)
            zinfo.compress_type = (
                self._zipfile.compression if compression is NOTSET else compression
            )
            zinfo._compresslevel = (  # type: ignore
                self._zipfile.compresslevel if level is NOTSET else level
            )
            if comment is not NOTSET:
                zinfo.comment = comment
        elif mode == "rb":
            zinfo = self.at
        else:
            raise ValueError('open() requires mode "rb" or "wb"')
        with self.root.open(zinfo, mode=mode[0]) as handle:
            yield handle

    def _write(self, content: Union[str, bytes]):
        """Write content to the zip path."""
        info = None
        with suppress(KeyError):
            info = self._zipfile.getinfo(self.at)
        if info is not None:
            raise FileExistsError(f"cannot write to an existing path: '{self.at}'")
        self._zipfile.writestr(self.at, content)

    def write_bytes(self, content: bytes):
        """Create the file and write bytes to it."""
        self._write(content)

    def write_text(self, content: str, encoding="utf8"):
        """Create the file and write text to it."""
        self._write(content.encode(encoding=encoding))

    def read_bytes(self) -> bytes:
        """Read bytes from the file."""
        try:
            content = self._zipfile.read(self.at)
        except KeyError:
            raise FileNotFoundError(f"No such file: '{self.at}'")
        return content

    def read_text(self, encoding="utf8") -> str:
        """Read text from the file."""
        content = self.read_bytes()
        return content.decode(encoding=encoding)

    def iterdir(self) -> Iterable["ZipPath"]:
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

        :param pattern: the pattern to match (e.g. use ``**/*`` to yield all)
        :param include_virtual: whether to yield paths that are not stored in the tar index

        """
        iterator = (
            self._all_at_set()
            if include_virtual
            else {name.rstrip("/") for name in self._zipfile.namelist()}
        )
        for name in match_glob(self.at, pattern, iterator):
            yield self.__class__(self, at=name)

    # shutil like interface

    def putfile(self, path: Union[str, Path]):
        """Copy a file's bytes to this path in the zip file."""
        if "r" in self.root.mode:  # type: ignore
            raise IOError("Cannot write a file in read ('r') mode")

        path = cast(Path, Path(path))
        if not path.exists():
            raise FileNotFoundError(f"Source file not found: {path}")
        if not path.is_file():
            raise IOError(f"Source is not a file: {path}")

        if self.exists():
            raise FileExistsError(f"cannot copy to an existing path: '{self.at}'")

        self._zipfile.write(path, self.at)

    def puttree(
        self,
        path: Union[str, Path],
        pattern: str = "**/*",
        symlinks: bool = False,
        check_exists: bool = True,
        callback: Optional[Callable[[str, Any], None]] = None,
        cb_descript: str = "Compressing objects",
    ):
        """Recursively copy a directory tree to this path in the zip file.

        Note: only files and directories will be copied.

        :param pattern: the glob pattern used to iterate through the path directory.
            Use this to filter files to copy.
        :param symlinks: whether to copy symbolic links
        :param check_exists: whether to check if the ZipPath already exists
            (this can be time consuming for a large zip)
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
        self._zipfile.write(path, self.at)

        for subpath in path.glob(pattern):
            callback("update", 1)
            if subpath.is_dir() or (
                subpath.is_file() and (symlinks or not subpath.is_symlink())
            ):
                zippath = posixpath.normpath(
                    posixpath.join(self.at, subpath.relative_to(path).as_posix())
                )
                self._zipfile.write(subpath, zippath)

    def extract_tree(
        self,
        outpath: Union[str, Path],
        *,
        pattern: str = "**/*",
        callback: Optional[Callable[[str, Any], None]] = None,
        cb_descript: str = "Extracting objects",
    ):
        """Extract the archive path (and recursive children) to an external path.

        :param outpath: The path to output to
        :param pattern: the glob pattern for selecting children to extract

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

        outpath = cast(str, os.path.abspath(outpath))

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
            try:
                info = self._zipfile.getinfo(path.at)
            except KeyError:
                info = self._zipfile.getinfo(path.at + "/")
            self._zipfile.extract(path=outpath, member=info)


class FileList(abc.Sequence):
    """A list of ``zipfile.ZipInfo`` which mirrors the ``zipfile.ZipFile.NameToInfo`` mapping.

    For indexing, assumes that ``NameToInfo`` is an ordered dict.
    """

    def __init__(
        self, name_to_info: Dict[str, zipfile.ZipInfo], info_order: Sequence[str] = ()
    ):
        self._name_to_info = name_to_info
        self._info_order = info_order

    def __getitem__(self, item):
        key = list(self._name_to_info)[item]
        return self._name_to_info[key]

    def __len__(self):
        return self._name_to_info.__len__()

    def __contains__(self, item: Any):
        if not isinstance(item, zipfile.ZipInfo):
            return False
        key = item.filename
        return key in self._name_to_info

    def __iter__(self):
        for key in self._info_order:
            if key in self._name_to_info:
                yield self._name_to_info[key]
        for key, value in self._name_to_info.items():
            if key in self._info_order:
                continue
            yield value

    def __reversed__(self):
        return reversed(list(self._name_to_info.values()))

    def append(self, item: zipfile.ZipInfo):
        """Add a ``ZipInfo`` object."""
        assert isinstance(item, zipfile.ZipInfo)
        assert (
            item.filename not in self._name_to_info
        ), "cannot append an existing ZipInfo"
        self._name_to_info[item.filename] = item


class StopZipIndexRead(Exception):
    """An exception to signal that the reading of the index should be stopped."""


class FilteredZipInfo(abc.MutableMapping):
    """A mapping which only stores pre-defined ``ZipInfo`` s.

    Once all required filenames are set, ``__setitem__`` will raise ``StopZipIndexRead``.

    """

    def __init__(self, filenames: Set[str], max_infos: Optional[int] = None):
        self._dict: Dict[str, zipfile.ZipInfo] = {}
        self._filenames = set(filenames)
        self._max_infos = max_infos
        self._read = 0.0

    def __getitem__(self, name):
        return self._dict.__getitem__(name)

    def __setitem__(self, name, item):
        self._read += (
            1 / 2
        )  # _RealGetContents appends to file list, then adds to mapping
        if name in self._filenames:
            self._dict.__setitem__(name, item)
        if self._max_infos and self._max_infos <= self._read:
            raise StopZipIndexRead
        if set(self._dict) == self._filenames:
            raise StopZipIndexRead

    def __delitem__(self, name):
        self._dict.__delitem__(name)

    def __iter__(self):
        return self._dict.__iter__()

    def __len__(self):
        return self._dict.__len__()


class ZipFileExtra(zipfile.ZipFile):
    """A subclass of ``zipfile.ZipFile``, which allows for specifying the name_to_info mapping.

    This mapping holds the zip file object index, which is fully generated on initiation.
    An example of its use, is when reading zip files with large amounts of objects,
    in a memory light manner::

        import shelve
        with shelve.open('name_to_info') as db:
            zipfile = ZipFileExtra('path/to/file.zip', name_to_info=db)

    Additionally, in read mode, the name_to_info object can raise a
    ``StopZipIndexRead`` on ``__setitem__``.
    This will break the index generation and can be useful,
    for example to efficiently find/read a single object in the zip file::

        zipfile = ZipFileExtra('path/to/file.zip', name_to_info=FilteredZipInfo({'file.txt'}))
        zipfile.read('file.txt')

    """

    def __init__(  # noqa: C901
        self,
        file: Union[str, Path, IO],
        mode: str = "r",
        compression: int = zipfile.ZIP_STORED,
        allowZip64: bool = True,
        compresslevel: Optional[int] = None,
        *,
        strict_timestamps: bool = True,
        name_to_info: Optional[abc.MutableMapping] = None,
        info_order: Sequence[str] = (),
    ):
        """Open the ZIP file with mode read 'r', write 'w', exclusive create 'x', or append 'a'.

        :param file: The zip file to use
        :param mode: The mode in which to open the zip file
        :param compression: the ZIP compression method to use when writing the archive
                ZIP_STORED (no compression), ZIP_DEFLATED (requires zlib),
                ZIP_BZIP2 (requires bz2) or ZIP_LZMA (requires lzma).
        :param compresslevel: control the compression level to use when writing files to the archive
                When using ZIP_DEFLATED integers 0 through 9 are accepted.
                When using ZIP_BZIP2 integers 1 through 9 are accepted.
        :param allowZip64: If True, zipfile will create ZIP files that use the ZIP64 extensions,
            when the zipfile is larger than 4 GiB
        :param strict_timestamps: when set to False, allows to zip files older than 1980-01-01

        :param name_to_info: The dictionary for storing mappings of filename -> ``ZipInfo``,
            if ``None``, defaults to ``{}``
        :param info_order: list of file names (if present) to write first to the central directory
            Writing first means they can be identified faster

        """
        if mode not in ("r", "w", "x", "a"):
            raise ValueError("ZipFile requires mode 'r', 'w', 'x', or 'a'")

        zipfile._check_compression(compression)  # type: ignore

        self._allowZip64: bool = allowZip64
        self._didModify: bool = False
        self.debug: int = 0  # Level of printing: 0 through 3
        # Find file info given name
        self.NameToInfo: Dict[str, zipfile.ZipInfo] = (
            name_to_info if name_to_info is not None else {}  # type: ignore
        )
        # List of ZipInfo instances for archive
        self.filelist: List[zipfile.ZipInfo] = FileList(self.NameToInfo, info_order)  # type: ignore
        self.compression: int = compression  # Method of compression
        self.compresslevel: Optional[int] = compresslevel
        self.mode: str = mode
        self.pwd: Optional[str] = None
        self._comment: bytes = b""
        self._strict_timestamps: bool = strict_timestamps

        self.filename: str
        self._filePassed: int
        self.fp: IO

        # Check if we were passed a file-like object
        if isinstance(file, os.PathLike):
            file = os.fspath(file)
        if isinstance(file, str):
            # No, it's a filename
            self._filePassed = 0
            self.filename = file
            modeDict = {
                "r": "rb",
                "w": "w+b",
                "x": "x+b",
                "a": "r+b",
                "r+b": "w+b",
                "w+b": "wb",
                "x+b": "xb",
            }
            filemode = modeDict[mode]
            while True:
                try:
                    self.fp = io.open(file, filemode)
                except OSError:
                    if filemode in modeDict:
                        filemode = modeDict[filemode]
                        continue
                    raise
                break
        else:
            self._filePassed = 1
            self.fp = cast(IO, file)
            self.filename = getattr(file, "name", None)
        self._fileRefCnt = 1
        self._lock = threading.RLock()
        self._seekable = True
        self._writing = False

        try:
            if mode == "r":
                with suppress(StopZipIndexRead):
                    self._RealGetContents()  # type: ignore
            elif mode in ("w", "x"):
                # set the modified flag so central directory gets written
                # even if no files are added to the archive
                self._didModify = True
                try:
                    self.start_dir = self.fp.tell()
                except (AttributeError, OSError):
                    self.fp = zipfile._Tellable(self.fp)  # type: ignore
                    self.start_dir = 0
                    self._seekable = False
                else:
                    # Some file-like objects can provide tell() but not seek()
                    try:
                        self.fp.seek(self.start_dir)
                    except (AttributeError, OSError):
                        self._seekable = False
            elif mode == "a":
                try:
                    # See if file is a zip file
                    self._RealGetContents()  # type: ignore
                    # seek to start of directory and overwrite
                    self.fp.seek(self.start_dir)
                except zipfile.BadZipFile:
                    # file is not a zip file, just append
                    self.fp.seek(0, 2)

                    # set the modified flag so central directory gets written
                    # even if no files are added to the archive
                    self._didModify = True
                    self.start_dir = self.fp.tell()
            else:
                raise ValueError("Mode must be 'r', 'w', 'x', or 'a'")
        except:  # noqa: E722
            fp = self.fp
            self.fp = None  # type: ignore
            self._fpclose(fp)  # type: ignore
            raise

    def namelist(self):
        """Return a list of file names in the archive."""
        return list(self.NameToInfo)


@contextmanager
def open_file_in_zip(
    filepath: str,
    path: str,
    *,
    search_limit: Optional[int] = None,
) -> Iterator[IO[bytes]]:
    """Open a file from inside a zip file.

    This function is optimised for cpu/memory performance,
    since it returns the file as soon as its index is found in the zip registry,
    and does not construct the full index in memory.

    For best performance, the path should have been stored near the start of the index.

    :param filepath: the path to the zip file
    :param path: the relative path within the zip file
    :param search_limit: Limit the search in the zip to the first n records

    :raises IOError: If the zip file cannot be read
    :raises FileNotFoundError: If the path in the zip file does not exist
    """
    try:
        with ZipFileExtra(
            filepath,
            "r",
            allowZip64=True,
            name_to_info=FilteredZipInfo({path}, max_infos=search_limit),
        ).open(path, "r") as handle:
            yield handle
    except zipfile.BadZipfile as error:
        raise IOError(f"The input file cannot be read: {error}")
    except KeyError:
        raise FileNotFoundError(f"required file {path} is not included")


def read_file_in_zip(
    filepath: str,
    path: str,
    encoding: Optional[str] = "utf8",
    *,
    search_limit: Optional[int] = None,
) -> Union[bytes, str]:
    """Read a file from inside a zip file and return its content.

    This function is optimised for cpu/memory performance,
    since it returns the file as soon as its index is found in the zip registry,
    and does not construct the full index in memory.

    For best performance, the path should have been stored near the start of the index.

    :param filepath: the path to the zip file
    :param path: the relative path within the zip file
    :param encoding: If not None, decode the bytes with this encoding
    :param search_limit: Limit the search in the zip to the first n records

    :raises IOError: If the zip file cannot be read
    :raises FileNotFoundError: If the path in the zip file does not exist

    """
    with open_file_in_zip(filepath, path, search_limit=search_limit) as zip_handle:
        output = zip_handle.read()
    if encoding is not None:
        return output.decode(encoding)
    return output


def extract_file_in_zip(
    filepath: str,
    path: str,
    handle: BinaryIO,
    *,
    buffer_size: Optional[int] = None,
    search_limit: Optional[int] = None,
) -> None:
    """Extract file from inside a zip file and return its content.

    This function is optimised for cpu/memory performance,
    since it returns the file as soon as its index is found in the zip registry,
    and does not construct the full index in memory.

    For best performance, the path should have been stored near the start of the index.

    :param filepath: the path to the zip file
    :param path: the relative path within the zip file
    :param handle: The handle to write to
    :param buffer_size: Specify the byte chunk size for streaming
    :param search_limit: Limit the search in the zip to the first n records

    :raises IOError: If the zip file cannot be read
    :raises FileNotFoundError: If the path in the zip file does not exist

    """
    with open_file_in_zip(filepath, path, search_limit=search_limit) as zip_handle:
        shutil.copyfileobj(
            zip_handle, handle, **({"length": buffer_size} if buffer_size else {})
        )
