# 12.11.26

import re

import pytest
from playwright.sync_api import expect

PAGES = ["/", "/downloads/", "/watchlist/", "/settings/", "/logs/"]


def open_more_menu_if_phone(page, device):
    if device == "mobile":
        page.get_by_role("button", name="More").click()


def assert_no_horizontal_scroll(page):
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0, f"{page.url} scrolls sideways by {overflow}px"


def search_for(page, query, site_name):
    page.goto(f"/search/?query={query}&site={site_name}")


@pytest.mark.parametrize("path", PAGES)
def test_pages_render_without_errors_or_sideways_scroll(page, path):
    page.goto(path)
    expect(page.locator("h1").first).to_be_visible()
    assert_no_horizontal_scroll(page)
    assert page.errors == []


def test_navigation_reaches_every_section_and_marks_the_current_one(page, device):
    page.goto("/")
    nav = page.get_by_role("navigation", name="Sections")
    for label, heading in (("Download", "Nothing running"), ("Watchlist", "Watchlist"), ("Search", "What do you want to watch?")):
        nav.get_by_role("link", name=label, exact=True).click()
        expect(nav.get_by_role("link", name=label, exact=True)).to_have_attribute("aria-current", "page")
        expect(page.get_by_text(heading).first).to_be_visible()

    for label in ("Settings", "Logs"):
        open_more_menu_if_phone(page, device)
        nav.get_by_role("link", name=label, exact=True).click()
        expect(page.get_by_role("heading", level=1, name=label)).to_be_visible()
        expect(nav.get_by_role("link", name=label, exact=True, include_hidden=True)).to_have_attribute("aria-current", "page")
    assert page.errors == []


def test_desktop_uses_a_sidebar_and_phones_a_bottom_tab_bar(page, device):
    page.goto("/")
    box = page.get_by_role("navigation", name="Sections").get_by_role("link", name="Search").bounding_box()
    more = page.get_by_role("button", name="More")
    if device == "desktop":
        assert box["x"] < 232
        expect(more).to_be_hidden()
    else:
        assert box["y"] > 844 - 80
        expect(more).to_be_visible()


@pytest.mark.parametrize("device", ["mobile"])
def test_phone_more_menu_opens_closes_with_escape_and_returns_focus(page):
    page.goto("/")
    more = page.get_by_role("button", name="More")
    settings = page.get_by_role("link", name="Settings", exact=True)
    expect(settings).to_be_hidden()
    more.click()
    expect(more).to_have_attribute("aria-expanded", "true")
    expect(settings).to_be_visible()
    page.keyboard.press("Escape")
    expect(settings).to_be_hidden()
    expect(more).to_be_focused()


@pytest.mark.parametrize("device", ["mobile"])
def test_touch_targets_are_at_least_44px_on_phones(page, site_name):
    search_for(page, "harbor", site_name)
    targets = page.locator(".cn-menu > a, .cn-menu-more, .cn-pick .cn-mini, .cn-opt:visible")
    for index in range(targets.count()):
        height = targets.nth(index).bounding_box()["height"]
        assert height >= 44, f"{targets.nth(index).inner_text()!r} is {height}px tall"


def test_search_shows_results_with_visible_actions_and_filters_by_kind(page, site_name):
    page.goto("/")
    page.get_by_label("What do you want to watch?").fill("harbor")
    page.get_by_role("search").get_by_role("button", name="Search").click()

    tiles = page.locator("#cn-results .cn-tile")
    expect(tiles).to_have_count(3)
    expect(page.get_by_role("heading", level=1)).to_have_text("harbor")
    expect(tiles.first.get_by_role("button", name="Download")).to_be_visible()
    expect(tiles.nth(1).get_by_role("button", name="Episodes")).to_be_visible()
    expect(tiles.first.get_by_role("button", name="Add to watchlist")).to_be_visible()

    page.locator("#cn-kinds").get_by_role("button", name="Movies").click()
    expect(page.locator("#cn-results .cn-tile:visible")).to_have_count(1)
    expect(page.locator("#cn-count")).to_have_text("1")
    assert_no_horizontal_scroll(page)
    assert page.errors == []


def test_quality_options_stay_folded_until_asked(page, site_name):
    search_for(page, "harbor", site_name)
    tile = page.locator("#cn-results .cn-tile").first
    quality = tile.get_by_label("Video quality")
    expect(quality).to_be_hidden()
    tile.get_by_text("Quality and tracks").click()
    expect(quality).to_be_visible()


