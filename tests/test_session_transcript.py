import os
import re
import sys
from pathlib import Path

from PySide6.QtWidgets import QPushButton, QToolButton


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import session_transcript
from session_creator import SessionCreatorWidget
from session_transcript import OllamaGenerationResult, OllamaRecapRunner, SessionTranscriptStore, TranscriptSessionController


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
        self.stage_two_calls = 0
        self.audit_calls = 0
        self.repair_calls = 0

    def _record_call(
        self,
        host: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        format_hint: object,
        num_predict: int,
    ) -> None:
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

    @staticmethod
    def _is_release_prompt(user_prompt: str) -> bool:
        lowered = user_prompt.lower()
        return "ship on friday" in lowered or "qa signoff" in lowered or "release mail" in lowered

    def _stage_one_release_response(self) -> str:
        return (
            "The session focused on release planning. The team agreed to ship on Friday, assigned the docs update and the release mail, and ended with final QA signoff still unresolved."
        )

    def _stage_two_release_response(self) -> str:
        return (
            "The session focused on release planning, where the team agreed to ship on Friday and turned the remaining release work into concrete assignments. "
            "They explicitly assigned the docs update and the release mail instead of leaving those steps vague, and the only major unresolved item at the end was final QA signoff."
        )

    def _stage_one_ledger_response(self) -> str:
        return (
            "The party investigated the toll house exchange, recovered a hidden ledger, and agreed that Captain Rusk should receive it. "
            "By the end, the east dock contact was still unidentified and one escape route remained unexplored."
        )

    def _stage_two_ledger_response(self) -> str:
        return (
            "The session centered on the party's investigation, which led them to recover a hidden ledger and establish it as the key evidence from the encounter. "
            "They decided to bring the ledger to Captain Rusk, but the east dock contact remained unidentified and one escape route was still unexplored by the end of the session."
        )

    def _audit_response(self, user_prompt: str) -> str:
        if self._is_release_prompt(user_prompt):
            return (
                "The recap already covers the Friday ship date, the assigned docs update, and the unresolved QA signoff. "
                "No major omissions stand out in the end-state."
            )
        return (
            "The recap already covers the recovered ledger, the planned handoff to Captain Rusk, and the unresolved east dock lead. "
            "No major omissions stand out in the ending state."
        )

    def _thinking_text(self, lowered_system: str) -> str:
        if "writing a gist recap" in lowered_system or "writing a recap summary" in lowered_system:
            return "Drafting the initial recap from the transcript."
        if "refining a gist recap" in lowered_system or "refining a recap summary" in lowered_system:
            return "Refining wording and checking transcript-supported coverage."
        if "checking whether a dnd session recap missed any important facts" in lowered_system:
            return "Auditing the recap against the transcript end-state."
        if "repairing a dnd session recap" in lowered_system:
            return "Applying the audit notes with minimal recap edits."
        return "Processing recap stage."

    def _emit_stream(
        self,
        lowered_system: str,
        text: str,
        stream_callback,
    ) -> str:
        thinking_text = self._thinking_text(lowered_system)
        if stream_callback is not None:
            stream_callback("thinking", thinking_text)
            midpoint = max(1, len(text) // 2)
            stream_callback("response", text[:midpoint])
            stream_callback("response", text[midpoint:])
        return thinking_text

    def generate(
        self,
        host: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        *,
        format_hint: object = "",
        num_predict: int = 0,
        stream_callback=None,
    ) -> OllamaGenerationResult:
        self._record_call(host, model, system_prompt, user_prompt, format_hint, num_predict)
        lowered_system = system_prompt.lower()
        is_release = self._is_release_prompt(user_prompt)
        if "writing a gist recap of a dnd session transcript" in lowered_system or "writing a recap summary of a dnd session transcript" in lowered_system:
            text = self._stage_one_release_response() if is_release else self._stage_one_ledger_response()
        elif "refining a gist recap of a dnd session" in lowered_system or "refining a recap summary of a dnd session" in lowered_system:
            self.stage_two_calls += 1
            text = self._stage_two_release_response() if is_release else self._stage_two_ledger_response()
        elif "checking whether a dnd session recap missed any important facts from the transcript" in lowered_system:
            self.audit_calls += 1
            text = self._audit_response(user_prompt)
        elif "repairing a dnd session recap" in lowered_system:
            self.repair_calls += 1
            text = self._stage_two_release_response() if is_release else self._stage_two_ledger_response()
        else:
            text = "The session recap request did not match a known test prompt."
        thinking_text = self._emit_stream(lowered_system, text, stream_callback)
        return OllamaGenerationResult(text=text, prompt_eval_count=4200, eval_count=500, thinking_text=thinking_text)


class _RetryingSecondStageRecapRunner(_FakeRecapRunner):
    def generate(
        self,
        host: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        *,
        format_hint: object = "",
        num_predict: int = 0,
        stream_callback=None,
    ) -> OllamaGenerationResult:
        lowered_system = system_prompt.lower()
        if "refining a gist recap of a dnd session" in lowered_system or "refining a recap summary of a dnd session" in lowered_system:
            self._record_call(host, model, system_prompt, user_prompt, format_hint, num_predict)
            self.stage_two_calls += 1
            if self.stage_two_calls == 1:
                invalid_text = "## Session Recap\n\nCoverage Window 1 spans slice range 000001.01 to 000001.08."
                thinking_text = self._emit_stream(lowered_system, invalid_text, stream_callback)
                return OllamaGenerationResult(
                    text=invalid_text,
                    prompt_eval_count=4200,
                    eval_count=500,
                    thinking_text=thinking_text,
                )
            refined_text = self._stage_two_ledger_response()
            thinking_text = self._emit_stream(lowered_system, refined_text, stream_callback)
            return OllamaGenerationResult(
                text=refined_text,
                prompt_eval_count=4200,
                eval_count=500,
                thinking_text=thinking_text,
            )
        return super().generate(
            host,
            model,
            system_prompt,
            user_prompt,
            format_hint=format_hint,
            num_predict=num_predict,
            stream_callback=stream_callback,
        )


class _InvalidRecapStageRunner(_FakeRecapRunner):
    def generate(
        self,
        host: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        *,
        format_hint: object = "",
        num_predict: int = 0,
        stream_callback=None,
    ) -> OllamaGenerationResult:
        self._record_call(host, model, system_prompt, user_prompt, format_hint, num_predict)
        if "writing a gist recap of a dnd session transcript" in system_prompt.lower() or "writing a recap summary of a dnd session transcript" in system_prompt.lower():
            text = "- invalid\n- still invalid"
            thinking_text = self._emit_stream(system_prompt.lower(), text, stream_callback)
            return OllamaGenerationResult(text=text, prompt_eval_count=4200, eval_count=500, thinking_text=thinking_text)
        thinking_text = self._emit_stream(system_prompt.lower(), "", stream_callback)
        return OllamaGenerationResult(text="", prompt_eval_count=4200, eval_count=500, thinking_text=thinking_text)


class _AuditRepairRecapRunner(_FakeRecapRunner):
    def _stage_two_ledger_response(self) -> str:
        return (
            "The party infiltrated the toll house, subdued the rear guard, and recovered the ledger and signet from the robed cultist. "
            "They chose to bring the evidence to Captain Rusk and left the scene with one captive while an unknown contact remained in the marsh."
        )

    def _audit_response(self, user_prompt: str) -> str:
        return (
            "The recap still misses that the Moon Gate remains unexplained at session end and that the rear guard fears the ones under the water. "
            "Those are unresolved hooks that still matter when the session stops."
        )

    def generate(
        self,
        host: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        *,
        format_hint: object = "",
        num_predict: int = 0,
        stream_callback=None,
    ) -> OllamaGenerationResult:
        self._record_call(host, model, system_prompt, user_prompt, format_hint, num_predict)
        lowered_system = system_prompt.lower()
        if "writing a gist recap of a dnd session transcript" in lowered_system or "writing a recap summary of a dnd session transcript" in lowered_system:
            text = (
                "The party found the toll house outside Harrowfen, confronted the cultists there, and recovered a ledger and signet tied to the ferryman case. "
                "They left with the evidence after learning that the cult had larger plans connected to the Moon Gate and a threat under the water."
            )
        elif "refining a gist recap of a dnd session" in lowered_system or "refining a recap summary of a dnd session" in lowered_system:
            self.stage_two_calls += 1
            text = self._stage_two_ledger_response()
        elif "checking whether a dnd session recap missed any important facts from the transcript" in lowered_system:
            self.audit_calls += 1
            text = self._audit_response(user_prompt)
        elif "repairing a dnd session recap" in lowered_system:
            self.repair_calls += 1
            text = (
                "The party infiltrated the toll house outside Harrowfen, subdued the rear guard, and recovered the ledger and silver signet from the robed cultist while disabling the green-flame signaling bowl. "
                "They chose to bring the evidence to Captain Rusk, but the Moon Gate remained unexplained and the rear guard's fear of the ones under the water left a larger threat unresolved as an unknown contact escaped back into the marsh."
            )
        else:
            text = "The session recap request did not match a known test prompt."
        thinking_text = self._emit_stream(lowered_system, text, stream_callback)
        return OllamaGenerationResult(text=text, prompt_eval_count=4200, eval_count=500, thinking_text=thinking_text)


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
    assert snapshot["recap"]["checkpoint_count"] == 2
    assert snapshot["recap"]["strategy"] == "v8.gist-two-pass-full-transcript"
    assert snapshot["recap"]["prompt_eval_max"] == 4200
    assert snapshot["recap"]["investigation_windows"] == 2
    assert snapshot["transcript_estimated_tokens"] > 0
    assert controller.recap_text().startswith("## Session Recap\n\n")
    assert "The session centered on the party's investigation" in controller.recap_text()
    assert "Captain Rusk" in controller.recap_text()
    assert "east dock contact" in controller.recap_text()
    assert "Coverage Window 1 spans slice range" not in controller.recap_text()
    assert len(recap_runner.calls) == 2
    assert recap_runner.audit_calls == 0
    assert recap_runner.repair_calls == 0
    assert not any(call["format_hint"] for call in recap_runner.calls)
    assert all(call["num_predict"] == 0 for call in recap_runner.calls)
    assert all(call["model"] == "gpt-oss:20b" for call in recap_runner.calls)
    assert any("writing a gist recap of a dnd session transcript" in str(call["system_prompt"]).lower() for call in recap_runner.calls)
    assert any("refining a gist recap of a dnd session" in str(call["system_prompt"]).lower() for call in recap_runner.calls)
    assert not any("checking whether a dnd session recap missed any important facts from the transcript" in str(call["system_prompt"]).lower() for call in recap_runner.calls)
    assert not any("repairing a dnd session recap" in str(call["system_prompt"]).lower() for call in recap_runner.calls)
    assert not any("Block Mode Classifier" in str(call["system_prompt"]) for call in recap_runner.calls)


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
    assert "docs update" in controller.recap_text()
    assert "final QA signoff" in controller.recap_text()
    assert len(recap_runner.calls) == 2


def test_transcript_controller_retries_invalid_second_stage_output():
    controller = TranscriptSessionController(
        transcriber=_FakeTranscriber(),
        recap_runner=_RetryingSecondStageRecapRunner(),
    )
    controller.bind_session("session_retry", "Retry Session")
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
    assert controller._recap_runner.stage_two_calls == 2
    assert controller._recap_runner.audit_calls == 0
    assert controller._recap_runner.repair_calls == 0


def test_transcript_controller_surfaces_recap_stage_validation_failures(tmp_path):
    controller = TranscriptSessionController(
        transcriber=_FakeTranscriber(),
        recap_runner=_InvalidRecapStageRunner(),
    )
    session_id = f"session_invalid_{tmp_path.name}"
    controller.bind_session(session_id, "Invalid Session")
    controller.save_manual_transcript(
        "DM: The party recovered the ledger from the toll house. "
        "Mira: We should bring it to Captain Rusk. "
        "Thorn: We still do not know who the east dock contact is."
    )

    recap_ok = controller.generate_recap_now()
    snapshot = controller.snapshot()

    assert recap_ok is False
    assert snapshot["recap"]["status"] == "failed"
    assert "failed after 3 invalid responses" in snapshot["recap"]["last_error"]
    assert "stage1_summary" in snapshot["recap"]["last_error"]
    assert controller._store is not None
    assert (controller._store.recap_debug_dir / "stage1_summary_failure.md").exists()
    assert controller.recap_text() == ""


def test_transcript_controller_limits_gist_recap_sentence_count():
    controller = TranscriptSessionController(
        transcriber=_FakeTranscriber(),
        recap_runner=_FakeRecapRunner(),
    )
    controller.bind_session("session_gist_limit", "Gist Limit Session")
    controller.save_manual_transcript(
        "DM: The party tracked lantern lights to the toll house outside Harrowfen. "
        "Mira: We heard that the Moon Gate mattered to the cult. "
        "Thorn: The rear guard said he feared the ones under the water. "
        "Bram: We take the ledger and signet to Captain Rusk."
    )

    recap_ok = controller.generate_recap_now()
    recap_text = controller.recap_text()
    snapshot = controller.snapshot()

    assert recap_ok is True
    assert "Captain Rusk" in recap_text
    assert snapshot["recap"]["checkpoint_count"] == 2
    assert snapshot["recap"]["investigation_windows"] == 2
    assert controller._store is not None
    assert (controller._store.recap_dir / "stage2_refined.md").exists()
    assert not (controller._store.recap_dir / "stage3_repaired.md").exists()
    assert not (controller._store.recap_dir / "stage3_audit.md").exists()
    assert not (controller._store.recap_dir / "stage3_reaudit.md").exists()
    assert len(re.findall(r"[.!?]+(?:\\s|$)", recap_text)) <= 15


def test_transcript_controller_halt_finalizes_active_chunk_and_transcribes_it(qtbot, tmp_path):
    controller = TranscriptSessionController(
        transcriber=_FakeTranscriber(),
        recap_runner=_FakeRecapRunner(),
    )
    session_id = f"session_halt_{tmp_path.name}"
    controller.bind_session(session_id, "Halt Session")

    assert controller._store is not None
    chunk = controller._store.begin_live_chunk(
        "mic",
        device_id="mic-1",
        device_name="Desk Mic",
        file_suffix=".wav",
    )
    audio_path = controller._store.chunk_audio_path(chunk)
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"RIFFhalt")

    class _FakeRecorder:
        def __init__(self) -> None:
            self.halt_calls = 0

        def halt(self) -> None:
            self.halt_calls += 1
            controller._store.finalize_live_chunk(str(chunk["chunk_id"]), audio_path.stat().st_size)

    recorder = _FakeRecorder()
    controller._recorders = {"mic": recorder}

    controller.halt()

    qtbot.waitUntil(lambda: controller.snapshot()["counts"]["completed"] == 1, timeout=3000)

    manifest = controller._store.snapshot()
    assert recorder.halt_calls == 1
    assert controller.snapshot()["recording"] is False
    assert "investigated" in controller.transcript_text()
    assert any(
        event.get("message") == "Capture stopped. Final chunk saved and queued for transcription."
        for event in manifest.get("events", [])
    )


