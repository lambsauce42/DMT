"""Pytest configuration for DMT tests.

This ensures pytest-qt uses PySide6 (matching the application code) instead of
auto-detecting a different Qt binding which causes QWidget type mismatches.

CRITICAL: QT_API must be set before any Qt bindings are imported.
"""

import os
from pathlib import Path

os.environ["QT_API"] = "pyside6"
os.environ["PYTEST_QT_API"] = "pyside6"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DMT_TEST_MODE", "1")

import pytest

_TIER_MARKERS = ("tier0", "tier1", "tier2")


@pytest.fixture(autouse=True)
def _isolate_test_save_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    test_save_root = tmp_path / "DMT"
    test_save_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DMT_TEST_SAVE_DIR", str(test_save_root))

# Sorted snapshot of current test files. New files must either:
# 1) add an explicit tier marker, or
# 2) be added here (and optionally to tier0/tier2) so tiering stays intentional.
_KNOWN_TEST_FILES = frozenset(
    {
        "test_adjusted_xp_rounding.py",
        "test_app_loading_indicator.py",
        "test_app_tab_close_host_cleanup_regression.py",
        "test_applets_init.py",
        "test_character_sheet_panel_splitter_lock.py",
        "test_compact_nav_duplicate_name_deletion.py",
        "test_compact_nav_tree_load_safety.py",
        "test_dungeon_applet_click_all.py",
        "test_dungeon_applet_ui.py",
        "test_dungeon_draw_colors_and_resize.py",
        "test_dungeon_entity_token_upgrade.py",
        "test_dungeon_fow.py",
        "test_dungeon_inspector.py",
        "test_dungeon_items.py",
        "test_dungeon_join_connect_fallback.py",
        "test_dungeon_lifecycle_cleanup.py",
        "test_dungeon_online_reconnect_behavior.py",
        "test_dungeon_online_security.py",
        "test_dungeon_online_state.py",
        "test_dungeon_online_undo_scope.py",
        "test_dungeon_origin.py",
        "test_dungeon_painter_cleanup.py",
        "test_dungeon_polygon.py",
        "test_dungeon_undo_redo.py",
        "test_encounter_crash.py",
        "test_encounter_custom_factor.py",
        "test_encounter_engine_errors.py",
        "test_encounter_party_size_limit.py",
        "test_encounter_selector_dialog.py",
        "test_encounter_tags_and_sort.py",
        "test_encounter_ui_layout.py",
        "test_eraser_behavior.py",
        "test_home_card_padding.py",
        "test_home_online_launch.py",
        "test_home_tab_behavior.py",
        "test_investigation_fixes.py",
        "test_item_creator_crash.py",
        "test_item_creator_filtering.py",
        "test_item_creator_icons.py",
        "test_item_export.py",
        "test_item_file_format.py",
        "test_item_renderer_required_level.py",
        "test_link_navigation_hooks.py",
        "test_loot_applet_filters.py",
        "test_loot_applet_results_io.py",
        "test_loot_curves.py",
        "test_loot_probabilities.py",
        "test_loot_probability_column.py",
        "test_maps_dialog.py",
        "test_models_unit.py",
        "test_modify_and_add_transient.py",
        "test_monster_card_ui.py",
        "test_multiplier_lookup.py",
        "test_navigate_widget.py",
        "test_navigate_widget_duplicate_destructive_actions.py",
        "test_navigate_widget_regressions.py",
        "test_navigation_context_sources.py",
        "test_navigation_group_shape.py",
        "test_navigation_trash.py",
        "test_npc_character_links_character_ui.py",
        "test_npc_character_links_npc_ui.py",
        "test_npc_character_links_persistence.py",
        "test_npc_character_links_rename_delete.py",
        "test_npc_crash.py",
        "test_npc_database_logic.py",
        "test_online_authz.py",
        "test_online_client_connect.py",
        "test_online_client_decoder_reset.py",
        "test_online_client_persistent_id_reuse.py",
        "test_online_reconnect_persistent_id_regression.py",
        "test_online_controller_reconnect_persistent_id.py",
        "test_online_protocol.py",
        "test_pdfium_viewer_widget_events.py",
        "test_persistence.py",
        "test_player_sheets_archive.py",
        "test_player_sheets_delete_button.py",
        "test_player_sheets_equipment_layout.py",
        "test_player_sheets_events.py",
        "test_player_sheets_filters.py",
        "test_player_sheets_utils.py",
        "test_room_merging.py",
        "test_save_paths.py",
        "test_session_creator_id_uniqueness.py",
        "test_session_creator_lifecycle.py",
        "test_session_creator_slash_links.py",
        "test_session_creator_widget.py",
        "test_session_file_pool_layout.py",
        "test_session_file_pool_limits.py",
        "test_session_file_pool_persistence.py",
        "test_session_file_pool_preview.py",
        "test_session_text_links.py",
        "test_suggest_greedy_is_deterministic.py",
        "test_target_xp_sums.py",
        "test_terminal_logic.py",
        "test_terminal_widget_inline_prompt.py",
        "test_tab_workspace_close_cleanup.py",
        "test_tab_workspace_detach_attach.py",
        "test_ui_interactions.py",
        "test_ui_interactions_expanded.py",
    }
)