def test_series_page_counts_selected_episodes_and_shows_the_season_tray(page, site_name):
    search_for(page, "orchard", site_name)
    page.locator("#cn-results .cn-tile").nth(1).get_by_role("button", name="Episodes").click()

    expect(page.get_by_role("heading", level=1, name="Glass Orchard")).to_be_visible()
    expect(page.get_by_role("tab")).to_have_count(2)
    episodes = page.locator('.cn-spanel[data-season="1"] .cn-ep')
    episodes.nth(0).click()
    episodes.nth(1).click()
    expect(page.locator("#cn-go-1")).to_have_text("Download 2 episodes")

    page.get_by_role("tab", name=re.compile("Season 2")).click()
    expect(page.locator('.cn-spanel[data-season="2"]')).to_be_visible()
    page.get_by_role("checkbox", name="Select season 2 for a batch download").check()
    expect(page.locator("#cn-tray")).to_have_class(re.compile("is-show"))
    expect(page.locator("#cn-tray-txt")).to_contain_text("1 season selected")
    assert_no_horizontal_scroll(page)
    assert page.errors == []


def test_downloads_page_shows_the_running_download_live(page, active_download):
    page.goto("/downloads/")
    expect(page.locator("#cn-hero-title")).to_have_text("Night Harbor")
    expect(page.locator("#cn-hero-pct")).to_contain_text("42")
    expect(page.get_by_role("progressbar")).to_have_attribute("aria-valuenow", "42")
    expect(page.locator("#cn-hero-stop")).to_be_visible()
    expect(page.locator("#cn-reel-active .cn-ln")).to_have_count(1)
    expect(page.locator("#cn-nav-active")).to_have_text("1")
    assert page.errors == []


def test_downloads_page_explains_an_empty_queue(page):
    page.goto("/downloads/")
    expect(page.get_by_text("No downloads running.")).to_be_visible()
    expect(page.get_by_text("Queue is empty.")).to_be_visible()
    expect(page.locator("#cn-nav-active")).to_be_hidden()
    expect(page.locator(".cn-skel")).to_have_count(0)


def test_watchlist_empty_state_points_to_search(page):
    page.goto("/watchlist/")
    expect(page.get_by_text("Nothing on your watchlist yet")).to_be_visible()
    page.get_by_role("link", name="Find something to watch").click()
    expect(page).to_have_url(re.compile(r"/$"))


def test_settings_tabs_follow_keyboard_and_deep_links(page):
    page.goto("/settings/#arr")
    expect(page.get_by_role("tab", name="ARR")).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("tabpanel", name="ARR")).to_be_visible()

    page.get_by_role("tab", name="ARR").focus()
    page.keyboard.press("ArrowRight")
    expect(page.get_by_role("tab", name="Extensions")).to_be_focused()
    expect(page.get_by_role("tabpanel", name="Extensions")).to_be_visible()
    expect(page).to_have_url(re.compile("#plug$"))


def test_logs_list_rows_are_keyboard_buttons(page):
    page.goto("/logs/")
    expect(page.locator("#cn-logs-list-logs")).not_to_have_attribute("aria-busy", "true")
    rows = page.locator("#cn-logs-list-logs button.cn-ln")
    if rows.count():
        rows.first.focus()
        page.keyboard.press("Enter")
        expect(rows.first).to_have_attribute("aria-current", "true")
    else:
        expect(page.locator("#cn-logs-list-logs")).to_contain_text("No log files found.")


def test_login_hides_the_app_until_signed_in(page, monkeypatch):
    monkeypatch.setenv("VIBRAVID_USERNAME", "admin")
    monkeypatch.setenv("VIBRAVID_PASSWORD", "s3cret")
    page.goto("/watchlist/")
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible()

    page.get_by_label("Username").fill("admin")
    page.get_by_label("Password", exact=True).fill("wrong")
    page.get_by_role("button", name="Show password").click()
    expect(page.get_by_label("Password", exact=True)).to_have_attribute("type", "text")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("alert")).to_be_visible()

    page.get_by_label("Password", exact=True).fill("s3cret")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", level=1, name="Watchlist")).to_be_visible()
    assert_no_horizontal_scroll(page)


def test_reduced_motion_turns_animations_off(open_context, device):
    page = open_context(device, reduced_motion="reduce").new_page()
    page.goto("/watchlist/")
    duration = page.locator(".cn-page-hd").evaluate("node => parseFloat(getComputedStyle(node).animationDuration)")
    assert duration < 0.01


def test_italian_interface_translates_the_new_shell(open_context, live_url, device):
    context = open_context(device)
    context.add_cookies([{"name": "vv_lang", "value": "it", "url": live_url}])
    page = context.new_page()
    page.goto("/")
    expect(page.get_by_text("Cosa vuoi guardare?")).to_be_visible()
    expect(page.get_by_role("navigation", name="Sezioni")).to_be_visible()
    if device == "mobile":
        expect(page.get_by_role("button", name="Altro")).to_be_visible()
