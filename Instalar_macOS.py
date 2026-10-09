#!/usr/bin/env python3
"""Instala los presets y scripts en la carpeta de usuario de Resolve (macOS)."""
from pathlib import Path
import argparse
from datetime import datetime
import shutil
import subprocess
import sys

def install(source, destination, dry_run=False):
    actions = []
    for item in sorted(source.rglob('*')):
        if not item.is_file():
            continue
        target = destination / item.relative_to(source)
        if target.exists() and target.read_bytes() == item.read_bytes():
            continue
        actions.append(str(target.relative_to(destination)))
        if dry_run:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            suffix = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            shutil.copy2(target, target.with_name(target.name + '.backup-' + suffix))
        shutil.copy2(item, target)
        if target.name == 'clipboard':
            target.chmod(0o755)
    return actions

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Muestra los archivos sin copiarlos.')
    parser.add_argument('--destino', type=Path, help='Ruta de Fusion alternativa para instalación manual o prueba.')
    args = parser.parse_args()
    if sys.platform != 'darwin' and not args.destino:
        parser.error('Este instalador es para macOS. Consulta LEEME.md para otros sistemas.')
    base = Path(__file__).resolve().parent
    destination = args.destino or Path.home() / 'Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion'
    actions = install(base / 'Fusion', destination, args.dry_run)
    print(('Se copiarían' if args.dry_run else 'Se han copiado') + f' {len(actions)} archivos.')
    for item in actions:
        print('  ' + item)
    print('Reinicia Resolve. FlowLyrics se instala por separado: consulta LEEME.md.')

if __name__ == '__main__':
    main()
