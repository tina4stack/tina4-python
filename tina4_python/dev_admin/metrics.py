# Tina4 Code Metrics — AST-based static analysis for the dev dashboard.
"""
Two-tier analysis:
  1. Quick metrics (instant): LOC, file counts, class/function counts
  2. Full analysis (on-demand, cached): cyclomatic complexity, maintainability
     index, coupling, Halstead metrics, violations

Zero dependencies — uses Python's built-in `ast` module.
"""
import ast
import os
import math
import time
import hashlib
from pathlib import Path


# ── Scan root tracking ────────────────────────────────────────
# Stores the resolved root so file_detail() can locate framework files.
_last_scan_root: str = ""


# ── Quick Metrics ──────────────────────────────────────────────


def _resolve_root(root: str = "src") -> str:
    """Pick the right directory to scan.

    If src/ has Python files, scan the user's project code.
    Otherwise, scan the framework itself — so the bubble chart is never empty.
    """
    global _last_scan_root
    src = Path(root)
    if src.exists() and list(src.rglob("*.py")):
        _last_scan_root = str(Path(root).resolve())
        return root
    # Fallback: scan the framework package
    import tina4_python
    framework_dir = str(Path(tina4_python.__file__).parent)
    _last_scan_root = framework_dir
    return framework_dir


def quick_metrics(root: str = "src") -> dict:
    """Scan project files and return instant metrics."""
    root = _resolve_root(root)
    root_path = Path(root)
    if not root_path.exists():
        return {"error": f"Directory not found: {root}"}

    py_files = list(root_path.rglob("*.py"))
    twig_files = list(root_path.rglob("*.twig")) + list(root_path.rglob("*.html"))
    sql_files = list(Path("migrations").rglob("*.sql")) if Path("migrations").exists() else []
    scss_files = list(root_path.rglob("*.scss")) + list(root_path.rglob("*.css"))

    total_loc = 0
    total_blank = 0
    total_comment = 0
    total_classes = 0
    total_functions = 0
    file_details = []

    for f in py_files:
        try:
            source = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        lines = source.splitlines()
        loc = 0
        blank = 0
        comment = 0
        in_docstring = False
        docstring_char = None

        for line in lines:
            stripped = line.strip()
            if not stripped:
                blank += 1
                continue

            # Docstring detection (triple quotes)
            if in_docstring:
                comment += 1
                if docstring_char in stripped:
                    in_docstring = False
                continue

            if stripped.startswith('"""') or stripped.startswith("'''"):
                comment += 1
                quote = stripped[:3]
                # Single-line docstring
                if stripped.count(quote) >= 2:
                    continue
                in_docstring = True
                docstring_char = quote
                continue

            if stripped.startswith("#"):
                comment += 1
                continue

            loc += 1

        # Count classes and functions via simple pattern matching
        classes = sum(1 for l in lines if l.strip().startswith("class ") and ":" in l)
        functions = sum(1 for l in lines if l.strip().startswith("def ") and ":" in l)

        total_loc += loc
        total_blank += blank
        total_comment += comment
        total_classes += classes
        total_functions += functions

        file_details.append({
            "path": str(f.relative_to(root_path)),
            "loc": loc,
            "blank": blank,
            "comment": comment,
            "classes": classes,
            "functions": functions,
        })

    # Sort by LOC descending
    file_details.sort(key=lambda x: x["loc"], reverse=True)

    # Route and ORM counts
    route_count = 0
    orm_count = 0
    try:
        from tina4_python.core.router import Router
        route_count = len(Router._routes) if hasattr(Router, "_routes") else 0
    except Exception:
        pass
    try:
        from tina4_python.orm.model import ORM
        orm_count = len(ORM.__subclasses__())
    except Exception:
        pass

    # File type breakdown
    breakdown = {
        "python": len(py_files),
        "templates": len(twig_files),
        "migrations": len(sql_files),
        "stylesheets": len(scss_files),
    }

    return {
        "file_count": len(py_files),
        "total_loc": total_loc,
        "total_blank": total_blank,
        "total_comment": total_comment,
        "lloc": total_loc,
        "classes": total_classes,
        "functions": total_functions,
        "route_count": route_count,
        "orm_count": orm_count,
        "template_count": len(twig_files),
        "migration_count": len(sql_files),
        "avg_file_size": round(total_loc / len(py_files), 1) if py_files else 0,
        "largest_files": file_details[:10],
        "breakdown": breakdown,
    }


