#!/usr/bin/env python3
# gptfakeQE.py
#
# FIXED CLI: ALWAYS include do_supercell (0/1)
#
# Usage:
#   python gptfakeQE.py INPUT.data opt1_steps opt1_fmax opt2_steps opt2_fmax npt_steps do_supercell(0/1) \
#       temp(K) press(GPa) timestep(fs) cx cy cz MODEL_NAME TASK_NAME
#
# Notes:
# - fake QE input includes: nstep=npt_steps, dt=timestep_fs*20 (fs)
# - If npt_steps==0 -> calculation="scf"
# - If cx=cy=cz=0 and npt_steps>0 -> use NVT (cell fixed)
# - DO NOT use "!" for comments. "!" is reserved ONLY for QE energy marker lines.

from __future__ import annotations

import os
import sys
import shutil
import time
import math
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

# ---- Make PyTorch honor OMP/MKL/SLURM thread settings (HPC friendly) ----
def _set_torch_threads_from_env():
    # Prefer SLURM_CPUS_PER_TASK, then OMP_NUM_THREADS
    for key in ("SLURM_CPUS_PER_TASK", "OMP_NUM_THREADS"):
        v = os.environ.get(key, "").strip()
        if v.isdigit() and int(v) > 0:
            n = int(v)
            try:
                torch.set_num_threads(n)
            except Exception:
                pass
            # interop threads usually doesn't need to be large
            try:
                torch.set_num_interop_threads(max(1, min(4, n)))
            except Exception:
                pass
            return

_set_torch_threads_from_env()

try:
    from fairchem.core import FAIRChemCalculator, pretrained_mlip
except ImportError:
    print("Error: fairchem-core not installed. Please install it via pip.")
    sys.exit(1)

from ase.data import atomic_numbers, chemical_symbols


OUTPUT_DIR = "data_files"

OPT1_PRESS_TOL_GPA = 1.0
OPT2_PRESS_TOL_GPA = 0.2

OPT1_MAXSTEP = 0.25
OPT2_MAXSTEP = 0.20

SUPERCELL_RCUT_A = 6.0   # Å -> target length = 2*rcut = 12 Å

FIX_ANGLES_NPT = True
TTIME_FS = 25.0
PFACTOR_COEFF = 75.0


def usage_and_die(exit_code: int = 1) -> None:
    prog = os.path.basename(sys.argv[0])
    msg = f"""Usage (FIXED: do_supercell is always required):
  python {prog} <input_data_file> <opt1_steps> <opt1_fmax> <opt2_steps> <opt2_fmax> <npt_steps> <do_supercell 0/1> \\
      <temp_K> <press_GPa> <timestep_fs> <cx> <cy> <cz> <MODEL_NAME> <TASK_NAME>

Example:
  python {prog} Al2Co2.data 5 0.2 5 0.1 20 1 300.0 0.0 1.0 1 1 1 uma-s-1p1 omat

Argument definitions:
  <input_data_file> : LAMMPS data file (atom_style atomic) with Masses block (# Element symbols required)
  <opt1_steps>      : OPT-1 steps (FixAtoms(all) + cell relax; angles fixed), int>=0
  <opt1_fmax>       : fmax for OPT-1 stopping criterion (eV/Å), float>=0
  <opt2_steps>      : OPT-2 steps (atoms + selected cell lengths; angles fixed), int>=0
  <opt2_fmax>       : fmax for OPT-2 stopping criterion (eV/Å), float>=0
  <npt_steps>       : MD steps, int>=0. If 0 -> fake QE input calculation = scf
  <do_supercell>    : 0/1. If 1, after OPT-2: repeat only dims with length < 12 Å until >=12 Å; then OPT-2 again.
  <temp_K>          : temperature for NPT/NVT (K)
  <press_GPa>       : target external pressure for OPT-1/OPT-2 and NPT (GPa). Ignored for NVT.
  <timestep_fs>     : MD timestep (fs). fake QE input dt = timestep_fs * 20 (fs)
  <cx cy cz>        : 0/1 flags. Which cell lengths can change in OPT/NPT (diag only). 0 0 0 => NVT
  <MODEL_NAME>      : fairchem model name (e.g., uma-s-1p1)
  <TASK_NAME>       : fairchem task name (e.g., omat)

QE output rule:
  - We print SCF-like '! total energy' blocks exactly nstep times: step 0..(nstep-1).
  - We still print CELL/ATOMIC_POSITIONS for the final structure step=nstep (e.g., 050.data),
    but do NOT print '! total energy' for that last step.
"""
    print(msg, file=sys.stderr)
    sys.exit(exit_code)


