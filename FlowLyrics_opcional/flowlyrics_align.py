"""Local word alignment worker. Audio stays on this computer."""
import json
import os
import sys
from pathlib import Path


def main(request_path, output_path):
    os.environ['PATH'] = '/opt/homebrew/bin:/usr/local/bin:' + os.environ.get('PATH', '')
    import torch
    import stable_whisper
    import whisper
    torch.set_num_threads(4)
    request = json.loads(Path(request_path).read_text(encoding='utf-8'))
    model = stable_whisper.load_model(request.get('model', 'large-v3'), device='cpu',
                                    download_root=request['models'])
    language = request.get('language')
    if not language:
        audio = whisper.load_audio(request['audio'])
        start = max(0, int(request['segments'][0]['start'] * 16000))
        mel = whisper.log_mel_spectrogram(whisper.pad_or_trim(audio[start:start + 480000]),
                                        n_mels=model.dims.n_mels)
        _, probabilities = model.detect_language(mel)
        language = max(probabilities, key=probabilities.get)
    result = model.align_words(request['audio'], request['segments'], language=language,
                               regroup=False, verbose=None, min_word_dur=0.02)
    if result is None:
        raise RuntimeError('No se pudo alinear esta letra con el audio.')
    payload = result.to_dict()
    payload['language'] = language
    Path(output_path).write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main(*sys.argv[1:])
