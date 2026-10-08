#!/usr/bin/env python3
# gptfakeQE.py
#
# FIXED CLI: ALWAYS include do_supercell (0/1)
#
# Stages: OPT-1 -> OPT-2 -> [Supercell+OPT-2] -> Eq MD -> Prod MD
# Outputs: stage_*.txt (per-stage logs) + thermo_summary.png + fake.sout + data_files/
#
# Usage:
#   python gptfakeQE.py INPUT.data opt1_steps opt1_fmax opt2_steps opt2_fmax npt_steps do_supercell(0/1) \
#       eq_steps eq_temp(K) eq_press(GPa) eq_timestep(fs) \
#       prod_steps prod_low(K) prod_high(K) prod_press(GPa) prod_timestep(fs) prod_freq \
#       cx cy cz MODEL_NAME TASK_NAME

from __future__ import annotations

import os
import sys
import shutil
import time
import math
import subprocess
import numpy as np

from ase.io import read
from ase import units
from ase.constraints import FixAtoms

try:
    from ase.filters import UnitCellFilter
except ImportError:
    from ase.constraints import UnitCellFilter

from ase.optimize import BFGS

try:
    from ase.md.melchionna import MelchionnaNPT as NPT
except ImportError:
    from ase.md.npt import NPT

try:
    from ase.md.nvtberendsen import NVTBerendsen
except ImportError:
    NVTBerendsen = None

from ase.md.velocitydistribution import MaxwellBoltzmannDistribution, Stationary

import torch

# ---- PyTorch thread settings ----
def _set_torch_threads_from_env():
    for key in ("SLURM_CPUS_PER_TASK", "OMP_NUM_THREADS"):
        v = os.environ.get(key, "").strip()
        if v.isdigit() and int(v) > 0:
            n = int(v)
            try:
                torch.set_num_threads(n)
            except Exception:
                pass
            try:
                torch.set_num_interop_threads(max(1, min(4, n)))
            except Exception:
                pass
            return

_set_torch_threads_from_env()

try:
    from fairchem.core import FAIRChemCalculator, pretrained_mlip
except ImportError:
    print("Error: fairchem-core not installed.", file=sys.stderr)
    sys.exit(1)

from ase.data import atomic_numbers, chemical_symbols

OUTPUT_DIR = "data_files"

OPT1_PRESS_TOL_GPA = 1.0
OPT2_PRESS_TOL_GPA = 0.2
OPT1_MAXSTEP = 0.25
OPT2_MAXSTEP = 0.20
SUPERCELL_RCUT_A = 6.0
FIX_ANGLES_NPT = True
TTIME_FS = 25.0
PFACTOR_COEFF = 75.0


# ============================================================================
# StageLogger — writes stage_*.txt files
# ============================================================================
class StageLogger:
    """Append-only logger for stage_*.txt files (tab-separated)."""

    def __init__(self, job_dir: str, stage_name: str, columns: list[str]):
        self.path = os.path.join(job_dir, f"stage_{stage_name}.txt")
        self.columns = columns
        self.step = 0
        with open(self.path, "w") as f:
            f.write("# " + "  ".join(columns) + "\n")

    def log(self, **values):
        self.step += 1
        vals = [values.get(c, "") for c in self.columns]
        with open(self.path, "a") as f:
            f.write("\t".join(
                f"{v:.8f}" if isinstance(v, float) else str(v) for v in vals
            ) + "\n")

    @property
    def count(self):
        return self.step


def _measure_atoms(atoms) -> dict:
    """Extract thermodynamic quantities from an ASE Atoms object."""
    cell = atoms.cell.lengths()
    stress = atoms.get_stress()  # Voigt: xx,yy,zz,yz,xz,xy in eV/A^3
    hydro_press_gpa = -(stress[0] + stress[1] + stress[2]) / 3.0 * 160.21766208
    n_atoms = len(atoms)
    vol = float(atoms.get_volume())
    mass_total = float(sum(atoms.get_masses()))
    return {
        "a_A": float(cell[0]),
        "b_A": float(cell[1]),
        "c_A": float(cell[2]),
        "vol_A3": vol,
        "P_GPa": hydro_press_gpa,
        "energy_eV": float(atoms.get_potential_energy()),
        "fmax_eV_A": float(np.max(np.linalg.norm(atoms.get_forces(), axis=1))) if n_atoms > 0 else 0.0,
        "T_K": float(atoms.get_temperature()),
        "density_g_cm3": mass_total / vol * 1.66053907,
    }


# ============================================================================
# OptimLogInterceptor (stdout + optional StageLogger)
# ============================================================================
class OptimLogInterceptor:
    def __init__(self, base_stream, atoms, mode: str, stage_logger: StageLogger | None = None):
        self.base = base_stream
        self.atoms = atoms
        self.mode = mode
        self.stage_logger = stage_logger
        self.t0 = None

    def write(self, s: str):
        stripped = s.lstrip()
        if len(stripped) >= 5 and ":" in stripped[:10]:
            tag = stripped.split(":", 1)[0]
            if tag.isalpha():
                if self.t0 is None:
                    self.t0 = time.time()
                elapsed_min = (time.time() - self.t0) / 60.0
                m = _measure_atoms(self.atoms)
                fmax_str = ""
                if self.mode == "mix":
                    fmax_str = f"  fmax(eV/A)={m['fmax_eV_A']:.6f}"
                line = (
                    f"{stripped.rstrip()}"
                    f"  Elap(min)={elapsed_min:6.2f}"
                    f"  a={m['a_A']:6.2f} b={m['b_A']:6.2f} c={m['c_A']:6.2f}"
                    f"  Vol={m['vol_A3']:9.2f}"
                    f"  P={m['P_GPa']:7.3f}"
                    f"{fmax_str}\n"
                )
                self.base.write(line)
                # Also log to stage file
                if self.stage_logger:
                    self.stage_logger.log(
                        step=self.stage_logger.count + 1,
                        **{k: v for k, v in m.items() if k in self.stage_logger.columns}
                    )
                return
        self.base.write(s)

    def flush(self):
        self.base.flush()


