from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from typing import Callable

from agents import (Agent, GuardrailFunctionOutput,
                    InputGuardrailTripwireTriggered, RunContextWrapper, Runner,
                    TResponseInputItem, function_tool, input_guardrail, trace)
from agents.mcp import MCPServerStdio
from agents.voice import VoiceWorkflowBase, VoiceWorkflowHelper
from config import JA_RECOMMENDED_PROMPT_PREFIX, MODEL, CallCenterAgentContext
from pydantic import BaseModel, Field

# コールセンターマニュアルの読み込み

try:
    with open("data/call_center_manual.txt", "r", encoding="utf-8") as f:
        CALL_CENTER_MANUAL = f.read()
except FileNotFoundError:
    CALL_CENTER_MANUAL = "コールセンターマニュアルが見つかりません。"

# TOOLS

@function_tool
async def update_customer_info(
    context: RunContextWrapper[CallCenterAgentContext], customer_name: str, question_type: str
) -> None:
    """
    Update the customer information.

    Args:
        customer_name: The name of the customer.
        question_type: The type of question being asked.
    """
    # Update the context based on the customer's input
    context.context.customer_name = customer_name
    context.context.question_type = question_type

# Guardrails

class AbnormalOutput(BaseModel):
    reasoning: str | None = Field(
        default=None, description="異常な質問かどうかの理由"
    )
    is_abnormal: bool = Field(default=False, description="異常な質問かどうか")

guardrail_agent = Agent(
    name="Guardrail check",
    instructions=(
        "カスタマーがコールセンターにしないような質問をしているかどうかを確認してください。"
        "例えば、「あなたの好きな色は何ですか？」や「あなたの趣味は何ですか？」などの質問は、コールセンターにするべきではありません。"
        "他にも「210たす4は？」といった計算問題や、「今日の経済ニュースは？」といった一般的な雑談もコールセンターにするべきではありません。"
        "このような質問を見つけたら、is_abnormalをTrueにしてください。"
    ),
    output_type=AbnormalOutput,
    model=MODEL,
)

@input_guardrail
async def abnormal_guardrail(
    context: RunContextWrapper[None], agent: Agent, input: str | list[TResponseInputItem]
) -> GuardrailFunctionOutput:
    """This is an input guardrail function, which happens to call an agent to check if the input
    is a abnormal question.
    """
    result = await Runner.run(guardrail_agent, input, context=context.context)
    final_output = result.final_output_as(AbnormalOutput)

    return GuardrailFunctionOutput(
        output_info=final_output,
        tripwire_triggered=final_output.is_abnormal,
    )