def parse_args():
    # program + 15 args = 16
    if len(sys.argv) != 16:
        usage_and_die(1)

    input_data_file = sys.argv[1]
    if not os.path.isfile(input_data_file):
        print(f"Error: input_data_file not found: {input_data_file}", file=sys.stderr)
        usage_and_die(1)

    def _int(tok, name):
        try:
            return int(tok)
        except ValueError:
            print(f"Error: <{name}> must be an integer.", file=sys.stderr)
            usage_and_die(1)

    def _float(tok, name):
        try:
            return float(tok)
        except ValueError:
            print(f"Error: <{name}> must be a float.", file=sys.stderr)
            usage_and_die(1)

    opt1_steps = _int(sys.argv[2], "opt1_steps")
    opt1_fmax  = _float(sys.argv[3], "opt1_fmax")
    opt2_steps = _int(sys.argv[4], "opt2_steps")
    opt2_fmax  = _float(sys.argv[5], "opt2_fmax")
    npt_steps  = _int(sys.argv[6], "npt_steps")
    do_supercell = _int(sys.argv[7], "do_supercell")

    temp_k      = _float(sys.argv[8], "temp_K")
    press_gpa   = _float(sys.argv[9], "press_GPa")
    timestep_fs = _float(sys.argv[10], "timestep_fs")

    cx = _int(sys.argv[11], "cx")
    cy = _int(sys.argv[12], "cy")
    cz = _int(sys.argv[13], "cz")

    model_name = sys.argv[14]
    task_name  = sys.argv[15]

    if opt1_steps < 0 or opt2_steps < 0 or npt_steps < 0:
        print("Error: step numbers must be >= 0.", file=sys.stderr)
        usage_and_die(1)
    if opt1_fmax < 0 or opt2_fmax < 0:
        print("Error: fmax must be >= 0.", file=sys.stderr)
        usage_and_die(1)
    if do_supercell not in (0, 1):
        print("Error: do_supercell must be 0 or 1.", file=sys.stderr)
        usage_and_die(1)

    for name, v in (("cx", cx), ("cy", cy), ("cz", cz)):
        if v not in (0, 1):
            print(f"Error: {name} must be 0 or 1.", file=sys.stderr)
            usage_and_die(1)

    if temp_k <= 0:
        print("Error: temp_K must be > 0.", file=sys.stderr)
        usage_and_die(1)
    if timestep_fs <= 0:
        print("Error: timestep_fs must be > 0.", file=sys.stderr)
        usage_and_die(1)

    return (input_data_file, opt1_steps, opt1_fmax, opt2_steps, opt2_fmax,
            npt_steps, do_supercell, temp_k, press_gpa, timestep_fs,
            cx, cy, cz, model_name, task_name)


def parse_lammps_masses_block(path: str) -> dict[int, tuple[float, str]]:
    masses: dict[int, tuple[float, str]] = {}
    in_masses = False
    with open(path, "r") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("Masses"):
                in_masses = True
                continue
            if in_masses:
                if line.startswith((
                    "Atoms", "Velocities", "Bonds", "Angles", "Dihedrals", "Impropers",
                    "Pair", "Coeffs"
                )):
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
                except:
                    continue
                sym = ""
                if len(parts) == 2:
                    sym = parts[1].strip().split()[0]
                masses[tid] = (mass, sym)
    return masses