def test_transcript_controller_emits_recap_stream_updates():
    recap_runner = _FakeRecapRunner()
    controller = TranscriptSessionController(
        transcriber=_FakeTranscriber(),
        recap_runner=recap_runner,
    )
    controller.bind_session("session_stream_monitor", "Stream Monitor Session")
    controller.save_manual_transcript(
        "DM: The party recovered the ledger from the toll house. "
        "Mira: We should bring it to Captain Rusk. "
        "Thorn: We still do not know who the east dock contact is."
    )

    snapshots: list[dict[str, object]] = []
    controller.recapStreamChanged.connect(lambda payload: snapshots.append(dict(payload or {})))

    recap_ok = controller.generate_recap_now()
    final_snapshot = controller.recap_stream_snapshot()

    assert recap_ok is True
    assert snapshots
    assert any(bool(snapshot.get("running")) for snapshot in snapshots)
    assert final_snapshot["running"] is False
    assert "=== stage1_summary_attempt_01 ===" in str(final_snapshot["thinking_log"])
    assert "=== stage2_refine_attempt_01 ===" in str(final_snapshot["response_log"])
    assert "Captain Rusk" in str(final_snapshot["response_log"])
    assert "Drafting the initial recap from the transcript." in str(final_snapshot["thinking_log"])


