#!/usr/bin/env python3
"""FlowLyrics: searchable, animated social lyrics for DaVinci Resolve Studio.

This file is both a Resolve Workflow Integration script and a small importable
module. Resolve injects ``resolve``, ``project``, ``fusion`` and ``bmd`` when it
launches the script from Workspace > Workflow Integrations.
"""

from __future__ import annotations

import json
import html
import math
import re
import subprocess
import os
import shutil
import uuid
import tempfile
import hashlib
from pathlib import Path
from dataclasses import dataclass, replace
from typing import Any, Iterable


PLUGIN_NAME = "FlowLyrics"
PLUGIN_VERSION = "0.4.0"
ALIGN_ROOT = Path.home() / 'Library' / 'Application Support' / 'FlowLyrics'
WINDOW_ID = "com.juantorralbo.resolve.flowlyrics"
LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
USER_AGENT = f"FlowLyricsResolve/{PLUGIN_VERSION} (DaVinci Resolve workflow integration)"


@dataclass(frozen=True)
class LyricLine:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class LyricPhrase:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class StyleOptions:
    width: int = 1920
    height: int = 1080
    font: str = "Montserrat"
    font_style: str = "ExtraBold"
    size: float = 0.06
    drift: float = 0.055
    base_y: float = 0.43
    uppercase: bool = False
    line_spacing: float = 0.65
    layout_frame: bool = False
    red: float = 1.0
    green: float = 1.0
    blue: float = 1.0


def _format_seconds(value: float) -> str:
    minutes = int(value // 60)
    seconds = value - minutes * 60
    return f"{minutes:02d}:{seconds:06.3f}"


def search_lrclib(query: str, limit: int = 40) -> list[dict[str, Any]]:
    """Search LRCLIB without third-party Python dependencies.

    macOS' system curl is used so Resolve's embedded Python does not depend on
    a particular CA bundle. Audio is never downloaded.
    """

    cleaned = query.strip()
    if len(cleaned) < 2:
        raise ValueError("Escribe al menos dos caracteres para buscar.")

    completed = subprocess.run(
        [
            "/usr/bin/curl",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--max-time",
            "18",
            "--user-agent",
            USER_AGENT,
            "--get",
            "--data-urlencode",
            f"q={cleaned}",
            LRCLIB_SEARCH_URL,
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip() or "No se pudo contactar con LRCLIB."
        raise RuntimeError(detail)

    # Keep curl output as bytes. Resolve's embedded Python can run with an
    # ASCII locale; asking subprocess to decode text implicitly would then
    # fail on accents or emoji. json.loads decodes JSON bytes as UTF-8.
    payload = json.loads(completed.stdout)
    if not isinstance(payload, list):
        raise RuntimeError("LRCLIB devolvió una respuesta inesperada.")

    synced = [row for row in payload if row.get("syncedLyrics") and not row.get("instrumental")]
    unsynced = [row for row in payload if not row.get("syncedLyrics") and not row.get("instrumental")]
    return (synced + unsynced)[:limit]


_TIMESTAMP_RE = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:\.\d{1,3})?)\]")


def parse_lrc(source: str, final_hold: float = 3.0) -> list[LyricLine]:
    """Parse standard LRC, including multiple timestamps on one line."""

    raw: list[tuple[float, str]] = []
    for source_line in source.splitlines():
        timestamps = _TIMESTAMP_RE.findall(source_line)
        if not timestamps:
            continue
        text = _TIMESTAMP_RE.sub("", source_line).strip()
        if not text:
            continue
        for minutes, seconds in timestamps:
            raw.append((int(minutes) * 60.0 + float(seconds), text))

    raw.sort(key=lambda entry: entry[0])
    lines: list[LyricLine] = []
    for index, (start, text) in enumerate(raw):
        if index + 1 < len(raw):
            end = max(start + 0.35, raw[index + 1][0] - 0.03)
        else:
            end = start + final_hold
        lines.append(LyricLine(start=start, end=end, text=text))
    return lines



_SRT_TIME = re.compile(r"^(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,3})(?:\s+.*)?$")


def parse_srt(source):
    source = source.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    phrases = []
    for number, block in enumerate(re.split(r"\n[ \t]*\n", source), 1):
        rows = block.strip().splitlines()
        if rows and rows[0].strip().isdigit():
            rows = rows[1:]
        if not rows:
            continue
        match = _SRT_TIME.fullmatch(rows[0].strip())
        if not match:
            raise ValueError(f"Subtítulo {number}: los tiempos SRT no son válidos.")
        def seconds(values):
            hours, minutes, secs, millis = values
            if int(minutes) >= 60 or int(secs) >= 60:
                raise ValueError(f"Subtítulo {number}: minutos o segundos fuera de rango.")
            return int(hours)*3600 + int(minutes)*60 + int(secs) + int(millis)/(10**len(millis))
        start, end = seconds(match.groups()[:4]), seconds(match.groups()[4:])
        if end <= start:
            raise ValueError(f"Subtítulo {number}: el fin debe ser posterior al inicio.")
        text = html.unescape(re.sub(r"<[^>]+>|\{\\[^}]*\}", "", " ".join(rows[1:])))
        text = " ".join(text.split())
        if not text:
            continue
        phrases.append(LyricPhrase(start, end, text))
    phrases.sort(key=lambda p: p.start)
    if not phrases:
        raise ValueError("El archivo SRT no contiene subtítulos con texto.")
    if any(a.start == b.start for a,b in zip(phrases, phrases[1:])):
        raise ValueError("Hay subtítulos con el mismo inicio. Combínalos antes de importar.")
    return phrases


def load_srt(path):
    path = Path(path)
    if path.suffix.lower() != ".srt":
        raise ValueError("Selecciona un archivo .srt.")
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        source = data.decode("utf-16")
    else:
        try:
            source = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            source = data.decode("cp1252")
    return parse_srt(source)

def _word_groups(words: list[str], preferred: int) -> list[list[str]]:
    preferred = max(1, min(12, preferred))
    groups = [words[index : index + preferred] for index in range(0, len(words), preferred)]
    return groups


