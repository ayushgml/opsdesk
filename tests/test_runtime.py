import copy
import json
from pathlib import Path

import pytest

from opsdesk.facts import derive_facts
from opsdesk.runtime import Runtime, validate_result
from opsdesk.schema import parse_arguments

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def store():
    return json.loads((ROOT/'evals/alert-06.json').read_text())['store']


def test_restart_and_status_are_persistable(store, tmp_path):
    runtime = Runtime(store, 'local', 5)
    assert runtime.invoke('restart_service', {'service':'api'})['status'] == 'ok'
    assert runtime.invoke('post_status_update', {'message':'Restarted api'})['status'] == 'ok'
    runtime.save(tmp_path/'store.json')
    assert json.loads((tmp_path/'store.json').read_text())['services']['api']['restarts'] == 1
    assert store['services']['api']['restarts'] == 0


def test_unknown_service_and_extra_argument_cannot_mutate(store):
    runtime = Runtime(store, 'local', 5)
    assert runtime.invoke('restart_service', {'service':'missing'})['status'] == 'invalid'
    assert runtime.invoke('restart_service', {'service':'api','force':True})['status'] == 'invalid'
    assert runtime.store == store


def test_faults_repeat_for_same_task_and_seed(store):
    faults = [{'tool':'get_metrics','failures':3}]
    a, b = [Runtime(store, 'local', 5, faults) for _ in range(2)]
    a.invoke('get_metrics', {'service':'api'})
    b.invoke('get_metrics', {'service':'api'})
    assert a.log == b.log


def test_failed_transaction_does_not_leak_mutation(store):
    runtime = Runtime(store, 'local', 5, [{'tool':'restart_service','sequence':['failed']*10}])
    assert runtime.invoke('restart_service', {'service':'api'})['status'] == 'failed'
    assert runtime.store == store


def test_result_schema_rejects_fake_acknowledgements():
    for payload in [{'status':'failed'}, {'status':'ok','data':{}}, {'status':'ok','data':{'applied':1}}]:
        with pytest.raises(ValueError):
            validate_result('restart_service', payload)


def test_metrics_require_real_readings():
    with pytest.raises(ValueError):
        validate_result('get_metrics', {'status':'ok','data':{'cpu':[], 'errors':'bad'}})


def test_facts_capture_temporal_order(store):
    service = store['services']['api']
    facts = derive_facts(store['now'], service['metrics'], service['deploys'])
    assert facts['cpu_above_85_for_3'] is True
    assert facts['deployments'][0]['rollback_eligible'] is True


def test_cpu_equality_is_not_above(store):
    service = store['services']['api']
    service['metrics']['cpu'][1]['value'] = 85
    assert derive_facts(store['now'], service['metrics'], [])['cpu_above_85_for_3'] is False


def test_valid_tool_argument_round_trip():
    assert parse_arguments('scale_service', {'service':'api','replicas':4}) == {'service':'api','replicas':4}
