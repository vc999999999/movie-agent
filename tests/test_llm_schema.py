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

@pytest.mark.asyncio
@pytest.mark.parametrize('wrong_count', [False, True])
async def test_30s_plan_repairs_22_8s_and_missing_slots(monkeypatch, wrong_count):
    from agent.models import CreativeBrief
    from agent.production_packs import ProductionPackRegistry
    client = LLMService()
    brief = CreativeBrief(logline='雨夜追逐', duration_seconds=30)
    screenplay = await client.build_screenplay(brief)
    pack = ProductionPackRegistry().get('emotional_short_v1')
    calls = []
    async def fake_structured(system, user, schema, fallback_fn=None):
        calls.append(user)
        result = fallback_fn()
        if wrong_count and len(calls) == 1:
            result.shots = result.shots[:-1]
        for shot in result.shots:
            shot.duration_seconds = 22.8 / len(result.shots)
        return result
    monkeypatch.setattr(client, 'structured_call', fake_structured)
    shots = await client.build_shot_list(screenplay, brief, pack)
    assert sum(s.duration_seconds for s in shots) == pytest.approx(30)
    assert all(1 <= s.duration_seconds <= 5 for s in shots)
    assert len(calls) == (2 if wrong_count else 1)
    assert all('Mandatory shot timing plan' in call for call in calls)

@pytest.mark.asyncio
async def test_bad_shot_count_is_not_padded_with_fake_shots(monkeypatch):
    from agent.models import CreativeBrief
    from agent.production_packs import ProductionPackRegistry
    client = LLMService()
    brief = CreativeBrief(logline='雨夜追逐', duration_seconds=30)
    screenplay = await client.build_screenplay(brief)
    async def fake_structured(system, user, schema, fallback_fn=None):
        result = fallback_fn()
        result.shots = result.shots[:1]
        return result
    monkeypatch.setattr(client, 'structured_call', fake_structured)
    with pytest.raises(ValueError, match='模型修复后仍返回 1 个'):
        await client.build_shot_list(screenplay, brief, ProductionPackRegistry().get('emotional_short_v1'))
