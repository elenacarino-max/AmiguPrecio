import importlib


def test_exactly_three_agents_are_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("appdirs.user_data_dir", lambda *args, **kwargs: str(tmp_path))
    agents_module = importlib.import_module("amiguprecio.agents")
    researcher, analyst, advisor = agents_module.create_agents()

    assert [researcher.role, analyst.role, advisor.role] == [
        "Investigador de mercado de amigurumis",
        "Analista de costes y precios",
        "Asesor comercial de producto artesanal",
    ]
    assert len(researcher.mcps) == 1
    assert len(analyst.tools) == 1
    assert advisor.tools == []


def test_crew_uses_sequential_process(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("appdirs.user_data_dir", lambda *args, **kwargs: str(tmp_path))
    agents_module = importlib.import_module("amiguprecio.agents")
    crew = agents_module.create_crew()

    assert len(crew.agents) == 3
    assert len(crew.tasks) == 3
    assert crew.process == agents_module.Process.sequential
