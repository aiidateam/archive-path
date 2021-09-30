import tarfile
import zipfile

import pytest

from archive_path import TarPath, ZipPath
from archive_path.common import match_glob


@pytest.mark.parametrize(
    "base,pattern,iterator,expected",
    [
        ("", "*", ["a", "b", "b/c", "b/c/d", ""], ["a", "b"]),
        ("", "a", ["a", "b", "b/c", "b/c/d", ""], ["a"]),
        ("b", "*", ["a", "b", "b/c", "b/c/d", ""], ["b/c"]),
        ("", "**/*", ["a", "b", "b/c", "b/c/d", ""], ["a", "b", "b/c", "b/c/d"]),
        ("b", "**/*", ["a", "b", "b/c", "b/c/d", ""], ["b/c", "b/c/d"]),
        ("b", "**/c", ["a", "b", "b/c", "b/c/d", ""], ["b/c"]),
        (
            "b",
            "**/*.txt",
            ["a", "b", "b/c", "b/c/d.txt", "b/c/e.txt", ""],
            ["b/c/d.txt", "b/c/e.txt"],
        ),
    ],
)
def test_match_glob(base, pattern, iterator, expected):
    assert set(match_glob(base, pattern, iterator)) == set(expected)


def test_glob_all_zip(tmp_path):
    """Test that the `*/**` pattern matches the central directory list."""
    for name in ("a", "b", "c"):
        tmp_path.joinpath(name).touch()
    tmp_path.joinpath("d").mkdir()
    tmp_path.joinpath("e").joinpath("f").mkdir(parents=True)
    for name in ("x", "y", "z"):
        tmp_path.joinpath("e").joinpath("f").joinpath(name).touch()
    with zipfile.ZipFile(tmp_path / "archive.zip", "w") as zipper:
        for path in tmp_path.glob("**/*"):
            if path.name in ("archive.zip", "e"):
                continue
            zipper.write(str(path), path.relative_to(tmp_path).as_posix())
        namelist = sorted(n.rstrip("/") for n in zipper.namelist())
    with ZipPath(tmp_path / "archive.zip") as zpath:
        assert (
            sorted(p.at for p in zpath.glob("**/*", include_virtual=False)) == namelist
        )


def test_glob_all_tar(tmp_path):
    """Test that the `*/**` pattern matches the central directory list."""
    for name in ("a", "b", "c"):
        tmp_path.joinpath(name).touch()
    tmp_path.joinpath("d").mkdir()
    tmp_path.joinpath("e").joinpath("f").mkdir(parents=True)
    for name in ("x", "y", "z"):
        tmp_path.joinpath("e").joinpath("f").joinpath(name).touch()
    with tarfile.TarFile(tmp_path / "archive.tar", "w") as zipper:
        for path in tmp_path.glob("**/*"):
            if path.name in ("archive.tar", "e"):
                continue
            zipper.add(
                str(path), path.relative_to(tmp_path).as_posix(), recursive=False
            )
        namelist = sorted(n.rstrip("/") for n in zipper.getnames())
    with TarPath(tmp_path / "archive.tar") as zpath:
        assert (
            sorted(p.at for p in zpath.glob("**/*", include_virtual=False)) == namelist
        )
