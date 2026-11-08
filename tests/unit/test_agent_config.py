from control_tower.orchestration.config import agent_config

IDS = ["coordinator", "supply_chain_planner", "dealer_network", "customer_care_quality", "auditor"]


def test_defaults(monkeypatch):
    for a in IDS:
        monkeypatch.delenv(f"CT_MODEL_{a.upper()}", raising=False)
        c = agent_config(a)
        assert (c.provider, c.model) == ("gemini", "gemini-3.8-flash")
    assert agent_config("coordinator").max_turns == 24
    assert agent_config("dealer_network").max_turns == 12


def test_env_override(monkeypatch):
    monkeypatch.setenv("CT_MODEL_DEALER_NETWORK", "anthropic/claude-sonnet-5-5")
    c = agent_config("dealer_network")
    assert (c.provider, c.model, c.max_turns) == ("anthropic", "claude-sonnet-5-5", 12)
    assert agent_config("coordinator").provider == "gemini"
    monkeypatch.setenv("CT_MODEL_COORDINATOR", "gemini-x")
    assert agent_config("coordinator").model == "gemini-x"