def parse_lammps_box_origin(path: str) -> np.ndarray:
    """Read the Cartesian box origin from a LAMMPS data header.

    ASE 3.27.0 preserves atom coordinates from a traditional LAMMPS data file
    but does not retain xlo/ylo/zlo in ``Atoms.celldisp``. This script writes
    zero-origin output boxes, so the input coordinates must be shifted into
    that same coordinate system before optimization.
    """
    lower_bounds: dict[str, float] = {}
    abc_origin = None

    with open(path, "r") as f:
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
        labels = "/".join(axis + "lo" for axis in missing)
        raise RuntimeError(f"Cannot find {labels} in LAMMPS data header: {path}")

    return np.array([lower_bounds[axis] for axis in "xyz"], dtype=float)


def assert_atoms_inside_cell(atoms, stage: str, tolerance: float = 1.0e-8) -> None:
    """Fail instead of writing a structure whose atoms are outside its cell."""
    scaled = atoms.get_scaled_positions(wrap=False)
    outside_mask = np.any(
        (scaled < -tolerance) | (scaled > 1.0 + tolerance),
        axis=1,
    )
    outside_ids = np.flatnonzero(outside_mask)
    if len(outside_ids):
        shown = ", ".join(str(int(i) + 1) for i in outside_ids[:20])
        raise RuntimeError(
            f"{stage}: {len(outside_ids)}/{len(atoms)} atoms are outside the cell; "
            f"atom IDs (first 20): {shown}; scaled-position range: "
            f"min={scaled.min(axis=0)}, max={scaled.max(axis=0)}"
        )


def get_types_array(atoms, mass_map: dict[int, tuple[float, str]]) -> np.ndarray:
    for key in ("type", "types"):
        if key in atoms.arrays:
            arr = np.array(atoms.arrays[key], dtype=int)
            if arr.size == len(atoms):
                return arr

    sym_to_type: dict[str, int] = {}
    for tid, (_, sym) in mass_map.items():
        if sym:
            sym_to_type[sym] = tid

    syms = atoms.get_chemical_symbols()
    out = np.zeros(len(atoms), dtype=int)
    for i, s in enumerate(syms):
        if s in sym_to_type:
            out[i] = sym_to_type[s]
        else:
            out[i] = sym_to_type.get(chemical_symbols[atoms.numbers[i]], 1)
    return out


def cell_to_lammps_triclinic(cell: np.ndarray):
    a = np.array(cell[0], dtype=float)
    b = np.array(cell[1], dtype=float)
    c = np.array(cell[2], dtype=float)

    ax = np.linalg.norm(a)
    if ax <= 0:
        raise ValueError("Invalid cell: |a|=0")

    xy = np.dot(b, a) / ax
    xz = np.dot(c, a) / ax

    by2 = np.dot(b, b) - xy**2
    by = np.sqrt(max(by2, 0.0))
    if by <= 0:
        by = 1e-12

    yz = (np.dot(b, c) - xy * xz) / by
    cz2 = np.dot(c, c) - xz**2 - yz**2
    cz = np.sqrt(max(cz2, 0.0))

    xlo, xhi = 0.0, ax
    ylo, yhi = 0.0, by
    zlo, zhi = 0.0, cz
    return (xlo, xhi, ylo, yhi, zlo, zhi, xy, xz, yz)


def write_lammps_data_ovito_style(path: str, atoms, masses_map: dict[int, tuple[float, str]], types: np.ndarray):
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
            if sym:
                f.write(f"{t} {mass:.7f}  # {sym}\n")
            else:
                f.write(f"{t} {mass:.7f}\n")

        f.write("\nAtoms  # atomic\n\n")
        for i in range(n_atoms):
            tid = int(types[i])
            x, y, z = pos[i]
            f.write(f"{i+1} {tid} {x:.10f} {y:.10f} {z:.10f}\n")


