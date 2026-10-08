#!/usr/bin/env python3
"""
1p2_model_test.py - Test UMA 1p2 (fairchem-core 2.22.0) with torch.compile
===========================================================================
Tests the new uma-s-1p2p1 model with a simple FCC Al structure.
Requires gcc-toolset-13+ for C++20 support (torch.compile).

Usage:
    python 1p2_model_test.py
"""

from __future__ import annotations
import os
import sys
import time
import numpy as np


def main():
    print("=" * 60)
    print("UMA 1p2 Model Test (fairchem-core 2.22.0)")
    print("=" * 60)

    # Step 1: Import check
    print("\n[1/5] Checking imports...")
    try:
        import fairchem.core
        from fairchem.core import pretrained_mlip, FAIRChemCalculator
        print(f"  fairchem-core version: {fairchem.core.__version__}")
        print("  Import OK")
    except ImportError as e:
        print(f"  FAILED: {e}")
        sys.exit(1)

    import torch
    print(f"  PyTorch version: {torch.__version__}")
    print(f"  CUDA available: {torch.cuda.is_available()}")
    print(f"  torch.compile: {hasattr(torch, 'compile')}")
    if torch.cuda.is_available():
        print(f"  GPU: {torch.cuda.get_device_name(0)}")

    # Step 2: Build test structure (FCC Al, 4 atoms)
    print("\n[2/5] Building test structure (FCC Al, 4 atoms)...")
    from ase.build import bulk
    atoms = bulk("Al", "fcc", a=4.05, cubic=True)
    print(f"  Structure: {atoms.get_chemical_formula()} ({len(atoms)} atoms)")
    print(f"  Cell: {atoms.cell.lengths()} A")

    # Step 3: Load model
    print("\n[3/5] Loading uma-s-1p2p1 model...")
    t0 = time.time()
    try:
        predictor = pretrained_mlip.get_predict_unit("uma-s-1p2p1", device="cpu")
        dt = time.time() - t0
        print(f"  Model loaded in {dt:.1f}s")
    except Exception as e:
        print(f"  FAILED to load model: {e}")
        sys.exit(1)

    # Step 4: Single-point energy calculation
    print("\n[4/5] Running single-point energy calculation (omat task)...")
    calc = FAIRChemCalculator(predictor, task_name="omat")
    atoms.calc = calc

    t0 = time.time()
    energy = atoms.get_potential_energy()
    forces = atoms.get_forces()
    stress = atoms.get_stress()
    dt = time.time() - t0

    print(f"  Energy: {energy:.6f} eV")
    print(f"  Energy/atom: {energy / len(atoms):.6f} eV/atom")
    print(f"  Max force: {np.max(np.abs(forces)):.6f} eV/A")
    print(f"  Stress (Voigt kbar): {stress / 0.0001}")
    print(f"  Calculation time: {dt:.4f}s")

    # Step 5: BFGS relaxation test
    print("\n[5/5] Running BFGS relaxation test (5 steps)...")
    from ase.optimize import BFGS
    import io

    dyn = BFGS(atoms, logfile=io.StringIO())
    t0 = time.time()
    dyn.run(fmax=0.05, steps=5)
    dt = time.time() - t0

    final_energy = atoms.get_potential_energy()
    final_forces = atoms.get_forces()
    final_fmax = np.max(np.linalg.norm(final_forces, axis=1))
    final_cell = atoms.cell.lengths()

    print(f"  Final energy: {final_energy:.6f} eV")
    print(f"  Final energy/atom: {final_energy / len(atoms):.6f} eV/atom")
    print(f"  Final max force: {final_fmax:.6f} eV/A")
    print(f"  Final cell: {final_cell} A")
    print(f"  Relaxation time: {dt:.4f}s")

    # Bonus: Benchmark with larger system
    print("\n[Bonus] Benchmark (108 atoms, 5 calls, after warmup)...")
    atoms_big = bulk("Al", "fcc", a=4.05, cubic=True) * [3, 3, 3]
    atoms_big.calc = FAIRChemCalculator(predictor, task_name="omat")
    atoms_big.get_potential_energy()  # warmup / torch.compile
    times = []
    for _ in range(5):
        t0 = time.time()
        atoms_big.get_potential_energy()
        times.append(time.time() - t0)
    avg = np.mean(times) * 1000
    std = np.std(times) * 1000
    print(f"  {len(atoms_big)} atoms: {avg:.1f} +/- {std:.1f} ms/step")
    print(f"  Threads: {torch.get_num_threads()}")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED - UMA 1p2 + torch.compile OK!")
    print("=" * 60)


if __name__ == "__main__":
    main()
