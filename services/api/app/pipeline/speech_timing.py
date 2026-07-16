from dataclasses import dataclass


@dataclass(frozen=True)
class TimedSpeechToken:
    """A spoken token with timestamps from the final voice track."""

    start: float
    end: float
    text: str
