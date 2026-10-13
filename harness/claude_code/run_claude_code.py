#!/usr/bin/env python3
"""Run ReconcileBench episodes in the Claude Code CLI harness, one Docker container per episode.

    python3 run_claude_code.py --suite general_propagation --tasks-dir ../../tasks/general_propagation \
        --ids evidence-atlas-01,policy-atlas-01
    add --dry-run to replace Claude Code with a stub (no model calls) for testing the driver

Per episode:
  1. Copy the task's starting workspace (symlinks followed) to
     runs/<suite>/<label>_0/<id>_<model>-cc/. The "-cc" suffix keeps these apart from the
     mini-swe-agent runs of the same model, because some scorers match on the model suffix.
  2. Make a fresh HOME with claude_code/home_template/.claude/settings.json (command sandbox on,
     no network for commands, no unsandboxed fallback; WebFetch/WebSearch denied) and a
     per-episode env file holding only ANTHROPIC_API_KEY plus
     CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1. The env file is deleted after the episode.
  3. Start the pinned image with only the workspace and that HOME mounted (seccomp and
     /proc-masking relaxed so Claude Code's bubblewrap sandbox can start; still an unprivileged
     user with no added capabilities). Deliver the task's turns in one session:
     `claude -p <turn> --session-id <uuid>` for the first turn, `--resume <uuid>` for the rest.
  4. A turn is valid only if the process exits 0 and its final `result` event is a success.
     Any failed or timed-out turn marks the episode invalid; invalid episodes are never scored
     and are rerun from scratch.
  5. Remove the container and the env file; redact the API key from every saved file; save the
     session transcript (authoritative: every message, tool call and output, plus model and
     effort per assistant message) and the stream-json output; append one record to
     results/<suite>/res_<label>_0.jsonl.
"""
import argparse, glob, json, os, shutil, subprocess, sys, time, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.dirname(os.path.dirname(HERE))   # repository root: runs/, results/, traces/ live here
IMAGE = 'reconcilebench-claude-code:2.1.289-mpl3.9.4'   # built from Dockerfile.mpl; the paper's run used it
MODEL = 'claude-opus-5'
EFFORT = 'low'
SUFFIX = MODEL + '-cc'
AGENT_HOME = '/' + 'home' + '/agent'      # the container user's home
WALL_LIMIT_S = 3600                      # the same one-hour episode limit as the other harnesses
COMMON = ['--model', MODEL, '--effort', EFFORT, '--permission-mode', 'dontAsk',
          '--disallowedTools', 'WebFetch', 'WebSearch', '--strict-mcp-config',
          '--output-format', 'stream-json', '--verbose', '--debug-file', AGENT_HOME + '/debug.log']
DOCKER_SECURITY = ['--security-opt', 'seccomp=unconfined', '--security-opt', 'systempaths=unconfined']


def load_turns(args, task_id):
    task = json.load(open(os.path.join(args.tasks_dir, task_id, 'task.json')))
    return list(task['turns']), os.path.join(args.tasks_dir, task_id, 'workspace')


def api_key():
    key = os.environ.get('ANTHROPIC_API_KEY')
    if not key:
        sys.exit('ANTHROPIC_API_KEY is not set')
    return key


def redact_tree(root, value):
    hits = 0
    for dp, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(dp, f)
            try:
                b = open(p, 'rb').read()
            except OSError:
                continue
            if value.encode() in b:
                hits += b.count(value.encode())
                open(p, 'wb').write(b.replace(value.encode(), b'<REDACTED_API_KEY>'))
    return hits


def claude_cmd(i, sid, text, dry):
    if dry:
        stub = ('python3 -c "import json,sys; t=sys.argv[1]; n=sys.argv[2]; '
                'print(json.dumps({\'type\':\'system\',\'subtype\':\'init\',\'model\':\'dry\'})); '
                'print(json.dumps({\'type\':\'assistant\',\'message\':{\'content\':[{\'type\':\'text\',\'text\':\'DRY turn \'+n+\': \'+t[:80]}]}})); '
                'print(json.dumps({\'type\':\'result\',\'subtype\':\'success\',\'is_error\':False,\'total_cost_usd\':0}))" "$0" "$1"')
        return ['sh', '-c', stub, text, str(i)]
    return ['claude', '-p', text] + (['--session-id', sid] if i == 0 else ['--resume', sid]) + COMMON


