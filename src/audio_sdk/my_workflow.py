import random
from collections.abc import AsyncIterator
from typing import Callable

from agents import Agent, Runner, TResponseInputItem, WebSearchTool
from agents.extensions.handoff_prompt import prompt_with_handoff_instructions
from agents.voice import VoiceWorkflowBase, VoiceWorkflowHelper

search_agent = Agent(
    name="Web searcher",
    instructions="You're a helpful Japaneseagent.",
    model="gpt-4o-mini",
    tools=[WebSearchTool(user_location="Japan")],
)

japanese_agent = Agent(
    name="Japanese Assistant",
    handoff_description="A japanese speaking agent.",
    instructions= (
        "You're speaking to a human, so be polite and concise. "
        "Speak in Japanese. You can use web search to find information.",
    ),
    model="gpt-4o-mini",
    tools=[
        search_agent.as_tool(
            tool_name="Web searcher",
            tool_description="A web searcher that can find information online.",
        )
    ],
)



class MyWorkflow(VoiceWorkflowBase):
    def __init__(self, on_start: Callable[[str], None], tts_output: Callable[[str], None]):
        """
        Args:
            on_start: A callback that is called when the workflow starts. The transcription
                is passed in as an argument.
        """
        self._input_history: list[TResponseInputItem] = []
        self._current_agent = agent
        self._on_start = on_start
        self._tts_output = tts_output

    async def run(self, transcription: str) -> AsyncIterator[str]:
        self._on_start(transcription)

        # Add the transcription to the input history
        self._input_history.append(
            {
                "role": "user",
                "content": transcription,
            }
        )
        # Otherwise, run the agent
        result = Runner.run_streamed(self._current_agent, self._input_history)
        full_response = ""
        async for chunk in VoiceWorkflowHelper.stream_text_from(result):
            full_response += chunk
            yield chunk
        self._tts_output(full_response)
        # Update the input history and current agent
        self._input_history = result.to_input_list()
        self._current_agent = result.last_agent