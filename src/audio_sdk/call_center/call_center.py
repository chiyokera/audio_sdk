from __future__ import annotations as _annotations

import asyncio
import os
import random
import shutil
import uuid

from agents import (Agent, GuardrailFunctionOutput, HandoffOutputItem,
                    InputGuardrailTripwireTriggered, ItemHelpers,
                    MessageOutputItem, RunContextWrapper, Runner, ToolCallItem,
                    ToolCallOutputItem, TResponseInputItem, function_tool,
                    handoff, input_guardrail, trace)
from agents.mcp import MCPServer, MCPServerSse, MCPServerStdio
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

MODEL = "gpt-4o-mini"
JA_RECOMMENDED_PROMPT_PREFIX = """
#システムコンテキスト\n
あなたは、エージェントの協調と実行を簡単にするために設計されたマルチエージェントシステム「Agents SDK」の一部です。
Agentsは主に2つの抽象概念、**Agent**と**Handoffs**を使用します。エージェントは指示とツールを含み、適切なタイミングで会話を他のエージェントに引き継ぐことができます。
ハンドオフは通常 transfer_to_<agent_name> という名前のハンドオフ関数を呼び出すことで実現されます。エージェント間の引き継ぎはバックグラウンドでシームレスに処理されます。
ユーザーとの会話の中で、これらの引き継ぎについて言及したり、注意を引いたりしないでください。\n"""

with open("../../../data/call_center_manual.txt", "r", encoding="utf-8") as f:
    CALL_CENTER_MANUAL = f.read()

PRODUCTS_LIST = [
    "タブレット A68 Air", 
    "スマートウォッチ B27 Max", 
    "スマートフォン C82 Lite", 
    "スマートスピーカー D47 Air",
    "スマートフォン E51 Mini",
    "スマートスピーカー F29 Pro",
    "スマートフォン G81 Standard",
    "ワイヤレスイヤホン H61 Air",
    "ワイヤレスイヤホン I79 Pro",
    "ゲーム機 J87 Max"
    ]

### CONTEXT

class CallCenterAgentContext(BaseModel):
    customer_name: str | None = None
    question_type: str | None = None


### TOOLS
#### MCP: products info lookup, slack summary notification

@function_tool(
    name_override="faq_lookup_tool", description_override="よく聞かれる質問を調べるツール"
)
async def faq_lookup_tool(question: str) -> str:
    if "bag" in question or "baggage" in question:
        return (
            "You are allowed to bring one bag on the plane. "
            "It must be under 50 pounds and 22 inches x 14 inches x 9 inches."
        )
    elif "seats" in question or "plane" in question:
        return (
            "There are 120 seats on the plane. "
            "There are 22 business class seats and 98 economy seats. "
            "Exit rows are rows 4 and 16. "
            "Rows 5-8 are Economy Plus, with extra legroom. "
        )
    elif "wifi" in question:
        return "We have free wifi on the plane, join Airline-Wifi"
    return "I'm sorry, I don't know the answer to that question."


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


### Guardrails

class AbnormalOutput(BaseModel):
    reasoning: str | None = Field(
        default=None, description="異常な質問かどうかの理由"
    )
    is_abnormal: bool = Field(default=False, description="異常な質問かどうか")

guardrail_agent = Agent(
    name="Guardrail check",
    instructions="ユーザからの質問が与えられる。ユーザーがコールセンターにしないようなアブノーマルな質問をしているかどうかを確認しろ。",
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

### HOOKS

async def on_seat_booking_handoff(context: RunContextWrapper[CallCenterAgentContext]) -> None:
    flight_number = f"FLT-{random.randint(100, 999)}"
    context.context.flight_number = flight_number

### RUN

async def main():
    async with MCPServerStdio(
        name="Filesystem Server, via npx",
        params={
            "command": "npx",
            "args": [
                "-y", 
                "@modelcontextprotocol/server-filesystem", 
                "/Users/chikaratanaka/Documents/audio_sdk/data/products"
                ]
        }
    ) as file_mcp_server:
        
        async with MCPServerStdio(
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
        ) as slack_file_mcp_server:

            error_trouble_agent = Agent[CallCenterAgentContext](
                name="エラー・トラブル・クレーム対応エージェント",
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
                mcp_servers=[file_mcp_server, slack_file_mcp_server],
            )

            how_to_agent = Agent[CallCenterAgentContext](
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
                mcp_servers=[file_mcp_server],
            )


            order_agent = Agent[CallCenterAgentContext](
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
                mcp_servers=[file_mcp_server, slack_file_mcp_server],
            )

            triage_agent = Agent[CallCenterAgentContext](
                name="トリアージエージェント",
                instructions=(
                    f"{JA_RECOMMENDED_PROMPT_PREFIX} "
                    "あなたは優秀なトリアージエージェントです。 あなたは、顧客のリクエストを適切なエージェントに委任することができます。\n"
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
                    how_to_agent,
                    order_agent,
                    error_trouble_agent,
                ],
                input_guardrails=[abnormal_guardrail],
                tools=[update_customer_info],
            )

            # 再びトリアージエージェントに戻るためのハンドオフ
            order_agent.handoffs.append(triage_agent)
            how_to_agent.handoffs.append(triage_agent)
            error_trouble_agent.handoffs.append(triage_agent)
            
            current_agent: Agent[CallCenterAgentContext] = triage_agent
            input_items: list[TResponseInputItem] = []
            context = CallCenterAgentContext()

            conversation_id = uuid.uuid4().hex[:16]
            while True:
                user_input = input("Enter your message: ")
                if user_input.lower() in ["q", "quit"]:
                    print("Exiting...")
                    break
                with trace("Customer service", group_id=conversation_id):
                    input_items.append({"content": user_input, "role": "user"})
                    try:
                        print(f"context: {context}")
                        result = await Runner.run(current_agent, input_items, context=context)
                        for new_item in result.new_items:
                            agent_name = new_item.agent.name
                            if isinstance(new_item, MessageOutputItem):
                                print(f"{agent_name}: {ItemHelpers.text_message_output(new_item)}")
                            elif isinstance(new_item, HandoffOutputItem):
                                print(
                                    f"Handed off from {new_item.source_agent.name} to {new_item.target_agent.name}"
                                )
                            elif isinstance(new_item, ToolCallItem):
                                print(f"{agent_name}: Calling a tool")
                            elif isinstance(new_item, ToolCallOutputItem):
                                # print(f"{agent_name}: Tool call output: {new_item.output}")
                                pass
                            else:
                                print(f"{agent_name}: Skipping item: {new_item.__class__.__name__}")

                            input_items = result.to_input_list()
                            current_agent = result.last_agent

                    except InputGuardrailTripwireTriggered as e:
                        message= "すみません。この質問にはお答えできません。"
                        print(f"{current_agent.name}: {message}")

if __name__ == "__main__":
    if not shutil.which("npx"):
        raise RuntimeError("npx is not installed. Please install it with `npm install -g npx`.")
    asyncio.run(main())