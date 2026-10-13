# Optional D3 dispersion correction (record-only; not active in production)

**Status**: not applied by `gptfakeQE.py`. This doc exists so an agent can add
it correctly on request. Reference: official `uma_catalysis_tutorial.ipynb`
(cells 9, 29, 31, 35, 61-71; the .md export omits the executed outputs).

## The pattern (official tutorial)

D3 (Grimme, BJ damping, via `torch-dftd`) is a **separate ASE calculator**,
evaluated as a single-point energy on UMA-relaxed structures. Forces and MD
never include D3.

```python
from torch_dftd.torch_dftd3_calculator import TorchDFTD3Calculator

calc    = FAIRChemCalculator(predictor, task_name="oc25")  # UMA: forces + E_ml
d3_calc = TorchDFTD3Calculator(device="cpu", damping="bj")  # D3: E only

# relax/MD with UMA only, then:
e_ml = atoms.get_potential_energy()
atoms.calc = d3_calc
e_d3 = atoms.get_potential_energy()
e_tot = e_ml + e_d3
```

## Measured effect (tutorial executed outputs, Ni systems)

| Quantity | D3 contribution |
|---|---|
| Clean Ni(111) slab (absolute) | -36.57 eV (nearly constant; cancels in differences) |
| E_ads(H) | -0.08 eV (-0.51 -> -0.59) |
| E_ads(CO) | -0.24 eV |
| C*+O* -> CO* reaction | +0.07 eV |
| Gas-phase H2 / CO | ~0 eV |

Takeaway: D3 matters for gas-vs-adsorbed differences, not for condensed-phase
energy differences.

## How to modify gptfakeQE.py (on request only)

1. Add an opt-in env flag, e.g. `UMA_D3=1` (default **off**), so existing
   production runs and the frozen single-theory-level datasets are untouched.
2. Construct `d3_calc = TorchDFTD3Calculator(device="cpu", damping="bj")` once
   per run, guarded by `try/except ImportError` (torch-dftd may be absent from
   the env; install with `pip install torch-dftd` into `fairchem` if needed).
3. In the prod-MD loop, after each written frame: copy the frame's atoms,
   swap `atoms.calc = d3_calc`, get the single-point energy, and log
   `E_UMA + E_D3` (and E_D3 alone) to the thermo/stage log. Optionally emit the
   combined value on the energy line of the fake `.sout`.
4. **Never** feed D3 into the dynamics: the trajectory, velocities, and all
   forces stay UMA-only, exactly like the tutorial. Changing forces would
   change the physics mid-run and invalidate all previously generated data.
5. Keep D3 frames out of DeePMD training data unless the user explicitly asks;
   the training labels stay pure UMA.

## Dependencies

- `torch-dftd` (pip). Works on CPU; no HuggingFace token needed (D3 is
  parameterized, not learned).
