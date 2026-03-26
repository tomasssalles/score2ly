from enum import Enum


class Stage(Enum):
    ORIGINAL      = "original"
    PREPROCESS    = "preprocess"
    OMR           = "omr"
    MUSICXML      = "musicxml"
    CLEAN_XML     = "clean_xml"
    LAYOUT        = "layout"
    IMAGES        = "images"
    XML_SNIPPETS  = "xml_snippets"
    LY_SNIPPETS   = "ly_snippets"
    LY_MERGE      = "ly_merge"
