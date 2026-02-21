import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from player_sheets import PlayerSheetEntry, PlayerSheetsManager, filter_entries


def test_tag_filter_matches_single_and_multiple() -> None:
    entries = [
        PlayerSheetEntry(name="A", pdf_path="a.pdf", tags=["Elf", "Ranger", "Scout"]),
        PlayerSheetEntry(name="B", pdf_path="b.pdf", tags=["Orc"]),
    ]

    assert filter_entries(entries, tag_query="elf") == [entries[0]]
    assert filter_entries(entries, tag_query="elf scout") == [entries[0]]
    assert filter_entries(entries, tag_query="elf, cleric") == []


def test_context_filtering_world_campaign_group() -> None:
    entry1 = PlayerSheetEntry(
        name="A",
        pdf_path="a.pdf",
        world="Eldervale",
        campaign="Ashen Crown",
        group="Silver Lances",
    )
    entry2 = PlayerSheetEntry(
        name="B",
        pdf_path="b.pdf",
        world="Eldervale",
        campaign="Hollow Pact",
        group="Night Cartel",
    )
    entry3 = PlayerSheetEntry(
        name="C",
        pdf_path="c.pdf",
        world="Stormreach",
        campaign="Iron Meridian",
        group="Cinderwatch",
    )
    entries = [entry1, entry2, entry3]

    assert filter_entries(entries, world="Eldervale") == [entry1, entry2]
    assert filter_entries(entries, world="Eldervale", campaign="Ashen Crown") == [entry1]
    assert filter_entries(entries, campaign="Iron Meridian") == [entry3]
    assert filter_entries(entries, group="Night Cartel") == [entry2]


def test_add_sheet_updates_filtered_list() -> None:
    entry = PlayerSheetEntry(
        name="A",
        pdf_path="a.pdf",
        world="Stormreach",
        campaign="Iron Meridian",
        group="Cinderwatch",
    )
    manager = PlayerSheetsManager(entries=[entry])
    manager.set_filters(world="Stormreach", campaign=None, group=None, tag_query="")
    before = manager.filtered_entries()

    manager.add_sheet(
        PlayerSheetEntry(
            name="B",
            pdf_path="b.pdf",
            world="Stormreach",
            campaign="Iron Meridian",
            group="Cinderwatch",
            tags=["fighter"],
        )
    )

    after = manager.filtered_entries()
    assert len(after) == len(before) + 1
