# ============================================================================== #
# MIT License                                                                    #
#                                                                                #
# Copyright (c) 2024 Nathan Juraj Michlo                                         #
#                                                                                #
# Permission is hereby granted, free of charge, to any person obtaining a copy   #
# of this software and associated documentation files (the "Software"), to deal  #
# in the Software without restriction, including without limitation the rights   #
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell      #
# copies of the Software, and to permit persons to whom the Software is          #
# furnished to do so, subject to the following conditions:                       #
#                                                                                #
# The above copyright notice and this permission notice shall be included in all #
# copies or substantial portions of the Software.                                #
#                                                                                #
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR     #
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,       #
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE    #
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER         #
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,  #
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE  #
# SOFTWARE.                                                                      #
# ============================================================================== #
import sys
import warnings
from collections import defaultdict
from enum import Enum
from pathlib import Path
from typing import Annotated, Dict, List, Literal, Optional, Union

import pydantic
from packaging.requirements import Requirement

from pydependence._core.module_imports_ast import ManualImportInfo, ManualSource
from pydependence._core.modules_scope import (
    ModulesScope,
    RestrictMode,
    RestrictOp,
    UnreachableModeEnum,
)
from pydependence._core.requirements_map import (
    DEFAULT_REQUIREMENTS_ENV,
    ImportMatcherBase,
    ImportMatcherGlobs,
    ImportMatcherScope,
    ReqMatcher,
    RequirementsMapper,
)
from pydependence._core.requirements_out import OutMappedRequirements
from pydependence._core.utils import (
    apply_root_to_path_str,
    load_toml_document,
    toml_file_replace_array,
    txt_file_dump,
)

# ========================================================================= #
# CONFIGS                                                                   #
# ========================================================================= #


class _ResolveRules(pydantic.BaseModel, extra="forbid"):
    visit_lazy: Optional[bool] = None
    exclude_unvisited: Optional[bool] = None
    exclude_in_search_space: Optional[bool] = None
    exclude_builtins: Optional[bool] = None
    strict_requirements_map: Optional[bool] = None

    @classmethod
    def make_default_base_rules(cls):
        return _ResolveRules(
            visit_lazy=False,
            exclude_unvisited=True,
            exclude_in_search_space=True,
            exclude_builtins=True,
            strict_requirements_map=True,
        )

    def set_defaults(self, defaults: "_ResolveRules"):
        assert defaults.visit_lazy is not None
        assert defaults.exclude_unvisited is not None
        assert defaults.exclude_in_search_space is not None
        assert defaults.exclude_builtins is not None
        assert defaults.strict_requirements_map is not None
        if self.visit_lazy is None:
            self.visit_lazy = defaults.visit_lazy
        if self.exclude_unvisited is None:
            self.exclude_unvisited = defaults.exclude_unvisited
        if self.exclude_in_search_space is None:
            self.exclude_in_search_space = defaults.exclude_in_search_space
        if self.exclude_builtins is None:
            self.exclude_builtins = defaults.exclude_builtins
        if self.strict_requirements_map is None:
            self.strict_requirements_map = defaults.strict_requirements_map


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - #
# CONFIG - OUTPUT                                                           #
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - #


class OutputModeEnum(str, Enum):
    requirements = "requirements"
    optional_dependencies = "optional-dependencies"
    dependencies = "dependencies"


