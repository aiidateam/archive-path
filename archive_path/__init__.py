# -*- coding: utf-8 -*-
###########################################################################
# Copyright (c), The AiiDA team. All rights reserved.                     #
#                                                                         #
# The code is hosted at https://github.com/aiidateam/archive-path         #
# For further information on the license, see the LICENSE file            #
###########################################################################
"""A package to provide pathlib like access to zip & tar archives."""
from .tar_path import *  # noqa: F401,F403
from .zip_path import *  # noqa: F401,F403

__version__ = "0.3.1"
