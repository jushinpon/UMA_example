# Theory-level notes: why ONE task per training dataset

Evidence log for the "single model + single task" policy. Sources:
UMA paper, the official catalysis tutorial, and an empirical head
comparison run on this cluster (2026-10-13, job 37050).

## 1. DeePMD itself does not care (technical level)

The DeePMD data format (upstream `doc/data/system.md`) is just
`type/coord/box` + labels `ener/force/virial` per frame. There is no
"label provenance" field and dpdata/DeepWD-kit happily trains on multiple
mixed systems. So mixing task outputs is *technically* possible.

## 2. Different task heads ARE different energy functions (science level)

### Empirical proof (reproducible)

Same structure, only `task_name` changed (FAIRChemCalculator,
`uma-s-1p2p1`, CPU):

| Structure | oc25 | oc20 | omat |
|---|---|---|---|
| Cu fcc bulk (108 atoms) | -3.93404 eV/atom | -3.25259 | -3.74887 |
| water box (192 atoms) | -4.74736 eV/atom | -4.67197 | -4.74156 |

Head-to-head deltas reach **0.19-0.68 eV/atom on the metal bulk** - one to
two orders of magnitude above DeePMD fitting targets. Mixing labels from
two heads therefore injects irreducible contradictions wherever local
environments sit near the boundary between the two training domains (an
atom moving from slab into water, for example).

Reproduce with any script that loops
`FAIRChemCalculator(predictor, task_name=t)` over the same Atoms; the
cluster copy of the original run lives outside the repo under
`runs/headtest/` of the proposal deployment.

### Paper backing (arXiv:2506.23971v2, "UMA: A Family of Universal Models
for Atoms")

- UMA-1.1 kept consistency across domains with an **energy referencing
  scheme + a SINGLE energy head** ("...allowed for the use of a single
  energy head across all tasks without the need for task-specific heads").
- UMA-1.2 (the `1p2`/`1p2p1` checkpoints) introduced **"Task specific
  output heads"** - i.e. each task really is a separate output function.
- Cross-domain consistency inside UMA comes from joint training on ~500M
  structures with a common referencing scheme. Post-hoc mixing of two
  heads' outputs cannot inherit that consistency.

Conclusion: one potential = one single-valued potential-energy surface.
Labeling one training set with two heads makes the target
self-contradictory at the domain boundary.

## 3. Legitimate multi-level approaches (not this repo's policy)

- Joint multi-task training with an energy-referencing scheme (what UMA
  itself does),
- multi-fidelity / delta-learning schemes that model the difference
  explicitly,
- or simply training separate potentials per domain.
Blending raw labels from two heads is none of these.

## 4. Why `oc25` for solid-liquid interfaces

- The official UMA catalysis tutorial
  (`docs/uma_tutorials/uma_catalysis_tutorial.md` upstream) switches
  `omat` (bulk/slabs) -> `oc20` (adsorbates, coverage, NEB): gas-phase
  surface catalysis, one independent calculation at a time.
- **OC25 = "The Open Catalyst 2025 (OC25) dataset and models for
  solid-liquid interfaces"** (Sahoo et al., arXiv:2509.17862). The UMA
  paper's UMA-S-1.2 training table lists OC25 with sampling ratio 16
  (highest tier, alongside OMol25+OPoly26).
- Metal + explicit water + electrolyte is a solid-liquid interface: that
  is `oc25`'s training domain, not `oc20`'s.
- The tutorial's task switching is fine for independent screening, but a
  DeePMD training database needs ONE level of theory (this repo's policy,
  see AGENTS.md).

## 5. Other takeaways from the official tutorial

- D3 on top: for adsorbate/coverage/NEB parts they relax with UMA and
  report `E = E_UMA + E_D3` (TorchDFTD3, BJ damping). Runs that mix
  labels with and without D3 would violate the single-level policy; pick
  one convention per dataset.
- ZPE corrections via vibrational frequencies and NEB barriers via
  `ase.mep.DyNEB` are demonstrated there and can be reused for PCET /
  adsorption-energy analysis after training.
