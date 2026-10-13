"""Batch runner for ReconcileBench episodes on upstream mini-SWE-agent.

    python harness/run_tasks.py --config harness/config.yaml --model-yaml harness/models/gpt-5.6-sol.yaml \
        --tasks tasks/general --ids atlas-01,atlas-02 --env local \
        --out results/demo/res.jsonl --dump_dir traces/demo --runs_dir runs/demo

harness/run_suite.sh is the usual entry point. Config precedence is the same as
`mini -c ... -c ...`: upstream mini.yaml, then --config, then --model-yaml. Agent limits, the
model and the environment all come from the merged config.

Each episode copies the task's workspace/ into its own run folder and delivers the task's turns in
one persistent conversation, with a per-turn step budget. The task's probe decides grading:
ATLAS episodes are graded in-run by reconcilebench/grade_vis_atlas.py and RNA_MIXED episodes by
scorers/score_rna_mixed.py; TYPED, NOOP and REVERT episodes are graded afterwards by the scripts
in scorers/.

mini-SWE-agent runs one task per episode. Here turn 0 goes through agent.run(); each later turn
answers any pending tool call, appends the user message and loops agent.step() with the same
error handling as run(). A plain-text reply ends a conversational turn.
"""
import os, sys, json, argparse, shutil, time, subprocess, hashlib, shlex, tempfile, re, fcntl
from pathlib import Path
HERE=os.path.dirname(os.path.abspath(__file__)); REPO=os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO,'reconcilebench'))
sys.path.insert(0, os.path.join(REPO,'scorers'))
from grade_vis_atlas import grade as grade_vis_atlas
from score_rna_mixed import grade as grade_rna_mixed
import yaml
from minisweagent.config import builtin_config_dir
from minisweagent.models import get_model
from minisweagent.environments import get_environment
from minisweagent.agents.default import DefaultAgent, AgentConfig
from minisweagent.exceptions import FormatError, InterruptAgentFlow


# ---- adapter-agnostic message helpers (chat-completions AND Responses API shapes) ----
def is_model_msg(m):   return isinstance(m,dict) and ('actions' in (m.get('extra') or {}) or m.get('role')=='assistant')
def is_obs(m):         return isinstance(m,dict) and (m.get('role') in ('tool','user') or m.get('type')=='function_call_output')
def msg_text(m):
    """Visible text of any message shape: chat 'content' str, or Responses 'output' text items /
    observation 'output'."""
    if not isinstance(m,dict): return ''
    if isinstance(m.get('content'),str): return m['content']
    if isinstance(m.get('output'),str):
        # observations are JSON envelopes {"returncode":0,"output":"..."}: return the inner output
        try:
            import json as _j; inner=_j.loads(m['output'])
            if isinstance(inner,dict) and 'output' in inner: return str(inner.get('output') or '')
        except Exception: pass
        return m['output']
    txt=[]
    for item in (m.get('output') or []):
        if isinstance(item,dict) and item.get('type')=='message':
            for c in item.get('content') or []:
                if isinstance(c,dict) and c.get('text'): txt.append(c['text'])
    return '\n'.join(txt)

def turn_answer(msgs):
    """The turn's answer: the model's own prose if it produced any, else the LAST command's
    output. Concatenating every echoed output would mix in old strings from re-read files."""
    prose=[msg_text(m).strip() for m in msgs if is_model_msg(m) and msg_text(m).strip()]
    if prose: return '\n'.join(prose)[-2000:]
    outs=[msg_text(m).strip() for m in msgs if is_obs(m) and msg_text(m).strip()]
    return (outs[-1] if outs else '')[-2000:]
def has_actions(m):    return bool((m.get('extra') or {}).get('actions')) if isinstance(m,dict) else False

def deep_merge(a,b):
    out=dict(a)
    for k,v in (b or {}).items():
        out[k]=deep_merge(out[k],v) if isinstance(v,dict) and isinstance(out.get(k),dict) else v
    return out

def load_config(config_path, model_yaml):
    cfg=yaml.safe_load(open(os.path.join(builtin_config_dir,'mini.yaml')))
    cfg=deep_merge(cfg, yaml.safe_load(open(config_path)))
    if model_yaml: cfg=deep_merge(cfg, yaml.safe_load(open(model_yaml)))
    return cfg

