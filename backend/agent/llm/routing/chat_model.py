from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field


class RoutedChatModel(BaseChatModel):
    """LangChain facade over Vellum's provider-neutral routing engine."""

    engine: Any = Field(exclude=True)
    primary_model_resolver: Callable[[], str] = Field(exclude=True)
    temperature: float = 0.3
    max_tokens: int = 2048
    bound_tools: tuple[Any, ...] = ()
    tool_binding_kwargs: dict[str, Any] = Field(default_factory=dict)

    @property
    def _llm_type(self) -> str:
        return "vellum-routed-chat"

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ):
        binding_kwargs = dict(kwargs)
        if tool_choice is not None:
            binding_kwargs["tool_choice"] = tool_choice
        return self.model_copy(
            update={
                "bound_tools": tuple(tools),
                "tool_binding_kwargs": binding_kwargs,
            },
            deep=False,
        )

    async def ainvoke(
        self,
        input: Any,
        config: Mapping[str, Any] | None = None,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> AIMessage:
        invoke_kwargs = dict(kwargs)
        configurable = config.get("configurable", {}) if config is not None else {}
        thread_id = configurable.get("thread_id") if isinstance(configurable, Mapping) else None
        if thread_id and "thread_id" not in invoke_kwargs:
            invoke_kwargs["thread_id"] = str(thread_id)
        return await super().ainvoke(
            input, config=config, stop=stop, **invoke_kwargs
        )

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs: Any,
    ) -> ChatResult:
        del run_manager
        invoke_kwargs = dict(self.tool_binding_kwargs)
        invoke_kwargs.update(kwargs)
        if stop is not None:
            invoke_kwargs["stop"] = stop
        message = await self.engine.ainvoke(
            messages=messages,
            primary_model=self.primary_model_resolver(),
            tools=self.bound_tools,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            **invoke_kwargs,
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs: Any,
    ) -> ChatResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self._agenerate(
                    messages,
                    stop=stop,
                    run_manager=run_manager,
                    **kwargs,
                )
            )
        raise RuntimeError("synchronous routed chat cannot run inside an active event loop")

    async def astream(
        self,
        input: Any,
        config: Mapping[str, Any] | None = None,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[AIMessageChunk]:
        stream_kwargs = dict(kwargs)
        configurable = config.get("configurable", {}) if config is not None else {}
        thread_id = configurable.get("thread_id") if isinstance(configurable, Mapping) else None
        if thread_id and "thread_id" not in stream_kwargs:
            stream_kwargs["thread_id"] = str(thread_id)
        async for chunk in super().astream(
            input, config=config, stop=stop, **stream_kwargs
        ):
            yield chunk

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs: Any,
    ):
        del run_manager
        stream_kwargs = dict(self.tool_binding_kwargs)
        stream_kwargs.update(kwargs)
        if stop is not None:
            stream_kwargs["stop"] = stop
        async for chunk in self.engine.astream(
            messages=messages,
            primary_model=self.primary_model_resolver(),
            tools=self.bound_tools,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            **stream_kwargs,
        ):
            yield ChatGenerationChunk(message=chunk)