_TIER0_FILES = frozenset(
    {
        "test_adjusted_xp_rounding.py",
        "test_encounter_engine_errors.py",
        "test_encounter_tags_and_sort.py",
        "test_item_file_format.py",
        "test_item_renderer_required_level.py",
        "test_models_unit.py",
        "test_multiplier_lookup.py",
        "test_npc_character_links_persistence.py",
        "test_npc_database_logic.py",
        "test_online_authz.py",
        "test_online_client_decoder_reset.py",
        "test_online_protocol.py",
        "test_persistence.py",
        "test_player_sheets_filters.py",
        "test_player_sheets_utils.py",
        "test_save_paths.py",
        "test_suggest_greedy_is_deterministic.py",
        "test_target_xp_sums.py",
        "test_terminal_logic.py",
    }
)

_TIER2_FILES = frozenset(
    {
        "test_character_sheet_panel_splitter_lock.py",
        "test_dungeon_applet_click_all.py",
        "test_dungeon_draw_colors_and_resize.py",
        "test_dungeon_fow.py",
        "test_dungeon_items.py",
        "test_dungeon_online_reconnect_behavior.py",
        "test_dungeon_online_security.py",
        "test_dungeon_online_state.py",
        "test_dungeon_online_undo_scope.py",
        "test_dungeon_undo_redo.py",
        "test_home_online_launch.py",
        "test_link_navigation_hooks.py",
        "test_maps_dialog.py",
        "test_navigate_widget.py",
        "test_navigate_widget_duplicate_destructive_actions.py",
        "test_navigate_widget_regressions.py",
        "test_navigation_trash.py",
        "test_online_client_connect.py",
        "test_online_client_persistent_id_reuse.py",
        "test_online_reconnect_persistent_id_regression.py",
        "test_online_controller_reconnect_persistent_id.py",
        "test_pdfium_viewer_widget_events.py",
        "test_player_sheets_archive.py",
        "test_player_sheets_delete_button.py",
        "test_player_sheets_equipment_layout.py",
        "test_room_merging.py",
        "test_app_tab_close_host_cleanup_regression.py",
        "test_session_creator_slash_links.py",
        "test_session_creator_widget.py",
        "test_session_file_pool_layout.py",
        "test_session_file_pool_preview.py",
        "test_session_text_links.py",
        "test_tab_workspace_close_cleanup.py",
        "test_ui_interactions_expanded.py",
    }
)


def _parse_tier(raw: str, flag: str) -> int:
    try:
        tier = int(raw)
    except (TypeError, ValueError) as exc:
        raise pytest.UsageError(f"{flag} expects 0, 1, or 2; got {raw!r}.") from exc
    if tier not in (0, 1, 2):
        raise pytest.UsageError(f"{flag} expects 0, 1, or 2; got {tier}.")
    return tier


def _selected_tiers(config: pytest.Config) -> set[int]:
    raw_subset = config.getoption("--tiers")
    if raw_subset:
        selected = set()
        for token in raw_subset.split(","):
            token = token.strip()
            if not token:
                continue
            selected.add(_parse_tier(token, "--tiers"))
        if not selected:
            raise pytest.UsageError("--tiers did not include any valid tier values.")
        return selected

    max_tier = _parse_tier(config.getoption("--tier-max"), "--tier-max")
    return set(range(max_tier + 1))


def _registered_tier_for_file(file_name: str) -> int | None:
    if file_name in _TIER0_FILES:
        return 0
    if file_name in _TIER2_FILES:
        return 2
    if file_name in _KNOWN_TEST_FILES:
        return 1
    return None


def _item_tier_markers(item: pytest.Item) -> list[str]:
    names = [m.name for m in item.iter_markers() if m.name in _TIER_MARKERS]
    return sorted(set(names))


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("tiered-tests")
    group.addoption(
        "--tier-max",
        action="store",
        default="1",
        help="Run tests up to this tier (0/1/2). Default: 1.",
    )
    group.addoption(
        "--tiers",
        action="store",
        default=None,
        help="Run only exact comma-separated tiers (example: --tiers 0,2).",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "tier0: Fast, logic-focused tests.")
    config.addinivalue_line("markers", "tier1: Standard feature/widget integration tests.")
    config.addinivalue_line("markers", "tier2: Heavy/slow integration and full-flow tests.")

    unknown_tier_files = (_TIER0_FILES | _TIER2_FILES) - _KNOWN_TEST_FILES
    if unknown_tier_files:
        raise pytest.UsageError(
            "Tier registry references files not listed in _KNOWN_TEST_FILES: "
            + ", ".join(sorted(unknown_tier_files))
        )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    selected = _selected_tiers(config)
    selected_markers = {f"tier{tier}" for tier in selected}
    keep: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    missing_tier_files: set[str] = set()
    multi_tier_items: list[str] = []

    for item in items:
        markers = _item_tier_markers(item)
        if not markers:
            file_name = Path(str(item.fspath)).name
            registered_tier = _registered_tier_for_file(file_name)
            if registered_tier is None:
                missing_tier_files.add(file_name)
                continue
            else:
                item.add_marker(getattr(pytest.mark, f"tier{registered_tier}"))
                markers = [f"tier{registered_tier}"]

        if len(markers) != 1:
            multi_tier_items.append(f"{item.nodeid} -> {markers}")
            continue

        if markers[0] in selected_markers:
            keep.append(item)
        else:
            deselected.append(item)

    if missing_tier_files or multi_tier_items:
        problems: list[str] = []
        if missing_tier_files:
            problems.append(
                "Missing tier for files: "
                + ", ".join(sorted(missing_tier_files))
                + ". Add @pytest.mark.tier0/1/2 or register the file in tests/conftest.py."
            )
        if multi_tier_items:
            problems.append(
                "Multiple tier markers found: "
                + "; ".join(sorted(multi_tier_items)[:8])
            )
        raise pytest.UsageError(" ".join(problems))

    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = keep