def write_elements_dat(path: str, atoms) -> None:
    elems = sorted(set(atoms.get_chemical_symbols()))
    with open(path, "w") as f:
        f.write(" ".join(elems) + "\n")


def _pressures_gpa_from_ase_stress(atoms):
    s_gpa = atoms.get_stress() / units.GPa
    pxx, pyy, pzz = (-float(s_gpa[0]), -float(s_gpa[1]), -float(s_gpa[2]))
    press = (pxx + pyy + pzz) / 3.0
    return pxx, pyy, pzz, press


class OptimLogInterceptor:
    def __init__(self, base_stream, atoms, mode: str):
        self.base = base_stream
        self.atoms = atoms
        self.mode = mode
        self.t0 = None

    def write(self, s: str):
        stripped = s.lstrip()
        if len(stripped) >= 5 and ":" in stripped[:10]:
            tag = stripped.split(":", 1)[0]
            if tag.isalpha():
                if self.t0 is None:
                    self.t0 = time.time()
                elapsed_min = (time.time() - self.t0) / 60.0

                a, b, c = self.atoms.cell.lengths()
                alpha, beta, gamma = self.atoms.cell.angles()
                vol = float(self.atoms.get_volume())
                pxx, pyy, pzz, press = _pressures_gpa_from_ase_stress(self.atoms)

                extra = (
                    f"  Elap(min)={elapsed_min:6.2f}"
                    f"  a={a:6.2f} b={b:6.2f} c={c:6.2f}"
                    f"  ang= {alpha:6.2f}, {beta:6.2f}, {gamma:6.2f}"
                    f"  Vol={vol:9.2f}"
                    f"  pxx={pxx:7.3f} pyy={pyy:7.3f} pzz={pzz:7.3f} P={press:7.3f}"
                )

                if self.mode == "mix":
                    forces = self.atoms.get_forces(apply_constraint=False)
                    fmax_atom = float(np.linalg.norm(forces, axis=1).max()) if len(forces) else 0.0
                    extra += f"  fmax(eV/A)={fmax_atom:.6f}"

                self.base.write(s.rstrip("\n") + extra + "\n")
                return
        self.base.write(s)

    def flush(self):
        self.base.flush()


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


def diag_mask_from_flags(cx: int, cy: int, cz: int):
    return [[cx, 0, 0],
            [0, cy, 0],
            [0, 0, cz]]


def run_opt1_cell_only(atoms, opt1_steps: int, opt1_fmax: float, cx: int, cy: int, cz: int) -> None:
    if opt1_steps <= 0:
        return
    if (cx + cy + cz) == 0:
        print("[OPT-1] cx=cy=cz=0 -> no cell-length DOF. OPT-1 skipped.")
        return

    intercept = OptimLogInterceptor(sys.stdout, atoms, mode="cell")
    atoms.set_constraint(FixAtoms(indices=range(len(atoms))))

    mask = diag_mask_from_flags(cx, cy, cz)
    ecf, mask_supported = make_unitcellfilter(atoms, mask=mask)
    target_angles = tuple(atoms.cell.angles())

    def enforce_fixed_angles():
        a, b, c = atoms.cell.lengths()
        alpha, beta, gamma = target_angles
        _set_cell_from_cellpar(atoms, a, b, c, alpha, beta, gamma, scale_atoms=True)

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


def run_opt2_atoms_plus_cell(atoms, opt2_steps: int, opt2_fmax: float, cx: int, cy: int, cz: int, label: str = "OPT-2") -> None:
    if opt2_steps <= 0:
        return

    intercept = OptimLogInterceptor(sys.stdout, atoms, mode="mix")

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
        alpha, beta, gamma = target_angles
        _set_cell_from_cellpar(atoms, a, b, c, alpha, beta, gamma, scale_atoms=True)

    opt = BFGS(ecf)
    opt.logfile = intercept
    opt.maxstep = OPT2_MAXSTEP
    if not mask_supported:
        opt.attach(enforce_fixed_angles, interval=1)

    for _ in range(opt2_steps):
        opt.run(fmax=max(opt2_fmax, 1e-12), steps=1)
        if not mask_supported:
            enforce_fixed_angles()


