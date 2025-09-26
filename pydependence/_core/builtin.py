# SPDX-License-Identifier: MIT
# Copyright (c) 2024 Nathan Juraj Michlo

__all__ = [
    "BUILTIN_MODULE_NAMES",
]

import sys

# check the python version
BUILTIN_MODULE_NAMES = {
    "__main__",
    *sys.builtin_module_names,
    *sys.stdlib_module_names,
}
