from pathlib import Path
import wave

import numpy as np

from tools.cosyvoice_clone import (
    COSYVOICE_REFERENCE_MAX_SECONDS,
    _collect_speech,
    _extract_reference_wav,
    _prepare_tts_text,
)


class FakeTensor:
    def __init__(self, values):
        self.values = np.asarray(values, dtype=np.float32)

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.values


def test_prepare_tts_text_preserves_words_and_adds_only_line_pauses():
    assert _prepare_tts_text("第一句话\n第二句话\n第三句话") == "第一句话，第二句话，第三句话"


def test_collect_speech_concatenates_all_cosyvoice_output_chunks():
    outputs = [
        {"tts_speech": FakeTensor([0.1, 0.2])},
        {"tts_speech": FakeTensor([0.3])},
        {"tts_speech": FakeTensor([0.4, 0.5])},
    ]

    speech = _collect_speech(iter(outputs))

    assert np.allclose(speech, [0.1, 0.2, 0.3, 0.4, 0.5])


def test_extract_reference_wav_limits_prompt_to_under_thirty_seconds(tmp_path):
    sample_rate = 16000
    source = tmp_path / "long-reference.wav"
    with wave.open(str(source), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\0\0" * sample_rate * 31)

    output = _extract_reference_wav(source, tmp_path / "prepared")

    with wave.open(str(output), "rb") as wav_file:
        assert wav_file.getframerate() == sample_rate
        assert wav_file.getnchannels() == 1
        assert (
            wav_file.getnframes()
            <= sample_rate * COSYVOICE_REFERENCE_MAX_SECONDS
        )