def aligned_phrases(payload, preferred=1):
    """Preserve measured word boundaries; never invent missing timestamps."""
    phrases = []
    for segment in payload.get('segments', []):
        words = [w for w in segment.get('words', []) if w.get('word', '').strip()]
        for index in range(0, len(words), max(1, preferred)):
            group = words[index:index + max(1, preferred)]
            start, end = float(group[0]['start']), float(group[-1]['end'])
            text = ''.join(w['word'] for w in group).strip()
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                raise ValueError('La alineación dejó palabras sin duración. Revisa la letra o el audio.')
            if phrases and start <= phrases[-1].start:
                raise ValueError('La alineación produjo palabras simultáneas. Revisa los tiempos antes de crear.')
            if phrases and start < phrases[-1].end:
                previous = phrases[-1]
                phrases[-1] = LyricPhrase(previous.start, start, previous.text)
            phrases.append(LyricPhrase(start, end, text))
    if not phrases:
        raise ValueError('El audio no produjo tiempos por palabra.')
    return phrases


def align_audio(audio_path, phrases, language=None):
    audio = Path(audio_path).expanduser().resolve()
    if not audio.is_file():
        raise ValueError('Selecciona el archivo de audio de esta misma versión de la canción.')
    request = {'audio': str(audio), 'language': language, 'model': 'large-v3',
               'models': str(ALIGN_ROOT / 'models'),
               'segments': [p.__dict__ for p in phrases]}
    fingerprint = hashlib.sha256((json.dumps(request, sort_keys=True) +
                                 str(audio.stat().st_mtime_ns) + str(audio.stat().st_size)).encode()).hexdigest()
    cache = ALIGN_ROOT / 'alignment-cache'
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / (fingerprint + '.json')
    if destination.is_file():
        return json.loads(destination.read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='flowlyrics-') as directory:
        source, output = Path(directory) / 'request.json', Path(directory) / 'result.json'
        source.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
        run_process([str(ALIGN_ROOT / 'alignment-env/bin/python'),
                     str(ALIGN_ROOT / 'flowlyrics_align.py'), str(source), str(output)], 7200)
        payload = json.loads(output.read_text(encoding='utf-8'))
        measured = aligned_phrases(payload)  # Validate before caching.
        normalize = lambda value: re.sub(r'\W+', '', value.casefold())
        if normalize(' '.join(p.text for p in measured)) != normalize(' '.join(p.text for p in phrases)):
            raise ValueError('La alineación no conservó toda la letra. Revisa texto y versión del audio.')
        destination.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        return payload


def sung_duration(text: str, rate: float = 5.0, hold: float = 0.4, minimum: float = 0.6) -> float:
    """Estimate how long a phrase stays sung: characters / rate + small hold.

    LRC timestamps mark when the *next* line starts, not when the current one
    stops being sung, so sparse lines would otherwise hold on screen for many
    seconds after the voice moved on.
    """

    chars = sum(len(word) for word in text.split())
    return max(minimum, chars / max(1.0, rate) + hold)


def lines_to_phrases(
    lines: Iterable[LyricLine],
    words_per_phrase: int = 3,
    gap: float = 0.0,
    rate: float = 5.0,
) -> list[LyricPhrase]:
    """Split timed LRC lines into short phrases and interpolate their timing.

    The line's duration is distributed by **character count**, not word count:
    "y tú" and "extraordinariamente" no longer get the same screen time, which
    tracks sung duration much better when only line-level timestamps exist.

    A short ``gap`` is trimmed from the end of every phrase so two consecutive
    phrases are never both mid-fade on screen (that overlap looked like
    ghosting).
    """

    phrases: list[LyricPhrase] = []
    for line in lines:
        words = line.text.split()
        if not words:
            continue
        groups = _word_groups(words, words_per_phrase)
        weights = [max(1, sum(len(word) for word in group)) for group in groups]
        total_weight = sum(weights)
        cursor = 0
        duration = line.end - line.start
        if duration <= 0:
            raise ValueError('La línea debe tener una duración positiva.')
        for group_index, group in enumerate(groups):
            start = line.start + duration * (cursor / total_weight)
            cursor += weights[group_index]
            end = line.start + duration * (cursor / total_weight)
            if group_index + 1 < len(groups):
                end -= gap
            phrase_text = " ".join(group)
            # Preserve the complete synchronized interval.
            phrases.append(LyricPhrase(start=start, end=max(start + min(0.01, duration / total_weight), end), text=phrase_text))
    return phrases


_PREVIEW_LINE_RE = re.compile(r"^\s*(\d{1,3}):(\d{1,2}(?:\.\d{1,3})?)\s+(.*\S)\s*$")


def parse_preview(source: str, **_kwargs: Any) -> list[LyricPhrase]:
    phrases = []
    pattern = re.compile(r"^\s*(\d+:\d+(?:\.\d+)?)\s*-->\s*(\d+:\d+(?:\.\d+)?)\s+(.+)$")
    def seconds(value):
        m, sec = value.split(":")
        if float(sec) >= 60:
            raise ValueError("Los segundos deben ser inferiores a 60.")
        return int(m) * 60 + float(sec)
    for number, line in enumerate(source.splitlines(), 1):
        if not line.strip():
            continue
        match = pattern.match(line)
        if not match:
            raise ValueError(f"Línea {number}: usa MM:SS.ss --> MM:SS.ss texto")
        start, end = seconds(match[1]), seconds(match[2])
        if end <= start:
            raise ValueError(f"Línea {number}: el fin debe ser posterior al inicio.")
        if phrases and start <= phrases[-1].start:
            raise ValueError(f"Línea {number}: los inicios deben estar en orden y ser distintos.")
        phrases.append(LyricPhrase(start, end, match[3].strip()))
    return phrases


def format_preview(phrases):
    return "\n".join(f"{_format_seconds(p.start)} --> {_format_seconds(p.end)}  {p.text}" for p in phrases)


def executable(name):
    for directory in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"):
        candidate = Path(directory) / name
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"Falta {name}. Instálalo antes de descargar audio.")
    return found