# ── Full Analysis (AST-based) ─────────────────────────────────

# Cache for full analysis
_full_cache: dict = {"hash": "", "data": None, "time": 0}
_CACHE_TTL = 60  # seconds


def _files_hash(root: str = "src") -> str:
    """Hash of all file mtimes for cache invalidation."""
    h = hashlib.md5()
    root_path = Path(root)
    if root_path.exists():
        for f in sorted(root_path.rglob("*.py")):
            try:
                h.update(f"{f}:{f.stat().st_mtime}".encode())
            except OSError:
                pass
    return h.hexdigest()


def full_analysis(root: str = "src") -> dict:
    """Deep AST-based analysis. Cached for 60 seconds.

    If src/ has no Python files, scans the framework itself
    so the bubble chart is never empty.
    """
    global _full_cache
    root = _resolve_root(root)

    current_hash = _files_hash(root)
    now = time.time()

    if (_full_cache["hash"] == current_hash and
            _full_cache["data"] is not None and
            now - _full_cache["time"] < _CACHE_TTL):
        return _full_cache["data"]

    root_path = Path(root)
    if not root_path.exists():
        return {"error": f"Directory not found: {root}"}

    py_files = list(root_path.rglob("*.py"))

    all_functions = []
    file_metrics = []
    import_graph = {}  # file -> [imported files]
    reverse_graph = {}  # file -> [files that import it]

    for f in py_files:
        try:
            source = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(f))
        except (SyntaxError, OSError):
            continue

        try:
            rel_path = str(f.relative_to(root_path))
        except ValueError:
            rel_path = str(f.relative_to(root_path.parent)) if root_path.parent != f else f.name
        lines = source.splitlines()
        loc = sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))

        # Extract imports for coupling analysis
        imports = _extract_imports(tree, rel_path)
        import_graph[rel_path] = imports

        for imp in imports:
            if imp not in reverse_graph:
                reverse_graph[imp] = []
            reverse_graph[imp].append(rel_path)

        # Analyze functions/methods
        file_complexity = 0
        file_functions = []
        file_halstead = {"operators": 0, "operands": 0, "unique_operators": set(), "unique_operands": set()}

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                cc = _cyclomatic_complexity(node)
                func_loc = _function_loc(node, lines)
                func_name = node.name
                # Include class name if it's a method
                parent = _get_parent_class(tree, node)
                if parent:
                    func_name = f"{parent}.{node.name}"

                func_info = {
                    "name": func_name,
                    "file": rel_path,
                    "line": node.lineno,
                    "complexity": cc,
                    "loc": func_loc,
                }
                all_functions.append(func_info)
                file_functions.append(func_info)
                file_complexity += cc

            # Halstead: count operators and operands
            _count_halstead(node, file_halstead)

        # Halstead volume
        n1 = len(file_halstead["unique_operators"])
        n2 = len(file_halstead["unique_operands"])
        N1 = file_halstead["operators"]
        N2 = file_halstead["operands"]
        vocabulary = n1 + n2
        length = N1 + N2
        volume = length * math.log2(vocabulary) if vocabulary > 0 else 0

        # Maintainability index
        avg_cc = file_complexity / len(file_functions) if file_functions else 0
        mi = _maintainability_index(volume, avg_cc, loc)

        # Coupling
        ce = len(imports)  # efferent
        ca = len(reverse_graph.get(rel_path, []))  # afferent
        instability = ce / (ca + ce) if (ca + ce) > 0 else 0.0

        # Test coverage detection (file-based matching)
        has_tests = _has_matching_test(rel_path)

        file_metrics.append({
            "path": rel_path,
            "loc": loc,
            "complexity": file_complexity,
            "avg_complexity": round(avg_cc, 2),
            "functions": len(file_functions),
            "maintainability": round(mi, 1),
            "halstead_volume": round(volume, 1),
            "coupling_afferent": ca,
            "coupling_efferent": ce,
            "instability": round(instability, 3),
            "has_tests": has_tests,
            "dep_count": ce,
        })

    # Sort by complexity descending
    all_functions.sort(key=lambda x: x["complexity"], reverse=True)
    file_metrics.sort(key=lambda x: x["maintainability"])

    # Violations
    violations = _detect_violations(all_functions, file_metrics)

    # Overall averages
    total_cc = sum(f["complexity"] for f in all_functions) if all_functions else 0
    avg_cc = total_cc / len(all_functions) if all_functions else 0
    total_mi = sum(f["maintainability"] for f in file_metrics) if file_metrics else 0
    avg_mi = total_mi / len(file_metrics) if file_metrics else 0

    # Detect if we're scanning framework or project
    import tina4_python
    framework_dir = str(Path(tina4_python.__file__).parent)
    scanning_framework = root_path == Path(framework_dir) or str(root_path).startswith(framework_dir)

    result = {
        "files_analyzed": len(file_metrics),
        "total_functions": len(all_functions),
        "avg_complexity": round(avg_cc, 2),
        "avg_maintainability": round(avg_mi, 1),
        "most_complex_functions": all_functions[:15],
        "file_metrics": file_metrics,
        "violations": violations,
        "dependency_graph": import_graph,
        "scan_mode": "framework" if scanning_framework else "project",
        "scan_root": str(root_path),
    }

    _full_cache = {"hash": current_hash, "data": result, "time": now}
    return result


