#!/usr/bin/env python3
"""Local macOS acquisition helper. Resolve imports from the resulting persistent path."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent

def run(args):
    p = subprocess.run(args, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout or 'Error del proceso')[-3500:].strip())
    return p.stdout.strip()

def tool(name):
    for path in [f'/opt/homebrew/bin/{name}', f'/usr/local/bin/{name}', shutil.which(name)]:
        if path and Path(path).is_file():
            return path
    raise RuntimeError(f'Falta {name}. Instálalo antes de utilizar esta acción.')

def dialog(script):
    return run(['/usr/bin/osascript', '-e', script])

def validate_url(url, youtube=False):
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Necesitas un enlace http o https válido.')
    host = parsed.hostname.lower()
    if youtube and not (host == 'youtu.be' or host == 'youtube.com' or host.endswith('.youtube.com')):
        raise ValueError('Pega un enlace de YouTube, no de otra página.')
    return url

FORMATS = {
    'MP4 - vídeo y audio (H.264 + AAC)': ('mp4', False),
    'MOV - vídeo y audio (H.264 + PCM)': ('mov', False),
    'WAV - solo audio (PCM)': ('wav', True),
    'MP3 - solo audio': ('mp3', True),
}

def choose_format():
    options = ', '.join('"' + label + '"' for label in FORMATS)
    chosen = dialog('set picked to choose from list {' + options + '} with title "YouTube a DaVinci" with prompt "Selecciona el archivo que quieres añadir. MP4/MOV convierten el vídeo para Resolve; WAV/MP3 descargan solo audio." default items {"' + next(iter(FORMATS)) + '"} OK button name "Continuar" cancel button name "Cancelar"\nif picked is false then error number -128\nreturn item 1 of picked')
    return FORMATS[chosen][0]

def probe_media(path):
    data = json.loads(run([tool('ffprobe'), '-v', 'error', '-show_streams', '-of', 'json', str(path)]))
    return data.get('streams', [])

def convert_media(source, extension, ff=None):
    if extension not in {'mp4', 'mov', 'wav', 'mp3'}:
        raise ValueError('Formato no admitido.')
    ff = ff or tool('ffmpeg')
    streams = probe_media(source)
    if not any(s.get('codec_type') == 'audio' for s in streams):
        raise RuntimeError('El archivo descargado no contiene audio. No se importará un recurso silencioso.')
    target = source.with_name(source.stem + '-compatible.' + extension)
    args = [ff, '-nostdin', '-v', 'error', '-i', str(source)]
    if extension in {'mp4', 'mov'}:
        args += ['-map', '0:v:0', '-map', '0:a:0', '-c:v', 'libx264',
                 '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p']
        args += ['-c:a', 'aac', '-b:a', '320k'] if extension == 'mp4' else ['-c:a', 'pcm_s24le']
        args += ['-movflags', '+faststart']
    else:
        args += ['-map', '0:a:0', '-vn']
        args += ['-c:a', 'pcm_s24le'] if extension == 'wav' else ['-c:a', 'libmp3lame', '-q:a', '0']
    run(args + [str(target)])
    result = probe_media(target)
    expected_audio = {'mp4': 'aac', 'mov': 'pcm_s24le', 'wav': 'pcm_s24le', 'mp3': 'mp3'}[extension]
    if not any(s.get('codec_name') == expected_audio and s.get('codec_type') == 'audio' for s in result):
        raise RuntimeError('La conversión no produjo el audio esperado.')
    if extension in {'mp4', 'mov'} and not any(s.get('codec_name') == 'h264' for s in result):
        raise RuntimeError('La conversión no produjo vídeo H.264.')
    return target

def acquire_youtube(folder):
    url = dialog('text returned of (display dialog "Pega el enlace del vídeo de YouTube:" default answer "" with title "YouTube a DaVinci" buttons {"Cancelar", "Continuar"} default button "Continuar")')
    validate_url(url, youtube=True)
    extension = choose_format()
    yt = tool('yt-dlp')
    ff = tool('ffmpeg')
    tool('ffprobe')
    folder.mkdir(parents=True)
    output = run([yt, '--ignore-config', '--no-playlist', '--no-progress',
                  '--format', 'bestaudio/best' if extension in {'wav', 'mp3'} else 'bestvideo+bestaudio/best',
                  '--merge-output-format', 'mkv',
                  '--ffmpeg-location', str(Path(ff).parent), '--print', 'after_move:filepath',
                  '--output', str(folder / '%(id)s.%(ext)s'), '--', url])
    paths = [Path(s) for s in output.splitlines() if Path(s).is_file()]
    if not paths:
        raise RuntimeError('La descarga no produjo un archivo.')
    return convert_media(paths[-1], extension, ff)

def acquire_image(folder):
    folder.mkdir(parents=True)
    result = run([str(ROOT / 'clipboard'), str(folder / 'imagen')])
    if result.startswith('URL:'):
        url = validate_url(result[4:])
        raw = folder / 'original'
        run(['/usr/bin/curl', '--fail', '--location', '--proto', '=http,https',
             '--proto-redir', '=http,https', '--max-time', '120', '--output', str(raw), '--', url])
        info = run(['/usr/bin/sips', '-g', 'format', str(raw)])
        fmt = info.rsplit('format:', 1)[-1].strip()
        ext = {'jpeg': 'jpg', 'png': 'png', 'tiff': 'tiff', 'gif': 'gif', 'bmp': 'bmp'}.get(fmt)
        if not ext:
            raise RuntimeError('El enlace no es una imagen compatible. Usa Copiar imagen, o la URL original PNG/JPEG/TIFF.')
        path = raw.with_suffix('.' + ext)
        raw.rename(path)
        return path
    path = Path(result)
    if not path.is_file():
        raise RuntimeError('No se pudo guardar la imagen del portapapeles.')
    return path

def main():
    mode, result_file = sys.argv[1:3]
    try:
        chosen = dialog('POSIX path of (choose folder with prompt "Carpeta donde conservar los medios de este proyecto (no la borres mientras lo uses):")')
        folder = Path(chosen) / 'ResolveWebMedia' / (datetime.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
        action = dialog('button returned of (display dialog "¿Dónde quieres colocar el recurso?" with title "DaVinci Web Bridge" buttons {"Cancelar", "Solo biblioteca", "Final de timeline"} default button "Final de timeline" cancel button "Cancelar")')
        path = acquire_youtube(folder) if mode == 'youtube' else acquire_image(folder)
        Path(result_file).write_text('OK\n' + str(path) + '\n' + ('timeline' if action == 'Final de timeline' else 'pool'), encoding='utf-8')
        (folder / 'origen.json').write_text(json.dumps({'mode': mode, 'file': str(path), 'created': datetime.datetime.now().isoformat()}, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as e:
        message = str(e)
        Path(result_file).write_text('CANCEL\n' if '(-128)' in message else 'ERROR\n' + message.replace('\n', ' '), encoding='utf-8')

if __name__ == '__main__':
    main()