def compute_supercell_reps(atoms, rcut_a: float):
    target = 2.0 * rcut_a  # 12 Å
    a, b, c = atoms.cell.lengths()
    lens = [a, b, c]
    reps = [1, 1, 1]
    for i in range(3):
        if lens[i] < target:
            reps[i] = int(math.ceil(target / lens[i]))
    reps_t = (reps[0], reps[1], reps[2])
    return target, reps_t, (reps_t != (1, 1, 1)), (a, b, c)


def build_supercell_if_needed(atoms, rcut_a: float):
    target, reps_t, did_expand, (a, b, c) = compute_supercell_reps(atoms, rcut_a)
    print(
        f"[SUPERCELL-CHECK] rcut={rcut_a:.2f}Å target={target:.2f}Å "
        f"lengths: a={a:.3f} b={b:.3f} c={c:.3f} -> reps={reps_t} need_expand={did_expand}"
    )
    if not did_expand:
        return atoms, reps_t, False

    old_types = atoms.arrays.get("type", None)
    new_atoms = atoms.repeat(reps_t)
    if old_types is not None:
        new_atoms.arrays["type"] = np.tile(np.array(old_types, dtype=int), reps_t[0] * reps_t[1] * reps_t[2])
    return new_atoms, reps_t, True


def write_fake_qe_input(filename: str, atoms, calculation: str, title: str,
                        nstep: int, dt_fs: float, model_name: str, task_name: str) -> int:
    ntyp = len(sorted(set(atoms.get_chemical_symbols())))
    with open(filename, "w") as f:
        f.write("# Fake QE input generated by gptfakeQE.py\n")
        f.write(f"# MODEL_NAME = {model_name}\n")
        f.write(f"# TASK_NAME  = {task_name}\n\n")

        f.write("&CONTROL\n")
        f.write(f"  calculation = \"{calculation}\"\n")
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
        for sym in sorted(list(set(atoms.get_chemical_symbols()))):
            f.write(f" {sym}  1.0  {sym}.upf\n")

        f.write("ATOMIC_POSITIONS {angstrom}\n")
        pos = atoms.get_positions()
        syms = atoms.get_chemical_symbols()
        for s, p in zip(syms, pos):
            f.write(f" {s} {p[0]:.9f} {p[1]:.9f} {p[2]:.9f}\n")

        f.write("CELL_PARAMETERS {angstrom}\n")
        cell = atoms.get_cell()
        for row in cell:
            f.write(f" {row[0]:.9f} {row[1]:.9f} {row[2]:.9f}\n")

    return ntyp


def init_fake_qe_output(filename: str, input_filename: str, atoms, ntyp: int, model_name: str, task_name: str) -> None:
    Bohr = units.Bohr
    vol_ang3 = atoms.get_volume()
    vol_au = vol_ang3 / (Bohr**3)
    with open(filename, "w") as f:
        f.write("\n     Program PWSCF v.FAKE_NPT starts ...\n")
        f.write(f"     # MODEL_NAME = {model_name}\n")
        f.write(f"     # TASK_NAME  = {task_name}\n")
        f.write(f"     Reading input from {os.path.basename(input_filename)}\n")
        f.write(f"     number of atoms/cell       =            {len(atoms)}\n")
        f.write(f"     number of atomic types     =            {int(ntyp)}\n")
        f.write(f"     unit-cell volume =    {vol_au:.4f} (a.u.)^3\n")