# ============================================================================
# Helper functions
# ============================================================================
def _set_cell_from_cellpar(atoms, a, b, c, alpha, beta, gamma, scale_atoms=True):
    cellpar = [a, b, c, alpha, beta, gamma]
    try:
        newcell = atoms.cell.from_cellpar(cellpar)
    except AttributeError:
        newcell = atoms.cell.fromcellpar(cellpar)
    atoms.set_cell(newcell, scale_atoms=scale_atoms)


def make_unitcellfilter(atoms, mask=None):
    if mask is None:
        return UnitCellFilter(atoms), True
    try:
        f = UnitCellFilter(atoms, mask=mask)
        return f, True
    except TypeError:
        return UnitCellFilter(atoms), False


def diag_mask_from_flags(cx, cy, cz):
    return [[cx, 0, 0], [0, cy, 0], [0, 0, cz]]


# ============================================================================
# OPT-1: Cell-only relaxation
# ============================================================================
def run_opt1_cell_only(atoms, opt1_steps, opt1_fmax, cx, cy, cz, stage_logger=None):
    if opt1_steps <= 0:
        return
    if (cx + cy + cz) == 0:
        print("[OPT-1] cx=cy=cz=0 -> no cell-length DOF. OPT-1 skipped.")
        return

    intercept = OptimLogInterceptor(sys.stdout, atoms, mode="cell", stage_logger=stage_logger)
    atoms.set_constraint(FixAtoms(indices=range(len(atoms))))

    mask = diag_mask_from_flags(cx, cy, cz)
    ecf, mask_supported = make_unitcellfilter(atoms, mask=mask)
    target_angles = tuple(atoms.cell.angles())

    def enforce_fixed_angles():
        a, b, c = atoms.cell.lengths()
        _set_cell_from_cellpar(atoms, a, b, c, *target_angles, scale_atoms=True)

    opt = BFGS(ecf)
    opt.logfile = intercept
    opt.maxstep = OPT1_MAXSTEP
    if not mask_supported:
        opt.attach(enforce_fixed_angles, interval=1)

    for _ in range(opt1_steps):
        opt.run(fmax=opt1_fmax, steps=1)
        if not mask_supported:
            enforce_fixed_angles()

    atoms.set_constraint()


# ============================================================================
# OPT-2: Atoms + cell relaxation
# ============================================================================
def run_opt2_atoms_plus_cell(atoms, opt2_steps, opt2_fmax, cx, cy, cz, label="OPT-2", stage_logger=None):
    if opt2_steps <= 0:
        return

    intercept = OptimLogInterceptor(sys.stdout, atoms, mode="mix", stage_logger=stage_logger)

    if (cx + cy + cz) == 0:
        opt = BFGS(atoms)
        opt.logfile = intercept
        opt.maxstep = OPT2_MAXSTEP
        for _ in range(opt2_steps):
            opt.run(fmax=max(opt2_fmax, 1e-12), steps=1)
        return

    target_angles = tuple(atoms.cell.angles())
    mask = diag_mask_from_flags(cx, cy, cz)
    ecf, mask_supported = make_unitcellfilter(atoms, mask=mask)

    def enforce_fixed_angles():
        a, b, c = atoms.cell.lengths()
        _set_cell_from_cellpar(atoms, a, b, c, *target_angles, scale_atoms=True)

    opt = BFGS(ecf)
    opt.logfile = intercept
    opt.maxstep = OPT2_MAXSTEP
    if not mask_supported:
        opt.attach(enforce_fixed_angles, interval=1)

    for _ in range(opt2_steps):
        opt.run(fmax=max(opt2_fmax, 1e-12), steps=1)
        if not mask_supported:
            enforce_fixed_angles()


# ============================================================================
# Supercell
# ============================================================================
# --- PBC inference -----------------------------------------------------------
# A LAMMPS .data file carries no boundary information (ASE always reads it back
# as pbc=[True,True,True]), so the periodicity has to be decided here from the
# geometry: an axis whose largest empty gap is >= MIN_VACUUM_A is a vacuum axis
# (slab in z, isolated cluster in x/y/z) and must be treated as non-periodic.
MIN_VACUUM_A = 6.0


def infer_pbc_from_vacuum(atoms, min_vacuum=MIN_VACUUM_A):
    """Return [bool, bool, bool]; False for any axis with a gap >= min_vacuum."""
    frac = atoms.get_scaled_positions(wrap=True)
    lengths = atoms.cell.lengths()
    pbc = [True, True, True]
    for ax in range(3):
        f = np.sort(frac[:, ax] % 1.0)
        if len(f) < 2:
            pbc[ax] = False
            continue
        gaps = np.diff(np.concatenate([f, [f[0] + 1.0]]))
        pbc[ax] = bool(gaps.max() * lengths[ax] < min_vacuum)
    return pbc


