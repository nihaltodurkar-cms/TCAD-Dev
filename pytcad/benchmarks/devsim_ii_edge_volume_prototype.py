"""Minimal clean test: recreate continuity equations with edge_volume
source (alpha=0).  If this converges to 20 V, plumbing is sound."""
import sys, os
sys.path.insert(0, ".")
import numpy as np
import devsim
from devsim.python_packages.model_create import (
    CreateSolution, CreateEdgeModel,
)
from devsim.python_packages.simple_physics import (
    SetSiliconParameters, CreateSiliconPotentialOnly,
    CreateSiliconPotentialOnlyContact, CreateSiliconDriftDiffusion,
    CreateSiliconDriftDiffusionAtContact, GetContactBiasName,
)

dev, reg = "p2", "sil"
x = np.linspace(0.0, 2e-4, 80)
doping = np.where(x < 1e-4, -1e19, 1e17)

devsim.create_1d_mesh(mesh="m")
for i, pos in enumerate(x):
    sp = x[1]-x[0] if i == 0 else (x[-1]-x[-2] if i == len(x)-1 else pos-x[i-1])
    devsim.add_1d_mesh_line(mesh="m", pos=float(pos), ps=sp, tag=f"n{i}")
devsim.add_1d_contact(mesh="m", name="left", tag="n0", material="metal")
devsim.add_1d_contact(mesh="m", name="right", tag=f"n{len(x)-1}", material="metal")
devsim.add_1d_region(mesh="m", material="Si", region=reg, tag1="n0", tag2=f"n{len(x)-1}")
devsim.finalize_mesh(mesh="m"); devsim.create_device(mesh="m", device=dev)

SetSiliconParameters(dev, reg, 300)
devsim.node_solution(device=dev, region=reg, name="Donors")
devsim.node_solution(device=dev, region=reg, name="Acceptors")
devsim.set_node_values(device=dev, region=reg, name="Donors", values=np.maximum(doping,0).tolist())
devsim.set_node_values(device=dev, region=reg, name="Acceptors", values=np.maximum(-doping,0).tolist())
devsim.node_model(device=dev, region=reg, name="NetDoping", equation="Donors-Acceptors")

CreateSolution(dev, reg, "Potential")
CreateSiliconPotentialOnly(dev, reg)
for c in devsim.get_contact_list(device=dev):
    devsim.set_parameter(device=dev, name=GetContactBiasName(c), value=0.0)
    CreateSiliconPotentialOnlyContact(dev, reg, c)
devsim.solve(type="dc", absolute_error=1e10, relative_error=1e-8, maximum_iterations=30)

CreateSolution(dev, reg, "Electrons"); CreateSolution(dev, reg, "Holes")
devsim.set_node_values(device=dev, region=reg, name="Electrons", init_from="IntrinsicElectrons")
devsim.set_node_values(device=dev, region=reg, name="Holes", init_from="IntrinsicHoles")
CreateSiliconDriftDiffusion(dev, reg)
for c in devsim.get_contact_list(device=dev):
    CreateSiliconDriftDiffusionAtContact(dev, reg, c)
r = devsim.solve(type="dc", absolute_error=1e6, relative_error=1e-6,
                 maximum_iterations=30, info=True)
print("equilibrium:", r.get("converged"))

# --- rewire with vOdM alpha + volume source ---
E0 = 5e5
AN_LO, BN_LO = 7.03e5, 1.231e6
AP_LO, BP_LO = 1.582e6, 2.036e6
AP_HI, BP_HI = 6.71e5, 1.693e6
an_expr = f"{AN_LO}*exp(-{BN_LO}/(abs(ElectricField) + 1.0))"
ap_expr = (f"ifelse(abs(ElectricField) < {E0}, "
           f"{AP_LO}*exp(-{BP_LO}/(abs(ElectricField) + 1.0)), "
           f"{AP_HI}*exp(-{BP_HI}/(abs(ElectricField) + 1.0)))")