def file_detail(file_path: str) -> dict:
    """Detailed metrics for a single file."""
    p = Path(file_path)
    if not p.exists() and _last_scan_root:
        # Try resolving relative to the last scan root (framework mode)
        candidate = Path(_last_scan_root) / file_path
        if candidate.exists():
            p = candidate
            file_path = str(p)
    if not p.exists():
        return {"error": f"File not found: {file_path}"}

    try:
        source = p.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=file_path)
    except SyntaxError as e:
        return {"error": f"Syntax error: {e}"}

    lines = source.splitlines()
    functions = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cc = _cyclomatic_complexity(node)
            func_loc = _function_loc(node, lines)
            parent = _get_parent_class(tree, node)
            name = f"{parent}.{node.name}" if parent else node.name

            functions.append({
                "name": name,
                "line": node.lineno,
                "complexity": cc,
                "loc": func_loc,
                "args": [a.arg for a in node.args.args if a.arg != "self"],
            })

    functions.sort(key=lambda x: x["complexity"], reverse=True)

    loc = sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))
    classes = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    imports = _extract_imports(tree, file_path)

    # Detect empty methods/functions (body is only `pass` or a docstring)
    warnings = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            # Strip leading docstring
            effective = body[1:] if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) else body
            if not effective or all(isinstance(s, ast.Pass) for s in effective):
                parent = _get_parent_class(tree, node)
                name = f"{parent}.{node.name}" if parent else node.name
                warnings.append({"type": "empty_method", "message": f"Method '{name}' appears to be empty", "line": node.lineno})
        elif isinstance(node, ast.ClassDef):
            body = node.body
            effective = body[1:] if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) else body
            if not effective or all(isinstance(s, ast.Pass) for s in effective):
                warnings.append({"type": "empty_class", "message": f"Class '{node.name}' appears to be empty", "line": node.lineno})

    return {
        "path": file_path,
        "loc": loc,
        "total_lines": len(lines),
        "classes": classes,
        "functions": functions,
        "imports": imports,
        "warnings": warnings,
    }