# Voice Call Center Workflow
class VoiceCallCenterWorkflow(VoiceWorkflowBase):
    def __init__(self, on_start: Callable[[str], None], tts_output: Callable[[str], None], on_agent_change: Callable[[str], None] = None):
        """
        Args:
            on_start: A callback that is called when the workflow starts. The transcription
                is passed in as an argument.
            tts_output: A callback that is called when the TTS output is generated.
            on_agent_change: A callback that is called when the agent changes.
        """
        self._input_history: list[TResponseInputItem] = []
        self._context = CallCenterAgentContext()
        self._conversation_id = uuid.uuid4().hex[:16]
        self._on_start = on_start
        self._tts_output = tts_output
        self._on_agent_change = on_agent_change
        self._current_agent = None
        self._agents_initialized = False

    async def _initialize_agents(self):
        """MCPサーバーを初期化してエージェントを設定"""
        if self._agents_initialized:
            return

        try:
            # MCPサーバーの初期化
            self.file_mcp_server = MCPServerStdio(
                name="Filesystem Server, via npx",
                params={
                    "command": "npx",
                    "args": [
                        "-y", 
                        "@modelcontextprotocol/server-filesystem", 
                        "/Users/hoge/audio_sdk/data/products"
                    ]
                }
            )
            
            self.slack_mcp_server = MCPServerStdio(
                name="SSE Slack API Server",
                params={
                    "command": "npx",
                    "args": [
                        "-y", 
                        "@modelcontextprotocol/server-slack"
                    ],
                    "env": {
                        "SLACK_BOT_TOKEN": os.environ.get("SLACK_BOT_TOKEN"),
                        "SLACK_TEAM_ID": os.environ.get("SLACK_TEAM_ID"),
                        "SLACK_CHANNEL_IDS": os.environ.get("SLACK_CHANNEL_ID"),
                    }
                }
            )

            # MCPサーバーを開始
            await self.file_mcp_server.__aenter__()
            await self.slack_mcp_server.__aenter__()

            # エージェントの初期化
            self.error_trouble_agent = Agent[CallCenterAgentContext](
                name="エラー・トラブル・クレーム対応エージェント",
                handoff_description="エラー・トラブル・クレーム対応エージェントは、商品のエラーやトラブル、クレームに関する質問に対応できます。",
                instructions=f"""{JA_RECOMMENDED_PROMPT_PREFIX}
                あなたはエラー・トラブル・クレーム対応エージェントです。もし顧客と話している場合、あなたはおそらくトリアージエージェントから仕事を委譲されました。
                コールセンターマニュアルと、以下のルーチンに従って顧客の質問に対応してください。
                # ルーチン
                1. 顧客がどの商品の、どのようなエラーやトラブルについて質問しているかを確認します。クレームであれば、どのようなクレームかを確認し、マニュアルに従って対応してください。
                2. 特定の商品に関するものである場合、file_mcp_serverで提供されているディレクトリのファイルの中に、一致するテキストファイルがあるかどうかを確認します。
                3. ある場合、そのテキストファイルの中から、顧客の質問に答えられる情報を抽出し、回答してください。質問の内容が答えれらない場合は、「申し訳ありませんが、それついてはお答えできません。」と伝えます。
                4. サポートセンターの電話番号やメールアドレスが書かれている場合は、顧客にその情報を伝え、Slackのチャンネルにその内容を送信してください。
                5. ない場合、「申し訳ありませんが、そのエラーやトラブルについてはお答えできません。」と伝えます。
                もし顧客がルーチンに関連しない質問をした場合、トリアージエージェントに引き継ぎます。
                """,
                mcp_servers=[self.file_mcp_server, self.slack_mcp_server],
            )

            self.how_to_agent = Agent[CallCenterAgentContext](
                name="商品取り扱いエージェント",
                handoff_description="商品取り扱いエージェントは、商品に関する質問に答えることができます。",
                instructions=f"""{JA_RECOMMENDED_PROMPT_PREFIX}
                あなたは商品取り扱いエージェントです。もし顧客と話している場合、あなたはおそらくトリアージエージェントから仕事を委譲されました。
                顧客をサポートするために、以下のルーチンを使用してください。
                # ルーチン
                1. 顧客がどのような商品について質問しているかを確認します。
                2. file_mcp_serverで提供されているディレクトリのファイルの中に、一致するテキストファイルがあるかどうかを確認します。
                3. ある場合、そのテキストファイルの中から、顧客の質問に答えられる情報を抽出し、回答してください。質問の内容が答えれらない場合は、「申し訳ありませんが、それついてはお答えできません。」と伝えます。
                4. ない場合、「申し訳ありませんが、その商品は取り扱っておりません。」と伝えます。
                もし顧客がルーチンに関連しない質問をした場合、トリアージエージェントに引き継ぎます。
                """,
                mcp_servers=[self.file_mcp_server],
            )

            self.order_agent = Agent[CallCenterAgentContext](
                name="商品注文・購入対応エージェント",
                handoff_description="商品注文・購入に関する質問に答えるエージェントです。",
                instructions=f"""{JA_RECOMMENDED_PROMPT_PREFIX}
                あなたは商品注文・購入対応エージェントです。もし顧客と話している場合、あなたはおそらくトリアージエージェントから仕事を委譲されました。
                顧客をサポートするために、以下のルーチンを使用してください。
                # ルーチン
                1. 顧客がどのような商品を購入したいかを確認します。
                2. file_mcp_serverで提供されているディレクトリのファイルの中に、一致する、もしくは類似するテキストファイルがあるかどうかを確認します。例えば、「スマホ」のようにスマートフォンの略称を使っている場合や、商品名の一部が異なる場合などです。
                3. ある場合、一度顧客に確認のため「<商品>ですね。注文してもよろしいですか？」と尋ねます。同意を得たら、slack_file_mcp_serverで#注文管理に「<商品名>を注文しました。」と送信してください。拒否されたら、トリアージエージェントに引き継ぎます。
                4. ない場合、「申し訳ありませんが、その商品は取り扱っておりません。」と伝えます。少しだけでも似ている名前の商品がある場合は、「<似ている商品名>はありますが、<商品名>はありません。」と伝えます。
                もし顧客がルーチンに関連しない質問をした場合、トリアージエージェントに引き継ぎます。
                """,
                mcp_servers=[self.file_mcp_server, self.slack_mcp_server],
            )

            self.triage_agent = Agent[CallCenterAgentContext](
                name="トリアージエージェント",
                instructions=(
                    f"{JA_RECOMMENDED_PROMPT_PREFIX} "
                    "あなたは優秀なトリアージエージェントです。 あなたは、顧客のリクエストを適切なエージェントに委任することができます。\n"
                    "顧客の質問がコールセンターにしないような質問をしているかもしれない場合は、ガードレールエージェントを使用してください。\n"
                    "顧客の名前より先に質問が来た場合、質問を記憶しつつ、名前を聞き、update_customer_infoを呼び出してください。\n"
                    "顧客の質問は、以下の3つのカテゴリに分けられます。\n"
                    "1. 商品の取り扱いに関する質問\n"
                    "2. 商品の注文・購入に関する質問\n"
                    "3. その他の回答不可能・専門知識が必要な質問\n"
                    "以下の顧客対応マニュアルを確認し、適切なエージェントに引き継いでください。"
                    "ただし、その他の質問は顧客対応マニュアルに書かれた通りに答えてください。\n"
                    f"{CALL_CENTER_MANUAL}\n"
                ),
                handoffs=[
                    self.how_to_agent,
                    self.order_agent,
                    self.error_trouble_agent,
                ],
                input_guardrails=[abnormal_guardrail],
                tools=[update_customer_info],
            )

            # 再びトリアージエージェントに戻るためのハンドオフ
            self.order_agent.handoffs.append(self.triage_agent)
            self.how_to_agent.handoffs.append(self.triage_agent)
            self.error_trouble_agent.handoffs.append(self.triage_agent)
            
            self._current_agent = self.triage_agent
            self._agents_initialized = True

        except Exception as e:
            print(f"エージェント初期化エラー: {e}")

    async def run(self, transcription: str) -> AsyncIterator[str]:
        self._on_start(transcription)

        # エージェントの初期化(基本的には一度だけ)
        await self._initialize_agents()

        # Add the transcription to the input history
        self._input_history.append(
            {
                "role": "user",
                "content": transcription,
            }
        )

        try:
            with trace("Customer service", group_id=self._conversation_id):
                # Run the agent
                result = Runner.run_streamed(self._current_agent, self._input_history, context=self._context)
                full_response = ""
                async for chunk in VoiceWorkflowHelper.stream_text_from(result):
                    full_response += chunk
                    yield chunk
                
                self._tts_output(full_response)
                
                # Update the input history and current agent
                self._input_history = result.to_input_list()
                if self._current_agent != result.last_agent:
                    self._current_agent = result.last_agent
                    if self._on_agent_change:
                        self._on_agent_change(self._current_agent.name)

        except InputGuardrailTripwireTriggered as e:
            message = "すみません。この質問にはお答えできません。"
            self._tts_output(message)
            # ガードレール作動の通知
            if self._on_agent_change:
                self._on_agent_change("ガードレール作動")

            self._input_history.append(
                {
                    "role": "assistant",
                    "content": message,
                }
            )
            self._current_agent = self.triage_agent
            if self._on_agent_change:
                self._on_agent_change(self._current_agent.name)

            yield message
            
        except Exception as e:
            error_message = f"申し訳ありません。システムエラーが発生しました: {str(e)}"
            self._tts_output(error_message)
            yield error_message

    async def cleanup(self):
        """リソースのクリーンアップ"""
        try:
            if hasattr(self, 'file_mcp_server'):
                await self.file_mcp_server.__aexit__(None, None, None)
            if hasattr(self, 'slack_mcp_server'):
                await self.slack_mcp_server.__aexit__(None, None, None)
        except Exception as e:
            print(f"クリーンアップエラー: {e}")