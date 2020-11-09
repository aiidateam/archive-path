import pytest

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
