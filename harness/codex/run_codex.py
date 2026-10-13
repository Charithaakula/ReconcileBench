#!/usr/bin/env python3
"""Run ReconcileBench episodes in the Codex CLI harness, one Docker container per episode.

    python3 run_codex.py --suite general_propagation --tasks-dir ../../tasks/general_propagation \
        --ids evidence-atlas-01,policy-atlas-01
    add --dry-run to replace Codex with a stub (no model calls) for testing the driver

Per episode:
  1. Copy the task's starting workspace (symlinks followed) to
     runs/<suite>/<label>_0/<id>_<model-slug>/, the layout the scorers read.
  2. Make a fresh CODEX_HOME from codex/home_template/config.toml plus the Codex login
     (codex/auth/auth.json). No state is shared between episodes.
  3. Start the pinned image with only those two directories mounted, then deliver the task's
     turns in one Codex session: `codex exec` for the first turn, `codex exec resume <thread>`
     for the rest. Stdin is closed (codex exec otherwise waits for more input).
  4. Any failed or timed-out turn marks the episode invalid. Invalid episodes are recorded and
     never scored; rerun them from scratch.
  5. Remove the container and the episode's login copy, redact login tokens from the saved
     events, and append one record to results/<suite>/res_<label>_0.jsonl.

Settings come from codex/home_template/config.toml (model, effort, sandbox, disabled features),
validated with --strict-config on every turn. See codex/README.md.
"""
import argparse, glob, hashlib, json, os, shutil, subprocess, sys, time, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.dirname(os.path.dirname(HERE))   # repository root: runs/, results/, traces/ live here
IMAGE = 'reconcilebench-codex:0.157.1'
MODEL_SLUG = 'gpt-5.6-sol'
WALL_LIMIT_S = 3600                      # the same one-hour episode limit as mini-SWE-agent


def sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def load_turns(args, task_id):
    task = json.load(open(os.path.join(args.tasks_dir, task_id, 'task.json')))
    return list(task['turns']), os.path.join(args.tasks_dir, task_id, 'workspace')


def secrets(auth_path):
    """Every string value in the login file long enough to be a credential, for redaction."""
    out = set()
    def walk(x):
        if isinstance(x, dict):
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
        elif isinstance(x, str) and len(x) >= 20:
            out.add(x)
    try:
        walk(json.load(open(auth_path)))
    except Exception:
        pass
    return out


def redact(paths, values):
    hits = 0
    for p in paths:
        text = open(p, encoding='utf-8', errors='replace').read()
        for v in values:
            if v in text:
                hits += text.count(v); text = text.replace(v, '<REDACTED_LOGIN_TOKEN>')
        open(p, 'w', encoding='utf-8').write(text)
    return hits


def session_summary(home):
    """Read the Codex session file (the complete record; --json events omit commands nested in
    code-mode `exec` scripts). Returns tool-use counts, settings seen, and plan usage."""
    files = sorted(glob.glob(os.path.join(home, 'sessions', '*', '*', '*', '*.jsonl')))
    out = dict(session_files=[os.path.basename(f) for f in files], top_level_tool_calls=0,
               nested_commands=0, turn_contexts=[], used_percent_first=None,
               used_percent_last=None, window_minutes=None, limit_reached=None)
    for f in files:
        for line in open(f, encoding='utf-8', errors='replace'):
            try: r = json.loads(line)
            except ValueError: continue
            t, p = r.get('type'), r.get('payload') or {}
            if t == 'response_item' and p.get('type') in ('function_call', 'custom_tool_call', 'local_shell_call'):
                out['top_level_tool_calls'] += 1
            elif t == 'event_msg' and p.get('type') == 'item_completed' and \
                    (p.get('item') or {}).get('type') == 'CommandExecution':
                out['nested_commands'] += 1
            elif t == 'turn_context':
                ctx = {k: p.get(k) for k in ('model', 'effort', 'approval_policy', 'summary')}
                ctx['sandbox'] = (p.get('sandbox_policy') or {}).get('type')
                ctx['network'] = (p.get('sandbox_policy') or {}).get('network_access')
                out['turn_contexts'].append(ctx)
            elif t == 'event_msg' and p.get('type') == 'token_count':
                rl = p.get('rate_limits') or {}
                prim = rl.get('primary') or {}
                if prim.get('used_percent') is not None:
                    if out['used_percent_first'] is None:
                        out['used_percent_first'] = prim['used_percent']
                    out['used_percent_last'] = prim['used_percent']
                    out['window_minutes'] = prim.get('window_minutes')
                if rl.get('rate_limit_reached_type'):
                    out['limit_reached'] = rl['rate_limit_reached_type']
    return out, files


