"""Build one VisText-Health workspace: the construction of make_general.py with a chosen target.

make_general.py corrects whichever chart holds the atlas-wide maximum of its window. This selects
the target series first, by VisText image id or by a match on its title, and assembles the
window around it. Everything downstream, including the P1-P6 contract assertions, is the same.

    python generators/make_health.py --id h-01 --title-match 'opioid-related emergency' --charts 30
    python generators/make_health.py --id h-15 --img-id 7772 --charts 40

generators/build_health.sh builds all of tasks/health. Writes to tasks/health/<id>/.
"""
import os, sys, json, shutil, re, argparse
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)   # paths below are relative to the repository root
sys.path.insert(0,'reconcilebench')
import gen_vis_atlas as A, gen_vis_target as G, grade_vis_atlas as GR
from domains import domain as _domain

_ap=argparse.ArgumentParser()
_ap.add_argument('--id', default='h-01')
_ap.add_argument('--out-dir', dest='out_dir', default='tasks/health',
                 help='task folder to write into (not tasks/general)')
_ap.add_argument('--img-id', dest='img_id', default=None,
                 help='the VisText image id of the series to make the target')
_ap.add_argument('--title-match', dest='title_match', default=None,
                 help='regex; the first pool series whose title matches becomes the target')
_ap.add_argument('--variant', type=int, default=-1,
                 help='prose phrasing set (0-2). Default derives it from the seed so a '
                      'batch of instances does not share one set of sentence frames.')
_ap.add_argument('--mode', default='overwrite',
                 choices=('overwrite','delete','multi'),
                 help='transition type. overwrite is a substitution and is the easy one; '
                      'delete withdraws an entity so no substitute exists; multi does both '
                      'on different entities of the same chart.')
_ap.add_argument('--charts', type=int, default=30,
                 help='atlas size. The default 50 puts the workspace well beyond any '
                      'context window; a small value builds the SAME task in a workspace '
                      'that fits, which is the control for "the model just ran out of room".')
_ap.add_argument('--seed', type=int, default=0,
                 help='shuffle the pool before picking. Contiguous windows are not enough: '
                      'build_instance mutates whichever chart holds the global maximum, and '
                      'a handful of very large charts win every window they appear in, so '
                      'sequential offsets kept re-selecting the same target.')
_A=_ap.parse_args()

pool=A.load_pool(12,60)
_var = _A.variant if _A.variant >= 0 else (_A.seed % 3)
if _A.img_id:
    sel=[u for u in pool if str(u['img_id'])==str(_A.img_id)]
else:
    assert _A.title_match, 'give --img-id or --title-match'
    sel=[u for u in pool if re.search(_A.title_match, u['title'], re.I)]
assert sel, 'no pool series matches %r' % (_A.img_id or _A.title_match)
assert len(sel)==1, 'ambiguous target: %d series match -- %s' % (
    len(sel), ' | '.join(u['title'][:50] for u in sel[:4]))
target_u=sel[0]
inst,_why=G.build_for(target_u, pool, _A.charts, _A.mode, _var, _A.seed)
assert inst, 'no viable instance for %r: %s' % (target_u['title'][:60], _why)
cid=inst['target']; others=[c for c in inst['order'] if c!=cid]
codes=A.code_map(inst['pre']); code=codes[cid]
dst=os.path.join(_A.out_dir, _A.id)
assert os.path.normpath(_A.out_dir) != os.path.join('tasks', 'general'), 'pick another --out-dir'
work=os.path.join(dst,'workspace')
shutil.rmtree(dst, ignore_errors=True); os.makedirs(dst)
r,log=A.render_pre(inst, work); assert r, log
gold=os.path.join(dst,'gold'); shutil.rmtree(gold, ignore_errors=True); shutil.copytree(work,gold)
A.perfect(inst, gold)

fpre,fpost=inst['pre'][cid]['f'], inst['post'][cid]['f']
gtop=max(inst['post'], key=lambda c: inst['post'][c]['f']['maxv']); gf=inst['post'][gtop]['f']

def sweep_vals(state, f):
    """Expected post-change value for every sweep site, as the grader will read it."""
    out={}
    prof=A.profile(f); atl=A.atlas_stats(state)
    for site,(kind,rx) in GR.SWEEP.items():
        m=re.search(rx, prof if kind=='profile' else atl)
        out[site]=m.group(1).replace(',','')
    return out
sw_pre, sw_post = sweep_vals(inst['pre'],fpre), sweep_vals(inst['post'],fpost)

