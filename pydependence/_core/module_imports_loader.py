# SPDX-License-Identifier: MIT
# Copyright (c) 2024 Nathan Juraj Michlo


import dataclasses
from typing import Dict, List, Tuple

from pydependence._core.module_data import ModuleMetadata
from pydependence._core.module_imports_ast import (
    LocImportInfo,
    load_imports_from_module_info,
)

# ========================================================================= #
# MODULE IMPORTS                                                            #
# ========================================================================= #


@dataclasses.dataclass
class ModuleImports:
    module_info: ModuleMetadata
    module_imports: "Dict[str, List[LocImportInfo]]"

    @classmethod
    def from_module_info_and_parsed_file(cls, module_info: ModuleMetadata):
        module_imports = load_imports_from_module_info(module_info=module_info)
        return ModuleImports(
            module_info=module_info,
            module_imports=dict(module_imports),
        )


# ========================================================================= #
# MODULE IMPORTS LOADER                                                     #
# ========================================================================= #


class _ModuleImportsLoader:
    def __init__(self):
        # TODO: tag could severally hurt performance? maybe should change data structure slightly?
        #       problem is tag is nested and applied to imports too. HOWEVER, Usually tag is
        #       automatically generated from the package name, so might not matter too much in practice.
        self._modules_imports: "Dict[Tuple[str, str], ModuleImports]" = {}

    def load_module_imports(self, module_info: ModuleMetadata) -> ModuleImports:
        k = (module_info.name, module_info.tag)
        v = self._modules_imports.get(k, None)
        if v is None:
            v = ModuleImports.from_module_info_and_parsed_file(module_info)
            self._modules_imports[k] = v
        else:
            if v.module_info != module_info:
                raise RuntimeError(
                    f"ModuleMetadata mismatch: {v.module_info} != {module_info}"
                )
        return v


# GLOBAL INSTANCE
# TODO: can replace with disk cache
DEFAULT_MODULE_IMPORTS_LOADER = _ModuleImportsLoader()


# ========================================================================= #
# END                                                                       #
# ========================================================================= #


__all__ = (
    "ModuleImports",
    "DEFAULT_MODULE_IMPORTS_LOADER",
)
