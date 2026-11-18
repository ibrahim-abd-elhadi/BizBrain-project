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


def test_the_client_only_sends_the_five_canonical_gets_and_the_draft_po() -> None:
    """Feature 003's five GETs, plus feature 004's one POST: the approved draft purchase order."""
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
    assert set(re.findall(r"self\._http\.(\w+)\(", source)) & verbs == {"get", "post"}
    posts = re.findall(r'self\._http\.post\(\s*"([^"]+)"', source)
    assert posts == ["/purchase-orders"]
    paths = {re.sub(r"\{.*", "", p) for p in re.findall(r'self\._get\(\s*f?"([^"]+)"', source)}
    assert paths == CANONICAL_PATHS


def test_the_api_writes_only_the_four_proposal_actions(manager_keys, monkeypatch) -> None:
    """Every route is a GET except the four proposal POSTs (feature 004): create, approve,
    reject, send-again. None of them runs a job (D-38)."""
    from conftest import reset_app_caches

    monkeypatch.setenv("BRAIN_ERP_JWT_PUBLIC_KEY_FILE", str(manager_keys[1]))
    reset_app_caches()
    from brain.api.app import create_app

    app = create_app()
    # The OpenAPI document lists every operation, including those of included routers.
    writes = {
        (path, method.upper())
        for path, item in app.openapi()["paths"].items()
        for method in item
        if method in ("post", "put", "patch", "delete")
    }
    prefix = "/api/v1/brain/proposals"
    assert writes == {
        (prefix, "POST"),
        (prefix + "/{proposal_id}/approve", "POST"),
        (prefix + "/{proposal_id}/reject", "POST"),
        (prefix + "/{proposal_id}/send-again", "POST"),
    }, writes
    reset_app_caches()


# ---------------------------------------------------------------- feature 004


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_proposals_never_import_an_llm_library() -> None:
    """FR-003: creating, approving and sending work with no LLM at all."""
    files = [*(SRC / "proposals").glob("*.py"), SRC / "api" / "proposals.py"]
    llm = re.compile(r"^(google|genai|langgraph|langchain|openai|anthropic)\b")
    for path in files:
        assert not [m for m in _imports(path) if llm.match(m)], path


def test_only_execution_sends_a_draft_po() -> None:
    """Principle V: the ERP write happens only from approve and send-again."""
    callers = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if "create_draft_purchase_order(" in path.read_text(encoding="utf-8")
        and path.name != "client.py"
    ]
    assert callers == ["proposals/execution.py"]


def test_proposals_never_expire() -> None:
    """FR-009, README Section 7: no expiry column, and nothing outside the proposal code (no job,
    no pipeline) touches a proposal, so no status changes by time alone."""
    from brain.models import Base

    for name in ("proposal", "proposal_line", "proposal_live_product", "proposal_attempt"):
        columns = {c.name for c in Base.metadata.tables[name].columns}
        assert not [c for c in columns if re.search(r"expir|ttl|deadline|valid_until", c)], name
    for folder in ("jobs", "pipeline", "forecasting", "sales"):
        for path in (SRC / folder).rglob("*.py"):
            assert "Proposal" not in path.read_text(encoding="utf-8"), path
