import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QToolButton


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import session_transcript
from session_creator import SessionCreatorWidget
from session_transcript import OllamaGenerationResult, SessionTranscriptStore, TranscriptSessionController


class _FakeTranscriber:
    def transcribe(self, audio_path: Path, cli_path: str, model_path: str) -> str:
        stem = audio_path.stem
        return (
            f"DM: The party investigated {stem} and found a hidden ledger. "
            f"Mira: We should bring the ledger back to Captain Rusk. "
            f"Thorn: We still need to identify the dock contact. "
            f"DM: One escape route remained unexplored."
        )


class _FakeRecapRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate(
        self,
        host: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        *,
        format_hint: object = "",
        num_predict: int = 0,
    ) -> OllamaGenerationResult:
        self.calls.append(
            {
                "host": host,
                "model": model,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "format_hint": format_hint,
                "num_predict": num_predict,
            }
        )
        call_index = len(self.calls)
        text = f"Draft {call_index} executive summary about the recovered ledger, Captain Rusk, and the unresolved dock contact."
        return OllamaGenerationResult(text=text, prompt_eval_count=4200, eval_count=500)


class _LowSignalRecapRunner(_FakeRecapRunner):
    def generate(
        self,
        host: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        *,
        format_hint: object = "",
        num_predict: int = 0,
    ) -> OllamaGenerationResult:
        result = super().generate(
            host,
            model,
            system_prompt,
            user_prompt,
            format_hint=format_hint,
            num_predict=num_predict,
        )
        return OllamaGenerationResult(
            text="Coverage Window 1 spans slice range 000001.01 to 000001.08. No concise summary was produced for this window.",
            prompt_eval_count=result.prompt_eval_count,
            eval_count=result.eval_count,
        )


def _write_audio_fixture(tmp_path: Path, name: str, payload: bytes = b"RIFFdemo") -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def test_session_transcript_store_persists_transcript_chunks(tmp_path):
    store = SessionTranscriptStore("session_alpha")
    audio_path = _write_audio_fixture(tmp_path, "clip.wav")

    imported = store.add_imported_audio("mic", str(audio_path))
    claimed = store.claim_next_transcript_chunk()

    assert claimed is not None
    assert claimed["chunk_id"] == imported["chunk_id"]

    store.mark_chunk_transcribed(claimed["chunk_id"], "Hello from the imported chunk")

    transcript_text = store.transcript_text()
    assert "Hello from the imported chunk" in transcript_text
    assert "[Mic]" in transcript_text

    reloaded = SessionTranscriptStore("session_alpha")
    assert "Hello from the imported chunk" in reloaded.transcript_text()
    assert reloaded.transcript_counts()["completed"] == 1


def test_transcript_controller_generates_checkpointed_recap(tmp_path):
    recap_runner = _FakeRecapRunner()
    controller = TranscriptSessionController(
        transcriber=_FakeTranscriber(),
        recap_runner=recap_runner,
    )
    controller.bind_session("session_beta", "Session Beta")
    controller.update_runtime_settings(
        "/tmp/whisper-cli",
        "/tmp/model.bin",
        "http://127.0.0.1:11434",
        "gpt-oss:20b",
    )

    assert controller._store is not None
    for index in range(7):
        audio_path = _write_audio_fixture(tmp_path, f"clip_{index}.wav", payload=f"chunk-{index}".encode("utf-8"))
        controller._store.add_imported_audio("system", str(audio_path))

    processed = controller.transcribe_pending_now()
    recap_ok = controller.generate_recap_now()
    snapshot = controller.snapshot()

    assert processed == 7
    assert recap_ok is True
    assert snapshot["recap"]["status"] == "ready"
    assert snapshot["recap"]["checkpoint_count"] == snapshot["recap"]["investigation_windows"]
    assert snapshot["recap"]["strategy"] == "v3.code-first"
    assert snapshot["recap"]["prompt_eval_max"] == 4200
    assert snapshot["recap"]["investigation_windows"] >= 1
    assert controller.recap_text().startswith("## Session Recap\n\nDraft")
    assert "Captain Rusk" in controller.recap_text()
    assert "dock contact" in controller.recap_text()
    assert "## Chronology" not in controller.recap_text()
    assert len(recap_runner.calls) == 1
    assert not any(call["format_hint"] for call in recap_runner.calls)
    assert all(call["model"] == "gpt-oss:20b" for call in recap_runner.calls)


