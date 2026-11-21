# 21.11.26

import pytest
from textual.app import App

from VibraVid.tui.widgets.fuzzy_list import FuzzyItem, FuzzyList


def _items(*keys):
    return [FuzzyItem(key=k, label=k.upper(), payload=(k,)) for k in keys]


class _ListApp(App):
    def __init__(self):
        super().__init__()
        self.highlighted: list[str] = []

    def compose(self):
        yield FuzzyList(id="fl")

    def on_fuzzy_list_highlighted(self, event: FuzzyList.Highlighted) -> None:
        self.highlighted.append(event.item.key)


@pytest.mark.anyio
async def test_refresh_keeps_the_highlighted_title():
    """Sites finishing during a global search re-render the list: Enter/d must still act on the same title."""
    app = _ListApp()
    async with app.run_test() as pilot:
        fuzzy = app.query_one(FuzzyList)
        fuzzy.set_items(_items("a", "b", "c"))
        await pilot.pause()
        fuzzy.query_one("#fuzzy-list").index = 1
        await pilot.pause()
        assert fuzzy.get_highlighted_item().key == "b"
        app.highlighted.clear()

        fuzzy.set_items(_items("new", "a", "b", "c"), reset_filter=False)
        await pilot.pause()

        assert fuzzy.get_highlighted_item().key == "b"
        assert app.highlighted == []  # same title: no spurious Highlighted (it would reset the provider pick)


@pytest.mark.anyio
async def test_refresh_falls_back_to_the_first_row_when_the_title_is_gone():
    app = _ListApp()
    async with app.run_test() as pilot:
        fuzzy = app.query_one(FuzzyList)
        fuzzy.set_items(_items("a", "b"))
        await pilot.pause()
        fuzzy.query_one("#fuzzy-list").index = 1
        await pilot.pause()
        app.highlighted.clear()

        fuzzy.set_items(_items("x", "a"), reset_filter=False)
        await pilot.pause()

        assert fuzzy.get_highlighted_item().key == "x"
        assert app.highlighted == ["x"]
