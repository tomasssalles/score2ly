from dataclasses import dataclass

from score2ly.image_processing import BlockMethod, SheetMethod
from score2ly.pdf import PdfKind


@dataclass(frozen=True, slots=True)
class ConvertSettings:
    # PDF type
    pdf_kind: PdfKind = PdfKind.AUTO

    # Image preprocessing (for scans)
    sheet_method: SheetMethod = SheetMethod.NONE
    block_method: BlockMethod = BlockMethod.NONE
    deskew: bool = False
    tight_crop: bool = False
    clahe: bool = False
    projection_k: float = 1.5
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