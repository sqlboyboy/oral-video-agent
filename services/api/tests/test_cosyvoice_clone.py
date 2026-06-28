from pathlib import Path

import numpy as np

from tools.cosyvoice_clone import _collect_speech, _prepare_tts_text


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
