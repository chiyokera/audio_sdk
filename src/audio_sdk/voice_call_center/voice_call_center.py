from __future__ import annotations

import asyncio
import shutil

import sounddevice as sd
from agents.voice import StreamedAudioInput, StreamedAudioResult, VoicePipeline
from config import CHANNELS, FORMAT, SAMPLE_RATE
from dotenv import load_dotenv
from my_workflow import VoiceCallCenterWorkflow
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import Button, RichLog, Static
from typing_extensions import override

load_dotenv()

# UI Components

class Header(Static):
    """A header widget."""

    session_id = reactive("")
    current_agent = reactive("音声コールセンター | 現在のエージェント: トリアージエージェント")

    @override
    def render(self) -> str:
        return f"音声コールセンター | 現在のエージェント: {self.current_agent}"

class AudioStatusIndicator(Static):
    """A widget that shows the current audio recording status."""

    is_recording = reactive(False)

    @override
    def render(self) -> str:
        status = (
            "🔴 録音中... (Kキーで停止)"
            if self.is_recording
            else "⚪ Kキーで録音開始 (Qキーで終了)"
        )
        return status

# Main Application

class VoiceCallCenterApp(App[None]):
    CSS = """
        Screen {
            background: #1a1b26;  /* Dark blue-grey background */
        }

        Container {
            border: double rgb(91, 164, 91);
        }

        Horizontal {
            width: 100%;
        }

        #input-container {
            height: 5;  /* Explicit height for input container */
            margin: 1 1;
            padding: 1 2;
        }

        Input {
            width: 80%;
            height: 3;  /* Explicit height for input */
        }

        Button {
            width: 20%;
            height: 3;  /* Explicit height for button */
        }

        #bottom-pane {
            width: 100%;
            height: 82%;  /* Reduced to make room for session display */
            border: round rgb(205, 133, 63);
            content-align: center middle;
        }

        #status-indicator {
            height: 3;
            content-align: center middle;
            background: #2a2b36;
            border: solid rgb(91, 164, 91);
            margin: 1 1;
        }

        #session-display {
            height: 3;
            content-align: center middle;
            background: #2a2b36;
            border: solid rgb(91, 164, 91);
            margin: 1 1;
        }

        Static {
            color: white;
        }
    """

    should_send_audio: asyncio.Event
    audio_player: sd.OutputStream
    last_audio_item_id: str | None
    connected: asyncio.Event

    def __init__(self) -> None:
        super().__init__()
        self.last_audio_item_id = None
        self.should_send_audio = asyncio.Event()
        self.connected = asyncio.Event()
        self.workflow = VoiceCallCenterWorkflow(
            on_start=self._on_transcription,
            tts_output=self._tts_output,
            on_agent_change=self._on_agent_change,
        )
        self.pipeline = VoicePipeline(workflow=self.workflow)
        self._audio_input = StreamedAudioInput()
        self.audio_player = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=FORMAT,
        )

    def _on_transcription(self, transcription: str) -> None:
        try:
            self.query_one("#bottom-pane", RichLog).write(
                f"音声認識: {transcription}"
            )
        except Exception:
            pass

    def _tts_output(self, text: str) -> None:
        try:
            self.query_one("#bottom-pane", RichLog).write(f"エージェント応答: {text}")
        except Exception:
            pass

    def _on_agent_change(self, agent_name: str) -> None:
        try:
            header = self.query_one("#session-display", Header)
            header.current_agent = agent_name
            self.query_one("#bottom-pane", RichLog).write(f"🔄 エージェント切り替え: {agent_name}")
        except Exception:
            pass

    @override
    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        with Container():
            yield Header(id="session-display")
            yield AudioStatusIndicator(id="status-indicator")
            yield RichLog(id="bottom-pane", wrap=True, highlight=True, markup=True)

    async def on_mount(self) -> None:
        self.run_worker(self.start_voice_pipeline())
        self.run_worker(self.send_mic_audio())

    async def start_voice_pipeline(self) -> None:
        try:
            self.audio_player.start()
            self.result: StreamedAudioResult = await self.pipeline.run(
                self._audio_input
            )
            async for event in self.result.stream():
                bottom_pane = self.query_one("#bottom-pane", RichLog)
                if event.type == "voice_stream_event_audio":
                    self.audio_player.write(event.data)  # Play the audio
                elif event.type == "voice_stream_event_lifecycle":
                    bottom_pane.write(f"ライフサイクルイベント: {event.event}")
        except Exception as e:
            bottom_pane = self.query_one("#bottom-pane", RichLog)
            bottom_pane.write(f"エラー: {e}")
        finally:
            self.audio_player.close()
            # クリーンアップ
            await self.workflow.cleanup()

    async def send_mic_audio(self) -> None:
        device_info = sd.query_devices()
        print(device_info)

        read_size = int(SAMPLE_RATE * 0.02)

        stream = sd.InputStream(
            channels=CHANNELS,
            samplerate=SAMPLE_RATE,
            dtype="int16",
        )
        stream.start()

        status_indicator = self.query_one(AudioStatusIndicator)

        try:
            while True:
                if stream.read_available < read_size:
                    await asyncio.sleep(0)
                    continue

                await self.should_send_audio.wait()
                status_indicator.is_recording = True

                data, _ = stream.read(read_size)

                await self._audio_input.add_audio(data)
                await asyncio.sleep(0)
        except KeyboardInterrupt:
            pass
        finally:
            stream.stop()
            stream.close()

    async def on_key(self, event: events.Key) -> None:
        """Handle key press events."""
        if event.key == "enter":
            self.query_one(Button).press()
            return

        if event.key == "q":
            await self.workflow.cleanup() # クリーンアップしてから終了
            self.exit()
            return

        if event.key == "k":
            status_indicator = self.query_one(AudioStatusIndicator)
            if status_indicator.is_recording:
                self.should_send_audio.clear()
                status_indicator.is_recording = False
            else:
                self.should_send_audio.set()
                status_indicator.is_recording = True

if __name__ == "__main__":
    if not shutil.which("npx"):
        raise RuntimeError("npx is not installed. Please install it with `npm install -g npx`.")
    app = VoiceCallCenterApp()
    app.run()