def docker_ok():
    try: return subprocess.run(['docker','info'],capture_output=True,timeout=10).returncode==0
    except Exception: return False

def snapshot(root):
    out={}
    for dp,_,fs in os.walk(root):
        if '.git' in dp: continue
        for f in fs:
            rel=os.path.relpath(os.path.join(dp,f),root)
            try: out[rel]=open(os.path.join(root,rel),encoding='utf-8').read()
            except Exception: pass
    return out

DENY_ROOTS = [REPO, os.path.expanduser('~/Library/Application Support/mini-swe-agent')]
# Any other checkout that holds gold or other runs must be unreadable from an episode too.
# List such directories in RB_EXTRA_DENY (os.pathsep-separated).
DENY_ROOTS += [d for d in os.environ.get('RB_EXTRA_DENY', '').split(os.pathsep) if d]


def sandbox_profile(workspace, runs_root):
    """Deny the repository, the credential store and every other episode's workspace.

    `(allow default)` first, then the denials, then a narrower allow for this episode's own
    directory: later rules win, so the nested allow re-opens exactly one subtree inside a
    denied one.
    """
    deny = [d for d in DENY_ROOTS + [runs_root] if d and os.path.isdir(d)]
    lines = ['(version 1)', '(allow default)']
    if deny:
        lines.append('(deny file-read* file-write*')
        lines += ['  (subpath "%s")' % os.path.realpath(d) for d in deny]
        lines.append(')')
    # No outbound network, and no writes to the user's Python package folders, so an episode
    # cannot install a package that every later episode would then see.
    lines.append('(deny network-outbound (remote ip))')
    home = os.path.expanduser('~')
    lines.append('(deny file-write* (subpath "%s/Library/Python") (subpath "%s/.local") (subpath "%s/Library/Caches/pip"))'
                 % (home, home, home))
    lines.append('(allow file-read* file-write* (subpath "%s"))' % os.path.realpath(workspace))
    return '\n'.join(lines) + '\n'


def sandboxed(env, workspace):
    """Wrap an environment so every command runs under that profile.

    LocalEnvironment passes each command straight to a shell, so the wrapping happens on the
    command itself, at the one place every action funnels through. The profile is written once
    per episode and removed with the episode.
    """
    if not shutil.which('sandbox-exec'):
        raise SystemExit('sandbox-exec not found: refusing to run models on the host with '
                         'no filesystem isolation. Use --env docker, or pass --no-sandbox '
                         'only for a run whose results will be discarded.')
    # Deny the whole runs root, not just this episode's shard, so no episode can read another
    # shard's workspaces.
    runs_root = os.environ.get('RB_RUNS_ROOT') or os.path.dirname(
        os.path.dirname(os.path.abspath(workspace)))
    prof = os.path.join(tempfile.mkdtemp(prefix='rb_sb_'), 'profile.sb')
    base = sandbox_profile(workspace, runs_root)
    open(prof, 'w').write(base + tmp_rules(set()))
    inner = env.execute

    # Private /tmp without deleting anything. Local mode shares /private/tmp, so before
    # every command the profile is rewritten to hide every /tmp entry this episode did not create
    # (other episodes' files, leftovers, the owner's files), and listing /tmp itself is denied.
    # Commands of all episodes on the machine take turns under one lock, so the entries that appear
    # during a command are known to be this episode's own; they stay usable by it and hidden from
    # every other episode. cmd_log records each command's interval and the /tmp entries it made.
    cmd_log, owned = [], set()
    lock_path = os.environ.get('RB_TMP_LOCK') or os.path.join(REPO, '.tmp_isolation.lock')

    def execute(action, cwd='', *, timeout=None):
        a = dict(action)
        a['command'] = 'sandbox-exec -f %s /bin/bash -c %s' % (
            shlex.quote(prof), shlex.quote(action.get('command', '')))
        with open(lock_path, 'a') as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                before = tmp_entries()
                owned.intersection_update(before)          # gone since: no longer ours
                open(prof, 'w').write(base + tmp_rules(owned))
                t_start = time.time()
                try:
                    return inner(a, cwd, timeout=timeout)
                finally:
                    after = tmp_entries()
                    new = sorted(x for x in after - before if not TMP_HOST.match(os.path.basename(x)))
                    owned.update(new)
                    owned.intersection_update(after)
                    cmd_log.append(dict(t0=round(t_start, 3), t1=round(time.time(), 3), command=action.get('command', ''),
                                        tmp_new=[os.path.basename(x) for x in new if os.path.dirname(x) == TMP_ROOT],
                                        vartmp_new=[os.path.basename(x) for x in new if os.path.dirname(x) == VARTMP_ROOT]))
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)

    env.execute = execute
    env._sandbox_profile = prof
    env._cmd_log = cmd_log
    return env


