import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import replace
from pathlib import Path

from score2ly import convert_pipeline, metadata
from score2ly.exceptions import PipelineError
from score2ly.pipeline_common import run_stage, StageParams, should_run, get_dependencies_to_outputs
from score2ly.settings import FixSettings, ConvertSettings
from score2ly.stages import Stage
from score2ly.utils import APIKey

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
            raise PipelineError(
                f"Stage {stage_idx} from the conversion pipeline is not done. Complete the conversion stages first with"
                f" 'score2ly update path/to/bundle.s2l' or run them from scratch with 'score2ly new path/to/score.pdf'."
            )

    logger.info("First %d stages (conversion) are already done. Moving on.", len(stage_params))


def _collect_llm_params(settings: FixSettings) -> FixSettings:
    model = settings.model
    if not model:
        while True:
            model = input("Model (e.g. gemini/gemini-2.5-flash): ").strip()

            if any(s in model.lower() for s in ("grok", "xai", "x-ai")):
                logger.warning("Sorry, xAI models are not supported.")
            else:
                break

    api_key = settings.api_key or APIKey(input("API key: ").strip())
    return replace(settings, model=model, api_key=api_key)


def run(output_dir: Path, settings: FixSettings) -> None:
    conv_pipeline_stage_params = convert_pipeline.get_stage_params(None, None)
    _verify_convert_pipeline(conv_pipeline_stage_params, output_dir)

    settings = _collect_llm_params(settings)

    stage_params: Sequence[StageParams[FixSettings]] = (
        StageParams(
            stage=Stage.LLM_PLAN,
            description="Plan LLM-assisted fixes for the full score (dummy)",
            output_dir_name="llm_plan",
            dependencies=(),
            fn=_llm_plan,
        ),
    )

    for stage_idx, params in enumerate(stage_params, start=len(conv_pipeline_stage_params) + 1):
        run_stage(params, output_dir, settings, stage_idx, logger)

    logger.info("Fixing pipeline finished successfully.")


def _llm_plan(
    stage_output_dir: Path,
    settings: FixSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    if not settings.model:
        raise PipelineError(f"Stage {stage_idx}: No model specified.")
    if not settings.api_key:
        raise PipelineError(f"Stage {stage_idx}: No API key provided.")
    logger.info("Stage %d: LLM planning (dummy)...", stage_idx)
    dest = stage_output_dir / "plan.json"
    dest.write_text(json.dumps({"status": "dummy"}, indent=2))
    yield dest