USE_DERIVS = os.environ.get("ALPHA_DERIVS", "0") == "1"
for name, A, B, expr in (("AlphaN", AN_LO, BN_LO, an_expr),
                         ("AlphaP", AP_LO, BP_LO, ap_expr)):
    CreateEdgeModel(device=dev, region=reg, model=name, expression=expr)
    if USE_DERIVS:
        # manual derivative: d(alpha)/d(Potential@n0/@n1), sign-split on
        # the field direction via ElectricField/Eabs
        CreateEdgeModel(device=dev, region=reg, model=name + "_Eabs",
                        expression=f"pow(abs(ElectricField)*abs(ElectricField) + 1e-20, 0.5)")
        dc = (f"{A}*{B}*exp(-{B}/({name}_Eabs + 1.0))"
              f"/(({name}_Eabs + 1.0)*({name}_Eabs + 1.0))")
        CreateEdgeModel(device=dev, region=reg, model=f"{name}:Potential@n0",
                        expression=f"{dc} * EdgeInverseLength * ElectricField/{name}_Eabs")
        CreateEdgeModel(device=dev, region=reg, model=f"{name}:Potential@n1",
                        expression=f"-{dc} * EdgeInverseLength * ElectricField/{name}_Eabs")
CreateEdgeModel(device=dev, region=reg, model="II_PairGen",
                expression="(AlphaN*abs(ElectronCurrent) + AlphaP*abs(HoleCurrent))")
import os as _o
SIGN = _o.environ.get("E_SIGN", "neg")
SCALE = _o.environ.get("E_SCALE", "1")
CreateEdgeModel(device=dev, region=reg, model="II_PairGen_S",
                expression=f"({SCALE})*II_PairGen")
CreateEdgeModel(device=dev, region=reg, model="II_GenerationE",
                expression=f"{'+-'[SIGN=='neg']}II_PairGen_S")
CreateEdgeModel(device=dev, region=reg, model="II_GenerationH",
                expression="+II_PairGen_S")

devsim.delete_equation(device=dev, region=reg, name="ElectronContinuityEquation")
devsim.delete_equation(device=dev, region=reg, name="HoleContinuityEquation")
for eqname, var, charge, node_gen, flux, ii in (
        ("ElectronContinuityEquation", "Electrons", "NCharge",
         "ElectronGeneration", "ElectronCurrent", "II_GenerationE"),
        ("HoleContinuityEquation", "Holes", "PCharge",
         "HoleGeneration", "HoleCurrent", "II_GenerationH")):
    devsim.equation(device=dev, region=reg, name=eqname, variable_name=var,
                    time_node_model=charge, edge_model=flux,
                    node_model=node_gen, edge_volume_model=ii,
                    variable_update="positive")
for c in devsim.get_contact_list(device=dev):
    CreateSiliconDriftDiffusionAtContact(dev, reg, c)
print("rewired")

def jtotal():
    je = np.asarray(devsim.get_edge_model_values(device=dev, region=reg, name="ElectronCurrent"))
    jh = np.asarray(devsim.get_edge_model_values(device=dev, region=reg, name="HoleCurrent"))
    return float(je[0] + jh[0])

v = 0.0
while v < 20:
    v += 0.5
    devsim.set_parameter(device=dev, name=GetContactBiasName("right"), value=v)
    try:
        info = devsim.solve(type="dc", absolute_error=1e6, relative_error=1e-6,
                            maximum_iterations=50, info=True)
        ok = bool(info.get("converged"))
        its = info.get("iterations") or ()
        if its:
            last = its[-1]["devices"][0]
            print(f"     lastRel={last['relative_error']:.2e} "
                  f"lastAbs={last['absolute_error']:.2e} "
                  f"nIter={len(its)}", flush=True)
    except Exception:
        ok = False
    print(f"V={v:+7.2f}  J={jtotal() if ok else float('nan'):+.4e}  conv={ok}",
          flush=True)
    if not ok:
        print("DIVERGED"); break