def resolve_pbc(atoms, min_vacuum=MIN_VACUUM_A):
    """Vacuum-inferred PBC, overridable per case with UMA_PBC='T T F'."""
    env = os.environ.get("UMA_PBC", "").strip()
    if env:
        toks = env.replace(",", " ").split()
        if len(toks) != 3:
            raise SystemExit(
                f"Error: UMA_PBC must have 3 flags (e.g. 'T T F'), got {env!r}")
        return [t.lower() in ("1", "t", "true", "yes") for t in toks]
    return infer_pbc_from_vacuum(atoms, min_vacuum)


def compute_supercell_reps(atoms, rcut_a):
    target = 2.0 * rcut_a
    a, b, c = atoms.cell.lengths()
    lens = [a, b, c]
    reps = [1, 1, 1]
    for i in range(3):
        # Never replicate along a non-periodic (vacuum) axis: that would
        # duplicate the system into empty space instead of making a bulk cell.
        if atoms.pbc[i] and lens[i] < target:
            reps[i] = int(math.ceil(target / lens[i]))
    reps_t = tuple(reps)
    return target, reps_t, (reps_t != (1, 1, 1)), (a, b, c)


def build_supercell_if_needed(atoms, rcut_a):
    target, reps_t, did_expand, (a, b, c) = compute_supercell_reps(atoms, rcut_a)
    print(f"[SUPERCELL-CHECK] rcut={rcut_a:.2f}A target={target:.2f}A lengths: a={a:.3f} b={b:.3f} c={c:.3f} -> reps={reps_t} need_expand={did_expand}")
    if not did_expand:
        return atoms, reps_t, False
    old_types = atoms.arrays.get("type", None)
    new_atoms = atoms.repeat(reps_t)
    if old_types is not None:
        new_atoms.arrays["type"] = np.tile(np.array(old_types, dtype=int), reps_t[0] * reps_t[1] * reps_t[2])
    return new_atoms, reps_t, True


# ============================================================================
# Fake QE output (for downstream Perl scripts)
# ============================================================================
def write_fake_qe_input(filename, atoms, calculation, title, nstep, dt_fs, model_name, task_name):
    ntyp = len(sorted(set(atoms.get_chemical_symbols())))
    with open(filename, "w") as f:
        f.write("# Fake QE input generated by gptfakeQE.py\n")
        f.write(f"# MODEL_NAME = {model_name}\n")
        f.write(f"# TASK_NAME  = {task_name}\n\n")
        f.write("&CONTROL\n")
        f.write(f'  calculation = "{calculation}"\n')
        f.write(f"  title = '{title}'\n")
        if calculation != "scf":
            f.write(f"  nstep = {int(nstep)}\n")
            f.write(f"  dt = {float(dt_fs):.6f}\n")
        f.write("/\n")
        f.write("&SYSTEM\n")
        f.write(f"  nat = {len(atoms)}\n")
        f.write(f"  ntyp = {ntyp}\n")
        f.write("/\n")
        f.write("&ELECTRONS\n/\n&IONS\n/\n&CELL\n/\n")
        f.write("ATOMIC_SPECIES\n")
        for sym in sorted(set(atoms.get_chemical_symbols())):
            f.write(f" {sym}  1.0  {sym}.upf\n")
        f.write("ATOMIC_POSITIONS {angstrom}\n")
        pos = atoms.get_positions()
        syms = atoms.get_chemical_symbols()
        for s, p in zip(syms, pos):
            f.write(f" {s} {p[0]:.9f} {p[1]:.9f} {p[2]:.9f}\n")
        f.write("CELL_PARAMETERS {angstrom}\n")
        for row in atoms.get_cell():
            f.write(f" {row[0]:.9f} {row[1]:.9f} {row[2]:.9f}\n")
    return ntyp


def init_fake_qe_output(filename, input_filename, atoms, ntyp, model_name, task_name):
    Bohr = units.Bohr
    vol_ang3 = atoms.get_volume()
    vol_au = vol_ang3 / (Bohr ** 3)
    with open(filename, "w") as f:
        f.write("\n     Program PWSCF v.FAKE_NPT starts ...\n")
        f.write(f"     # MODEL_NAME = {model_name}\n")
        f.write(f"     # TASK_NAME  = {task_name}\n")
        f.write(f"     Reading input from {os.path.basename(input_filename)}\n")
        f.write(f"     number of atoms/cell       =            {len(atoms)}\n")
        f.write(f"     number of atomic types     =            {int(ntyp)}\n")
        f.write(f"     unit-cell volume =    {vol_au:.4f} (a.u.)^3\n")


