# SPDX-License-Identifier: MIT
# Copyright (c) 2024 Nathan Juraj Michlo

import sys

# check the python version
if sys.version_info < (3, 10):
    print("please use python >= 3.10")
    exit(1)


# TODO: for python 3.10 and up, can use `sys.stdlib_module_names` or `sys.builtin_module_names`
BUILTIN_MODULE_NAMES = {
    # "__main__",
    # *sys.builtin_module_names,
    # *sys.stdlib_module_names,
    *_stdlib_list(),
}


__all__ = ("BUILTIN_MODULE_NAMES",)
