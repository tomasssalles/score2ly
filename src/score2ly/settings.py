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
    on_omr_failure: Literal["abort", "skip-page", "ask"] = "abort"

    # Image preprocessing (for scans)
    sheet_method: SheetMethod = DEFAULT_SHEET_METHOD
    block_method: BlockMethod = DEFAULT_BLOCK_METHOD
    deskew: bool = False
    tight_crop: bool = False
    clahe: bool = False
    projection_k: float = DEFAULT_PROJECTION_K
    projection_denoise: bool = False

    # Score info (CLI overrides for interactive prompts)
    title: str = ""
    subtitle: str = ""
    composer: str = ""
    work_number: str = ""
    copyright: str = ""
    tagline: str = ""
    no_prompt: bool = False

    def preprocessing_is_noop(self) -> bool:
        return (
            self.sheet_method is SheetMethod.NONE
            and self.block_method is BlockMethod.NONE
            and not self.deskew
            and not self.tight_crop
            and not self.clahe
        )