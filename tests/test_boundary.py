#!/usr/bin/env python3
"""Architectural boundary test for the standalone `python-wealthfolio`
package.

This package is a self-contained REST client for Wealthfolio's HTTP API.
Only its own modules, reviewed standard-library modules, and declared
runtime dependencies may be imported.
Statically parsing every module's AST (rather than importing it) lets this
test fail loudly on a forbidden import even if it happens to be unreachable
at runtime (e.g. guarded by a conditional or inside a rarely-called
function).

Run with:
    python -m unittest discover -s tests -p 'test_*.py' -v
"""

import ast
import pathlib
import unittest

_PACKAGE_SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "wealthfolio"

# Explicit allowlist works on every supported Python version. Review additions
# alongside pyproject.toml when extending the package's dependency surface.
_ALLOWED_TOP_LEVEL_MODULES = {
    "__future__", "argparse", "csv", "dataclasses", "datetime", "json",
    "math", "os", "pathlib", "requests", "sys", "typing", "wealthfolio",
}


def _iter_source_files():
    return sorted(_PACKAGE_SRC.rglob("*.py"))


def _top_level_module_names(tree: ast.Module):
    """Yield the top-level module name of every `import x[.y]` and
    `from x[.y] import z` statement in `tree` (e.g. `os.path` -> `os`)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            # Relative imports (`from .foo import bar`, level > 0) are
            # always intra-package and never forbidden.
            if node.level and node.level > 0:
                continue
            if node.module:
                yield node.module.split(".")[0]


class BoundaryTest(unittest.TestCase):
    def test_package_source_files_exist(self):
        files = _iter_source_files()
        self.assertTrue(files, f"Expected .py files under {_PACKAGE_SRC}")

    def test_only_reviewed_imports(self):
        violations = []
        for path in _iter_source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for name in _top_level_module_names(tree):
                if name not in _ALLOWED_TOP_LEVEL_MODULES:
                    violations.append(f"{path.relative_to(_PACKAGE_SRC.parent.parent)}: imports '{name}'")
        self.assertEqual(
            violations,
            [],
            "python-wealthfolio must not import undeclared dependencies:\n"
            + "\n".join(violations),
        )

    def test_no_sys_path_hacks(self):
        """Package imports must work without modifying the module search path."""
        offenders = []
        for path in _iter_source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "path":
                    value = node.value
                    if isinstance(value, ast.Name) and value.id == "sys":
                        offenders.append(str(path.relative_to(_PACKAGE_SRC.parent.parent)))
        self.assertEqual(
            offenders,
            [],
            "python-wealthfolio source files must not reference sys.path:\n" + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