def session_summary(home, sid):
    files = glob.glob(os.path.join(home, '.claude', 'projects', '*', f'{sid}.jsonl'))
    out = dict(session_file=os.path.basename(files[0]) if files else None, tool_calls=0,
               tool_calls_by_name={}, models=set(), efforts=set())
    for f in files:
        for line in open(f, encoding='utf-8', errors='replace'):
            try: r = json.loads(line)
            except ValueError: continue
            if r.get('type') != 'assistant':
                continue
            m = r.get('message') or {}
            if m.get('model'): out['models'].add(m['model'])
            if r.get('effort') or m.get('effort'): out['efforts'].add(r.get('effort') or m.get('effort'))
            for c in m.get('content') or []:
                if isinstance(c, dict) and c.get('type') == 'tool_use':
                    out['tool_calls'] += 1
                    out['tool_calls_by_name'][c['name']] = out['tool_calls_by_name'].get(c['name'], 0) + 1
    out['models'] = sorted(out['models']); out['efforts'] = sorted(out['efforts'])
    return out, files


def run_episode(args, task_id):
    label = args.label + ('_dryrun' if args.dry_run else '')
    turns, src = load_turns(args, task_id)
    ws = os.path.join(D, 'runs', args.suite, f'{label}_0', f'{task_id}_{SUFFIX}')
    ep = os.path.join(D, 'runs', '_episodes', 'claude_code', args.suite, label, task_id)
    home = os.path.join(ep, 'home')
    for p in (ws, ep):
        shutil.rmtree(p, ignore_errors=True)
    shutil.copytree(src, ws, symlinks=False)
    shutil.copytree(os.path.join(HERE, 'home_template'), home)
    key = None if args.dry_run else api_key()
    envf = os.path.join(ep, 'episode.env')
    with open(envf, 'w') as fh:
        os.chmod(envf, 0o600)
        if key:
            fh.write(f'ANTHROPIC_API_KEY={key}\n')
        fh.write(f'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1\nHOME={AGENT_HOME}\n')

    name = f'rb-cc-{uuid.uuid4().hex[:10]}'
    sid = str(uuid.uuid4())
    started = time.time(); status = []; costs = []; error = None
    try:
        subprocess.run(['docker', 'run', '-d', '--name', name] + DOCKER_SECURITY +
                       ['--env-file', envf, '-w', '/workspace',
                        '-v', f'{ws}:/workspace', '-v', f'{home}:{AGENT_HOME}', IMAGE, 'sleep', 'infinity'],
                       check=True, capture_output=True, timeout=180)
        for i, text in enumerate(turns):
            left = WALL_LIMIT_S - (time.time() - started)
            if left <= 0:
                error = 'wall limit reached before turn %d' % i; break
            out_p, err_p = os.path.join(ep, f'turn_{i}.jsonl'), os.path.join(ep, f'turn_{i}.stderr')
            cmd = ['docker', 'exec', '-w', '/workspace', name] + claude_cmd(i, sid, text, args.dry_run)
            try:
                with open(out_p, 'w') as o, open(err_p, 'w') as e:
                    rc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=o, stderr=e, timeout=left).returncode
            except subprocess.TimeoutExpired:
                error = 'wall limit reached during turn %d' % i; status.append('Timeout'); break
            results = []
            for line in open(out_p, encoding='utf-8', errors='replace'):
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get('type') == 'result':
                    results.append(ev)
            last = results[-1] if results else {}
            costs.append(last.get('total_cost_usd'))
            if rc != 0 or not results or last.get('is_error') or last.get('subtype') != 'success':
                status.append('Failed')
                error = 'turn %d: rc=%s result=%s %s' % (i, rc, last.get('subtype'),
                                                         open(err_p, errors='replace').read()[-300:])
                break
            status.append('Completed')
    except subprocess.TimeoutExpired:
        error = error or 'docker run timed out (daemon unresponsive)'
    except subprocess.CalledProcessError as exc:
        error = error or 'docker run failed: %s' % (exc.stderr or b'')[-300:]
    finally:
        try:
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=120)
        except subprocess.TimeoutExpired:
            error = error or 'docker rm timed out (daemon unresponsive)'
        if os.path.exists(envf):
            os.remove(envf)

    summary, session_files = session_summary(home, sid)
    redacted = redact_tree(ep, key) + redact_tree(ws, key) if key else 0
    trace_dir = os.path.join(D, 'traces', args.suite); os.makedirs(trace_dir, exist_ok=True)
    with open(os.path.join(trace_dir, f'{task_id}_{SUFFIX}.{label}.jsonl'), 'w') as t:
        for p in sorted(glob.glob(os.path.join(ep, 'turn_*.jsonl'))):
            for line in open(p, encoding='utf-8', errors='replace'):
                t.write(json.dumps({'turn_file': os.path.basename(p), 'event': line.rstrip('\n')}) + '\n')
    for f in session_files:
        shutil.copy(f, os.path.join(trace_dir, f'{task_id}_{SUFFIX}.{label}.session.jsonl'))
    valid = error is None and len(status) == len(turns)
    if not args.dry_run and valid and (summary['models'] != [MODEL] or summary['efforts'] != [EFFORT]):
        valid, error = False, f"settings mismatch: models={summary['models']} efforts={summary['efforts']}"
    record = dict(task_id=task_id, harness='claude-code 2.1.289', model=MODEL, effort=EFFORT, label=label,
                  valid=valid, error=error, turns=len(turns), turn_status=status, session_id=sid,
                  cost_per_turn_usd=costs, cost_usd=round(sum(c or 0 for c in costs), 4),
                  tool_calls=summary['tool_calls'], tool_calls_by_name=summary['tool_calls_by_name'],
                  models_seen=summary['models'], efforts_seen=summary['efforts'],
                  wall_s=round(time.time() - started, 1), redacted_key_occurrences=redacted,
                  image=IMAGE, workspace=ws)
    res_dir = os.path.join(D, 'results', args.suite); os.makedirs(res_dir, exist_ok=True)
    with open(os.path.join(res_dir, f'res_{label}_0.jsonl'), 'a') as r:
        r.write(json.dumps(record) + '\n')
    print(f"{task_id}: valid={valid} status={status} tool_calls={summary['tool_calls']} "
          f"cost=${record['cost_usd']} wall={record['wall_s']}s" + (f" ERROR {error}" if error else ''), flush=True)
    return record


def main():
    global MODEL, SUFFIX, IMAGE, COMMON          # read by run_episode / claude_cmd at call time
    ap = argparse.ArgumentParser()
    ap.add_argument('--suite', required=True)
    ap.add_argument('--tasks-dir', required=True)
    ap.add_argument('--ids', required=True, help='comma list or @file')
    ap.add_argument('--label', default='claude-code-opus-5')
    ap.add_argument('--model', default=MODEL, help='Claude model id (default: the paper\'s Opus 5 run)')
    ap.add_argument('--image', default=IMAGE, help='episode image (default: built from Dockerfile.mpl)')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    MODEL, IMAGE = a.model, a.image
    SUFFIX = MODEL + '-cc'
    COMMON = ['--model', MODEL] + COMMON[2:]
    assert COMMON[:4] == ['--model', MODEL, '--effort', EFFORT], COMMON[:4]
    ids = [x.strip() for x in (open(a.ids[1:]).read().split() if a.ids.startswith('@') else a.ids.split(',')) if x.strip()]
    for task_id in ids:          # sequential, like the Codex runs
        run_episode(a, task_id)


if __name__ == '__main__':
    main()
