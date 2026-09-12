import json
import pytest
from pydantic import BaseModel
from agent.llm import LLMService

class Response(BaseModel):
    options: list[str]

@pytest.mark.asyncio
async def test_schema_and_original_constraints_reach_repair(monkeypatch):
    client = LLMService(api_key='test-only-key')
    calls = []
    async def fake_call(system, user):
        calls.append((system, user))
        return '{}' if len(calls) == 1 else json.dumps({'options': ['valid']})
    monkeypatch.setattr(client, 'call_llm', fake_call)
    result = await client.structured_call('Generate options', 'Preserve a 15-second duration', Response)
    assert result.options == ['valid']
    assert len(calls) == 2
    for system, user in calls:
        assert '"required": ["options"]' in system
        assert 'Preserve a 15-second duration' in user