def test_transcript_controller_does_not_prefill_response_log_before_response_tokens():
    controller = TranscriptSessionController(
        transcriber=_FakeTranscriber(),
        recap_runner=_FakeRecapRunner(),
    )

    controller._reset_recap_stream(running=True, host="http://127.0.0.1:11434", model="gpt-oss:20b")
    controller._mark_recap_stream_stage("stage1_summary_attempt_01")
    before_chunks = controller.recap_stream_snapshot()

    controller._append_recap_stream_chunk("stage1_summary_attempt_01", "thinking", "Need a short recap.")
    after_thinking = controller.recap_stream_snapshot()

    assert before_chunks["thinking_log"] == ""
    assert before_chunks["response_log"] == ""
    assert "=== stage1_summary_attempt_01 ===" in str(after_thinking["thinking_log"])
    assert "Need a short recap." in str(after_thinking["thinking_log"])
    assert after_thinking["response_log"] == ""


def test_gist_stage_prompts_are_concise_and_sentence_limited():
    controller = TranscriptSessionController(
        transcriber=_FakeTranscriber(),
        recap_runner=_FakeRecapRunner(),
    )

    stage_one_prompt = controller._stage_one_recap_system_prompt()
    stage_two_prompt = controller._stage_two_recap_system_prompt()

    assert "gist recap" in stage_one_prompt.lower()
    assert "15 sentences" in stage_one_prompt
    assert "omit minor tactical detail" in stage_one_prompt.lower()
    assert "past tense" in stage_one_prompt.lower()
    assert "gist recap" in stage_two_prompt.lower()
    assert "prefer gist over detail" in stage_two_prompt.lower()
    assert "15 sentences" in stage_two_prompt
    assert "past tense" in stage_two_prompt.lower()


