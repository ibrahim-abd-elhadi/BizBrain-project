"""Scope guards (FR-002, FR-035; constitution Principles I, II and VI).

The words are checked in code (identifiers, imports, attribute names and string literals), not
in docstrings or comments, which state these very rules ("No tenant, branch or location column").
"""

import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "brain"
BANNED = re.compile(r"erp_db|tenant|branch|location_id|pickle|joblib", re.IGNORECASE)
CANONICAL_PATHS = {"/sales", "/products/", "/inventory/", "/suppliers/", "/purchase-orders"}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _code_words(tree: ast.AST) -> list[str]:
    docstrings = _docstring_nodes(tree)
    words: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                words.append(node.value)
        elif isinstance(node, ast.Name):
            words.append(node.id)
        elif isinstance(node, ast.Attribute):
            words.append(node.attr)
        elif isinstance(node, ast.arg):
            words.append(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            words.append(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            words.extend(a.name for a in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                words.append(node.module)
    return words


@pytest.mark.parametrize(
    "path", sorted(SRC.rglob("*.py")), ids=lambda p: p.relative_to(SRC).as_posix()
)
def test_no_banned_word_in_code(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits = [w for w in _code_words(tree) if BANNED.search(w)]
    assert hits == [], hits


def test_the_client_only_sends_the_five_canonical_gets() -> None:
    source = (SRC / "canonical" / "client.py").read_text(encoding="utf-8")
    verbs = {
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "request",
        "stream",
        "send",
        "head",
        "options",
    }
    assert set(re.findall(r"self\._http\.(\w+)\(", source)) & verbs == {"get"}
    paths = {re.sub(r"\{.*", "", p) for p in re.findall(r'self\._get\(\s*f?"([^"]+)"', source)}
    assert paths == CANONICAL_PATHS


def test_the_api_has_only_get_routes(manager_keys, monkeypatch) -> None:
    from conftest import reset_app_caches

    monkeypatch.setenv("BRAIN_ERP_JWT_PUBLIC_KEY_FILE", str(manager_keys[1]))
    reset_app_caches()
    from brain.api.app import create_app

    app = create_app()
    methods = {m for route in app.routes for m in (getattr(route, "methods", None) or ())}
    assert methods <= {"GET", "HEAD"}, methods
    reset_app_caches()