def append_fake_qe_properties(filename: str, atoms, iteration_num: int) -> None:
    Ry = units.Ry
    Bohr = units.Bohr
    kbar = 1000.0 * units.bar

    epot_ry = atoms.get_potential_energy() / Ry
    ekin_ry = atoms.get_kinetic_energy() / Ry
    etot_ry = epot_ry + ekin_ry

    forces_ry_bohr = atoms.get_forces() * Bohr / Ry
    total_force = float(np.sqrt(np.sum(forces_ry_bohr**2)))

    stress_ev_ang3 = atoms.get_stress(voigt=False)
    stress_kbar = -1.0 * stress_ev_ang3 / kbar
    stress_ry_bohr3 = -1.0 * stress_ev_ang3 * (Bohr**3) / Ry
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
            f.write(
                f"     atom    {i+1} type  1   force =      "
                f"{force[0]:.8f}      {force[1]:.8f}      {force[2]:.8f}\n"
            )
        f.write(f"\n     Total force =      {total_force:.6f}\n")

        f.write(
            f"\n          total   stress  (Ry/bohr**3)                   (kbar)     P=       {pressure_kbar:.2f}\n"
        )
        for i in range(3):
            f.write(
                f"    {stress_ry_bohr3[i,0]:.8f}   {stress_ry_bohr3[i,1]:.8f}   {stress_ry_bohr3[i,2]:.8f}           "
                f"{stress_kbar[i,0]:.2f}       {stress_kbar[i,1]:.2f}       {stress_kbar[i,2]:.2f}\n"
            )

        f.write(f"\n     Ekin =      {ekin_ry:.8f} Ry    T =     {temp_k:4.1f} K  Etot =      {etot_ry:.8f}\n")
        f.write(f"     density =       {density_g_cm3:.5f} g/cm^3\n")


def append_fake_qe_structure(filename: str, atoms) -> None:
    Bohr = units.Bohr
    vol_ang3 = float(atoms.get_volume())
    vol_au = vol_ang3 / (Bohr**3)

    with open(filename, "a") as f:
        f.write(f"\n     new unit-cell volume =   {vol_au:.5f} a.u.^3 (  {vol_ang3:.5f} Ang^3 )\n")

        f.write("\nCELL_PARAMETERS (angstrom)\n")
        cell = atoms.get_cell()
        for row in cell:
            f.write(f"      {row[0]:.8f}   {row[1]:.8f}   {row[2]:.8f}\n")

        f.write("\nATOMIC_POSITIONS (angstrom)\n")
        pos = atoms.get_positions()
        syms = atoms.get_chemical_symbols()
        for s, p in zip(syms, pos):
            f.write(f"{s}      {p[0]:.8f}   {p[1]:.8f}   {p[2]:.8f}\n")
        f.write("\n")


def finalize_fake_qe_output(filename: str) -> None:
    with open(filename, "a") as f:
        f.write("\n     JOB DONE.\n")