def run_process(args, timeout=120):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-1600:] or "Falló el proceso externo.")
    return result.stdout.decode("utf-8", errors="replace").strip()


def audio_candidates(entries, expected_duration=None):
    """Only explicit audio/lyric/Topic uploads; reject music videos and variants."""
    rows = []
    blocked = re.compile(r"\bvideo\b|\bvídeo\b|videoclip|vídeo\s+oficial|video\s+oficial|live\b|en\s+vivo|remix|karaoke|sped\s+up|slowed|8d|instrumental|cover|clean\s+version", re.I)
    audio = re.compile(r"official\s+audio|audio\s+oficial|\baudio\b|\blyrics?\b|\bletra\b|visualizer|visualiser", re.I)
    for row in entries:
        if not row or not row.get("id"):
            continue
        title, channel = row.get("title", ""), row.get("channel") or row.get("uploader") or ""
        if blocked.search(title) or not (audio.search(title) or channel.lower().endswith(" - topic")):
            continue
        duration = row.get("duration")
        if expected_duration and duration and abs(duration - expected_duration) > 5:
            continue
        rows.append({"id": row["id"], "title": title, "duration": duration, "channel": channel, "url": "https://www.youtube.com/watch?v=" + row["id"]})
    rows.sort(key=lambda row: (0 if row["channel"].lower().endswith(" - topic") else 1, abs((row.get("duration") or expected_duration or 0) - (expected_duration or 0))))
    return rows[:8]


def search_youtube(query, expected_duration=None):
    if len(query.strip()) < 2:
        raise ValueError("Escribe canción y artista.")
    result = json.loads(run_process([executable("yt-dlp"), "--ignore-config", "--flat-playlist", "--dump-single-json", "--no-warnings", "--socket-timeout", "15", "--", "ytsearch20:" + query.strip() + " official audio"], 60))
    return audio_candidates(result.get("entries", []), expected_duration)


def media_directory():
    path = Path.home() / "Documents" / "FlowLyrics Media"
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_mp3(url):
    if not re.fullmatch(r"https://(?:www\.)?youtube\.com/watch\?v=[A-Za-z0-9_-]{11}", url):
        raise ValueError("Selecciona un resultado de YouTube válido.")
    video_id = url.rsplit("=", 1)[-1]
    destination = media_directory() / (video_id + ".mp3")
    if not destination.is_file():
        run_process([executable("yt-dlp"), "--ignore-config", "--no-playlist", "--socket-timeout", "20", "--retries", "2", "-f", "bestaudio/best", "-x", "--audio-format", "mp3", "--audio-quality", "192K", "--ffmpeg-location", executable("ffmpeg"), "-o", str(media_directory() / (video_id + ".%(ext)s")), "--", url], 240)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("No se obtuvo un MP3 válido.")
    return str(destination)



def _nominal_fps(frame_rate: Any) -> int:
    value = float(frame_rate)
    if abs(value - 23.976) < 0.02:
        return 24
    if abs(value - 29.97) < 0.02:
        return 30
    if abs(value - 59.94) < 0.02:
        return 60
    return max(1, int(round(value)))