# ── AST Helpers ────────────────────────────────────────────────


def _cyclomatic_complexity(node: ast.AST) -> int:
    """Calculate cyclomatic complexity for a function/method node.

    CC = 1 + number of decision points (if/elif/for/while/except/and/or/assert)
    """
    cc = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.IfExp)):
            cc += 1
        elif isinstance(child, ast.For):
            cc += 1
        elif isinstance(child, ast.While):
            cc += 1
        elif isinstance(child, ast.ExceptHandler):
            cc += 1
        elif isinstance(child, ast.Assert):
            cc += 1
        elif isinstance(child, ast.BoolOp):
            # Each 'and'/'or' adds a decision point
            cc += len(child.values) - 1
        elif isinstance(child, ast.comprehension):
            cc += 1
            cc += len(child.ifs)
    return cc


def _function_loc(node: ast.AST, lines: list) -> int:
    """Count lines of code in a function."""
    if hasattr(node, "end_lineno") and node.end_lineno:
        return node.end_lineno - node.lineno + 1
    # Fallback: count indented lines
    start = node.lineno - 1
    count = 1
    if start + 1 < len(lines):
        base_indent = len(lines[start]) - len(lines[start].lstrip())
        for i in range(start + 1, len(lines)):
            line = lines[i]
            if line.strip() and (len(line) - len(line.lstrip())) > base_indent:
                count += 1
            elif line.strip():
                break
    return count


