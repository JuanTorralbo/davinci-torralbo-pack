#!/usr/bin/env python3
"""Prepara las dependencias opcionales de alineación de FlowLyrics en macOS."""
from pathlib import Path
import shutil
import subprocess
import sys
import venv

if sys.platform != 'darwin':
    raise SystemExit('Este asistente es solo para macOS.')
if not (3, 11) <= sys.version_info[:2] <= (3, 13):
    raise SystemExit('Ejecuta este asistente con Python 3.11, 3.12 o 3.13.')
root = Path.home() / 'Library/Application Support/FlowLyrics'
environment = root / 'alignment-env'
root.mkdir(parents=True, exist_ok=True)
if environment.exists():
    raise SystemExit('Ya existe alignment-env. Se conserva sin cambios; consulta la guía.')
venv.EnvBuilder(with_pip=True).create(environment)
python = environment / 'bin/python'
subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(Path(__file__).with_name('requirements.txt'))], check=True)
shutil.copy2(Path(__file__).with_name('flowlyrics_align.py'), root / 'flowlyrics_align.py')
print('Alineación preparada. El modelo se descargará cuando uses la función por primera vez.')
