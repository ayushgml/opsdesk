from types import SimpleNamespace

import pytest

from opsdesk.llm import Budget, LLM


def fake_response():
    return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100,completion_tokens=20),choices=[SimpleNamespace(message=SimpleNamespace(content='{"actions":[]}'))])


def adapter(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER','openrouter')
    monkeypatch.setenv('OPENROUTER_API_KEY','test-not-a-real-key')
    monkeypatch.setenv('VICTIM_MODEL','qwen/qwen3.8-flash')
    monkeypatch.delenv('OPSDESK_BUDGET_FILE',raising=False)
    return LLM()


def test_temperature_rejection_retries_once_without_it(monkeypatch):
    llm = adapter(monkeypatch)
    calls=[]
    class Rejected(Exception):
        status_code=400
    def send(**kwargs):
        calls.append(kwargs)
        if len(calls)==1:
            raise Rejected('temperature unsupported')
        return fake_response()
    llm.client.chat.completions.create=send
    assert llm.complete([{'role':'system','content':'test'},{'role':'user','content':'test'}],0)=='{"actions":[]}'
    assert calls[0]['temperature']==0
    assert 'temperature' not in calls[1]
    assert llm.tokens=={'input':100,'output':20}
    assert llm.cost==pytest.approx((100*.15+20*.47)/1e6)


def test_other_errors_are_not_retried(monkeypatch):
    llm=adapter(monkeypatch)
    calls=[]
    class Rejected(Exception):
        status_code=400
    def send(**kwargs):
        calls.append(kwargs)
        raise Rejected('invalid model')
    llm.client.chat.completions.create=send
    with pytest.raises(Rejected):llm.complete([{'role':'system','content':'test'}],0)
    assert len(calls)==1
    assert llm.cost==0


def test_budget_reservation_and_settlement(tmp_path,monkeypatch):
    monkeypatch.setenv('OPSDESK_BUDGET_FILE',str(tmp_path/'budget.json'))
    monkeypatch.setenv('OPSDESK_BUDGET_USD','0.1')
    budget=Budget();budget.reserve(.08)
    with pytest.raises(RuntimeError):budget.reserve(.03)
    budget.settle(.08,.01)
    budget.reserve(.08)
    budget.settle(.08,None)
    with pytest.raises(RuntimeError):budget.reserve(.001)


def test_unknown_model_fails_without_price_override(monkeypatch):
    monkeypatch.setenv('VICTIM_MODEL','unknown')
    monkeypatch.delenv('VICTIM_PRICE_IN',raising=False)
    monkeypatch.delenv('VICTIM_PRICE_OUT',raising=False)
    with pytest.raises(ValueError,match='pricing'):LLM()