def _get_parent_class(tree: ast.AST, target_node: ast.AST) -> str | None:
    """Find the parent class of a method node."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for child in ast.walk(node):
                if child is target_node:
                    return node.name
    return None


def _extract_imports(tree: ast.AST, file_path: str) -> list:
    """Extract import targets from an AST."""
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def _count_halstead(node: ast.AST, stats: dict):
    """Count Halstead operators and operands from AST nodes."""
    # Operators: binary ops, unary ops, comparisons, boolops, augmented assigns
    if isinstance(node, ast.BinOp):
        op_name = type(node.op).__name__
        stats["operators"] += 1
        stats["unique_operators"].add(op_name)
    elif isinstance(node, ast.UnaryOp):
        op_name = type(node.op).__name__
        stats["operators"] += 1
        stats["unique_operators"].add(op_name)
    elif isinstance(node, ast.Compare):
        for op in node.ops:
            op_name = type(op).__name__
            stats["operators"] += 1
            stats["unique_operators"].add(op_name)
    elif isinstance(node, ast.BoolOp):
        op_name = type(node.op).__name__
        stats["operators"] += 1
        stats["unique_operators"].add(op_name)
    elif isinstance(node, ast.AugAssign):
        op_name = type(node.op).__name__
        stats["operators"] += 1
        stats["unique_operators"].add(f"Aug{op_name}")

    # Operands: names, constants
    if isinstance(node, ast.Name):
        stats["operands"] += 1
        stats["unique_operands"].add(node.id)
    elif isinstance(node, ast.Constant):
        stats["operands"] += 1
        stats["unique_operands"].add(str(node.value)[:50])


def _has_matching_test(rel_path: str) -> bool:
    """Check if a source file has a matching test file.

    Three-stage detection:
    1. Filename matching — test_module.py, module_test.py, module_spec.py
    2. Path matching — any test file referencing the full import path
    3. Content matching — any test file mentioning the module or class name
    """
    import re

    p = Path(rel_path)
    module = p.stem  # e.g. "sqlite" from "tina4_python/database/sqlite.py"
    if module == "__init__":
        module = p.parent.name  # use parent dir name

    # Build the full dotted import path for deeper matching
    # e.g. "tina4_python/database/sqlite.py" → "tina4_python.database.sqlite"
    parts = list(p.with_suffix("").parts)
    dotted_path = ".".join(parts)  # "tina4_python.database.sqlite"

    # Also track the parent package name for broader matching
    # e.g. "database" from "tina4_python/database/sqlite.py"
    parent_module = p.parent.name if len(p.parts) > 1 else ""

    # Stage 1: Filename patterns
    test_dirs = [Path("tests"), Path("test"), Path("spec")]
    for td in test_dirs:
        patterns = [
            td / f"test_{module}.py",
            td / f"test_{module}s.py",
            td / f"{module}_test.py",
            td / f"{module}_spec.py",
        ]
        # Also check parent-named tests (test_database.py covers database/sqlite.py)
        if parent_module and parent_module != module:
            patterns.extend([
                td / f"test_{parent_module}.py",
                td / f"test_{parent_module}s.py",
                td / f"{parent_module}_test.py",
            ])
        if any(tp.exists() for tp in patterns):
            return True

    # Stage 2+3: Content scan — check if ANY test file references this module
    search_terms = [
        re.compile(rf'\b{re.escape(module)}\b', re.IGNORECASE),
    ]
    # Add dotted path patterns for import matching
    if dotted_path:
        search_terms.append(re.compile(rf'{re.escape(dotted_path)}'))
    # Add class name guesses (CamelCase from snake_case module name)
    class_name = "".join(w.capitalize() for w in module.split("_"))
    if class_name != module:
        search_terms.append(re.compile(rf'\b{re.escape(class_name)}\b'))

    for td in test_dirs:
        if not td.is_dir():
            continue
        for test_file in td.rglob("*.py"):
            try:
                content = test_file.read_text(encoding="utf-8", errors="ignore")
                if any(pat.search(content) for pat in search_terms):
                    return True
            except OSError:
                pass
    return False


def _maintainability_index(halstead_volume: float, avg_cc: float, loc: int) -> float:
    """Calculate Maintainability Index (0-100 scale).

    MI = max(0, (171 - 5.2 * ln(V) - 0.23 * CC - 16.2 * ln(LOC)) * 100 / 171)
    """
    if loc <= 0:
        return 100.0
    v = max(halstead_volume, 1)
    mi = 171 - 5.2 * math.log(v) - 0.23 * avg_cc - 16.2 * math.log(loc)
    return max(0.0, min(100.0, mi * 100 / 171))


def _detect_violations(functions: list, file_metrics: list) -> list:
    """Detect code quality violations."""
    violations = []

    for f in functions:
        if f["complexity"] > 20:
            violations.append({
                "type": "error",
                "rule": "high_complexity",
                "message": f"{f['name']} has cyclomatic complexity {f['complexity']} (max 20)",
                "file": f["file"],
                "line": f["line"],
            })
        elif f["complexity"] > 10:
            violations.append({
                "type": "warning",
                "rule": "moderate_complexity",
                "message": f"{f['name']} has cyclomatic complexity {f['complexity']} (recommended max 10)",
                "file": f["file"],
                "line": f["line"],
            })

    for fm in file_metrics:
        if fm["loc"] > 500:
            violations.append({
                "type": "warning",
                "rule": "large_file",
                "message": f"{fm['path']} has {fm['loc']} LOC (recommended max 500)",
                "file": fm["path"],
                "line": 1,
            })
        if fm["functions"] > 20:
            violations.append({
                "type": "warning",
                "rule": "too_many_functions",
                "message": f"{fm['path']} has {fm['functions']} functions (recommended max 20)",
                "file": fm["path"],
                "line": 1,
            })
        if fm["maintainability"] < 20:
            violations.append({
                "type": "error",
                "rule": "low_maintainability",
                "message": f"{fm['path']} has maintainability index {fm['maintainability']} (min 20)",
                "file": fm["path"],
                "line": 1,
            })
        elif fm["maintainability"] < 40:
            violations.append({
                "type": "warning",
                "rule": "moderate_maintainability",
                "message": f"{fm['path']} has maintainability index {fm['maintainability']} (recommended min 40)",
                "file": fm["path"],
                "line": 1,
            })

    violations.sort(key=lambda v: (0 if v["type"] == "error" else 1, v["file"]))
    return violations
