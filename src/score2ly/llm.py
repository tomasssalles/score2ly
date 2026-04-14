import logging
from typing import TypeVar

import instructor
import litellm
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True

T = TypeVar("T", bound=BaseModel)


def complete(
    model: str,
    api_key: str,
    messages: list[ChatCompletionMessageParam],
    response_model: type[T],
    max_retries: int,
) -> T:
    # model: LiteLLM provider/model string, e.g. "anthropic/claude-opus-4-6"
    # See https://docs.litellm.ai/docs/providers for the full list.
    client = instructor.from_litellm(litellm.completion)
    return client.chat.completions.create(
        model=model,
        api_key=api_key,
        messages=messages,
        response_model=response_model,
        max_retries=max_retries,
    )