"""Worker process: runs a case adapter inside the case's own environment and answers JSON-line requests."""
import importlib.util, json, os, sys, traceback
from pathlib import Path

def main():
    # Systems print freely. Keep the protocol on a private copy of stdout and send everything
    # else, from Python or from native code, to stderr.
    proto = os.fdopen(os.dup(1), 'w', buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    case_dir = Path(sys.argv[1]).resolve()
    backend, effort, cache = sys.argv[2], sys.argv[3], sys.argv[4]
    from halo.run.llm import LLM
    spec = importlib.util.spec_from_file_location('case_adapter', case_dir / 'adapter.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    adapter = mod.Adapter(case_dir, LLM(backend, effort, cache))
    for line in sys.stdin:
        req = json.loads(line)
        try:
            if req['method'] == 'items':
                res = adapter.items()
            elif req['method'] == 'info':
                res = {'channels': adapter.channels, 'steps': adapter.steps}
            else:
                p = req['params']; res = adapter.run(p['item'], p['cut'], p['sample'])
            out = {'id': req['id'], 'result': res}
        except Exception as e:
            out = {'id': req['id'], 'error': f'{type(e).__name__}: {e}', 'trace': traceback.format_exc()[-3000:]}
        proto.write(json.dumps(out, ensure_ascii=False) + '\n'); proto.flush()

if __name__ == '__main__':
    main()
