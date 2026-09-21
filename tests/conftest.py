from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixture():
    """fixture("event_modern_8a0a35e7c74bebcc.html") -> conteúdo do arquivo."""

    def load(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return load
