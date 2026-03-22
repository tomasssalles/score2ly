from enum import Enum


class Stage(Enum):
    ORIGINAL   = "original"
    PREPROCESS = "preprocess"
    OMR        = "omr"
    MUSICXML   = "musicxml"
    LAYOUT     = "layout"
    IMAGES     = "images"
    LILYPOND   = "lilypond"
    RENDER     = "render"