def codex_cmd(turn_index, thread_id, text, dry):
    if dry:
        # Stub: echoes events shaped like Codex's, so ordering, parsing and layout can be checked.
        stub = ('python3 -c "import json,sys; t=sys.argv[1]; n=sys.argv[2]; '
                'print(json.dumps({\'type\':\'thread.started\',\'thread_id\':\'dry-thread\'})); '
                'print(json.dumps({\'type\':\'item.completed\',\'item\':{\'type\':\'agent_message\',\'text\':\'DRY turn \'+n+\': \'+t[:80]}})); '
                'print(json.dumps({\'type\':\'turn.completed\',\'usage\':{}}))" "$0" "$1"')
        return ['sh', '-c', stub, text, str(turn_index)]
    base = ['codex', 'exec']
    if turn_index > 0:
        base += ['resume', thread_id]
    return base + ['--strict-config', '--skip-git-repo-check', '--json', text]


def run_episode(args, task_id):
    label = args.label + ('_dryrun' if args.dry_run else '')
    turns, src = load_turns(args, task_id)
    ws = os.path.join(D, 'runs', args.suite, f'{label}_0', f'{task_id}_{MODEL_SLUG}')
    ep = os.path.join(D, 'runs', '_episodes', 'codex', args.suite, label, task_id)
    home = os.path.join(ep, 'home')
    for p in (ws, ep):
        shutil.rmtree(p, ignore_errors=True)
    shutil.copytree(src, ws, symlinks=False)
    os.makedirs(home)
    shutil.copy(os.path.join(HERE, 'home_template', 'config.toml'), home)
    auth_src = os.path.join(HERE, 'auth', 'auth.json')
    if not args.dry_run:
        shutil.copy(auth_src, os.path.join(home, 'auth.json'))
    tokens = secrets(auth_src) if os.path.exists(auth_src) else set()

    name = f'rb-codex-{uuid.uuid4().hex[:10]}'
    subprocess.run(['docker', 'run', '-d', '--name', name, '--security-opt', 'seccomp=unconfined',
                    '-e', 'SHELL=/bin/bash', '-w', '/workspace',
                    '-v', f'{ws}:/workspace', '-v', f'{home}:/codex-home',
                    IMAGE, 'sleep', 'infinity'], check=True, capture_output=True,
                   timeout=180)   # fail fast if the Docker daemon hangs
    started = time.time(); thread_id = None; status = []; usage = []; n_cmds = []; error = None
    try:
        for i, text in enumerate(turns):
            left = WALL_LIMIT_S - (time.time() - started)
            if left <= 0:
                error = 'wall limit reached before turn %d' % i; break
            out_p, err_p = os.path.join(ep, f'turn_{i}.jsonl'), os.path.join(ep, f'turn_{i}.stderr')
            cmd = ['docker', 'exec', '-w', '/workspace', name] + codex_cmd(i, thread_id, text, args.dry_run)
            try:
                with open(out_p, 'w') as o, open(err_p, 'w') as e:
                    rc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=o, stderr=e,
                                        timeout=left).returncode
            except subprocess.TimeoutExpired:
                error = 'wall limit reached during turn %d' % i; status.append('Timeout'); break
            events = []
            for line in open(out_p, encoding='utf-8', errors='replace'):
                try: events.append(json.loads(line))
                except ValueError: pass
            for ev in events:
                if ev.get('type') == 'thread.started' and thread_id is None:
                    thread_id = ev.get('thread_id')
            done = [ev for ev in events if ev.get('type') == 'turn.completed']
            failed = [ev for ev in events if ev.get('type') in ('turn.failed', 'error')]
            n_cmds.append(sum(1 for ev in events if ev.get('type') == 'item.completed'
                              and (ev.get('item') or {}).get('type') == 'command_execution'))
            usage.append(done[-1].get('usage') if done else None)
            if rc != 0 or failed or not done or thread_id is None:
                status.append('Failed')
                error = 'turn %d: rc=%s %s' % (i, rc, json.dumps(failed[-1])[:400] if failed else
                                               open(err_p, errors='replace').read()[-400:])
                break
            status.append('Completed')
    finally:
        try:
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=120)
        except subprocess.TimeoutExpired:
            error = error or 'docker rm timed out (daemon unresponsive)'
        # Keep the login fresh for the next episode if Codex refreshed it, then drop the copy.
        ep_auth = os.path.join(home, 'auth.json')
        if os.path.exists(ep_auth):
            try:
                if json.load(open(ep_auth)).get('last_refresh') != json.load(open(auth_src)).get('last_refresh'):
                    shutil.copy(ep_auth, auth_src)
            except Exception:
                pass
            tokens |= secrets(ep_auth)
            os.remove(ep_auth)

    logs = sorted(os.path.join(ep, f) for f in os.listdir(ep) if f.startswith('turn_'))
    summary, session_files = session_summary(home)
    redacted = redact(logs + session_files, tokens)
    trace_dir = os.path.join(D, 'traces', args.suite); os.makedirs(trace_dir, exist_ok=True)
    with open(os.path.join(trace_dir, f'{task_id}_{MODEL_SLUG}.{label}.jsonl'), 'w') as t:
        for p in logs:
            if p.endswith('.jsonl'):
                for line in open(p, encoding='utf-8', errors='replace'):
                    t.write(json.dumps({'turn_file': os.path.basename(p), 'event': line.rstrip('\n')}) + '\n')
    # The session file is the authoritative trace (complete tool calls, outputs, settings).
    for f in session_files:
        shutil.copy(f, os.path.join(trace_dir, f'{task_id}_{MODEL_SLUG}.{label}.session.jsonl'))
    if summary['limit_reached'] and error is None:
        error = 'plan usage limit reached: %s' % summary['limit_reached']
    valid = error is None and len(status) == len(turns)
    record = dict(task_id=task_id, harness='codex-cli 0.157.1', model=MODEL_SLUG, label=label,
                  valid=valid, error=error, turns=len(turns), turn_status=status,
                  commands_per_turn_json_events=n_cmds, usage_per_turn=usage, thread_id=thread_id,
                  top_level_tool_calls=summary['top_level_tool_calls'],
                  nested_commands=summary['nested_commands'], turn_contexts=summary['turn_contexts'],
                  plan_used_percent=[summary['used_percent_first'], summary['used_percent_last']],
                  plan_window_minutes=summary['window_minutes'], plan_limit_reached=summary['limit_reached'],
                  wall_s=round(time.time() - started, 1), redacted_token_occurrences=redacted,
                  config_sha256=sha(os.path.join(HERE, 'home_template', 'config.toml')),
                  image=IMAGE, workspace=ws)
    res_dir = os.path.join(D, 'results', args.suite); os.makedirs(res_dir, exist_ok=True)
    with open(os.path.join(res_dir, f'res_{label}_0.jsonl'), 'a') as r:
        r.write(json.dumps(record) + '\n')
    print(f"{task_id}: valid={valid} status={status} tool_calls={summary['top_level_tool_calls']} "
          f"nested_cmds={summary['nested_commands']} plan_used={record['plan_used_percent']} "
          f"wall={record['wall_s']}s" + (f" ERROR {error}" if error else ''), flush=True)
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--suite', required=True)
    ap.add_argument('--tasks-dir', required=True)
    ap.add_argument('--ids', required=True, help='comma list or @file')
    ap.add_argument('--label', default='codex-gpt-5.6-sol')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--max-plan-used', type=float, default=None,
                    help='stop the batch once the plan usage percentage reaches this value')
    a = ap.parse_args()
    if not a.dry_run and not os.path.exists(os.path.join(HERE, 'auth', 'auth.json')):
        sys.exit('no Codex login at codex/auth/auth.json')
    ids = [x.strip() for x in (open(a.ids[1:]).read().split() if a.ids.startswith('@') else a.ids.split(',')) if x.strip()]
    for task_id in ids:          # sequential: one episode at a time (login refresh, plan limits)
        rec = run_episode(a, task_id)
        used = (rec.get('plan_used_percent') or [None, None])[1]
        if rec.get('plan_limit_reached'):
            sys.exit(f'stopping: plan usage limit reached after {task_id}; rerun invalid episodes after the reset')
        if a.max_plan_used is not None and used is not None and used >= a.max_plan_used:
            sys.exit(f'stopping: plan usage {used}% reached the --max-plan-used ceiling ({a.max_plan_used}%) after {task_id}')


if __name__ == '__main__':
    main()
