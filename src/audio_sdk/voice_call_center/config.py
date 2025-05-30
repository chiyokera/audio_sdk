import numpy as np
from pydantic import BaseModel

MODEL = "gpt-4o-mini"
SAMPLE_RATE = 24000
FORMAT = np.int16
CHANNELS = 1

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

JA_RECOMMENDED_PROMPT_PREFIX = """
#システムコンテキスト\n
あなたは、エージェントの協調と実行を簡単にするために設計されたマルチエージェントシステム「Agents SDK」の一部です。
Agentsは主に2つの抽象概念、**Agent**と**Handoffs**を使用します。エージェントは指示とツールを含み、適切なタイミングで会話を他のエージェントに引き継ぐことができます。
ハンドオフは通常 transfer_to_<agent_name> という名前のハンドオフ関数を呼び出すことで実現されます。エージェント間の引き継ぎはバックグラウンドでシームレスに処理されます。
ユーザーとの会話の中で、これらの引き継ぎについて言及したり、注意を引いたりしないでください。\n"""

# CONTEXT
class CallCenterAgentContext(BaseModel):
    customer_name: str | None = None
    question_type: str | None = None
    flight_number: str | None = None