def test_ollama_runner_truncates_reasoning_only(monkeypatch):
    class _FakeStreamingResponse:
        def __init__(self, lines: list[str]) -> None:
            self._lines = [line.encode("utf-8") for line in lines]
            self._index = 0

        def readline(self) -> bytes:
            if self._index >= len(self._lines):
                return b""
            line = self._lines[self._index]
            self._index += 1
            return line

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    long_thinking = "loop " * 7000
    payload_lines = [
        '{"model":"gpt-oss:20b","response":"","thinking":"' + long_thinking + '","done":false}\n',
        '{"model":"gpt-oss:20b","response":"final visible answer","thinking":"","done":true,"prompt_eval_count":123,"eval_count":45}\n',
    ]
    monkeypatch.setattr(
        session_transcript.urllib_request,
        "urlopen",
        lambda req, timeout=300: _FakeStreamingResponse(payload_lines),
    )

    streamed_chunks: list[tuple[str, str]] = []
    result = OllamaRecapRunner().generate(
        "http://127.0.0.1:11434",
        "gpt-oss:20b",
        "audit",
        "prompt",
        stream_callback=lambda channel, text: streamed_chunks.append((channel, text)),
    )

    assert result.text == "final visible answer"
    assert result.thinking_truncated is True
    assert "reasoning truncated after about" in result.thinking_text
    assert any(channel == "response" and "final visible answer" in text for channel, text in streamed_chunks)
    assert any(channel == "thinking" and "reasoning truncated after about" in text for channel, text in streamed_chunks)


