# (c) 2015-2017 Acellera Ltd http://www.acellera.com
# All Rights Reserved
# Distributed under HTMD Software License Agreement
# No redistribution in whole or part
#
import numpy as np
from tempfile import NamedTemporaryFile
from os import path
from htmd.home import home
import os
import shutil
from subprocess import call, check_output
from htmd.util import tempname
from htmd.molecule.molecule import Molecule
from natsort import natsorted
from glob import glob


def dock(protein, ligand, center=None, extent=None, numposes=20, babelexe='obabel', vinaexe=None):
    """ Molecular docking, using Vina

    If centre and extent are not provided, docking will be performed over the whole protein

    Parameters
    ----------
    protein : :class:`Molecule <htmd.molecule.molecule.Molecule>` object
        Molecule object representing the receptor
    ligand : :class:`Molecule <htmd.molecule.molecule.Molecule>` object
        Molecule object representing the ligand to dock
    center : list
        3-vec centre of of the search bounding box (optional)
    extent : list
        3-vec linear extent of the search bounding box (optional)
    numposes : int
        Number of poses to return. Vina cannot return more than 20 poses.
    babelexe : str
        Path to babel executable.
    vinaexe : str
        Path to AutoDock Vina executable.

    Returns
    -------
    poses
        Molecule object representing the N<10 best poses
    scores
        3x num_poses matrix containing kcal, rmsd lb, rmsd ub

    Examples
    --------
    >>> poses, scoring = dock(protein, ligand)
    >>> poses, scoring = dock(protein, ligand, center=[ 10., 5., 12. ], extent=[ 15., 15., 15. ] )

    """
    if np.size(protein.coords, 2) != 1 or np.size(ligand.coords, 2) != 1:
        raise NameError('Protein and ligand Molecules should be single frames')

    buffer = 10.  # Angstrom buffer around protein for whole-protein docking
    c_min = np.min(protein.coords, 0).reshape((1, 3))[0]
    c_max = np.max(protein.coords, 0).reshape((1, 3))[0]

    if center is None:
        center = (buffer + (c_max + c_min)) / 2
    if extent is None:
        extent = (c_max - c_min) + buffer

    # babel -i pdb protein.pdb  -o pdbqt protein.pdbqt -xr
    # babel -i pdb ligand.pdb   -o pdbqt ligand.pdbqt -xhn
    # vina --ligand ligand.pdbqt --receptor protein.pdbqt --center_x 0. --center_y 0. --center_z 0. --size_x 60. --size_y 60. --size_z 60 --exhaustiveness 10
    # babel -m -i pdbqt ligand_out.pdbqt -o pdb out_.pdb -xhn

    protein_pdb = tempname(suffix=".pdb")
    ligand_pdb = tempname(suffix=".pdb")
    output_pdb = tempname(suffix="_.pdb")
    output_prefix = path.splitext(output_pdb)[0]

    protein_pdbqt = tempname(suffix=".pdbqt")
    ligand_pdbqt = tempname(suffix=".pdbqt")
    output_pdbqt = tempname(suffix=".pdbqt")

    protein.write(protein_pdb)
    ligand.write(ligand_pdb)

    # Dirty hack to remove the 'END' line from the PDBs since babel hates it
    with open(protein_pdb, 'r') as f:
        lines = f.readlines()
    with open(protein_pdb, 'w') as f:
        f.writelines(lines[:-1])
    with open(ligand_pdb, 'r') as f:
        lines = f.readlines()
    with open(ligand_pdb, 'w') as f:
        f.writelines(lines[:-1])
    # End of dirty hack

    try:
        if vinaexe is None:
            import platform
            suffix = ''
            if platform.system() == "Windows":
                suffix = '.exe'
            vinaexe = '{}-vina{}'.format(platform.system(), suffix)

        vinaexe = shutil.which(vinaexe, mode=os.X_OK)
        if not vinaexe:
            raise NameError('Could not find vina, or no execute permissions are given')
    except:
        raise NameError('Could not find vina, or no execute permissions are given')
    try:
        babelexe = shutil.which(babelexe, mode=os.X_OK)
        if babelexe is None:
            raise NameError('Could not find babel, or no execute permissions are given')
    except:
        raise NameError('Could not find babel, or no execute permissions are given')

    call([babelexe, '-i', 'pdb', protein_pdb, '-o', 'pdbqt', '-O', protein_pdbqt, '-xr'])
    call([babelexe, '-i', 'pdb', ligand_pdb, '-o', 'pdbqt', '-O', ligand_pdbqt, '-xn', '-xh', '--partialcharge', 'gasteiger'])
    from IPython.core.debugger import Tracer
    Tracer()()
    if not path.isfile(ligand_pdbqt):
        raise NameError('Ligand could not be converted to PDBQT')
    if not path.isfile(protein_pdbqt):
        raise NameError('Protein could not be converted to PDBQT')

    call([vinaexe, '--receptor', protein_pdbqt, '--ligand', ligand_pdbqt, '--out', output_pdbqt,
          '--center_x', str(center[0]), '--center_y', str(center[1]), '--center_z', str(center[2]),
          '--size_x', str(extent[0]), '--size_y', str(extent[1]), '--size_z', str(extent[2]), '--num_modes', str(numposes)])

    call([babelexe, '-m', '-i', 'pdbqt', output_pdbqt, '-o', 'pdb', '-O', output_pdb, '-xhn'])

    outfiles = natsorted(glob('{}*.pdb'.format(output_prefix)))
    # !!! This assumed that the atoms have unique names which is quite uncommon. Disabling it
    # for outf in outfiles:
    #     # First get the scoring
    #     scoring.append(_parseScoring(outf))
    #     next_pose = Molecule(outf)
    #     os.remove(outf)
    #     c = next_pose.coords
    #     co = c.copy()
    #     natoms = len(ligand.name)
    #
    #     # Order atoms back to original order
    #     for idx_i in range(natoms):
    #         for idx_j in range(natoms):
    #             if ligand.name[idx_i] == next_pose.name[idx_j]:
    #                 co[idx_i, :, :] = c[idx_j, :, :]
    #
    #     coords.append(co)

    scoring = []
    poses = []
    for i, ligf in enumerate(outfiles):
        scoring.append(_parseScoring(ligf))
        l = Molecule(ligf)
        l.viewname = 'Pose {}'.format(i)
        poses.append(l)

    os.remove(protein_pdb)
    os.remove(ligand_pdb)
    os.remove(protein_pdbqt)
    os.remove(ligand_pdbqt)
    os.remove(output_pdbqt)

    return poses, np.array(scoring)


def _parseScoring(outf):
    kcal = rmsdlb = rmsdub = None
    with open(outf, 'r') as f:
        for line in f:
            if line.startswith('REMARK VINA RESULT:'):
                pieces = line.split()
                kcal = float(pieces[3])
                rmsdlb = float(pieces[4])
                rmsdub = float(pieces[5])
                break
    if kcal is None or rmsdlb is None or rmsdub is None:
        raise RuntimeError('Could not parse vina output correctly {}'.format(outf))
    return kcal, rmsdlb, rmsdub

if __name__ == "__main__":
    from htmd.molecule.molecule import Molecule
    from os import path
    from htmd.home import home
    protein = Molecule(path.join(home(), 'data', 'docking', 'protein.pdb'))
    ligand = Molecule(path.join(home(), 'data', 'docking', 'ligand.pdb'))
    #poses, scoring = dock(protein, ligand)

