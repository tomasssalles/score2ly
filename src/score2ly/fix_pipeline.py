import logging
from collections.abc import Sequence
from pathlib import Path

from score2ly import convert_pipeline, metadata
from score2ly.pipeline_common import run_stage, StageParams, should_run, get_dependencies_to_outputs
from score2ly.settings import FixSettings, ConvertSettings

logger = logging.getLogger(__name__)


def _verify_convert_pipeline(stage_params: Sequence[StageParams[ConvertSettings]], output_dir: Path) -> None:
    logger.info("Verifying stages 1 to %d have been completed...", len(stage_params))

    stages_meta = metadata.get_stages(output_dir)

    null_logger = logging.getLogger("_verify_convert_pipeline_null_logger")
    null_logger.setLevel(logging.CRITICAL + 1)

    for stage_idx, params in enumerate(stage_params, start=1):
        stage_meta = stages_meta.get(params.stage)
        dependencies_to_outputs = get_dependencies_to_outputs(stage_idx, params.dependencies, stages_meta)

        if should_run(stage_idx, params.dependencies, stage_meta, output_dir, dependencies_to_outputs, null_logger):
            raise RuntimeError(
                f"Stage {stage_idx} from the conversion pipeline is not done. Complete the conversion stages first with"
                f" 'score2ly update path/to/bundle.s2l' or run them from scratch with 'score2ly new path/to/score.pdf'."
            )

    logger.info("First %d stages (conversion) are already done. Moving on.", len(stage_params))


def run(output_dir: Path, settings: FixSettings) -> None:
    conv_pipeline_stage_params = convert_pipeline.get_stage_params(None, None)
    _verify_convert_pipeline(conv_pipeline_stage_params, output_dir)

    stage_params: Sequence[StageParams[FixSettings]] = ()

    for stage_idx, params in enumerate(stage_params, start=len(conv_pipeline_stage_params) + 1):
        run_stage(params, output_dir, settings, stage_idx, logger)

    logger.info("Fixing pipeline finished successfully.")