def test_transcript_controller_generates_recap_from_manual_transcript():
    recap_runner = _FakeRecapRunner()
    controller = TranscriptSessionController(
        transcriber=_FakeTranscriber(),
        recap_runner=recap_runner,
    )
    controller.bind_session("session_manual", "Manual Session")
    controller.save_manual_transcript(
        "Alice: We decided to ship on Friday. "
        "Bob: I will update the docs and send the release mail. "
        "Alice: We still need final QA signoff."
    )

    recap_ok = controller.generate_recap_now()
    snapshot = controller.snapshot()

    assert recap_ok is True
    assert snapshot["manual_transcript"]["enabled"] is True
    assert snapshot["recap"]["status"] == "ready"
    assert snapshot["recap"]["processed_chunk_count"] >= 1
    assert controller.recap_text().startswith("## Session Recap\n\n")
    assert "ship on Friday" in controller.recap_text()
    assert "update the docs" in controller.recap_text()
    assert "final QA signoff" in controller.recap_text()
    assert len(recap_runner.calls) == 1


def test_transcript_controller_rejects_low_signal_model_summary():
    controller = TranscriptSessionController(
        transcriber=_FakeTranscriber(),
        recap_runner=_LowSignalRecapRunner(),
    )
    controller.bind_session("session_low_signal", "Low Signal Session")
    controller.save_manual_transcript(
        "DM: The party recovered the ledger from the toll house. "
        "Mira: We should bring it to Captain Rusk. "
        "Thorn: We still do not know who the east dock contact is."
    )

    recap_ok = controller.generate_recap_now()
    recap_text = controller.recap_text()

    assert recap_ok is True
    assert "Coverage Window 1 spans slice range" not in recap_text
    assert "Captain Rusk" in recap_text
    assert "east dock contact" in recap_text
    assert "## Chronology" not in recap_text


def test_soundcard_loopback_listing_filters_to_loopback_devices(monkeypatch):
    class _FakeLoopbackDevice:
        def __init__(self, device_id: str, name: str, isloopback: bool) -> None:
            self.id = device_id
            self.name = name
            self.isloopback = isloopback

    class _FakeSoundCardModule:
        @staticmethod
        def all_microphones(*, include_loopback: bool = False):
            assert include_loopback is True
            return [
                _FakeLoopbackDevice("mic-real", "Real Mic", False),
                _FakeLoopbackDevice("loopback-1", "Speakers (Loopback)", True),
                _FakeLoopbackDevice("loopback-2", "Monitor of Sink", True),
            ]

    monkeypatch.setattr(
        session_transcript,
        "_soundcard_modules",
        lambda: (_FakeSoundCardModule(), object(), ""),
    )

    devices, error_message = session_transcript._list_soundcard_loopback_inputs()

    assert error_message == ""
    assert [device.device_id for device in devices] == ["loopback-1", "loopback-2"]
    assert [device.name for device in devices] == ["Speakers (Loopback)", "Monitor of Sink"]


def test_transcript_controller_uses_loopback_recorder_for_system_source():
    controller = TranscriptSessionController(
        transcriber=_FakeTranscriber(),
        recap_runner=_FakeRecapRunner(),
    )
    controller.bind_session("session_gamma", "Session Gamma")

    recorder = controller._build_recorder("system", "loopback-1", "Speakers (Loopback)")

    assert recorder.__class__.__name__ == "_SoundCardLoopbackRecorder"


def test_session_creator_wires_live_transcript_and_recap_tabs(qtbot):
    widget = SessionCreatorWidget()
    qtbot.addWidget(widget)

    widget._create_session()

    assert widget.ref_tabs.tabText(2) == "Transcript"
    assert widget.ref_tabs.tabText(3) == "Recap"
    assert widget._transcript_controller.snapshot()["has_session"] is True
    assert widget.transcript_panel.transcript_editor.isReadOnly() is False
    assert isinstance(widget.transcript_panel.start_btn, QToolButton)
    assert isinstance(widget.transcript_panel.save_editor_btn, QToolButton)
    assert isinstance(widget.recap_panel.generate_btn, QToolButton)
    assert widget.transcript_panel.refresh_devices_btn.isEnabled()
    assert widget.recap_panel.generate_btn.isEnabled()
    assert widget.transcript_panel.start_btn.width() == widget.transcript_panel.start_btn.height()
    assert widget.transcript_panel.start_btn.size() == widget.transcript_panel.import_btn.size()
    assert widget.transcript_panel.save_editor_btn.size() == widget.transcript_panel.reload_editor_btn.size()
    assert widget.transcript_panel.whisper_cli_browse_btn.height() == widget.transcript_panel.whisper_cli_edit.height()
    assert widget.recap_panel.generate_btn.size() == widget.recap_panel.halt_btn.size()