def append_fake_qe_properties(filename, atoms, iteration_num):
    Ry = units.Ry
    Bohr = units.Bohr
    kbar = 1000.0 * units.bar
    epot_ry = atoms.get_potential_energy() / Ry
    ekin_ry = atoms.get_kinetic_energy() / Ry
    etot_ry = epot_ry + ekin_ry
    forces_ry_bohr = atoms.get_forces() * Bohr / Ry
    total_force = float(np.sqrt(np.sum(forces_ry_bohr ** 2)))
    stress_ev_ang3 = atoms.get_stress(voigt=False)
    stress_kbar = -1.0 * stress_ev_ang3 / kbar
    stress_ry_bohr3 = -1.0 * stress_ev_ang3 * (Bohr ** 3) / Ry
    pressure_kbar = float(np.trace(stress_kbar) / 3.0)
    temp_k = float(atoms.get_temperature())
    vol_ang3 = float(atoms.get_volume())
    total_mass_amu = float(sum(atoms.get_masses()))
    density_g_cm3 = (total_mass_amu / vol_ang3) * 1.66053907

    with open(filename, "a") as f:
        f.write(f"\n     Entering Dynamics.  Iteration =      {iteration_num}\n\n")
        f.write(f"!    total energy              =          {epot_ry:.8f} Ry\n")
        f.write(f"     internal energy E=F+TS    =          {epot_ry:.8f} Ry\n")
        f.write(f"     Harris-Foulkes estimate   =          {epot_ry:.8f} Ry\n")
        f.write("\n     Forces acting on atoms (cartesian axes, Ry/au):\n\n")
        for i, force in enumerate(forces_ry_bohr):
            f.write(f"     atom    {i+1} type  1   force =      {force[0]:.8f}      {force[1]:.8f}      {force[2]:.8f}\n")
        f.write(f"\n     Total force =      {total_force:.6f}\n")
        f.write(f"\n          total   stress  (Ry/bohr**3)                   (kbar)     P=       {pressure_kbar:.2f}\n")
        for i in range(3):
            f.write(f"    {stress_ry_bohr3[i,0]:.8f}   {stress_ry_bohr3[i,1]:.8f}   {stress_ry_bohr3[i,2]:.8f}           {stress_kbar[i,0]:.2f}       {stress_kbar[i,1]:.2f}       {stress_kbar[i,2]:.2f}\n")
        f.write(f"\n     Ekin =      {ekin_ry:.8f} Ry    T =     {temp_k:4.1f} K  Etot =      {etot_ry:.8f}\n")
        f.write(f"     density =       {density_g_cm3:.5f} g/cm^3\n")


def append_fake_qe_structure(filename, atoms):
    Bohr = units.Bohr
    vol_ang3 = float(atoms.get_volume())
    vol_au = vol_ang3 / (Bohr ** 3)
    with open(filename, "a") as f:
        f.write(f"\n     new unit-cell volume =   {vol_au:.5f} a.u.^3 (  {vol_ang3:.5f} Ang^3 )\n")
        f.write("\nCELL_PARAMETERS (angstrom)\n")
        for row in atoms.get_cell():
            f.write(f"      {row[0]:.8f}   {row[1]:.8f}   {row[2]:.8f}\n")
        f.write("\nATOMIC_POSITIONS (angstrom)\n")
        pos = atoms.get_positions()
        syms = atoms.get_chemical_symbols()
        for s, p in zip(syms, pos):
            f.write(f"{s}      {p[0]:.8f}   {p[1]:.8f}   {p[2]:.8f}\n")
        f.write("\n")


def finalize_fake_qe_output(filename):
    with open(filename, "a") as f:
        f.write("\n     JOB DONE.\n")


# ============================================================================
# LAMMPS data I/O
# ============================================================================
def parse_lammps_masses_block(path):
    masses = {}
    in_masses = False
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("Masses"):
                in_masses = True
                continue
            if in_masses:
                if line.startswith(("Atoms", "Velocities", "Bonds", "Angles", "Dihedrals", "Impropers", "Pair", "Coeffs")):
                    break
                if line.startswith("#"):
                    continue
                parts = line.split("#", 1)
                left = parts[0].split()
                if len(left) < 2:
                    continue
                try:
                    tid = int(left[0])
                    mass = float(left[1])
                except Exception:
                    continue
                sym = parts[1].strip().split()[0] if len(parts) == 2 else ""
                masses[tid] = (mass, sym)
    return masses


def parse_lammps_box_origin(path):
    lower_bounds = {}
    abc_origin = None
    with open(path) as f:
        for raw in f:
            fields = raw.split("#", 1)[0].split()
            if len(fields) >= 4 and fields[-2:] == ["xlo", "xhi"]:
                lower_bounds["x"] = float(fields[0])
            elif len(fields) >= 4 and fields[-2:] == ["ylo", "yhi"]:
                lower_bounds["y"] = float(fields[0])
            elif len(fields) >= 4 and fields[-2:] == ["zlo", "zhi"]:
                lower_bounds["z"] = float(fields[0])
            elif len(fields) >= 5 and fields[-2:] == ["abc", "origin"]:
                abc_origin = np.array([float(v) for v in fields[:3]], dtype=float)
            if abc_origin is not None or len(lower_bounds) == 3:
                break
    if abc_origin is not None:
        return abc_origin
    missing = [axis for axis in "xyz" if axis not in lower_bounds]
    if missing:
        raise RuntimeError(f"Cannot find {'/'.join(axis+'lo' for axis in missing)} in LAMMPS data header: {path}")
    return np.array([lower_bounds[axis] for axis in "xyz"], dtype=float)


def assert_atoms_inside_cell(atoms, stage, tolerance=1e-8):
    scaled = atoms.get_scaled_positions(wrap=False)
    outside_mask = np.any((scaled < -tolerance) | (scaled > 1.0 + tolerance), axis=1)
    outside_ids = np.flatnonzero(outside_mask)
    if len(outside_ids):
        shown = ", ".join(str(int(i) + 1) for i in outside_ids[:20])
        raise RuntimeError(f"{stage}: {len(outside_ids)}/{len(atoms)} atoms outside cell; IDs: {shown}")


def get_types_array(atoms, mass_map):
    for key in ("type", "types"):
        if key in atoms.arrays:
            arr = np.array(atoms.arrays[key], dtype=int)
            if arr.size == len(atoms):
                return arr
    sym_to_type = {}
    for tid, (_, sym) in mass_map.items():
        if sym:
            sym_to_type[sym] = tid
    syms = atoms.get_chemical_symbols()
    out = np.zeros(len(atoms), dtype=int)
    for i, s in enumerate(syms):
        out[i] = sym_to_type.get(s, sym_to_type.get(chemical_symbols[atoms.numbers[i]], 1))
    return out


