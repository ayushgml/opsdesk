import json
import subprocess
import sys
from pathlib import Path

from opsdesk.checks import evaluate
from opsdesk.eval import load_task, run

ROOT = Path(__file__).resolve().parents[1]

class FakeLLM:
    tokens = {'input': 1, 'output': 1}
    cost = 0.0
    def complete(self, messages, seed):
        return json.dumps({'actions':[{'tool':'restart_service','arguments':{'service':'api'}}]})


def test_eval_contract_and_trace(tmp_path, monkeypatch):
    monkeypatch.setenv('OPSDESK_TRACE_DIR', str(tmp_path))
    monkeypatch.setenv('CULPRIT_RUN_ID','local-run')
    result = run('alert-10', 0, ROOT/'evals', FakeLLM)
    assert result['passed'] is True
    assert set(result) == {'passed','cost','latency','tokens','trace_id','error'}
    trace = json.loads((tmp_path/(result['trace_id']+'.json')).read_text())
    assert trace['metadata']['CULPRIT_RUN_ID'] == 'local-run'
    assert trace['store']['services']['api']['restarts'] == 1


def test_cli_bad_task_is_one_line_and_exit_zero(tmp_path):
    child = subprocess.run([sys.executable,'-m','opsdesk.eval','--task','missing','--seed','2'],cwd=ROOT,capture_output=True,text=True)
    assert child.returncode == 0
    assert len(child.stdout.splitlines()) == 1
    assert json.loads(child.stdout)['passed'] is False


def test_invalid_cli_arguments_are_json():
    child = subprocess.run([sys.executable,'-m','opsdesk.eval','--task','x','--seed','bad'],capture_output=True,text=True)
    assert child.returncode == 0
    assert json.loads(child.stdout)['error']


def test_tasks_have_unique_ids_and_checks():
    paths = list((ROOT/'evals').glob('*.json'))
    assert 24 <= len(paths) <= 30
    assert len(list((ROOT/'evals/heldout').glob('*.json'))) == 6
    for path in paths + list((ROOT/'evals/heldout').glob('*.json')):
        task = load_task(path.stem, ROOT/'evals')
        assert task['checks'] and task['turns']
        evaluate(task['checks'],task['store'],[])
