"""Versioned, explicitly registered local rules shared by CLI and the workbench."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable
from threading import RLock

from ..common import QuantError, finite_float


@dataclass(frozen=True)
class Parameter:
    label: str
    kind: str
    default: object
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()

    def validate(self, value):
        if self.kind == "choice":
            if value not in self.choices:
                raise QuantError("INVALID_STRATEGY_PARAM", f"{self.label} 必须属于 {self.choices}")
            return value
        if isinstance(value, bool) or (self.kind == "int" and type(value) is not int):
            raise QuantError("INVALID_STRATEGY_PARAM", f"{self.label} 类型不正确")
        try:
            number = finite_float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise QuantError("INVALID_STRATEGY_PARAM", f"{self.label} 必须是有限数值") from exc
        if (self.minimum is not None and number < self.minimum) or (self.maximum is not None and number > self.maximum):
            raise QuantError("INVALID_STRATEGY_PARAM", f"{self.label} 超出范围 [{self.minimum}, {self.maximum}]")
        return int(number) if self.kind == "int" else number


@dataclass(frozen=True)
class Definition:
    template_id: str
    name: str
    description: str
    parameters: dict[str, Parameter]
    history_size: Callable
    compute: Callable
    version: str = "1.0.0"

    def normalize(self, supplied: dict, symbols: tuple[str, ...]):
        if not isinstance(supplied, dict) or set(supplied) - self.parameters.keys():
            raise QuantError("INVALID_STRATEGY_PARAM", "模板含未知参数")
        params = {key: param.validate(supplied.get(key, param.default)) for key, param in self.parameters.items()}
        if params.get("top_k", 1) > len(symbols):
            raise QuantError("INVALID_STRATEGY_PARAM", "入选数量不能超过篮子标的数")
        if self.template_id == "multi_factor" and len(symbols) < 2:
            raise QuantError("INVALID_STRATEGY_PARAM", "多因子排名至少需要两个标的")
        return params

    def content(self):
        return {"template_id": self.template_id, "name": self.name, "description": self.description,
                "implementation_version": self.version,
                "parameters": {name: asdict(value) for name, value in self.parameters.items()}}


_REGISTRY: dict[str, Definition] = {}
_LOCK = RLock()
_BUILTINS_LOADED = False


def register(definition: Definition):
    if definition.template_id in _REGISTRY:
        raise QuantError("DUPLICATE_TEMPLATE", "模板已注册，不能覆盖实现")
    _REGISTRY[definition.template_id] = definition


def definitions():
    global _BUILTINS_LOADED
    with _LOCK:
        if not _BUILTINS_LOADED:
            from . import templates
            templates.install()
            _BUILTINS_LOADED = True
        return dict(_REGISTRY)


def definition(template_id, version=None):
    found = definitions().get(template_id)
    if found is None or (version is not None and version != found.version):
        raise QuantError("UNKNOWN_STRATEGY_VERSION", f"未安装策略实现：{template_id}@{version or 'default'}")
    return found