def test_recap_panel_warns_when_transcript_is_above_auto_limit(qtbot, monkeypatch):
    widget = SessionCreatorWidget()
    qtbot.addWidget(widget)
    widget._create_session()

    huge_transcript = "DM: test.\n" * 30000
    widget._transcript_controller.save_manual_transcript(huge_transcript)

    captured: dict[str, str] = {}
    request_count = {"count": 0}

    def _fake_warning(parent, title, message):
        captured["title"] = title
        captured["message"] = message
        return None

    def _fake_request_recap() -> None:
        request_count["count"] += 1

    monkeypatch.setattr(session_transcript.QMessageBox, "warning", staticmethod(_fake_warning))
    monkeypatch.setattr(widget._transcript_controller, "request_recap", _fake_request_recap)

    widget.recap_panel._on_generate_clicked()

    assert request_count["count"] == 0
    assert captured["title"] == "Cannot Auto Generate Recap"
    assert "Cannot auto generate recap" in captured["message"]
    assert str(session_transcript.RECAP_AUTO_GENERATE_MAX_TOKENS) in captured["message"]


def test_recap_panel_autosaves_idle_editor_text(qtbot):
    widget = SessionCreatorWidget()
    qtbot.addWidget(widget)
    widget._create_session()

    widget.recap_panel.recap_editor.setPlainText("## Session Recap\n\nManual recap.")

    qtbot.waitUntil(lambda: widget._transcript_controller.recap_text() == "## Session Recap\n\nManual recap.")

    assert widget.recap_panel.recap_editor.isReadOnly() is False