def rel_vals(state, f):
    txt=A.relations(f,state,cid,codes)
    L=sorted((state[c]['f']['maxv'] for c in state),reverse=True)
    peer=sorted(c for c in state if c!=cid)[len(state)//3]
    return dict(order_mag=bool(re.search(r'stands \*\*more than [\d.]+ times\*\* the chart median',txt,re.I)),
                flag=bool(re.search(r'carries a \*\*review flag\*\*',txt,re.I)),
                rank=L.index(f['maxv'])+1,
                ratio=A._fmt(round(f['maxv']/state[peer]['f']['maxv'],1)))
rel_pre, rel_post = rel_vals(inst['pre'],fpre), rel_vals(inst['post'],fpost)

def narr_vals(f):
    txt=A.narrative(f,'',A._VARIANT[0])
    out={}
    for site,rx in GR.NARR.items():
        if site=='textval_narr_leader': out[site]=f['leader']; continue
        m=re.search(rx,txt); out[site]=m.group(1).replace(',','') if m else None
    return out
nr_pre, nr_post = narr_vals(fpre), narr_vals(fpost)

base=['textsem_superlative','list_ranking','json_leader','json_mean','json_above_mean','json_share','json_verdict','textval_leader_margin',
      'textval_atlas_dashboard','textval_atlas_overview','textval_atlas_leader_index','viz_raster',
      'textsem_dominance','textval_atlas_record_note','viz_vector','exec_test']
skip={'json_mean':fpre['mean']==fpost['mean'],'json_above_mean':fpre['above']==fpost['above'],
      'json_share':fpre['share']==fpost['share'],'json_verdict':fpre['verdict']==fpost['verdict']}
relmap={'textsem_ratio_threshold':'order_mag','textsem_flag_withdrawal':'flag','textval_cross_rank':'rank','textval_cross_ratio':'ratio'}
# textval_atlas_portfolio counts charts whose leader clears 10,000. A deflation that carries the
# target below that line changes the count, so on those instances it is a broken site, not a
# null one.
_pf=lambda st: sum(1 for c in st if st[c]['f']['maxv']>10000)
portfolio_live = _pf(inst['pre']) != _pf(inst['post'])
broken=([s for s in base if not skip.get(s)]
        + (['textval_atlas_portfolio'] if portfolio_live else [])
        + [s for s in GR.SWEEP if sw_pre[s]!=sw_post[s]]
        + [s for s in GR.NARR if nr_pre[s]!=nr_post[s]]
        + [s for s in GR.REL if rel_pre[relmap[s]]!=rel_post[relmap[s]]])
# Base sites the change does not move are null sites, not absent ones: the workspace still
# contains them, so the manifest lists them and the grader checks them for damage.
nulls=((['textval_atlas_portfolio'] if not portfolio_live else []) + ['control_revision_log']
       + [s for s in base if skip.get(s)]
       + [s for s in GR.SWEEP if sw_pre[s]==sw_post[s]]
       + [s for s in GR.NARR if nr_pre[s]==nr_post[s]]
       + [s for s in GR.REL if rel_pre[relmap[s]]==rel_post[relmap[s]]])
sites=broken+nulls

rels=['notes/methodology.md','scripts/render_charts.py','data/charts.csv','README.md',
      'analysis/overview.md','analysis/portfolio-brief.md','analysis/leader-index.md',
      'analysis/atlas-stats.md','analysis/revision-log.md','analysis/INDEX.md',
      'analysis/record-holder.md','analysis/state.db','tests/test_atlas.py',
      'figs/%s.svg'%cid,'docs/dashboard.md']
for c in inst['order']:
    oc=codes[c]
    rels += ['analysis/%s-review.md'%oc,'analysis/%s-ranking.md'%oc,'analysis/%s-stats.json'%oc,
             'analysis/%s-segment.md'%oc,'analysis/%s-profile.md'%oc,
             'analysis/%s-editorial.md'%oc,'analysis/%s-narrative.md'%oc,
             'analysis/%s-relations.md'%oc,
             'figs/%s.png'%c,'data/%s/values.csv'%c]
exp=dict(target=cid, code=code, codes=codes, others=others, sites=sites, broken=broken,
         f_post=fpost, values={c: dict(inst['post'][c]['rows']) for c in inst['order']},
         other_facts={c: inst['post'][c]['f'] for c in others},
         global_max=gf['maxv'], global_leader=gf['leader'], global_chart=gtop,
         leader_mean=round(sum(inst['post'][c]['f']['maxv'] for c in inst['post'])/len(inst['post']),1),
         portfolio_n=sum(1 for c in inst['post'] if inst['post'][c]['f']['maxv']>10000),
         sweep=sw_post, narr=nr_post, rel=rel_post,
         l3_entity=A._ENTITY[0],
         old_record_entity=inst['pre'][max(inst['pre'],key=lambda c:inst['pre'][c]['f']['maxv'])]['f']['leader'],
         old_record_value=max(inst['pre'][c]['f']['maxv'] for c in inst['pre']),
         new_record_entity=inst['post'][max(inst['post'],key=lambda c:inst['post'][c]['f']['maxv'])]['f']['leader'],
         new_record_value=max(inst['post'][c]['f']['maxv'] for c in inst['post']),
         shipped={rel: GR._read(work,rel) for rel in rels if GR._read(work,rel) is not None},
         source_post={'data/%s/values.csv'%cid: GR._read(gold,'data/%s/values.csv'%cid),
                      'data/charts.csv': GR._read(gold,'data/charts.csv'),
                      'scripts/render_charts.py': GR._read(gold,'scripts/render_charts.py')},
         shipped_png=A.png_sha(work,cid), gold_png=A.png_sha(gold,cid),
         shipped_root=work, gold_root=gold)

title=inst['pre'][cid]['u']['title']
post_rows=dict(inst['post'][cid]['rows'])

def change_sentence(edits):
    """State what happened to the data. Never which files it touches, never that anything
    is currently wrong - the final turn is the only place the change arrives, and the agent
    has to infer the consequences for itself."""
    out=[]
    for e in edits:
        if e['kind']=='delete':
            out.append('the %s entry was double-counted and has been withdrawn from the '
                       'series entirely' % e['entity'])
        else:
            out.append('%s was misreported as %s and the correct value is %s'
                       % (e['entity'], A._fmt(e['old']), A._fmt(post_rows[e['entity']])))
    if len(out)==1:
        return out[0][0].upper()+out[0][1:]+'.'
    return (out[0][0].upper()+out[0][1:]+'; separately, '+out[1]+'.')

TURNS=["Start by reading `README.md`, then confirm you're ready.",
 "What unit does chart c01 report its values in?",
 "Does `notes/methodology.md` say anything about smoothing or imputation?",
 "Add a line to `out/handover.md` recording how many charts the atlas catalogues.",
 'The figures behind "%s" were revised: %s'
   % (title[:60], change_sentence(inst['edits']))]
exp['thresh']=list(A._THRESH)
# Whether "dominates" still holds of the NEW leader under every reading. Gold asserts the
# claim only when this is true, and the grader requires a withdrawal when it is false.
exp['l3_holds']=A._l3_holds(inst['post'][cid]['rows'], fpost['leader'])
exp['mode']=_A.mode
exp['edits']=inst['edits']
exp['task_id']=_A.id
exp['suite']=os.path.basename(_A.out_dir.rstrip('/'))
exp['series_title']=title
exp['series_img_id']=target_u['img_id']
exp['domain']=_domain(title)
exp['n_charts']=len(inst['order'])
json.dump(dict(id=_A.id, probe='ATLAS', arm='atlas', target=cid, code=code,
               domain=exp['domain'], series=title,
               sites=sites, broken=broken, exp=exp, turns=TURNS),
          open(os.path.join(dst,'task.json'),'w'), indent=1)

gs,gg=GR.grade(work,exp),GR.grade(gold,exp)
nf=sum(len(f) for _,_,f in os.walk(work))
rows=sum(len(inst['pre'][c]['rows']) for c in inst['pre'])
print('== %s =='%_A.id)
print('files %d | analysis/ %d | data rows %d'%(nf,len(os.listdir(os.path.join(work,'analysis'))),rows))
print('target %s code %s | %s [%s]'%(cid,code,title[:56],exp['domain']))
print('BROKEN (%d): %s'%(len(broken),broken))
print('NULL-LIVE (%d): %s'%(len(nulls),nulls))
print('CONTRACT shipped rr=%s exact-stale=%s'%(gs['rr'],sorted(gs['stale'])==sorted(broken)))
print('CONTRACT gold    rr=%s exact=%s misses=%s damaged=%s'%(gg['rr'],gg['exact_match'],
      [k for k,v in gg['outcomes'].items() if v!='ok'] or 'none', gg['bulk_damaged'] or 'none'))
print('Correction turn:',TURNS[4])

# Construction contract. P1 the shipped workspace fails every broken site, P2 it fails exactly
# that set, P3 gold passes every broken site, P4 gold matches itself exactly, P5 gold damages no
# file, P6 gold keeps the dated revision log. A failure exits non-zero, so a broken fixture cannot
# reach the corpus.
_n=len(broken)
assert gs['rr']=='0/%d'%_n, 'P1: shipped scored %s, expected 0/%d'%(gs['rr'],_n)
assert sorted(gs['stale'])==sorted(broken), 'P2: shipped fails the wrong set'
assert gg['rr']=='%d/%d'%(_n,_n), 'P3: gold scored %s'%gg['rr']
assert gg['exact_match'], 'P4: gold is not tree-exact against itself'
assert not gg['bulk_damaged'], 'P5: gold damages %s'%gg['bulk_damaged']
assert gg['history_intact'], 'P6: gold falsifies history'
print('CONTRACT P1-P6 asserted OK')
