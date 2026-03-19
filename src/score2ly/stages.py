from enum import IntEnum, auto


class Stage(IntEnum):
    ORIGINAL   = 1
    PREPROCESS = auto()
    OMR        = auto()
    MUSICXML   = auto()
    LAYOUT     = auto()
    IMAGES     = auto()
    LILYPOND   = auto()