def cell_to_lammps_triclinic(cell):
    a, b, c = np.array(cell[0], dtype=float), np.array(cell[1], dtype=float), np.array(cell[2], dtype=float)
    ax = np.linalg.norm(a)
    if ax <= 0:
        raise ValueError("Invalid cell: |a|=0")
    xy = np.dot(b, a) / ax
    xz = np.dot(c, a) / ax
    by = np.sqrt(max(np.dot(b, b) - xy ** 2, 0.0)) or 1e-12
    yz = (np.dot(b, c) - xy * xz) / by
    cz = np.sqrt(max(np.dot(c, c) - xz ** 2 - yz ** 2, 0.0))
    return 0.0, ax, 0.0, by, 0.0, cz, xy, xz, yz


def write_lammps_data_ovito_style(path, atoms, masses_map, types):
    n_atoms = len(atoms)
    n_types = int(np.max(types)) if len(types) else len(masses_map)
    cell = np.array(atoms.get_cell(), dtype=float)
    xlo, xhi, ylo, yhi, zlo, zhi, xy, xz, yz = cell_to_lammps_triclinic(cell)
    pos = np.array(atoms.get_positions(), dtype=float)
    filled = dict(masses_map)
    for t in range(1, n_types + 1):
        if t not in filled:
            filled[t] = (1.0, "")
    with open(path, "w") as f:
        f.write("# LAMMPS data file written by OVITO Basic 3.7.8\n\n")
        f.write(f"{n_atoms} atoms\n")
        f.write(f"{n_types} atom types\n\n")
        f.write(f"{xlo:0.6f} {xhi:0.6f} xlo xhi\n")
        f.write(f"{ylo:0.6f} {yhi:0.6f} ylo yhi\n")
        f.write(f"{zlo:0.6f} {zhi:0.6f} zlo zhi\n")
        f.write(f"{xy:0.6f} {xz:0.6f} {yz:0.6f} xy xz yz\n\n")
        f.write("Masses\n\n")
        for t in range(1, n_types + 1):
            mass, sym = filled[t]
            f.write(f"{t} {mass:.7f}  # {sym}\n" if sym else f"{t} {mass:.7f}\n")
        f.write("\nAtoms  # atomic\n\n")
        for i in range(n_atoms):
            tid = int(types[i])
            x, y, z = pos[i]
            f.write(f"{i+1} {tid} {x:.10f} {y:.10f} {z:.10f}\n")


def write_elements_dat(path, atoms):
    elems = sorted(set(atoms.get_chemical_symbols()))
    with open(path, "w") as f:
        f.write(" ".join(elems) + "\n")


# ============================================================================
# CLI
# ============================================================================
def usage_and_die(exit_code=1):
    prog = os.path.basename(sys.argv[0])
    print(f"""Usage:
  python {prog} INPUT.data opt1_steps opt1_fmax opt2_steps opt2_fmax npt_steps do_supercell(0/1) \\
      eq_steps eq_temp(K) eq_press(GPa) eq_timestep(fs) \\
      prod_steps prod_low(K) prod_high(K) prod_press(GPa) prod_timestep(fs) prod_freq \\
      cx cy cz MODEL_NAME TASK_NAME
""", file=sys.stderr)
    sys.exit(exit_code)


def parse_args():
    if len(sys.argv) != 23:
        usage_and_die(1)
    def _int(t, n):
        try: return int(t)
        except ValueError: print(f"Error: <{n}> must be int.", file=sys.stderr); usage_and_die(1)
    def _float(t, n):
        try: return float(t)
        except ValueError: print(f"Error: <{n}> must be float.", file=sys.stderr); usage_and_die(1)

    a = sys.argv
    input_data_file = a[1]
    if not os.path.isfile(input_data_file):
        print(f"Error: not found: {input_data_file}", file=sys.stderr); usage_and_die(1)
    opt1_steps = _int(a[2], "opt1_steps")
    opt1_fmax = _float(a[3], "opt1_fmax")
    opt2_steps = _int(a[4], "opt2_steps")
    opt2_fmax = _float(a[5], "opt2_fmax")
    npt_steps = _int(a[6], "npt_steps")  # kept for compat, but prod_steps is the real one
    do_supercell = _int(a[7], "do_supercell")
    eq_steps = _int(a[8], "eq_steps")
    eq_temp_k = _float(a[9], "eq_temp_K")
    eq_press_gpa = _float(a[10], "eq_press_GPa")
    eq_timestep_fs = _float(a[11], "eq_timestep_fs")
    prod_steps = _int(a[12], "prod_steps")
    prod_low_k = _float(a[13], "prod_low_K")
    prod_high_k = _float(a[14], "prod_high_K")
    prod_press_gpa = _float(a[15], "prod_press_GPa")
    prod_timestep_fs = _float(a[16], "prod_timestep_fs")
    prod_freq = _int(a[17], "prod_freq")
    cx = _int(a[18], "cx")
    cy = _int(a[19], "cy")
    cz = _int(a[20], "cz")
    model_name = a[21]
    task_name = a[22]

    for name, v in (("cx", cx), ("cy", cy), ("cz", cz)):
        if v not in (0, 1):
            print(f"Error: {name} must be 0 or 1.", file=sys.stderr); usage_and_die(1)
    if temp_k := eq_temp_k:
        pass
    if prod_low_k <= 0 or prod_high_k <= 0:
        print("Error: temperatures must be > 0.", file=sys.stderr); usage_and_die(1)

    return (input_data_file, opt1_steps, opt1_fmax, opt2_steps, opt2_fmax,
            npt_steps, do_supercell, eq_steps, eq_temp_k, eq_press_gpa, eq_timestep_fs,
            prod_steps, prod_low_k, prod_high_k, prod_press_gpa, prod_timestep_fs, prod_freq,
            cx, cy, cz, model_name, task_name)


