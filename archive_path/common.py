# -*- coding: utf-8 -*-
###########################################################################
# Copyright (c), The AiiDA team. All rights reserved.                     #
#                                                                         #
# The code is hosted at https://github.com/aiidateam/archive-path         #
# For further information on the license, see the LICENSE file            #
###########################################################################
"""Shared code."""
from fnmatch import fnmatch
import itertools
import posixpath
from typing import Iterable


def _parents(path: str) -> Iterable[str]:
    """
    Given a path with elements separated by
    posixpath.sep, generate all parents of that path.

    >>> list(_parents('b/d'))
    ['b']
    >>> list(_parents('/b/d/'))
    ['/b']
    >>> list(_parents('b/d/f/'))
    ['b/d', 'b']
    >>> list(_parents('b'))
    []
    >>> list(_parents(''))
    []
    """
    return itertools.islice(_ancestry(path), 1, None)


def _ancestry(path: str) -> Iterable[str]:
    """
    Given a path with elements separated by
    posixpath.sep, generate all elements of that path

    >>> list(_ancestry('b/d'))
    ['b/d', 'b']
    >>> list(_ancestry('/b/d/'))
    ['/b/d', '/b']
    >>> list(_ancestry('b/d/f/'))
    ['b/d/f', 'b/d', 'b']
    >>> list(_ancestry('b'))
    ['b']
    >>> list(_ancestry(''))
    []
    """
    path = path.rstrip(posixpath.sep)
    while path and path != posixpath.sep:
        yield path
        path, _ = posixpath.split(path)


def match_glob(base: str, pattern: str, iterator: Iterable[str]) -> Iterable[str]:
    """Yield paths in the iterator that match the pattern, relative to a base path."""
    # TODO I haven't yet found any simple glob match implementation yet (#4)
    if not pattern:
        return

    pat_parts = posixpath.normpath(pattern).split("/")

    if len(pat_parts) == 1:
        recursive = False
        match = pat_parts[0]
    elif len(pat_parts) == 2 and pat_parts[0] == "**":
        recursive = True
        match = pat_parts[1]
    else:
        raise NotImplementedError(f"glob pattern: {pattern}")

    at_parts = base.split("/") if base else []
    at_parts_len = len(at_parts)

    for name in iterator:
        name_parts = name.split("/") if name else []
        if len(name_parts) <= at_parts_len:
            continue
        if (not recursive) and (len(name_parts) != (at_parts_len + 1)):
            continue
        if name_parts[:at_parts_len] != at_parts:
            continue
        if fnmatch(name_parts[-1], match):
            yield name
