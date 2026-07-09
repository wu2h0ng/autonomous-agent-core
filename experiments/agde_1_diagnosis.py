"""AGDE-1 post-hoc DIAGNOSIS (labeled; scored verdict NULL stands untouched).
Q1: what is the TRUTH-BLIND optimal ceiling at B=1 on the scored families (oracle is truth-INFORMED —
    was the frozen >=50%-of-oracle-gap bar above any blind policy's reach)?
Q2: B=2 (frozen report-only): does active close the gap when two chosen splits can resolve the 4-MEC?"""
import json, statistics
import experiments.intervention_scm as scm
from aac.discovery_loop import run_discovery
from aac.structure_consistency import fit_mechanisms, predict_do_means
from aac.intervention_chooser import partition_blocks

TOL,N_INT=0.6,100; RUN_SEEDS=[10,11,12]
fams=[]; s=100
while len(fams)<30 and s<500:
    f=scm.Family(s)
    if scm.valid_family(f,TOL): fams.append(f)
    s+=1

def id_score(res,f):
    if not res.survivors: return 0.0
    idx=[i for i,h in enumerate(f.pool) if h in res.survivors]
    return (1.0/len(idx)) if f.truth_index in idx else 0.0

blind_ceiling=[]; b2={a:[] for a in ("A","R","O")}
for f in fams:
    for rs in RUN_SEEDS:
        obs=f.sample_obs(rs)
        mechs=[fit_mechanisms(f.n,h,obs) for h in f.pool]
        base=[predict_do_means(f.n,h,m,-1,0.0) for h,m in zip(f.pool,mechs)]
        # blind-optimal expected ID at B=1: for each node, partition; expected ID = sum over blocks
        # P(truth in block)*1/|block| = (#blocks)/|pool| under uniform truth. maximize over nodes.
        best=0.0
        for k in range(f.n):
            blocks=partition_blocks(f.n,f.pool,mechs,k,scm.SCM_PARAMS["do_value"],base,TOL)
            best=max(best, len(blocks)/len(f.pool))
        blind_ceiling.append(best)
        def env(k,step,_f=f,_rs=rs): return _f.sample_do(k,_rs,step,N_INT)
        env.truth_index=f.truth_index
        for arm,pol in (("A","active"),("R","random"),("O","oracle")):
            r=run_discovery(f.n,f.pool,obs,env,2,pol,seed=rs,tol=TOL,c=scm.SCM_PARAMS["do_value"])
            b2[arm].append(id_score(r,f))
out={"blind_optimal_ceiling_B1_mean":round(statistics.mean(blind_ceiling),4),
     "scored_A_B1_mean":0.6611,"scored_R_B1_mean":0.3574,"scored_O_B1_mean":0.9778,
     "capture_vs_blind_ceiling":round((0.6611-0.3574)/(statistics.mean(blind_ceiling)-0.3574),4),
     "B2":{a:round(statistics.mean(v),4) for a,v in b2.items()}}
out["B2_capture_vs_truth_informed_oracle"]=round((out["B2"]["A"]-out["B2"]["R"])/(out["B2"]["O"]-out["B2"]["R"]),4)
open("experiments/agde_1_diagnosis.result.json","w").write(json.dumps(out,indent=2))
print(json.dumps(out,indent=2))