TMP_ROOT = '/private/tmp'
VARTMP_ROOT = '/private/var/tmp'   # also shared between episodes


def tmp_entries():
    """Full paths of the top-level entries of both shared temp folders."""
    return {os.path.join(r, n) for r in (TMP_ROOT, VARTMP_ROOT) if os.path.isdir(r) for n in os.listdir(r)}
# entries made by the machine itself while a command runs; never attributed to an episode
TMP_HOST = re.compile(r'^(claude|claude-.+|codex-.+|com\..+|node-compile-cache|powerlog|tmux-\d+|launchd-.+)$')


def tmp_rules(owned):
    """Profile lines hiding every /private/tmp and /private/var/tmp entry not in `owned` (full
    paths) and denying a listing of either folder."""
    paths = sorted(x for x in tmp_entries() if x not in owned)
    esc = lambda x: x.replace('\\', '\\\\').replace('"', '\\"')
    lines = ['(deny file-read-data (literal "%s") (literal "%s"))' % (TMP_ROOT, VARTMP_ROOT)]
    if paths:
        lines.append('(deny file-read* file-write*')
        lines += ['  (subpath "%s")' % esc(x) for x in paths]
        lines.append(')')
    return '\n'.join(lines) + '\n'


def build_agent(cfg, root, env_kind, no_sandbox=False):
    mcfg=dict(cfg['model']); model=get_model(None, mcfg)
    _orig=model._calculate_cost
    def _safe(resp):
        try: return _orig(resp)
        except Exception: return 0.0
    model._calculate_cost=_safe
    ecfg=dict(cfg['environment'])
    if env_kind=='docker':
        ecfg['run_args']=list(ecfg.get('run_args',[]))+['--mount',f'type=bind,source={root},target={ecfg.get("cwd","/workspace")}']
        env=get_environment(ecfg)
    else:
        # The local environment runs model-generated shell commands directly on the host.
        #
        # (1) It inherits the process environment, including the API key driving the run.
        #     config.env is merged over os.environ, so blanking the credential names removes
        #     them from the agent's shell.
        # (2) It inherits the filesystem. Run folders live outside the task folders (see
        #     --runs_dir), and every command runs under a sandbox profile that denies the
        #     repository (gold, the grader, every task.json), the credential directory and
        #     every other episode's workspace, while allowing this episode's own.
        scrub={k:'' for k in os.environ
               if any(t in k.upper() for t in ('API_KEY','TOKEN','SECRET','PASSWORD',
                                               'CREDENTIAL','_KEY','AWS_','ANTHROPIC',
                                               'OPENAI','SESSION'))}
        env=get_environment({'environment_class':'local','cwd':root,
                             'timeout':ecfg.get('timeout',30),'env':scrub})
        if not no_sandbox:
            env=sandboxed(env, root)
    acfg={k:v for k,v in cfg['agent'].items() if k in AgentConfig.model_fields}
    acfg['step_limit']=int(acfg.get('step_limit',60))
    return DefaultAgent(model, env, **acfg)

STATUS = []          # exit status per turn of the episode run_turns() is driving


