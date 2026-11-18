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


def test_the_api_writes_only_the_proposal_actions_and_the_chat(manager_keys, monkeypatch) -> None:
    """Every route is a GET except the four proposal POSTs (feature 004: create, approve, reject,
    send-again) and the chat turn (feature 005). None of them runs a job (D-38)."""
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
        ("/api/v1/brain/assistant/messages", "POST"),
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


# ---------------------------------------------------------------- feature 005 (T012)

LLM_PREFIX = re.compile(r"^(langgraph|langchain\w*)\b")
GENAI = re.compile(r"^google\.genai\b|^google$")


def _all_imports() -> dict[str, set[str]]:
    return {path.relative_to(SRC).as_posix(): _imports(path) for path in SRC.rglob("*.py")}


def test_langgraph_and_langchain_only_under_assistant() -> None:
    for name, imported in _all_imports().items():
        if not name.startswith("assistant/"):
            assert not [m for m in imported if LLM_PREFIX.match(m)], name


def test_google_genai_only_in_the_adapter() -> None:
    for name, imported in _all_imports().items():
        if name != "assistant/model.py":
            assert not [m for m in imported if GENAI.match(m)], name


def test_nothing_imports_langsmith() -> None:
    for name, imported in _all_imports().items():
        assert not [m for m in imported if m.split(".")[0] == "langsmith"], name


def test_compose_turns_tracing_off_and_never_passes_a_key_variable() -> None:
    import yaml

    compose = yaml.safe_load((SRC.parents[2] / "docker-compose.yml").read_text(encoding="utf-8"))
    for service in ("brain-worker", "brain-api"):
        env = compose["services"][service]["environment"]
        assert str(env["LANGSMITH_TRACING"]).lower() == "false", service
        assert env["BRAIN_GEMINI_API_KEY_FILE"] == "/run/secrets/gemini_api_key", service
        for banned in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "LANGCHAIN_TRACING_V2"):
            assert banned not in env, (service, banned)
        mounts = compose["services"][service]["volumes"]
        assert "./secrets/gemini_api_key:/run/secrets/gemini_api_key:ro" in mounts, service


def test_no_code_sets_a_key_environment_variable() -> None:
    for path in SRC.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
            assert name not in source, (path, name)
        assert "os.environ[" not in source or "LANGSMITH" not in source, path


def test_no_model_id_literal_outside_the_settings() -> None:
    for path in SRC.rglob("*.py"):
        if path.name == "config.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        assert not [s for s in literals if re.search(r"\bgemini-\d", s)], path


def test_the_assistant_only_creates_proposals() -> None:
    """Principle V: the propose tool uses feature 004's create function and never execution."""
    callers = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if "create_draft_purchase_order(" in path.read_text(encoding="utf-8")
        and path.name != "client.py"
    ]
    assert callers == ["proposals/execution.py"]
    for path in (SRC / "assistant").glob("*.py"):
        imported = _imports(path)
        assert "brain.proposals.execution" not in imported, path
    assert "brain.proposals.service" in _imports(SRC / "assistant" / "propose.py")
