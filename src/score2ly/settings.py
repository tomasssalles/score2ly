from dataclasses import dataclass
from typing import Literal

from score2ly.image_processing import (
    BlockMethod,
    SheetMethod,
    DEFAULT_SHEET_METHOD,
    DEFAULT_BLOCK_METHOD,
    DEFAULT_PROJECTION_K,
)


@dataclass
class ConvertSettings:
    # PDF type
    pdf_kind: Literal["auto", "vector", "scan"] = "auto"
    preprocess_images: bool = False

    # Image preprocessing (for scans)
    sheet_method: SheetMethod = DEFAULT_SHEET_METHOD
    block_method: BlockMethod = DEFAULT_BLOCK_METHOD
    deskew: bool = False
    tight_crop: bool = False
    clahe: bool = False
    projection_k: float = DEFAULT_PROJECTION_K
    projection_denoise: bool = False