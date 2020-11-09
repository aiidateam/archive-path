# -*- coding: utf-8 -*-
###########################################################################
# Copyright (c), The AiiDA team. All rights reserved.                     #
#                                                                         #
# The code is hosted at https://github.com/aiidateam/archive-path         #
# For further information on the license, see the LICENSE file            #
###########################################################################
"""Test compression utilities"""
import pytest

from archive_path import TarPath, ZipPath, read_file_in_tar, read_file_in_zip


@pytest.mark.parametrize(
    "klass,filename,write_mode,read_mode,read_func",
    [
        (ZipPath, "test.zip", "w", "r", read_file_in_zip),
        (TarPath, "test.tar.gz", "w:gz", "r:gz", read_file_in_tar),
    ],
    ids=("zip", "tar.gz"),
)
def test_path(tmp_path, klass, filename, write_mode, read_mode, read_func):
    """Test basic functionality and equivalence of ``ZipPath`` and ``TarPath``."""

    # test write
    with klass(tmp_path / filename, mode=write_mode) as file_write:

        assert file_write.at == ""
        new_file = file_write / "new_file.txt"
        assert new_file.at == "new_file.txt"
        assert not new_file.exists()
        new_file.write_text("some text")
        assert new_file.exists()
        assert new_file.is_file()
        with pytest.raises(
            FileExistsError, match="cannot write to an existing path: 'new_file.txt'"
        ):
            new_file.write_text("some text")
        file_write.joinpath("bytes.exe").write_bytes(b"some bytes")
        with file_write.joinpath("bytes2.exe").open("wb") as handle:
            handle.write(b"some other bytes")

        # test shutil functionality
        tmp_path.joinpath("other_file.txt").write_text("other text")
        file_write.joinpath("folder", "other_file.txt").putfile(
            tmp_path.joinpath("other_file.txt")
        )
        assert file_write.joinpath("folder").exists()
        assert file_write.joinpath("folder").is_dir()

        tmp_path.joinpath("other_folder", "sub_folder").mkdir(parents=True)
        tmp_path.joinpath("other_folder", "nested1", "nested2").mkdir(parents=True)
        tmp_path.joinpath("other_folder", "sub_file.txt").write_text("sub_file text")
        (file_write / "other_folder").puttree(tmp_path.joinpath("other_folder"))

        assert file_write._all_at_set() == {  # pylint: disable=protected-access
            "",
            "new_file.txt",
            "other_folder/nested1",
            "bytes.exe",
            "bytes2.exe",
            "folder",
            "folder/other_file.txt",
            "other_folder/nested1/nested2",
            "other_folder",
            "other_folder/sub_file.txt",
            "other_folder/sub_folder",
        }
        assert {p.at for p in new_file.parent.iterdir()} == {
            "new_file.txt",
            "bytes.exe",
            "bytes2.exe",
            "folder",
            "other_folder",
        }
        assert {p.at for p in file_write.glob("**/*")} == {
            "new_file.txt",
            "other_folder/nested1",
            "bytes.exe",
            "bytes2.exe",
            "folder",
            "folder/other_file.txt",
            "other_folder/nested1/nested2",
            "other_folder",
            "other_folder/sub_file.txt",
            "other_folder/sub_folder",
        }
        assert {p.at for p in file_write.glob("*")} == {
            "new_file.txt",
            "bytes.exe",
            "bytes2.exe",
            "folder",
            "other_folder",
        }
        assert {p.at for p in file_write.glob("**/*.txt")} == {
            "new_file.txt",
            "folder/other_file.txt",
            "other_folder/sub_file.txt",
        }

    # test read
    file_read = klass(tmp_path / filename, mode=read_mode)

    assert {p.at for p in file_read.iterdir()} == {
        "new_file.txt",
        "bytes.exe",
        "bytes2.exe",
        "folder",
        "other_folder",
    }
    assert {p.at for p in file_read.joinpath("folder").iterdir()} == {
        "folder/other_file.txt"
    }
    assert {p.at for p in file_read.joinpath("other_folder").iterdir()} == {
        "other_folder/sub_folder",
        "other_folder/sub_file.txt",
        "other_folder/nested1",
    }
    assert (file_read / "new_file.txt").read_text() == "some text"
    assert (file_read / "bytes.exe").read_bytes() == b"some bytes"
    with (file_read / "bytes2.exe").open("rb") as handle:
        assert handle.read() == b"some other bytes"
    assert (file_read / "folder" / "other_file.txt").read_text() == "other text"

    # test read single file
    assert read_func(tmp_path / filename, "new_file.txt") == "some text"
    with pytest.raises(FileNotFoundError):
        read_func(tmp_path / filename, "unknown.txt")

    # test equality
    assert file_read == file_write
    assert klass(tmp_path / filename) == klass(tmp_path / filename)
    assert (klass(tmp_path / filename) / "a") == klass(tmp_path / filename).joinpath(
        "a"
    )