def run_turns(agent, turns, per_turn_steps=12):
    def loop(max_steps):
        n0=len(agent.messages); steps=0
        while True:
            if steps>=max_steps:
                txt=turn_answer(agent.messages[n0:])
                agent.add_messages({'role':'exit','content':txt,'extra':{'exit_status':'TurnBudget','submission':txt}}); break
            steps+=1
            try: agent.step()
            except FormatError as e:
                # the adapter guarantees e.messages[0] is the model's response message; on the
                # Responses API it carries neither 'role' nor parsed 'actions', so test it directly
                asst=e.messages[0] if e.messages else None
                txt=msg_text(asst).strip() if asst else ''
                if asst and txt and not has_actions(asst) and not asst.get('tool_calls'):
                    agent.add_messages(asst)
                    agent.add_messages({'role':'exit','content':txt,'extra':{'exit_status':'ChatAnswer','submission':txt}}); break
                agent.add_messages(*e.messages)
            except InterruptAgentFlow as e: agent.add_messages(*e.messages)
            if agent.messages and agent.messages[-1].get('role')=='exit': break
    finals=[]; STATUS.clear()
    for ti,t in enumerate(turns):
        start=len(agent.messages)
        if ti==0:
            agent.run(t)
            res=(agent.messages[-1].get('extra') or {}) if agent.messages else {}
        else:
            exit_content=''
            if agent.messages[-1].get('role')=='exit': exit_content=str(agent.messages.pop().get('content') or '')
            # The submit action's tool call has no observation yet (Submitted interrupts
            # execute_actions). Give it one via the MODEL'S OWN formatter, so chat and Responses
            # adapters both accept it.
            last=next((m for m in reversed(agent.messages) if is_model_msg(m)),None)
            if last is not None:
                acts=(last.get('extra') or {}).get('actions') or []
                idx=len(agent.messages)-1-next(i for i,m in enumerate(reversed(agent.messages)) if m is last)
                has_obs=any(is_obs(m) for m in agent.messages[idx+1:])
                if acts and not has_obs:
                    outs=[{'output': exit_content or 'submitted', 'returncode': 0, 'exception_info': '', 'extra': {}} for _ in acts]   # full env.execute shape (templates read exception_info)
                    agent.add_messages(*agent.model.format_observation_messages(last, outs, agent.get_template_vars()))
            agent.add_messages(agent.model.format_message(role='user',content=t)); loop(per_turn_steps)
            res=agent.messages[-1].get('extra',{})
        sub=str(res.get('submission','') or '').strip()
        if not sub:
            sub=turn_answer(agent.messages[start:])
        # The exit status of each turn. A turn that ended in a format-error loop and used its
        # whole step budget otherwise looks the same, in the results file, as one that simply
        # answered with no prose.
        STATUS.append(str(res.get('exit_status','') or ''))
        finals.append(sub); yield ti, sub

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--config', default=os.path.join(HERE,'config.yaml'))
    ap.add_argument('--model-yaml', default=None)
    ap.add_argument('--env', default='auto', choices=['auto','local','docker'])
    ap.add_argument('--tasks', default=os.path.join(REPO,'tasks','general'))
    ap.add_argument('--ids', required=True, help='comma-separated task ids')
    ap.add_argument('--out', default=os.path.join(REPO,'results','manual','res.jsonl'))
    ap.add_argument('--dump_dir', default=os.path.join(REPO,'traces','manual'))
    ap.add_argument('--runs_dir', default=os.path.join(REPO,'runs','manual'))
    ap.add_argument('--no-sandbox', dest='no_sandbox', action='store_true',
                    help='run WITHOUT filesystem isolation. Only for a run whose results '
                         'will be discarded; the episode record marks it.')
    a=ap.parse_args(); os.environ['MSWEA_SILENT_STARTUP']='1'
    cfg=load_config(a.config, a.model_yaml)
    env_kind=a.env if a.env!='auto' else ('docker' if cfg['environment'].get('environment_class')=='docker' and docker_ok() else 'local')
    if cfg['environment'].get('environment_class')=='docker' and env_kind=='local': print('[note] Docker not available -> local environment', flush=True)
    ids=[x.strip() for x in a.ids.split(',') if x.strip()]
    os.makedirs(os.path.dirname(a.out),exist_ok=True); os.makedirs(a.dump_dir,exist_ok=True)
    # Truncate, never append: a resumed run would otherwise leave two records for one episode.
    fh=open(a.out,'w')
    mname=cfg['model']['model_name']
    for tid in ids:
        task=json.load(open(os.path.join(a.tasks,tid,'task.json')))
        root=os.path.join(a.runs_dir,f"{tid}_{mname.split('/')[-1]}")
        if os.path.exists(root): shutil.rmtree(root)
        shutil.copytree(os.path.join(a.tasks,tid,'workspace'), root)
        agent=build_agent(cfg, root, env_kind, a.no_sandbox); t0=time.time(); finals=[]
        print(f'→ {tid} [mini-swe/{env_kind}] {mname}', flush=True)
        for ti,fin in run_turns(agent, task['turns']):
            finals.append(fin)
        probe=task.get('probe')
        if probe=='ATLAS':
            g=grade_vis_atlas(root, task['exp']); g['arm']=task['arm']
            g['final']=finals[-1][:600]
        elif probe=='RNA_MIXED':
            g=grade_rna_mixed(tid, Path(root)); g['probe']=probe; g['arm']=task['arm']
        elif probe in ('TYPED','NOOP','REVERT'):
            # Graded afterwards: scorers/score_general_*.py (TYPED), scorers/score_noop.py
            # and scorers/score_retraction.py.
            g=dict(probe=probe, arm=task['arm'], graded='offline',
                   final=finals[-1][:400])
        else:
            raise SystemExit('unsupported probe %r in %s' % (probe, tid))
        # The decision-relevant part of the merged config, and a hash of it, so a results file
        # states what produced it and two runs can be checked for the same configuration.
        _sbp = ('docker' if env_kind == 'docker' else
                getattr(getattr(agent, 'env', None), '_sandbox_profile', None))
        _mc=cfg['model']; _ac=cfg['agent']
        run_cfg=dict(model_name=_mc.get('model_name'), model_kwargs=_mc.get('model_kwargs'),
                     step_limit=_ac.get('step_limit'), cost_limit=_ac.get('cost_limit'),
                     wall_time_limit_seconds=_ac.get('wall_time_limit_seconds'),
                     environment_class=cfg['environment'].get('environment_class'), env=env_kind,
                     sandboxed=bool(env_kind == 'docker' or not a.no_sandbox))
        run_cfg['sha']=hashlib.sha256(
            json.dumps(run_cfg, sort_keys=True).encode()).hexdigest()[:16]
        rec=dict(task_id=tid, scaffold='mini-swe', env=env_kind, model=mname, cost=getattr(agent,'cost',0.0),
                 wall_s=round(time.time()-t0,1), grade=g, run_cfg=run_cfg,
                 # The profile the episode ran under. Kept out of run_cfg, whose hash must be
                 # the same for every episode of one configuration.
                 sandbox=dict(
                     profile_path=_sbp,
                     profile_sha=(hashlib.sha256(open(_sbp, 'rb').read()).hexdigest()[:16]
                                  if _sbp and os.path.exists(_sbp) else None),
                     denied_roots=sorted(
                         re.findall(r'\(subpath "([^"]+)"\)',
                                    open(_sbp).read().split('(allow file-read* file-write*')[0])
                     ) if _sbp and os.path.exists(_sbp) else []),
                 turn_status=list(STATUS),
                 turn_finals=[f[:200] for f in finals])
        _cmd_log = list(getattr(getattr(agent, 'env', None), '_cmd_log', None) or [])
        rec['episode_t0'] = round(t0, 3); rec['episode_t1'] = round(time.time(), 3)
        fh.write(json.dumps(rec)+'\n'); fh.flush()
        json.dump(dict(task=task, scaffold='mini-swe', env=env_kind, model=mname, config=cfg, messages=agent.messages,
                       post_workspace=snapshot(root), grade=g,
                       cmd_log=_cmd_log, episode_t0=rec['episode_t0'], episode_t1=rec['episode_t1']),
                  open(os.path.join(a.dump_dir,f"{tid}_{mname.split('/')[-1]}.json"),'w'), indent=1)
        if probe=='ATLAS':
            print(f"   [ATLAS/{g['target']}] rr={g['rr']} exact={g['exact_match']} "
                  f"src_edit={g['source_edit_ok']} build={g['build_step_run']}\n"
                  f"   repaired={g['repaired']}\n   stale={g['stale']}\n"
                  f"   bulk {g['bulk_files']} files, touched={len(g['bulk_touched'])}, "
                  f"DAMAGED={g['bulk_damaged'] or 'none'}\n"
                  f"   control={g['control_intact']}  ${rec['cost']:.3f}", flush=True)
        elif probe=='RNA_MIXED':
            r=g['roles']
            print('   ' + ' '.join('%s=%d/%d' % (k, r[k]['correct'], r[k]['total']) for k in r) +
                  f" closed={g['strict_closure']} collateral={len(g['files']['collateral_edits'])}"
                  f"  ${rec['cost']:.3f}", flush=True)
        else:
            print(f"   [{probe}/{g['arm']}] graded offline  ${rec['cost']:.3f}", flush=True)

if __name__=='__main__': main()