def timecode_to_frames(timecode: str, frame_rate: Any) -> int:
    """Convert non-drop or SMPTE drop-frame timecode to an absolute frame."""

    drop = ";" in timecode
    parts = [int(value) for value in re.split(r"[:;]", timecode)]
    if len(parts) != 4:
        raise ValueError(f"Timecode no válido: {timecode}")
    hours, minutes, seconds, frames = parts
    nominal = _nominal_fps(frame_rate)
    total = ((hours * 3600 + minutes * 60 + seconds) * nominal) + frames
    if drop and nominal in (30, 60):
        dropped = (2 if nominal == 30 else 4) * (60 * hours + minutes - (60 * hours + minutes) // 10)
        total -= dropped
    return total


def frames_to_timecode(frame_number: int, frame_rate: Any, drop: bool = False) -> str:
    """Convert an absolute frame to SMPTE timecode."""

    nominal = _nominal_fps(frame_rate)
    frame_number = max(0, int(round(frame_number)))
    if drop and nominal in (30, 60):
        drop_frames = 2 if nominal == 30 else 4
        frames_per_minute = nominal * 60 - drop_frames
        frames_per_10_minutes = nominal * 600 - drop_frames * 9
        frames_per_hour = frames_per_10_minutes * 6
        frames_per_24_hours = frames_per_hour * 24
        value = frame_number % frames_per_24_hours
        ten_minute_blocks, remainder = divmod(value, frames_per_10_minutes)
        extra_minutes = max(0, (remainder - drop_frames) // frames_per_minute)
        value += drop_frames * 9 * ten_minute_blocks + drop_frames * extra_minutes
    else:
        value = frame_number

    frames = value % nominal
    total_seconds = value // nominal
    seconds = total_seconds % 60
    minutes = (total_seconds // 60) % 60
    hours = (total_seconds // 3600) % 24
    separator = ";" if drop else ":"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{frames:02d}"


def _find_input(tool: Any, input_id: str) -> Any | None:
    for input_obj in tool.GetInputList().values():
        if input_obj.GetAttrs().get("INPS_ID") == input_id:
            return input_obj
    return None


def _set_constant(tool: Any, input_id: str, value: Any) -> None:
    tool.SetInput(input_id, value, 0)


def populate_composition(item, phrases, chunk_start_seconds, fps, style):
    # Five reusable text slots cover the active phrase and two neighbours.
    # Changing text outside the visible window avoids rendering the whole song.
    comp = item.GetFusionCompByIndex(1) or item.AddFusionComp()
    if not comp:
        raise RuntimeError("No se pudo crear la composición Fusion.")
    comp.Lock()
    comp.StartUndo("FlowLyrics optimizado")
    try:
        tools = list(comp.GetToolList(False).values())
        media_out = next((t for t in tools if t.GetAttrs().get("TOOLS_RegID") == "MediaOut"), None)
        for tool in tools:
            if tool is not media_out:
                tool.Delete()
        if media_out is None:
            media_out = comp.AddTool("MediaOut", True, 5, 0)
        scroll = comp.AddTool("Custom", True, 3, 0)
        scroll.SetAttrs({"TOOLS_Name": "FlowScroll"})
        # Flat scalar transitions avoid Fusion's nested-expression depth limit.
        steps = []
        for previous, phrase in zip(phrases, phrases[1:]):
            frame = (phrase.start - chunk_start_seconds) * fps
            transition = max(0.001, min(0.08, (phrase.start - previous.start) / 2)) * fps
            u = f"min(1,max(0,(time-({frame-transition}))/{transition}))"
            steps.append(f"({u})*({u})*(3-2*({u}))")
        _find_input(scroll, "NumberIn1").SetExpression("+".join(steps) or "0")
        output = None
        for slot in range(min(5, len(phrases))):
            entries = [(i, phrase) for i, phrase in enumerate(phrases) if i % 5 == slot]
            text = comp.AddTool("TextPlus", True, -4, slot)
            text.SetAttrs({"TOOLS_Name": f"Slot_{slot+1}"})
            text.UserControls = {"PhraseIndex": {"LINKS_Name": "Frase", "LINKID_DataType": "Number", "INPID_InputControl": "ScrewControl", "INP_Default": entries[0][0], "ICS_ControlPage": "Lyrics"}}
            text = text.Refresh()
            for key, value in {"Font": style.font, "Style": style.font_style, "Size": style.size, "HorizontalJustificationCenter": 1, "UseFrameFormatSettings": 0, "Width": style.width, "Height": style.height, "Red1": style.red, "Green1": style.green, "Blue1": style.blue, "Alpha1": 1, "LineSpacing": style.line_spacing}.items():
                text.SetInput(key, value)
            if style.layout_frame:
                for key, value in {"LayoutType": 1, "Wrap": 1, "LayoutWidth": 0.86, "LayoutHeight": 0.15}.items():
                    text.SetInput(key, value)
            def select(values):
                result = values[0]
                for (index, phrase), value in zip(entries[1:], values[1:]):
                    switch = (phrases[index-2].start - chunk_start_seconds) * fps
                    result = f"iif(time < {switch}, {result}, {value})"
                return result
            _find_input(text, "StyledText").SetExpression(select([json.dumps(p.text.upper() if style.uppercase else p.text, ensure_ascii=False) for i,p in entries]))
            _find_input(text, "PhraseIndex").SetExpression(select([str(i) for i,p in entries]))
            begin = select([str((p.start-chunk_start_seconds)*fps) for i,p in entries])
            end = select([str((p.end-chunk_start_seconds)*fps) for i,p in entries])
            distance = "abs(FlowScroll.NumberIn1-PhraseIndex)"
            _find_input(text, "Center").SetExpression(f"Point(0.5, 0.5 + (FlowScroll.NumberIn1-PhraseIndex)*{max(0.06,style.drift)})")
            _find_input(text, "Opacity1").SetExpression(f"iif(time >= ({begin}) and time < ({end}),1,0.42)*max(0,1-({distance})/2.5)")
            if output is None:
                output = text
            else:
                merge = comp.AddTool("Merge", True, 0, slot)
                merge.ConnectInput("Background", output)
                merge.ConnectInput("Foreground", text)
                output = merge
        media_out.ConnectInput("Input", output)
        media_out.SetInput("Index", 0)
        comp.SetData("FlowLyrics.Version", PLUGIN_VERSION)
        comp.SetData("FlowLyrics.Phrases", json.dumps([p.__dict__ for p in phrases], ensure_ascii=False))
        comp.SetData("FlowLyrics.Style", json.dumps(style.__dict__))
    finally:
        comp.EndUndo(True)
        comp.Unlock()
    names = item.GetFusionCompNameList()
    if names:
        item.LoadFusionCompByName(names[0])
    media_out.SetInput("Index", 0)
    return int(item.GetDuration())


def create_flowlyrics(resolve_object, project_object, phrases, style, offset_seconds=0.0, audio_path=""):
    if not phrases:
        raise ValueError("No hay frases para crear.")
    timeline = project_object.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("Abre una cronología.")
    fps = float(timeline.GetSetting("timelineFrameRate") or 24)
    style = replace(style, width=int(timeline.GetSetting("timelineResolutionWidth") or 1920), height=int(timeline.GetSetting("timelineResolutionHeight") or 1080))
    original_timecode = timeline.GetCurrentTimecode()
    base_frame = timecode_to_frames(original_timecode, fps)
    lyric_start = base_frame + round(offset_seconds * fps)
    if lyric_start < timeline.GetStartFrame():
        raise ValueError("El desfase sitúa la letra antes del inicio de la cronología.")
    duration = max(p.end for p in phrases) + 0.5
    frames = int(math.ceil(duration * fps))
    session_id = uuid.uuid4().hex[:10]
    source = media_directory() / ("lyrics-" + session_id + ".mov")
    run_process([executable("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s={style.width}x{style.height}:r={fps}", "-vf", "format=argb,colorchannelmixer=aa=0", "-frames:v", str(frames), "-c:v", "qtrle", "-y", str(source)])
    pool = project_object.GetMediaPool()
    media = pool.ImportMedia([str(source)])
    if not media:
        raise RuntimeError("No se pudo importar el soporte de Fusion.")
    audio_media = pool.ImportMedia([audio_path]) if audio_path else []
    if audio_path and not audio_media:
        raise RuntimeError("No se pudo importar el MP3.")
    created = []
    video_track = timeline.GetTrackCount("video") + 1
    audio_track = None
    try:
        if not timeline.AddTrack("video"):
            raise RuntimeError("No se pudo añadir una pista de vídeo.")
        timeline.SetTrackName("video", video_track, "FlowLyrics " + session_id)
        clips = pool.AppendToTimeline([{"mediaPoolItem": media[0], "startFrame": 0, "endFrame": frames - 1, "trackIndex": video_track, "recordFrame": lyric_start, "mediaType": 1}])
        if not clips:
            raise RuntimeError("No se pudo añadir la letra a la cronología.")
        created.extend(clips)
        item = clips[0]
        if abs(item.GetDuration() - frames) > 1:
            raise RuntimeError("Resolve no respetó la duración solicitada.")
        item.SetName("FlowLyrics " + session_id)
        item.SetClipColor("Teal")
        populate_composition(item, phrases, 0, fps, style)
        resolve_object.OpenPage("fusion")
        resolve_object.OpenPage("edit")
        if audio_media:
            audio_track = timeline.GetTrackCount("audio") + 1
            if not timeline.AddTrack("audio", "stereo"):
                raise RuntimeError("No se pudo añadir una pista de audio.")
            timeline.SetTrackName("audio", audio_track, "FlowLyrics MP3")
            audio_clips = pool.AppendToTimeline([{"mediaPoolItem": audio_media[0], "mediaType": 2, "trackIndex": audio_track, "recordFrame": base_frame}])
            if not audio_clips:
                raise RuntimeError("No se pudo colocar el MP3.")
            created.extend(audio_clips)
    except Exception:
        if created:
            timeline.DeleteClips(created, False)
        if audio_track:
            timeline.DeleteTrack("audio", audio_track)
        if timeline.GetTrackCount("video") >= video_track:
            timeline.DeleteTrack("video", video_track)
        raise
    finally:
        timeline.SetCurrentTimecode(original_timecode)
    return {"clips": 1, "phrases": len(phrases), "fps": fps, "start_timecode": original_timecode, "duration_seconds": duration, "item": item}


def current_lyrics(project):
    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise ValueError("Abre una cronología.")
    fps = float(timeline.GetSetting("timelineFrameRate") or 24)
    position = timecode_to_frames(timeline.GetCurrentTimecode(), fps)
    for track in range(timeline.GetTrackCount("video"), 0, -1):
        for item in timeline.GetItemListInTrack("video", track) or []:
            if item.GetStart() <= position < item.GetEnd():
                comp = item.GetFusionCompByIndex(1)
                if comp and str(comp.GetData("FlowLyrics.Version") or "").startswith(("0.2.", "0.3.")):
                    return item, comp, fps
    raise ValueError("Coloca el cabezal sobre una composición FlowLyrics 0.2.")


def read_current_phrases(comp):
    saved = json.loads(comp.GetData("FlowLyrics.Phrases"))
    if str(comp.GetData("FlowLyrics.Version") or "").startswith("0.3."):
        return [LyricPhrase(**row) for row in saved]
    phrases = []
    for i, row in enumerate(saved):
        tool = comp.FindTool(f"Lyric_{i+1:03d}")
        phrases.append(LyricPhrase(float(tool.GetInput("StartSeconds")), float(tool.GetInput("EndSeconds")), str(tool.GetInput("StyledText"))))
    return phrases


def _result_label(row: dict[str, Any]) -> str:
    duration = float(row.get("duration") or 0)
    minutes = int(duration // 60)
    seconds = int(round(duration - minutes * 60))
    sync = "SYNC" if row.get("syncedLyrics") else "SIN SYNC"
    return f"{row.get('trackName', 'Sin título')} — {row.get('artistName', 'Artista desconocido')}  |  {minutes}:{seconds:02d}  |  {sync}"


def launch_ui(resolve_object: Any, project_object: Any, fusion_object: Any, bmd_module: Any) -> None:
    ui = fusion_object.UIManager
    dispatcher = bmd_module.UIDispatcher(ui)
    existing = ui.FindWindow(WINDOW_ID)
    if existing:
        existing.Show()
        existing.Raise()
        return

    style_sheet = """
        QWidget { background: #111318; color: #F4F5F7; font-family: 'Helvetica Neue'; }
        QLabel#Title { color: #FFFFFF; font-size: 24px; font-weight: 700; }
        QLabel#Kicker { color: #60E6C7; font-size: 11px; font-weight: 700; }
        QLabel#HelpIntro, QLabel#HelpTrack { color: #A9AFBA; font-size: 11px; }
        QLabel#Status { color: #60E6C7; font-size: 11px; }
        QLineEdit, QComboBox, QSpinBox, QTextEdit {
            background: #1B1F27; border: 1px solid #303642; border-radius: 7px;
            padding: 7px; selection-background-color: #31BFA0;
        }
        QPushButton { background: #262C36; border: 1px solid #3A4350; border-radius: 8px; padding: 8px 13px; }
        QPushButton:hover { background: #303845; }
        QPushButton#CreateButton { background: #52D7B7; color: #0E1715; font-weight: 700; border: 0; }
        QCheckBox { spacing: 8px; }
    """

    win = dispatcher.AddWindow(
        {
            "ID": WINDOW_ID,
            "Geometry": [180, 50, 860, 850],
            "WindowTitle": f"{PLUGIN_NAME} {PLUGIN_VERSION}",
            "StyleSheet": style_sheet,
        },
        ui.VGroup(
            {"Spacing": 10, "ContentsMargins": [18, 16, 18, 16]},
            [
                ui.Label({"ID": "Kicker", "Text": "LYRICS PARA REELS | FUSION NATIVO", "Weight": 0}),
                ui.Label({"ID": "Title", "Text": "FlowLyrics", "Weight": 0}),
                ui.Label(
                    {
                        "ID": "HelpIntro",
                        "Text": "Busca una canción o importa un .srt. Genera líneas que suben y se desvanecen en los bordes.",
                        "WordWrap": True,
                        "Weight": 0,
                    }
                ),
                ui.HGroup(
                    {"Weight": 0, "Spacing": 8},
                    [
                        ui.LineEdit(
                            {
                                "ID": "SearchInput",
                                "PlaceholderText": "Canción y artista…",
                                "ClearButtonEnabled": True,
                                "Weight": 1,
                            }
                        ),
                        ui.Button({"ID": "SearchButton", "Text": "Buscar", "Weight": 0}),
                    ],
                ),
                ui.HGroup(
                    {"Weight": 0, "Spacing": 8},
                    [
                        ui.ComboBox({"ID": "Results", "Weight": 1, "MaxVisibleItems": 40}),
                        ui.Button({"ID": "LoadButton", "Text": "Cargar", "Weight": 0}),
                    ],
                ),
                ui.HGroup({"Weight": 0}, [
                    ui.Button({"ID": "YouTubeSearch", "Text": "Buscar audio en YouTube"}),
                    ui.ComboBox({"ID": "YouTubeResults", "Weight": 1}),
                    ui.Button({"ID": "Download", "Text": "Descargar MP3"}),
                ]),
                ui.HGroup({"Weight": 0}, [
                    ui.LineEdit({"ID": "AudioPath", "PlaceholderText": "MP3 descargado o archivo de audio local", "Weight": 1}),
                    ui.Button({"ID": "Browse", "Text": "Archivo…"}),
                    ui.CheckBox({"ID": "LyricsOnly", "Text": "Solo letra", "Checked": False}),
                ]),
                ui.HGroup({"Weight": 0}, [
                    ui.Button({"ID": "ImportSRT", "Text": "Importar .srt…"}),
                    ui.Button({"ID": "ReadCurrent", "Text": "Leer letra del cabezal"}),
                    ui.Button({"ID": "UpdateCurrent", "Text": "Actualizar texto y tiempos"}),
                    ui.Label({"Text": "Inicio --> fin y texto editables", "Weight": 1}),
                ]),
                ui.HGroup({"Weight": 0}, [
                    ui.CheckBox({"ID": "AutoAlign", "Text": "Alinear con audio al crear", "Checked": True}),
                    ui.ComboBox({"ID": "Language"}),
                    ui.Button({"ID": "AlignAudio", "Text": "Sincronizar palabras"}),
                ]),
                ui.TextEdit(
                    {
                        "ID": "Preview",
                        "ReadOnly": False,
                        "AcceptRichText": False,
                        "PlaceholderText": "Edita inicio, fin y texto: MM:SS.ss --> MM:SS.ss texto",
                        "Weight": 1,
                    }
                ),
                ui.HGroup(
                    {"Weight": 0, "Spacing": 10},
                    [
                        ui.VGroup(
                            {"Weight": 1},
                            [
                                ui.Label({"Text": "Modo", "Weight": 0}),
                                ui.ComboBox({"ID": "Mode", "Weight": 0}),
                            ],
                        ),
                        ui.VGroup(
                            {"Weight": 1},
                            [
                                ui.Label({"Text": "Distribución", "Weight": 0}),
                                ui.ComboBox({"ID": "Layout", "Weight": 0}),
                            ],
                        ),
                    ],
                ),
                ui.HGroup(
                    {"Weight": 0, "Spacing": 10},
                    [
                        ui.VGroup(
                            {"Weight": 1},
                            [
                                ui.Label({"Text": "Palabras por frase", "Weight": 0}),
                                ui.ComboBox({"ID": "Words", "Weight": 0}),
                            ],
                        ),
                        ui.VGroup(
                            {"Weight": 1},
                            [
                                ui.Label({"Text": "Tamaño", "Weight": 0}),
                                ui.SpinBox({"ID": "Size", "Minimum": 3, "Maximum": 10, "Value": 6, "Suffix": "%", "Weight": 0}),
                            ],
                        ),
                        ui.VGroup(
                            {"Weight": 1},
                            [
                                ui.Label({"Text": "Separación de líneas", "Weight": 0}),
                                ui.SpinBox({"ID": "Drift", "Minimum": 1, "Maximum": 18, "Value": 8, "Suffix": "%", "Weight": 0}),
                            ],
                        ),
                        ui.VGroup(
                            {"Weight": 1},
                            [
                                ui.Label({"Text": "Desfase", "Weight": 0}),
                                ui.LineEdit({"ID": "Offset", "Text": "0.00", "PlaceholderText": "segundos", "Weight": 0}),
                            ],
                        ),
                    ],
                ),
                ui.HGroup(
                    {"Weight": 0, "Spacing": 10},
                    [
                        ui.VGroup(
                            {"Weight": 2},
                            [
                                ui.Label({"Text": "Fuente", "Weight": 0}),
                                ui.LineEdit({"ID": "Font", "Text": "Montserrat", "PlaceholderText": "p. ej. Montserrat", "Weight": 0}),
                            ],
                        ),
                        ui.VGroup(
                            {"Weight": 2},
                            [
                                ui.Label({"Text": "Estilo", "Weight": 0}),
                                ui.LineEdit({"ID": "FontStyle", "Text": "ExtraBold", "PlaceholderText": "p. ej. ExtraBold", "Weight": 0}),
                            ],
                        ),
                        ui.VGroup(
                            {"Weight": 1},
                            [
                                ui.Label({"Text": "Interlineado", "Weight": 0}),
                                ui.SpinBox({"ID": "LineSpacing", "Minimum": 30, "Maximum": 120, "Value": 65, "Suffix": "%", "Weight": 0}),
                            ],
                        ),
                    ],
                ),
                ui.HGroup(
                    {"Weight": 0, "Spacing": 12},
                    [
                        ui.CheckBox({"ID": "Uppercase", "Text": "Mayúsculas", "Checked": False, "Weight": 0}),
                        ui.Label(
                            {
                                "ID": "HelpTrack",
                                "Text": "Alineación local con audio. Desfase corrige el inicio global; edita tiempos para ajustes de cada palabra.",
                                "WordWrap": True,
                                "Weight": 1,
                            }
                        ),
                    ],
                ),
                ui.HGroup(
                    {"Weight": 0, "Spacing": 8},
                    [
                        ui.Label({"ID": "Status", "Text": "Listo para buscar.", "Weight": 1}),
                        ui.Button({"ID": "CreateButton", "Text": "Crear letra y MP3", "Weight": 0}),
                    ],
                ),
            ],
        ),
    )

    state: dict[str, Any] = {"results": [], "phrases": []}
    words_combo = win.Find("Words")
    words_combo.AddItems([str(n) for n in range(1, 13)])
    words_combo.CurrentIndex = 0
    win.Find("Language").AddItems(["Idioma automático", "Español", "Inglés"])
    mode_combo = win.Find("Mode")
    mode_combo.AddItems(["Palabras por línea", "Líneas originales completas"])
    mode_combo.CurrentIndex = 0
    layout_combo = win.Find("Layout")
    layout_combo.AddItems(["Libre (punto)", "Cuadro de texto centrado"])
    layout_combo.CurrentIndex = 0

    def set_status(message: str, error: bool = False) -> None:
        label = win.Find("Status")
        label.Text = message
        label.StyleSheet = "color: #FF7B86;" if error else "color: #60E6C7;"

    def load_selection() -> None:
        if state.get("srt_phrases"):
            cues = state["srt_phrases"]
            phrases = cues if win.Find("Mode").CurrentIndex == 1 else lines_to_phrases([LyricLine(p.start,p.end,p.text) for p in cues], int(win.Find("Words").CurrentText or "3"))
            state["source_lines"] = cues
            state["phrases"] = phrases
            state.pop("aligned_signature", None)
            state["loaded_preview"] = format_preview(phrases)
            win.Find("Preview").PlainText = format_preview(phrases)
            set_status(f"SRT: {len(phrases)} frases. Dividir una frase estima los tiempos; alinea con audio para medirlos.")
            return
        rows = state["results"]
        if not rows:
            return
        index = max(0, win.Find("Results").CurrentIndex)
        row = rows[index]
        synced = row.get("syncedLyrics")
        if not synced:
            raise ValueError("Ese resultado no tiene tiempos sincronizados. Elige uno marcado SYNC.")
        preferred = int(win.Find("Words").CurrentText or "3")
        rate = 5.0
        lines = parse_lrc(synced)
        if win.Find("Mode").CurrentIndex == 1:
            phrases = [
                LyricPhrase(
                    start=line.start,
                    end=line.end,
                    text=line.text,
                )
                for line in lines
            ]
        else:
            phrases = lines_to_phrases(lines, preferred, rate=rate)
        state["source_lines"] = lines
        state.pop("aligned_signature", None)
        changed_song = state.get("selected_song", {}).get("id") != row.get("id")
        state["selected_song"] = row
        state["phrases"] = phrases
        if changed_song:
            win.Find("AudioPath").Text = ""
            state["youtube"] = []
            win.Find("YouTubeResults").Clear()
        win.Find("Preview").PlainText = format_preview(phrases)
        state["loaded_preview"] = format_preview(phrases)
        set_status(f"{len(phrases)} frases | tiempos estimados: pulsa Sincronizar palabras con el audio.")

    def perform_task(message, operation, completion):
        if state.get("busy"):
            set_status("Espera a que termine la operación actual.")
            return
        state["busy"] = True
        set_status(message)
        try:
            result = operation()
        except Exception as exc:
            state["busy"] = False
            set_status(str(exc), True)
            return
        state["busy"] = False
        try:
            completion(result)
        except Exception as exc:
            set_status(str(exc), True)

    def on_search(_event):
        query = win.Find("SearchInput").Text
        def complete(rows):
            state.pop("srt_phrases", None)
            state["results"] = rows
            combo = win.Find("Results")
            combo.Clear()
            combo.AddItems([_result_label(row) for row in rows])
            if not rows:
                raise ValueError("No encontré letras. Prueba con título y artista.")
            combo.CurrentIndex = 0
            load_selection()
            on_youtube(None)
        perform_task("Buscando letras sincronizadas…", lambda: search_lrclib(query), complete)

    def on_load(_event: Any) -> None:
        try:
            load_selection()
        except Exception as exc:
            set_status(str(exc), True)

    def alignment_signature():
        path = (win.Find("AudioPath").Text or "").strip()
        stat = Path(path).stat() if Path(path).is_file() else None
        return (path, stat.st_mtime_ns if stat else None, win.Find("Preview").PlainText,
                win.Find("Words").CurrentIndex, win.Find("Language").CurrentIndex)

    def on_align(_event=None, create_after=False):
        if state.get("busy"):
            return
        try:
            preview = win.Find("Preview").PlainText
            phrases = parse_preview(preview)
            if not phrases:
                raise ValueError("Carga primero la letra.")
            source = state.get("source_lines") if preview == state.get("loaded_preview") else phrases
            path = (win.Find("AudioPath").Text or "").strip()
            if not Path(path).is_file():
                raise ValueError("Descarga el MP3 o selecciona el audio antes de sincronizar.")
            language = [None, "es", "en"][win.Find("Language").CurrentIndex]
            preferred = int(win.Find("Words").CurrentText or "1")
            state["busy"] = True
            set_status("Alineando palabras con audio. Espera varios minutos hasta que termine…")
            payload = align_audio(path, source or phrases, language)
            state["phrases"] = aligned_phrases(payload, preferred)
            win.Find("Preview").PlainText = format_preview(state["phrases"])
            state["aligned_signature"] = alignment_signature()
            set_status(f"{len(state['phrases'])} bloques alineados con audio. Revisa las palabras cantadas.")
        except Exception as exc:
            set_status("No se pudo medir: " + str(exc) + " Desmarca Alinear para usar tiempos estimados.", True)
            create_after = False
        finally:
            state["busy"] = False
        if create_after:
            on_create(None)

    def on_create(_event: Any) -> None:
        if state.get("busy"):
            set_status("Espera a que termine la descarga o la búsqueda.")
            return
        try:
            edited = win.Find("Preview").PlainText
            if edited.strip():
                state["phrases"] = parse_preview(edited)
            if not state["phrases"]:
                raise ValueError("El texto está vacío: no hay frases para crear.")
            offset = float((win.Find("Offset").Text or "0").replace(",", "."))
            options = StyleOptions(
                font=(win.Find("Font").Text or "Montserrat").strip() or "Montserrat",
                font_style=(win.Find("FontStyle").Text or "ExtraBold").strip() or "ExtraBold",
                size=win.Find("Size").Value / 100.0,
                drift=win.Find("Drift").Value / 100.0,
                line_spacing=win.Find("LineSpacing").Value / 100.0,
                layout_frame=win.Find("Layout").CurrentIndex == 1,
                uppercase=bool(win.Find("Uppercase").Checked),
            )
            set_status("Construyendo composiciones Fusion…")
            audio_path = (win.Find("AudioPath").Text or "").strip()
            if not audio_path and not win.Find("LyricsOnly").Checked:
                rows = state.get("youtube", [])
                if not rows:
                    raise ValueError("Busca y selecciona el audio de YouTube o elige un archivo.")
                url = rows[max(0, win.Find("YouTubeResults").CurrentIndex)]["url"]
                def complete(path):
                    win.Find("AudioPath").Text = path
                    on_create(None)
                perform_task("Descargando el MP3 seleccionado…", lambda: download_mp3(url), complete)
                return
            if audio_path and win.Find("AutoAlign").Checked and state.get("aligned_signature") != alignment_signature():
                on_align(create_after=True)
                return
            summary = create_flowlyrics(resolve_object, project_object, state["phrases"], options, offset, audio_path)
            resolve_object.GetProjectManager().SaveProject()
            set_status(
                f"Hecho: {summary['phrases']} frases en {summary['clips']} bloques | inicio {summary['start_timecode']}"
            )
        except Exception as exc:
            set_status(str(exc), True)

    def on_youtube(_event):
        song = state.get("selected_song", {})
        title = re.sub(r"\([^)]*(?:video|vídeo)[^)]*\)", "", song.get("trackName", ""), flags=re.I).strip()
        query = " ".join([song.get("artistName", ""), title]).strip() or win.Find("SearchInput").Text
        def complete(rows):
            win.Find("AudioPath").Text = ""
            state["youtube"] = rows
            combo = win.Find("YouTubeResults")
            combo.Clear()
            combo.AddItems([f"{r['title']} | {r['channel']} | {r.get('duration') or '?'} s" for r in rows])
            if not rows:
                raise ValueError("No encontré una versión de audio compatible. Elige un archivo de la misma versión que la letra.")
            combo.CurrentIndex = 0
            set_status("Versiones de audio filtradas por duración. Revisa que coincidan con la letra antes de Crear.")
        perform_task("Buscando audio en YouTube…", lambda: search_youtube(query, song.get("duration")), complete)

    def on_download(_event):
        rows = state.get("youtube", [])
        if not rows:
            set_status("Busca primero el audio en YouTube.", True)
            return
        url = rows[max(0, win.Find("YouTubeResults").CurrentIndex)]["url"]
        def complete(path):
            win.Find("AudioPath").Text = path
            set_status("MP3 preparado. Revisa texto y tiempos y pulsa Crear.")
        perform_task("Descargando y convirtiendo a MP3…", lambda: download_mp3(url), complete)

    def on_browse(_event):
        path = fusion_object.RequestFile()
        if path:
            win.Find("AudioPath").Text = path

    def on_import_srt(_event):
        try:
            path = fusion_object.RequestFile()
            if not path:
                return
            cues = load_srt(path)
            state["srt_phrases"] = cues
            state["results"] = []
            state.pop("selected_song", None)
            state["youtube"] = []
            win.Find("Results").Clear()
            win.Find("YouTubeResults").Clear()
            win.Find("AudioPath").Text = ""
            win.Find("LyricsOnly").Checked = True
            win.Find("Mode").CurrentIndex = 1
            load_selection()
            set_status(f"{Path(path).name}: {len(cues)} subtítulos importados. Revisa y pulsa Crear.")
        except Exception as exc:
            set_status(str(exc), True)

    def on_read(_event):
        try:
            item, comp, fps = current_lyrics(project_object)
            win.Find("Preview").PlainText = format_preview(read_current_phrases(comp))
            set_status("Letra cargada del cabezal. Puedes editar texto, inicio y fin.")
        except Exception as exc:
            set_status(str(exc), True)

    def on_update(_event):
        try:
            item, comp, fps = current_lyrics(project_object)
            phrases = parse_preview(win.Find("Preview").PlainText)
            if not phrases:
                raise ValueError("No hay frases.")
            if max(p.end for p in phrases) * fps > item.GetDuration():
                raise ValueError("El fin supera el clip: alarga el clip en la cronología antes de actualizar.")
            style = StyleOptions(**json.loads(comp.GetData("FlowLyrics.Style")))
            populate_composition(item, phrases, 0, fps, style)
            resolve_object.OpenPage("fusion")
            resolve_object.OpenPage("edit")
            resolve_object.GetProjectManager().SaveProject()
            set_status("Texto y tiempos actualizados en la composición del cabezal.")
        except Exception as exc:
            set_status(str(exc), True)

    def on_close(_event: Any) -> None:
        dispatcher.ExitLoop()

    win.On["AlignAudio"].Clicked = on_align
    win.On["YouTubeResults"].CurrentIndexChanged = lambda event: setattr(win.Find("AudioPath"), "Text", "")
    win.On["YouTubeSearch"].Clicked = on_youtube
    win.On["Download"].Clicked = on_download
    win.On["Browse"].Clicked = on_browse
    win.On["ImportSRT"].Clicked = on_import_srt
    win.On["ReadCurrent"].Clicked = on_read
    win.On["UpdateCurrent"].Clicked = on_update
    win.On["Words"].CurrentIndexChanged = on_load
    win.On["SearchButton"].Clicked = on_search
    win.On["LoadButton"].Clicked = on_load
    win.On["Mode"].CurrentIndexChanged = on_load
    win.On["CreateButton"].Clicked = on_create
    win.On[WINDOW_ID].Close = on_close
    win.Show()
    dispatcher.RunLoop()


if globals().get("FLOWLYRICS_AUTORUN", True) and (
    __name__ == "__main__" or globals().get("resolve") is not None
):
    if not all(name in globals() for name in ("resolve", "project", "fusion", "bmd")):
        import sys
        sys.path.insert(0, "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules")
        import DaVinciResolveScript as bmd
        resolve = bmd.scriptapp("Resolve")
        if resolve is None:
            raise RuntimeError("No se pudo conectar con DaVinci Resolve.")
        project = resolve.GetProjectManager().GetCurrentProject()
        fusion = resolve.Fusion()
    launch_ui(resolve, project, fusion, bmd)
