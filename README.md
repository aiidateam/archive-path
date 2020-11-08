# archive-path

[![Build Status][ci-badge]][ci-link]
[![codecov.io][cov-badge]][cov-link]
[![PyPI version][pypi-badge]][pypi-link]

A package to provide pathlib like access to zip & tar archives.

## Usage

For reading zip (`ZipPath`) or tar (`TarPath`) files:

```python
from archive_path import TarPath, ZipPath

path = TarPath("path/to/file.tar.gz", mode="r:gz")

sub_path = path / "folder" / "file.txt"
assert sub_path.filepath == "path/to/file.tar.gz"
assert sub_path.at == "folder/file.txt"
assert sub_path.exists() and sub_path.is_file()
assert sub_path.parent.is_dir()
content = sub_path.read_text()

for sub_path in path.iterdir():
    print(sub_path)
```

For writing files, you should use within a context manager, or directly call the `close` method:

```python
with TarPath("path/to/file.tar.gz", mode="w:gz") as path:

    (path / "new_file.txt").write_text("hallo world")
    # there are also some features equivalent to shutil
    (path / "other_file.txt").putfile("path/to/external_file.txt")
    (path / "other_folder").puttree("path/to/external_folder", pattern="**/*")
```

Note that archive formats do not allow to overwrite existing files (they will raise a `FileExistsError`).

For performant access to single files:

```python
from archive_path import read_file_in_tar, read_file_in_zip

content = read_file_in_tar("path/to/file.tar.gz", "file.txt", encoding="utf8")
```

These methods allow for faster access to files (using less RAM) in archives containing 1000's of files.
This is because, the archive's file index is only read until the path is found (discarding non-matches),
rather than the standard `tarfile`/`zipfile` approach that is to read the entire index into memory first.

## Windows compatibility

Paths within the archives are **always** read and written as being `/` delimited.
This means that the package works on Windows,
but will not be compatible with archives written outside this package with `\\` path delimiters.

## Development

This package utilises [flit](https://flit.readthedocs.io) as the build engine, and [tox](https://tox.readthedocs.io) for test automation.

To install these development dependencies:

```bash
pip install tox
```

To run the tests:

```bash
tox
```

and with test coverage:

```bash
tox -e py37-cov
```

The easiest way to write tests, is to edit tests/fixtures.md

To run the code formatting and style checks:

```bash
tox -e py37-pre-commit
```

or directly

```bash
pip install pre-commit
pre-commit run --all
```

## Publish to PyPi

Either use flit directly:

```bash
pip install flit
flit publish
```

or trigger the GitHub Action job, by creating a release with a tag equal to the version, e.g. `v0.1.1`.

Note, this requires generating an API key on PyPi and adding it to the repository `Settings/Secrets`, under the name `PYPI_KEY`.

[ci-badge]: https://github.com/aiidateam/archive-path/workflows/CI/badge.svg?branch=main
[ci-link]: https://github.com/aiidateam/archive-path/actions?query=workflow%3ACI+branch%3Amain+event%3Apush
[cov-badge]: https://codecov.io/gh/aiidateam/archive-path/branch/main/graph/badge.svg
[cov-link]: https://codecov.io/gh/aiidateam/archive-path
[pypi-badge]: https://img.shields.io/pypi/v/archive-path.svg
[pypi-link]: https://pypi.org/project/archive-path