def test_recap_halt_returns_to_idle_without_failed_error():
    controller = TranscriptSessionController(
        transcriber=_FakeTranscriber(),
        recap_runner=_FakeRecapRunner(),
    )
    controller.bind_session("session_recap_halt", "Recap Halt Session")

    controller._store.mark_recap_running("gpt-oss:20b")
    controller._reset_recap_stream(running=True, host="http://127.0.0.1:11434", model="gpt-oss:20b")
    controller._append_recap_stream_chunk("stage1_summary_attempt_01", "thinking", "Looping reasoning.")
    controller._append_recap_stream_chunk("stage1_summary_attempt_01", "response", "Draft output.")

    controller.halt()

    snapshot = controller.snapshot()
    stream_snapshot = controller.recap_stream_snapshot()

    assert snapshot["recap"]["status"] == "idle"
    assert snapshot["recap"]["last_error"] == ""
    assert stream_snapshot["running"] is False
    assert stream_snapshot["thinking_log"] == ""
    assert "Draft output." in str(stream_snapshot["response_log"])


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
    assert isinstance(widget.recap_panel.generate_btn, QPushButton)
    assert widget.recap_panel.recap_editor.isReadOnly() is False
    assert widget.transcript_panel.refresh_devices_btn.isEnabled()
    assert widget.recap_panel.generate_btn.isEnabled()
    transcript_action_height = widget.transcript_panel.start_btn.height()
    assert transcript_action_height == widget.transcript_panel.import_btn.height()
    assert transcript_action_height == widget.transcript_panel.run_pending_btn.height()
    assert transcript_action_height == widget.transcript_panel.retry_failed_btn.height()
    assert transcript_action_height == widget.transcript_panel.save_editor_btn.height()
    assert transcript_action_height == widget.transcript_panel.refresh_devices_btn.height()
    assert transcript_action_height == widget.transcript_panel.reload_editor_btn.height()
    assert transcript_action_height == widget.transcript_panel.use_generated_btn.height()
    assert widget.transcript_panel.start_btn.width() == widget.transcript_panel.import_btn.width()
    assert widget.transcript_panel.start_btn.width() == widget.transcript_panel.run_pending_btn.width()
    assert widget.transcript_panel.start_btn.width() == widget.transcript_panel.retry_failed_btn.width()
    assert widget.transcript_panel.start_btn.width() == widget.transcript_panel.save_editor_btn.width()
    assert widget.transcript_panel.start_btn.width() == widget.transcript_panel.reload_editor_btn.width()
    assert widget.transcript_panel.start_btn.width() == widget.transcript_panel.use_generated_btn.width()
    assert transcript_action_height < session_transcript.ACTION_ROW_HEIGHT
    assert not hasattr(widget.transcript_panel, "whisper_cli_edit")
    assert widget.transcript_panel.halt_btn.isHidden()
    assert widget.transcript_panel.start_btn.accessibleName() == "Start capture"
    assert widget.recap_panel.generate_btn.accessibleName() == "Generate recap"
    assert widget.recap_panel.generate_btn.text() == "AutoRecap"
    assert widget.recap_panel.generate_btn.height() < session_transcript.ACTION_ROW_HEIGHT

    widget._transcript_controller._recorders = {"mic": object()}
    widget._transcript_controller.stateChanged.emit()
    qtbot.waitUntil(lambda: widget.transcript_panel.start_btn.accessibleName() == "Stop capture")

    widget._transcript_controller._recorders = {}
    assert widget._transcript_controller._store is not None
    widget._transcript_controller._store.mark_recap_running("gpt-oss:20b")
    widget._transcript_controller.stateChanged.emit()
    qtbot.waitUntil(
        lambda: widget.recap_panel.generate_btn.accessibleName() == "Stop recap"
        and widget.recap_panel.recap_editor.isReadOnly() is True
    )

    widget._transcript_controller._reset_recap_stream(
        running=True,
        host="http://127.0.0.1:11434",
        model="gpt-oss:20b",
        message="Recap generation started.",
    )
    widget._transcript_controller._append_recap_stream_chunk(
        "stage2_refine_attempt_01",
        "thinking",
        "Checking recap coverage.",
    )
    widget._transcript_controller._append_recap_stream_chunk(
        "stage2_refine_attempt_01",
        "response",
        "Visible response text.",
    )

    qtbot.waitUntil(
        lambda: widget.recap_panel.recap_heading_label.text() == "Final Recap"
        and "Visible response text." in widget.recap_panel.recap_editor.toPlainText()
    )

    widget._transcript_controller._finish_recap_stream("Final recap is ready.")
    widget._transcript_controller.save_recap_text("## Session Recap\n\nSaved text.")
    qtbot.waitUntil(
        lambda: widget.recap_panel.recap_editor.isReadOnly() is False
        and widget.recap_panel.recap_heading_label.text() == "Final Recap"
        and "Saved text." in widget.recap_panel.recap_editor.toPlainText()
    )