def main() -> None:
    (input_data_file,
     opt1_steps, opt1_fmax,
     opt2_steps, opt2_fmax,
     npt_steps, do_supercell,
     temp_k, press_gpa, timestep_fs,
     cx, cy, cz,
     model_name, task_name) = parse_args()

    input_dir = os.path.dirname(os.path.abspath(input_data_file))
    data_base = os.path.splitext(os.path.basename(input_data_file))[0]
    fake_in = os.path.join(input_dir, f"{data_base}.in")
    fake_sout = os.path.join(input_dir, f"{data_base}.sout")
    elements_path = os.path.join(input_dir, "elements.dat")

    print(f"[THREADS] torch_num_threads={torch.get_num_threads()}  torch_interop_threads={(torch.get_num_interop_threads() if hasattr(torch,'get_num_interop_threads') else 'NA')}  OMP_NUM_THREADS={os.environ.get('OMP_NUM_THREADS')}  SLURM_CPUS_PER_TASK={os.environ.get('SLURM_CPUS_PER_TASK')}")
    print(f"[RUN] model={model_name} task={task_name} temp_K={temp_k} press_GPa={press_gpa} timestep_fs={timestep_fs} md_steps={npt_steps} do_supercell={do_supercell} cell_flags={cx}{cy}{cz}")

    mass_map = parse_lammps_masses_block(input_data_file)
    if not mass_map:
        print("Error: cannot find 'Masses' block in input .data.", file=sys.stderr)
        sys.exit(1)

    Z_map: dict[int, int] = {}
    for tid, (_, sym) in mass_map.items():
        if sym and sym in atomic_numbers:
            Z_map[tid] = atomic_numbers[sym]
    missing = [t for t in mass_map.keys() if t not in Z_map]
    if missing:
        print(f"Error: Masses block missing valid '# Element' for types: {missing}", file=sys.stderr)
        sys.exit(1)

    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.mkdir(OUTPUT_DIR)

    atoms = read(input_data_file, format="lammps-data", atom_style="atomic", Z_of_type=Z_map)
    atoms.set_pbc(True)

    # Normalize the input coordinates to the zero-origin box emitted by
    # write_lammps_data_ovito_style(). Read the origin from the data header;
    # ASE 3.27.0 returns zero celldisp for traditional xlo/xhi headers.
    cell_origin = parse_lammps_box_origin(input_data_file)
    atoms.set_positions(atoms.get_positions() - cell_origin)
    atoms.set_celldisp(np.zeros(3))
    assert_atoms_inside_cell(atoms, "after input-origin normalization")

    atoms.arrays["type"] = np.array(get_types_array(atoms, mass_map), dtype=int)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    predictor = pretrained_mlip.get_predict_unit(model_name, device=device)
    atoms.calc = FAIRChemCalculator(predictor, task_name=task_name)

    # OPT-1 + OPT-2
    run_opt1_cell_only(atoms, opt1_steps, opt1_fmax, cx=cx, cy=cy, cz=cz)
    assert_atoms_inside_cell(atoms, "after OPT-1")
    write_lammps_data_ovito_style(os.path.join(OUTPUT_DIR, "minimized_1.data"), atoms, mass_map, atoms.arrays["type"])

    run_opt2_atoms_plus_cell(atoms, opt2_steps, opt2_fmax, cx=cx, cy=cy, cz=cz, label="OPT-2")
    assert_atoms_inside_cell(atoms, "after OPT-2")
    write_lammps_data_ovito_style(os.path.join(OUTPUT_DIR, "minimized_2.data"), atoms, mass_map, atoms.arrays["type"])

    final_atoms = atoms
    final_types = atoms.arrays["type"]

    # Supercell (after OPT-2), then OPT-2 again if applied
    if do_supercell == 1:
        sc_atoms, reps_t, did_expand = build_supercell_if_needed(atoms, rcut_a=SUPERCELL_RCUT_A)
        if not did_expand:
            print("[SUPERCELL] skipped: no expansion needed -> OPT-2 #2 skipped.")
        else:
            print(f"[SUPERCELL] applied: repeat={reps_t}. Running OPT-2 #2 on supercell.")
            sc_atoms.calc = FAIRChemCalculator(predictor, task_name=task_name)
            if "type" not in sc_atoms.arrays or len(sc_atoms.arrays["type"]) != len(sc_atoms):
                sc_atoms.arrays["type"] = np.tile(np.array(atoms.arrays["type"], dtype=int), reps_t[0] * reps_t[1] * reps_t[2])

            assert_atoms_inside_cell(sc_atoms, "after supercell construction")
            write_lammps_data_ovito_style(os.path.join(OUTPUT_DIR, "supercell.data"), sc_atoms, mass_map, sc_atoms.arrays["type"])
            run_opt2_atoms_plus_cell(sc_atoms, opt2_steps, opt2_fmax, cx=cx, cy=cy, cz=cz, label="OPT-2-SUPERCELL")
            assert_atoms_inside_cell(sc_atoms, "after OPT-2-SUPERCELL")
            write_lammps_data_ovito_style(os.path.join(OUTPUT_DIR, "minimized_2_supercell.data"), sc_atoms, mass_map, sc_atoms.arrays["type"])

            final_atoms = sc_atoms
            final_types = sc_atoms.arrays["type"]

    # elements.dat (same dir as input)
    write_elements_dat(elements_path, final_atoms)

    # fake.in + fake.sout (same dir as input)
    calculation = "scf" if npt_steps == 0 else "vc-md"
    fake_dt_fs = timestep_fs * 20.0
    ntyp = write_fake_qe_input(
        fake_in,
        final_atoms,
        calculation=calculation,
        title="Fake QE Input",
        nstep=npt_steps,
        dt_fs=fake_dt_fs,
        model_name=model_name,
        task_name=task_name
    )

    init_fake_qe_output(fake_sout, fake_in, final_atoms, ntyp=ntyp, model_name=model_name, task_name=task_name)

    # velocities for MD; safe even if scf (just unused)
    MaxwellBoltzmannDistribution(final_atoms, temperature_K=temp_k)
    Stationary(final_atoms)

    # step 0 output and step 0 SCF-like properties (counts as the 1st "!" for nstep>0)
    write_lammps_data_ovito_style(os.path.join(OUTPUT_DIR, "000.data"), final_atoms, mass_map, final_types)
    append_fake_qe_properties(fake_sout, final_atoms, iteration_num=1)

    if npt_steps == 0:
        append_fake_qe_structure(fake_sout, final_atoms)
        finalize_fake_qe_output(fake_sout)
        print("Done (SCF mode).")
        print(f"  fake.in       : {fake_in}")
        print(f"  fake.sout     : {fake_sout}")
        print(f"  elements.dat  : {elements_path}")
        print(f"  data_files dir: {os.path.abspath(OUTPUT_DIR)}")
        return

    # MD: NPT or NVT
    ttime = TTIME_FS * units.fs

    if (cx + cy + cz) == 0:
        if NVTBerendsen is None:
            print("Error: ase.md.nvtberendsen.NVTBerendsen not available in your ASE version.", file=sys.stderr)
            sys.exit(1)
        print("[MD] cx=cy=cz=0 -> switching from NPT to NVT (cell fixed). press_GPa ignored in NVT.")
        dyn = NVTBerendsen(
            final_atoms,
            timestep=timestep_fs * units.fs,
            temperature_K=temp_k,
            taut=ttime,
        )
    else:
        pfactor = PFACTOR_COEFF * units.GPa * (ttime) ** 2
        npt_mask = diag_mask_from_flags(cx, cy, cz) if FIX_ANGLES_NPT else None
        dyn = NPT(
            final_atoms,
            timestep=timestep_fs * units.fs,
            temperature_K=temp_k,
            externalstress=press_gpa * units.GPa,
            ttime=ttime,
            pfactor=pfactor,
            mask=npt_mask,
        )

    # Run exactly npt_steps updates to produce 001..npt_steps data files (e.g. 050.data)
    # Print structure for every step INCLUDING final step=npt_steps
    # Print SCF-like properties only for steps 1..(npt_steps-1) so total "!" equals npt_steps
    for step in range(1, npt_steps + 1):
        dyn.run(1)

        append_fake_qe_structure(fake_sout, final_atoms)
        write_lammps_data_ovito_style(
            os.path.join(OUTPUT_DIR, f"{step:03d}.data"),
            final_atoms, mass_map, final_types
        )

        if step <= npt_steps - 1:
            append_fake_qe_properties(fake_sout, final_atoms, iteration_num=step + 1)
        else:
            with open(fake_sout, "a") as f:
                f.write("     (NOTE: final step printed CELL/ATOMIC_POSITIONS only; no energy/forces/stress.)\n")

    finalize_fake_qe_output(fake_sout)

    print("Done.")
    print(f"  fake.in       : {fake_in}")
    print(f"  fake.sout     : {fake_sout}")
    print(f"  elements.dat  : {elements_path}")
    print(f"  data_files dir: {os.path.abspath(OUTPUT_DIR)}")


if __name__ == "__main__":
    main()