# ============================================================================
# MAIN
# ============================================================================
def main():
    (input_data_file,
     opt1_steps, opt1_fmax, opt2_steps, opt2_fmax,
     npt_steps, do_supercell,
     eq_steps, eq_temp_k, eq_press_gpa, eq_timestep_fs,
     prod_steps, prod_low_k, prod_high_k, prod_press_gpa, prod_timestep_fs, prod_freq,
     cx, cy, cz,
     model_name, task_name) = parse_args()

    input_dir = os.path.dirname(os.path.abspath(input_data_file))
    data_base = os.path.splitext(os.path.basename(input_data_file))[0]
    fake_in = os.path.join(input_dir, f"{data_base}.in")
    fake_sout = os.path.join(input_dir, f"{data_base}.sout")
    elements_path = os.path.join(input_dir, "elements.dat")
    eq_profile_png = os.path.join(input_dir, f"{data_base}_eq_profile.png")

    print(f"[THREADS] torch_num_threads={torch.get_num_threads()}  OMP_NUM_THREADS={os.environ.get('OMP_NUM_THREADS')}")
    print(f"[RUN] model={model_name} task={task_name} eq_steps={eq_steps} eq_T={eq_temp_k} eq_P={eq_press_gpa} prod_steps={prod_steps} prod_low_T={prod_low_k} prod_high_T={prod_high_k} prod_P={prod_press_gpa} prod_freq={prod_freq} do_supercell={do_supercell} cell_flags={cx}{cy}{cz}")

    mass_map = parse_lammps_masses_block(input_data_file)
    if not mass_map:
        print("Error: cannot find 'Masses' block.", file=sys.stderr); sys.exit(1)

    Z_map = {}
    for tid, (_, sym) in mass_map.items():
        if sym and sym in atomic_numbers:
            Z_map[tid] = atomic_numbers[sym]
    missing = [t for t in mass_map if t not in Z_map]
    if missing:
        print(f"Error: Masses block missing '# Element' for types: {missing}", file=sys.stderr); sys.exit(1)

    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.mkdir(OUTPUT_DIR)

    atoms = read(input_data_file, format="lammps-data", atom_style="atomic", Z_of_type=Z_map)
    pbc = resolve_pbc(atoms)
    atoms.set_pbc(pbc)
    print(f"[PBC] {' '.join('T' if x else 'F' for x in pbc)}  "
          f"(vacuum-gap rule, min_vacuum={MIN_VACUUM_A} A; override with UMA_PBC)")
    cell_origin = parse_lammps_box_origin(input_data_file)
    atoms.set_positions(atoms.get_positions() - cell_origin)
    atoms.set_celldisp(np.zeros(3))
    assert_atoms_inside_cell(atoms, "after input-origin normalization")
    atoms.arrays["type"] = np.array(get_types_array(atoms, mass_map), dtype=int)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    predictor = pretrained_mlip.get_predict_unit(model_name, device=device)
    atoms.calc = FAIRChemCalculator(predictor, task_name=task_name)

    # ---- Create loggers ----
    opt1_log = StageLogger(input_dir, "opt1", ["step", "energy_eV", "a_A", "b_A", "c_A", "vol_A3", "P_GPa"]) if opt1_steps > 0 and (cx + cy + cz) > 0 else None
    opt2_log = StageLogger(input_dir, "opt2", ["step", "energy_eV", "fmax_eV_A", "a_A", "b_A", "c_A", "vol_A3", "P_GPa"]) if opt2_steps > 0 else None

    # ---- OPT-1 ----
    print(f"[OPT-1] Starting {opt1_steps} steps...")
    run_opt1_cell_only(atoms, opt1_steps, opt1_fmax, cx=cx, cy=cy, cz=cz, stage_logger=opt1_log)
    assert_atoms_inside_cell(atoms, "after OPT-1")
    write_lammps_data_ovito_style(os.path.join(OUTPUT_DIR, "minimized_1.data"), atoms, mass_map, atoms.arrays["type"])
    if opt1_log:
        print(f"[OPT-1] Done. {opt1_log.count} steps logged -> {opt1_log.path}")

    # ---- OPT-2 ----
    print(f"[OPT-2] Starting {opt2_steps} steps...")
    run_opt2_atoms_plus_cell(atoms, opt2_steps, opt2_fmax, cx=cx, cy=cy, cz=cz, label="OPT-2", stage_logger=opt2_log)
    assert_atoms_inside_cell(atoms, "after OPT-2")
    write_lammps_data_ovito_style(os.path.join(OUTPUT_DIR, "minimized_2.data"), atoms, mass_map, atoms.arrays["type"])
    if opt2_log:
        print(f"[OPT-2] Done. {opt2_log.count} steps logged -> {opt2_log.path}")

    final_atoms = atoms
    final_types = atoms.arrays["type"]

    # ---- Supercell + OPT-2 ----
    sc_opt2_log = None
    if do_supercell == 1:
        sc_atoms, reps_t, did_expand = build_supercell_if_needed(atoms, rcut_a=SUPERCELL_RCUT_A)
        if not did_expand:
            print("[SUPERCELL] skipped: no expansion needed.")
        else:
            print(f"[SUPERCELL] applied: repeat={reps_t}. Running OPT-2 #2 on supercell.")
            sc_atoms.calc = FAIRChemCalculator(predictor, task_name=task_name)
            if "type" not in sc_atoms.arrays or len(sc_atoms.arrays["type"]) != len(sc_atoms):
                sc_atoms.arrays["type"] = np.tile(np.array(atoms.arrays["type"], dtype=int), reps_t[0] * reps_t[1] * reps_t[2])
            assert_atoms_inside_cell(sc_atoms, "after supercell construction")
            write_lammps_data_ovito_style(os.path.join(OUTPUT_DIR, "supercell.data"), sc_atoms, mass_map, sc_atoms.arrays["type"])
            sc_opt2_log = StageLogger(input_dir, "opt2_sc", ["step", "energy_eV", "fmax_eV_A", "a_A", "b_A", "c_A", "vol_A3", "P_GPa"])
            run_opt2_atoms_plus_cell(sc_atoms, opt2_steps, opt2_fmax, cx=cx, cy=cy, cz=cz, label="OPT-2-SUPERCELL", stage_logger=sc_opt2_log)
            assert_atoms_inside_cell(sc_atoms, "after OPT-2-SUPERCELL")
            write_lammps_data_ovito_style(os.path.join(OUTPUT_DIR, "minimized_2_supercell.data"), sc_atoms, mass_map, sc_atoms.arrays["type"])
            final_atoms = sc_atoms
            final_types = sc_atoms.arrays["type"]
            if sc_opt2_log:
                print(f"[OPT-2-SC] Done. {sc_opt2_log.count} steps logged -> {sc_opt2_log.path}")

    write_elements_dat(elements_path, final_atoms)

    # ---- Equilibrium MD ----
    eq_log = None
    if eq_steps > 0:
        eq_log = StageLogger(input_dir, "eq_md", ["step", "time_fs", "energy_eV", "T_K", "P_GPa", "vol_A3", "density_g_cm3"])
        ttime_eq = TTIME_FS * units.fs
        print(f"[EQ-MD] Running {eq_steps} steps at {eq_temp_k} K, {eq_press_gpa} GPa ...")
        MaxwellBoltzmannDistribution(final_atoms, temperature_K=eq_temp_k)
        Stationary(final_atoms)
        n_atoms_total = len(final_atoms)

        if (cx + cy + cz) == 0:
            dyn_eq = NVTBerendsen(final_atoms, timestep=eq_timestep_fs * units.fs, temperature_K=eq_temp_k, taut=ttime_eq)
        else:
            pfactor_eq = PFACTOR_COEFF * units.GPa * (ttime_eq ** 2)
            npt_mask_eq = diag_mask_from_flags(cx, cy, cz) if FIX_ANGLES_NPT else None
            dyn_eq = NPT(final_atoms, timestep=eq_timestep_fs * units.fs, temperature_K=eq_temp_k,
                         externalstress=eq_press_gpa * units.GPa, ttime=ttime_eq, pfactor=pfactor_eq, mask=npt_mask_eq)

        for s in range(1, eq_steps + 1):
            dyn_eq.run(1)
            m = _measure_atoms(final_atoms)
            eq_log.log(step=s, time_fs=s * eq_timestep_fs,
                       energy_eV=m["energy_eV"] / n_atoms_total,
                       T_K=m["T_K"], P_GPa=m["P_GPa"],
                       vol_A3=m["vol_A3"], density_g_cm3=m["density_g_cm3"])

        assert_atoms_inside_cell(final_atoms, "after EQ-MD")
        print(f"[EQ-MD] Done. {eq_log.count} steps -> {eq_log.path}")

        # ---- Generate eq_profile.png (4-panel: T, P, E, density vs step) ----
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            eq_data = np.loadtxt(eq_log.path, skiprows=1)  # step, time_fs, energy_eV, T_K, P_GPa, vol_A3, density_g_cm3
            eq_steps_arr = eq_data[:, 0]
            eq_T = eq_data[:, 3]
            eq_P = eq_data[:, 4]
            eq_E = eq_data[:, 2]
            eq_rho = eq_data[:, 6]

            fig, axes = plt.subplots(2, 2, figsize=(12, 8))
            fig.suptitle(f"Equilibrium MD Profile — {data_base}", fontsize=13)

            axes[0, 0].plot(eq_steps_arr, eq_T, "b-", linewidth=0.8)
            axes[0, 0].axhline(eq_temp_k, color="r", linestyle="--", linewidth=0.6, label=f"target={eq_temp_k} K")
            axes[0, 0].set_xlabel("Step")
            axes[0, 0].set_ylabel("Temperature (K)")
            axes[0, 0].legend(fontsize=8)

            axes[0, 1].plot(eq_steps_arr, eq_P, "g-", linewidth=0.8)
            axes[0, 1].axhline(eq_press_gpa, color="r", linestyle="--", linewidth=0.6, label=f"target={eq_press_gpa} GPa")
            axes[0, 1].set_xlabel("Step")
            axes[0, 1].set_ylabel("Pressure (GPa)")
            axes[0, 1].legend(fontsize=8)

            axes[1, 0].plot(eq_steps_arr, eq_E / len(final_atoms), "m-", linewidth=0.8)
            axes[1, 0].set_xlabel("Step")
            axes[1, 0].set_ylabel("Potential Energy (eV/atom)")

            axes[1, 1].plot(eq_steps_arr, eq_rho, "c-", linewidth=0.8)
            axes[1, 1].set_xlabel("Step")
            axes[1, 1].set_ylabel("Density (g/cm$^3$)")

            fig.tight_layout()
            fig.savefig(eq_profile_png, dpi=150)
            plt.close(fig)
            print(f"[EQ-MD] Profile saved: {eq_profile_png}")
        except Exception as e:
            print(f"[EQ-MD] Warning: profile plot failed: {e}")

    else:
        print("[EQ-MD] Skipped (eq_steps=0).")

    # ---- Production MD ----
    prod_log = None
    calculation = "scf" if prod_steps == 0 else "vc-md"
    fake_dt_fs = prod_timestep_fs * 20.0
    ntyp = write_fake_qe_input(fake_in, final_atoms, calculation=calculation, title="Fake QE Input",
                               nstep=prod_steps // prod_freq, dt_fs=fake_dt_fs,
                               model_name=model_name, task_name=task_name)
    init_fake_qe_output(fake_sout, fake_in, final_atoms, ntyp=ntyp, model_name=model_name, task_name=task_name)

    MaxwellBoltzmannDistribution(final_atoms, temperature_K=prod_low_k)
    Stationary(final_atoms)

    write_lammps_data_ovito_style(os.path.join(OUTPUT_DIR, "000.data"), final_atoms, mass_map, final_types)
    append_fake_qe_properties(fake_sout, final_atoms, iteration_num=1)

    if prod_steps == 0:
        append_fake_qe_structure(fake_sout, final_atoms)
        finalize_fake_qe_output(fake_sout)
        print("Done (SCF mode).")
    else:
        prod_log = StageLogger(input_dir, "prod_md", ["step", "time_fs", "energy_eV", "T_K", "P_GPa", "vol_A3", "density_g_cm3"])
        ttime = TTIME_FS * units.fs
        print(f"[PROD-MD] Heating ramp: {prod_low_k} K -> {prod_high_k} K over {prod_steps} steps")

        if (cx + cy + cz) == 0:
            dyn = NVTBerendsen(final_atoms, timestep=prod_timestep_fs * units.fs, temperature_K=prod_low_k, taut=ttime)
        else:
            pfactor = PFACTOR_COEFF * units.GPa * (ttime ** 2)
            npt_mask = diag_mask_from_flags(cx, cy, cz) if FIX_ANGLES_NPT else None
            dyn = NPT(final_atoms, timestep=prod_timestep_fs * units.fs, temperature_K=prod_low_k,
                      externalstress=prod_press_gpa * units.GPa, ttime=ttime, pfactor=pfactor, mask=npt_mask)

        n_atoms_total = len(final_atoms)
        qe_output_count = 0
        for step in range(1, prod_steps + 1):
            ramp_frac = (step - 1) / (prod_steps - 1) if prod_steps > 1 else 1.0
            current_temp_k = prod_low_k + ramp_frac * (prod_high_k - prod_low_k)
            dyn.set_temperature(current_temp_k)
            dyn.run(1)

            # Log every step to txt
            m = _measure_atoms(final_atoms)
            prod_log.log(step=step, time_fs=step * prod_timestep_fs,
                         energy_eV=m["energy_eV"] / n_atoms_total,
                         T_K=m["T_K"], P_GPa=m["P_GPa"],
                         vol_A3=m["vol_A3"], density_g_cm3=m["density_g_cm3"])

            # QE output at prod_freq intervals
            if step % prod_freq == 0:
                append_fake_qe_structure(fake_sout, final_atoms)
                append_fake_qe_properties(fake_sout, final_atoms, iteration_num=qe_output_count + 2)
                write_lammps_data_ovito_style(os.path.join(OUTPUT_DIR, f"{step:03d}.data"), final_atoms, mass_map, final_types)
                qe_output_count += 1

        append_fake_qe_structure(fake_sout, final_atoms)
        with open(fake_sout, "a") as f:
            f.write("     (NOTE: final structure only; no energy/forces/stress.)\n")
        finalize_fake_qe_output(fake_sout)
        print(f"[PROD-MD] Done. {prod_log.count} steps -> {prod_log.path}. {qe_output_count} QE blocks.")

    # ---- Run plotting script ----
    print("[PLOT] Generating thermo_summary.png ...")
    plot_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plot_thermo.py")
    if os.path.isfile(plot_script):
        try:
            subprocess.run([sys.executable, plot_script, input_dir], check=True, timeout=60)
        except Exception as e:
            print(f"[PLOT] Warning: plotting failed: {e}")
    else:
        print(f"[PLOT] Warning: {plot_script} not found, skipping plot.")

    print(f"Done.")
    print(f"  fake.in       : {fake_in}")
    print(f"  fake.sout     : {fake_sout}")
    print(f"  elements.dat  : {elements_path}")
    print(f"  data_files dir: {os.path.abspath(OUTPUT_DIR)}")
    stage_files = [f for f in os.listdir(input_dir) if f.startswith("stage_") and f.endswith(".txt")]
    print(f"  stage logs    : {stage_files}")
    png_path = os.path.join(input_dir, "thermo_summary.png")
    if os.path.isfile(png_path):
        print(f"  thermo plot   : {png_path}")


if __name__ == "__main__":
    main()
