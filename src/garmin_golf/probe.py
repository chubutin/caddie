"""Inspector de estructura de JSON crudo.

Es una API reverseada: antes de escribir cualquier normalizador quiero ver
que devuelve realmente cada endpoint. Esto recorre un payload y arma un
arbol de tipos con cobertura (en cuantos registros aparece cada campo) y
valores de ejemplo.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    return {
        bool: "bool",
        int: "int",
        float: "float",
        str: "str",
        list: "list",
        dict: "dict",
    }.get(type(value), type(value).__name__)


def _short(value: Any, width: int = 48) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    text = text.replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


class FieldStats:
    __slots__ = ("types", "present", "nulls", "samples")

    def __init__(self) -> None:
        self.types: set[str] = set()
        self.present = 0
        self.nulls = 0
        self.samples: list[Any] = []

    def observe(self, value: Any) -> None:
        self.present += 1
        self.types.add(_type_name(value))
        if value is None:
            self.nulls += 1
        elif len(self.samples) < 3 and value not in self.samples:
            if not isinstance(value, (dict, list)):
                self.samples.append(value)


def _walk(node: Any, path: str, stats: dict[str, FieldStats], counts: dict[str, int]) -> None:
    if isinstance(node, dict):
        counts[path] += 1
        for key, value in node.items():
            child = f"{path}.{key}" if path else key
            stats[child].observe(value)
            _walk(value, child, stats, counts)
    elif isinstance(node, list):
        child = f"{path}[]"
        for item in node:
            stats[child].observe(item)
            _walk(item, child, stats, counts)


def describe(payload: Any, *, title: str = "", max_rows: int = 200) -> str:
    """Devolver un reporte en texto de la estructura real del payload."""
    stats: dict[str, FieldStats] = defaultdict(FieldStats)
    counts: dict[str, int] = defaultdict(int)

    root_label = _type_name(payload)
    if isinstance(payload, list):
        root_label = f"list[{len(payload)}]"
    _walk(payload, "", stats, counts)

    lines: list[str] = []
    if title:
        lines.append(title)
        lines.append("=" * len(title))
    lines.append(f"raiz: {root_label}")
    lines.append("")
    lines.append(f"{'campo':<52} {'tipo':<16} {'n':>6}  ejemplos")
    lines.append("-" * 112)

    for path in sorted(stats)[:max_rows]:
        stat = stats[path]
        types = "|".join(sorted(stat.types))
        nullness = f" ({stat.nulls} null)" if stat.nulls else ""
        depth = path.count(".")
        label = ("  " * depth) + path.rsplit(".", 1)[-1]
        samples = ", ".join(_short(s, 30) for s in stat.samples)
        lines.append(
            f"{label[:52]:<52} {types[:16]:<16} {stat.present:>6}  {samples}{nullness}"
        )

    omitted = len(stats) - max_rows
    if omitted > 0:
        lines.append(f"... y {omitted} campos mas")
    return "\n".join(lines)


def describe_file(path: str | Path, **kwargs: Any) -> str:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    payload = doc["data"] if isinstance(doc, dict) and "data" in doc else doc
    return describe(payload, title=str(path), **kwargs)


if __name__ == "__main__":  # pragma: no cover
    import sys

    for arg in sys.argv[1:]:
        print(describe_file(arg))
        print()
