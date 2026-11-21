# 21.11.26

import pytest

from VibraVid.core.ui.tracker import context_tracker
from VibraVid.services._base import tmdb_artwork, tv_display_manager, tv_download_manager


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(tmdb_artwork, "resolve_episode_artwork_url", lambda *a, **k: None)
    prev_id, prev_filter = context_tracker.download_id, context_tracker.audio_filter
    context_tracker.download_id, context_tracker.audio_filter = None, None
    yield
    context_tracker.download_id, context_tracker.audio_filter = prev_id, prev_filter


def _season(numbers):
    class _Scrape:
        def getEpisodeSeasons(self, season):
            return [{"number": n, "name": f"ep{n}"} for n in numbers]

    return _Scrape()


def _downloaded(numbers, selection):
    got = []

    def _download(episode, season, index):
        got.append(episode["number"])
        return (None, False, None)

    tv_download_manager.process_episode_download(
        index_season_selected=2,
        scrape_serie=_season(numbers),
        download_video_callback=_download,
        download_all=False,
        episode_selection=selection,
    )
    return got


def test_star_downloads_each_episode_once_when_numbers_exceed_the_count():
    """A season numbered 13-24 has 12 entries: `*` expanded to 1..24 and each value matched once as index, once as number."""
    assert _downloaded(range(13, 25), "*") == list(range(13, 25))


def test_open_range_does_not_repeat_the_last_episode():
    assert _downloaded([1, 2, 3, 5], "1-") == [1, 2, 3, 5]


def test_an_episode_number_beyond_the_count_still_selects_that_episode():
    assert _downloaded(range(13, 25), "14") == [14]


def _answers(monkeypatch, *answers):
    replies = iter(answers)
    monkeypatch.setattr(tv_display_manager.msg, "ask", lambda *a, **k: next(replies))


def test_the_season_prompt_takes_a_range_after_an_invalid_season(monkeypatch):
    """The re-prompt parsed its answer with int() only: `1-2` fell through to a second, unguarded prompt and crashed."""
    _answers(monkeypatch, "1-2")
    assert tv_display_manager.validate_selection([9], [1, 2, 3]) == [1, 2]


def test_the_season_prompt_asks_again_until_a_season_exists(monkeypatch):
    _answers(monkeypatch, "x", "7", "3")
    assert tv_display_manager.validate_selection([9], [1, 2, 3]) == [3]


def test_a_typo_in_a_range_end_is_asked_again_instead_of_selecting_to_the_end(monkeypatch):
    _answers(monkeypatch, "2-3")
    assert tv_display_manager.manage_selection("1-5x", 10) == [2, 3]
    assert tv_display_manager.manage_selection("8-", 10) == [8, 9, 10]
    assert tv_display_manager.manage_selection("8-*", 10) == [8, 9, 10]


def _seasons_called(numbers, season_selection, episode_selection=None):
    """(season, download_all, episode_selection) of every season process_season_selection hands to the callback."""
    from VibraVid.services._base.object import Season, SeasonManager

    manager = SeasonManager()
    for number in numbers:
        manager.add(Season(number=number))

    class _Scrape:
        seasons_manager = manager

    calls = []
    tv_download_manager.process_season_selection(
        _Scrape(), len(numbers), season_selection, episode_selection,
        lambda season_number, download_all, episode_selection: calls.append((season_number, download_all, episode_selection)),
    )
    return calls


def test_an_episode_selection_applies_to_each_selected_season():
    """`-S 1-2 -E 1` downloaded both seasons entirely: the episode selection was dropped as soon as two seasons were picked."""
    assert _seasons_called([1, 2, 3], "1-2", "1") == [(1, False, "1"), (2, False, "1")]


def test_several_seasons_without_an_episode_selection_download_everything():
    assert _seasons_called([1, 2, 3], "1,3") == [(1, True, None), (3, True, None)]
    assert _seasons_called([1, 2, 3], "*", "1") == [(1, True, None), (2, True, None), (3, True, None)]


def test_a_repeated_season_is_downloaded_once():
    assert _seasons_called([1, 2], "1,1") == [(1, False, None)]
    assert _seasons_called([1, 2, 3], "1-2,2") == [(1, True, None), (2, True, None)]


def test_a_season_number_wins_over_a_position():
    """`-S 4` on seasons 1,2,4,5 picked the 4th entry (season 5); `-S 1` on seasons 0-3 picked season 0."""
    assert _seasons_called([1, 2, 4, 5], "4") == [(4, False, None)]
    assert _seasons_called([0, 1, 2, 3], "1") == [(1, False, None)]
    assert _seasons_called([1, 2, 4, 5], "1-3") == [(1, True, None), (2, True, None)]
    assert _seasons_called([1, 2, 4, 5], "2-") == [(2, True, None), (4, True, None), (5, True, None)]


def test_a_position_is_used_when_no_season_has_that_number():
    assert _seasons_called([2019, 2020, 2021], "2") == [(2020, False, None)]
    assert _seasons_called([2019, 2020, 2021], "2-3") == [(2020, True, None), (2021, True, None)]


def test_a_reversed_season_range_says_so(capsys):
    assert _seasons_called([1, 2, 3], "3-1") == []
    assert "3-1" in capsys.readouterr().out