class _Output(_ResolveRules, extra="forbid"):
    # resolve
    scope: Optional[str] = None
    start_scope: Optional[str] = None

    # raw requirements / imports that are mapped
    raw: Optional[List[str]] = None

    # requirements mapping
    env: str = DEFAULT_REQUIREMENTS_ENV

    # output
    output_mode: str
    output_file: str
    output_name: Optional[str] = None

    def get_output_name(self) -> str:
        if self.output_name is not None:
            return self.output_name
        elif self.start_scope is not None:
            return self.start_scope
        elif self.scope is not None:
            return self.scope
        else:
            raise ValueError(
                f"output_name cannot be determined, please set output_name, start_scope, or scope for: {self}"
            )

    def get_manual_imports(self):
        if not self.raw:
            return []
        return [ManualImportInfo.from_target(r) for r in self.raw]

    @pydantic.model_validator(mode="after")
    @classmethod
    def _validate_model(cls, v):
        if v.start_scope is not None:
            if v.scope is None:
                raise ValueError(f"start_scope is set, but scope is not set for: {v}")
        return v

    def get_resolved_imports(
        self,
        loaded_scopes: "LoadedScopes",
    ):
        if not self.scope:
            return []
        # * normal scope
        if self.scope not in loaded_scopes:
            raise ValueError(
                f"scope {repr(self.scope)} does not exist, must be one of: {loaded_scopes.sorted_names}"
            )
        else:
            scope = loaded_scopes[self.scope]
        # * start scope
        start_scope = None
        if self.start_scope:
            if self.start_scope not in loaded_scopes:
                raise ValueError(
                    f"start_scope {repr(self.start_scope)} does not exist, must be one of: {loaded_scopes.sorted_names}"
                )
            else:
                start_scope = loaded_scopes[self.start_scope]
        # * resolve imports
        return scope.resolve_imports(
            start_scope=start_scope,
            visit_lazy=self.visit_lazy,
            exclude_unvisited=self.exclude_unvisited,
            exclude_in_search_space=self.exclude_in_search_space,
            exclude_builtins=self.exclude_builtins,
        )

    def resolve_generate_and_write_requirements(
        self,
        loaded_scopes: "LoadedScopes",
        requirements_mapper: RequirementsMapper,
    ) -> None:
        resolved_imports = self.get_resolved_imports(loaded_scopes=loaded_scopes)
        manual_imports = self.get_manual_imports()
        mapped_requirements = requirements_mapper.generate_output_requirements(
            imports=resolved_imports + manual_imports,
            requirements_env=self.env,
            strict=self.strict_requirements_map,
            resolver_name=self.get_output_name(),
        )
        self._write_requirements(
            mapped_requirements=mapped_requirements,
        )

    def _write_requirements(self, mapped_requirements: OutMappedRequirements) -> None:
        raise NotImplementedError(
            f"tried to write imports for {repr(self.get_output_name())}, write_imports not implemented for {self.__class__.__name__}"
        )


class _OutputRequirements(_Output):
    output_mode: Literal[OutputModeEnum.requirements]

    def _write_requirements(self, mapped_requirements: OutMappedRequirements):
        string = mapped_requirements.as_requirements_txt(
            notice=True,
            sources=True,
            sources_compact=False,
            sources_roots=False,
            indent_size=4,
        )
        txt_file_dump(
            file=self.output_file,
            contents=string,
        )


class _OutputPyprojectOptionalDeps(_Output):
    output_mode: Literal[OutputModeEnum.optional_dependencies]
    output_file: Optional[str] = None

    def _write_requirements(self, mapped_requirements: OutMappedRequirements):
        array = mapped_requirements.as_toml_array(
            notice=True,
            sources=True,
            sources_compact=False,
            sources_roots=False,
            indent_size=4,
        )
        toml_file_replace_array(
            file=self.output_file,
            keys=["project", "optional-dependencies", self.get_output_name()],
            array=array,
        )


class _OutputPyprojectDeps(_Output):
    output_mode: Literal[OutputModeEnum.dependencies]
    output_file: Optional[str] = None

    def _write_requirements(self, mapped_requirements: OutMappedRequirements):
        array = mapped_requirements.as_toml_array(
            notice=True,
            sources=True,
            sources_compact=False,
            sources_roots=False,
            indent_size=4,
        )
        toml_file_replace_array(
            file=self.output_file,
            keys=["project", "dependencies"],
            array=array,
        )


CfgResolver = Annotated[
    Union[
        _OutputRequirements,
        _OutputPyprojectOptionalDeps,
        _OutputPyprojectDeps,
    ],
    pydantic.Field(discriminator="output_mode", union_mode="left_to_right"),
]

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - #
# CONFIG - PACKAGES                                                         #
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - #


class CfgVersion(pydantic.BaseModel, extra="forbid", arbitrary_types_allowed=True):
    # the pip install requirement
    requirement: str
    # the imports to replace
    import_: Optional[List[str]] = pydantic.Field(default=None, alias="import")
    scope: Optional[str] = None
    # only apply this import to this environment
    env: str = DEFAULT_REQUIREMENTS_ENV

    @property
    def parsed_requirement(self) -> Requirement:
        return Requirement(self.requirement)

    @property
    def package(self) -> str:
        return self.parsed_requirement.name.replace("-", "_")

    @classmethod
    def from_string(cls, requirement: str):
        return cls(requirement=requirement)

    def get_import_matcher(self, loaded_scopes: "LoadedScopes") -> ImportMatcherBase:
        if self.scope is not None:
            if self.import_ is not None:
                raise ValueError(f"cannot specify both scope and import for: {self}")
            else:
                return ImportMatcherScope(scope=loaded_scopes[self.scope])
        else:
            if self.import_ is None:
                raise ValueError(f"must specify either scope or import for: {self}")
            else:
                return ImportMatcherGlobs(import_globs=self.import_)

    @pydantic.model_validator(mode="after")
    @classmethod
    def _validate_model_before(cls, v: "CfgVersion"):
        if not str.isidentifier(v.env.replace("-", "_")):
            raise ValueError(
                f"env must be a valid identifier (with hyphens replaced with underscores), got: {v.env}"
            )
        if v.import_ is None and v.scope is None:
            v.import_ = [f"{v.package}.*"]  # wildcard
        elif v.import_ is not None and v.scope is not None:
            raise ValueError(f"cannot specify both scope and import for: {v}")
        return v

    @pydantic.field_validator("import_", mode="before")
    @classmethod
    def _validate_import(cls, v):
        if v is not None:
            if isinstance(v, str):
                v = v.split(",")
        return v


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - #
# CONFIG - SCOPE                                                            #
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - #


class _ScopeRules(pydantic.BaseModel, extra="forbid"):

    unreachable_mode: Optional[UnreachableModeEnum] = None

    @classmethod
    def make_default_base_rules(cls):
        return _ScopeRules(
            unreachable_mode=UnreachableModeEnum.error,
        )

    def set_defaults(self, defaults: "_ScopeRules"):
        assert defaults.unreachable_mode is not None
        if self.unreachable_mode is None:
            self.unreachable_mode = defaults.unreachable_mode


class CfgScope(_ScopeRules, extra="forbid"):
    # name
    # - must be unique across all scopes & sub-scopes
    name: str

    # parents
    parents: List[str] = pydantic.Field(default_factory=list)

    # search paths
    search_paths: List[str] = pydantic.Field(default_factory=list)
    pkg_paths: List[str] = pydantic.Field(default_factory=list)
    unreachable_mode: Optional[UnreachableModeEnum] = None

    # extra packages
    # packages: List[str] = pydantic.Field(default_factory=list)

    # filtering: limit > exclude > [include!!] (in that order)
    # - order is important because it allows us to remove a band of modules
    #   e.g. limit=foo.bar, exclude=foo.bar.baz, include=foo.bar.baz.qux
    #   if order of include and exclude were swapped, then the exclude would
    #   remove the module after the include added it back in
    limit: Optional[List[str]] = None
    exclude: Optional[List[str]] = None
    # include: Optional[str] = None  # NOT IMPLEMENTED BECAUSE IT IS REDUNDANT, AND `PARENTS` CAN BE USED INSTEAD

    # sub-scopes
    # - name to import path map
    # - names must be unique across all scopes & sub-scopes
    # - imports must belong to the scope
    subscopes: Dict[str, str] = pydantic.Field(default_factory=dict)

    @pydantic.field_validator("search_paths", mode="before")
    @classmethod
    def _validate_search_paths(cls, v):
        return [v] if isinstance(v, str) else v

    @pydantic.field_validator("pkg_paths", mode="before")
    @classmethod
    def _validate_pkg_paths(cls, v):
        return [v] if isinstance(v, str) else v

    @pydantic.field_validator("limit", mode="before")
    @classmethod
    def _validate_limit(cls, v):
        return [v] if isinstance(v, str) else v

    @pydantic.field_validator("exclude", mode="before")
    @classmethod
    def _validate_exclude(cls, v):
        return [v] if isinstance(v, str) else v

    def make_module_scope(self, loaded_scopes: "LoadedScopes" = None):
        m = ModulesScope()

        # 1. load parents
        if self.parents:
            if loaded_scopes is None:
                raise ValueError("loaded_scopes must be provided if parents are used!")
            for parent in self.parents:
                if parent not in loaded_scopes:
                    raise ValueError(
                        f"parent scope {repr(parent)} has not yet been created, are you sure the order of definitions is correct?"
                    )
                m.add_modules_from_scope(loaded_scopes[parent])

        # 2. load new search paths and packages
        for path in self.search_paths:
            m.add_modules_from_search_path(
                Path(path),
                tag=self.name,
                unreachable_mode=self.unreachable_mode,
            )
        for path in self.pkg_paths:
            m.add_modules_from_package_path(
                Path(path),
                tag=self.name,
                unreachable_mode=self.unreachable_mode,
            )

        # 3. add extra packages
        # if self.packages:
        # m.add_modules_from_raw_imports(
        #     imports=self.packages,
        #     tag=self.name,
        # )
        # raise NotImplementedError("extra packages not yet implemented!")

        # 4. filter everything
        # - a. limit, b. exclude, [c. include (replaced with parents)]
        if self.limit:
            m = m.get_restricted_scope(
                imports=self.limit,
                mode=RestrictMode.CHILDREN,
                op=RestrictOp.LIMIT,
            )
        if self.exclude:
            m = m.get_restricted_scope(
                imports=self.exclude,
                mode=RestrictMode.CHILDREN,
                op=RestrictOp.EXCLUDE,
            )

        # done!
        return m


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - #
# Loaded Scopes                                                             #
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - #


class UndefinedScopeError(ValueError):
    pass


class LoadedScopes:

    def __init__(self):
        self._scopes = {}

    def __contains__(self, item):
        return item in self._scopes

    def __getitem__(self, item: str) -> ModulesScope:
        if item not in self._scopes:
            raise UndefinedScopeError(
                f"scope {repr(item)} is not defined, must be one of: {self.sorted_names}"
            )
        return self._scopes[item]

    def __setitem__(self, key, value):
        assert isinstance(value, ModulesScope)
        if key in self:
            raise ValueError(f"scope {repr(key)} is already defined!")
        self._scopes[key] = value

    @property
    def sorted_names(self) -> List[str]:
        return sorted(self._scopes.keys())


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - #
# CONFIG - ROOT                                                             #
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - #


class PydependenceCfg(pydantic.BaseModel, extra="forbid"):
    # default root is relative to the parent of the pyproject.toml file
    # and is the folder containing the repo of the pyproject.toml file
    default_root: str = ".."

    # default write modes
    default_resolve_rules: _ResolveRules = pydantic.Field(
        default_factory=_ResolveRules.make_default_base_rules
    )
    default_scope_rules: _ScopeRules = pydantic.Field(
        default_factory=_ScopeRules.make_default_base_rules
    )

    # package versions
    versions: List[CfgVersion] = pydantic.Field(default_factory=list)

    # resolve
    scopes: List[CfgScope] = pydantic.Field(default_factory=dict)

    # outputs
    resolvers: List[CfgResolver] = pydantic.Field(default_factory=list)

    @pydantic.field_validator("versions", mode="before")
    @classmethod
    def _validate_versions(cls, v, values):
        versions = []
        reqs_envs = set()  # pairs of tags and req names must be unique for now
        for x in v:
            if isinstance(x, str):
                x = CfgVersion.from_string(x)
            else:
                x = CfgVersion.model_validate(x)
            req_env = (x.package, x.env)
            if req_env in reqs_envs:
                raise ValueError(
                    f"requirement {repr(x.package)} and env {repr(x.env)} combination is defined multiple times! ({repr(x.requirement)})"
                )
            reqs_envs.add(req_env)
            versions.append(x)
        return versions

    @pydantic.model_validator(mode="after")
    @classmethod
    def _validate_model(cls, cfg: "PydependenceCfg"):
        # 1. check that scope names are all unique
        scope_names = set()
        for scope in cfg.scopes:
            if scope.name in scope_names:
                raise ValueError(f"scope name {repr(scope.name)} is not unique!")
            scope_names.add(scope.name)

        # 2. check that all sub-scope names are unique
        for scope in cfg.scopes:
            for subscope_name in scope.subscopes:
                if subscope_name in scope_names:
                    raise ValueError(
                        f"sub-scope name {repr(subscope_name)} is not unique!"
                    )
                scope_names.add(subscope_name)

        # 3. check that all packages
        # TODO

        # 4. check that the default root is a relative path
        if Path(cfg.default_root).is_absolute():
            raise ValueError(
                f"default_root must be a relative path, got: {repr(cfg.default_root)}"
            )
        return cfg

    def apply_defaults(self, *, pyproject_path: Path):
        if pyproject_path.name != "pyproject.toml":
            raise ValueError(
                f"path must be a pyproject.toml file, got: {pyproject_path}"
            )

        # helper
        self.default_root = apply_root_to_path_str(
            pyproject_path.parent, self.default_root
        )
        s = lambda x: apply_root_to_path_str(self.default_root, x)

        # apply to all paths
        for scope in self.scopes:
            scope.search_paths = [s(x) for x in scope.search_paths]
            scope.pkg_paths = [s(x) for x in scope.pkg_paths]
        for output in self.resolvers:
            if output.output_file is not None:
                output.output_file = s(output.output_file)
            if output.output_file is None:
                if isinstance(
                    output, (_OutputPyprojectDeps, _OutputPyprojectOptionalDeps)
                ):
                    output.output_file = s(pyproject_path)

        # also apply all default write modes
        for scope in self.scopes:
            scope.set_defaults(self.default_scope_rules)
        for output in self.resolvers:
            output.set_defaults(self.default_resolve_rules)

    def load_scopes(self) -> "LoadedScopes":
        # resolve all scopes
        loaded_scopes = LoadedScopes()
        for scope_cfg in self.scopes:
            scope = scope_cfg.make_module_scope(loaded_scopes=loaded_scopes)
            loaded_scopes[scope_cfg.name] = scope
            # now create sub-scopes
            for subcol_name, subcol_import_root in scope_cfg.subscopes.items():
                subscope = scope.get_restricted_scope(
                    imports=[subcol_import_root], mode=RestrictMode.CHILDREN
                )
                loaded_scopes[subcol_name] = subscope
        # done!
        return loaded_scopes

    def make_requirements_mapper(
        self,
        loaded_scopes: "LoadedScopes",
    ):
        env_matchers = defaultdict(list)
        for v in self.versions:
            import_matcher = v.get_import_matcher(loaded_scopes=loaded_scopes)
            pair = ReqMatcher(requirement=v.requirement, matcher=import_matcher)
            env_matchers[v.env].append(pair)
        env_matchers = dict(env_matchers)

        return RequirementsMapper(
            env_matchers=env_matchers,
        )

    def write_all_outputs(self, loaded_scopes: "LoadedScopes"):
        # check that scope output names are unique
        # - output names only need to be unique if they are optional-dependencies!
        # - warn if generally not unique, error if optional-deps not unique
        names_all = set()
        names_optional_deps = set()
        for output in self.resolvers:
            name = output.get_output_name()
            if name in names_all:
                warnings.warn(
                    f"output name {repr(name)} is not unique across all resolvers!"
                )
            names_all.add(name)
            if output.output_mode == OutputModeEnum.optional_dependencies:
                if name in names_optional_deps:
                    raise ValueError(
                        f"output name {repr(name)} is not unique across resolvers for optional dependencies!"
                    )
                names_optional_deps.add(name)

        # check that the scopes exists
        for output in self.resolvers:
            if output.scope is None:
                assert output.start_scope is None
                continue
            if output.scope not in loaded_scopes:
                raise ValueError(
                    f"output scope {repr(output.scope)} does not exist! Are you sure it has been defined? Available scopes: {loaded_scopes.sorted_names}"
                )
            if output.start_scope and output.start_scope not in loaded_scopes:
                raise ValueError(
                    f"output start_scope {repr(output.start_scope)} does not exist! Are you sure it has been defined? Available scopes: {loaded_scopes.sorted_names}"
                )

        # make the mapper
        requirements_mapper = self.make_requirements_mapper(loaded_scopes=loaded_scopes)

        # resolve the scopes!
        for output in self.resolvers:
            output.resolve_generate_and_write_requirements(
                loaded_scopes=loaded_scopes,
                requirements_mapper=requirements_mapper,
            )


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - #
# CONFIG - PYPROJECT                                                        #
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - #


class PyprojectTomlTools(pydantic.BaseModel, extra="ignore"):
    pydependence: PydependenceCfg


class PyprojectToml(pydantic.BaseModel, extra="ignore"):
    tool: PyprojectTomlTools = pydantic.Field(default_factory=PyprojectTomlTools)

    @classmethod
    def from_pyproject(cls, path: Path) -> "PyprojectToml":
        # 1. load pyproject.toml
        toml = load_toml_document(path)
        # 2. validate the model
        pyproject = PyprojectToml.model_validate(toml.unwrap())
        # 3. override paths in cfg using the default root
        pyproject.tool.pydependence.apply_defaults(
            pyproject_path=path,
        )
        return pyproject


# ========================================================================= #
# COLLECT MODULES                                                           #
# ========================================================================= #


def pydeps(
    file: Optional[Union[str, Path]] = None,
):
    # 0. cli
    if file is None:
        if len(sys.argv) == 1:
            script = sys.argv[0]
            file = Path(__file__).parent.parent / "pyproject.toml"
        elif len(sys.argv) == 2:
            script, file = sys.argv
        else:
            raise ValueError("too many arguments!")
    # 1. get absolute
    file = Path(file).resolve().absolute()
    # 2. load pyproject.toml
    pyproject = PyprojectToml.from_pyproject(file)
    # 3. generate search spaces, recursively resolving!
    loaded_scopes = pyproject.tool.pydependence.load_scopes()
    # 4. generate outputs
    pyproject.tool.pydependence.write_all_outputs(loaded_scopes)


# ========================================================================= #
# END                                                                       #
# ========================================================================= #
