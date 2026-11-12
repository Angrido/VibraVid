# VibraVid Web GUI design system

Source of truth for the Django GUI (`GUI/searchapp`, `GUI/scheduleapp`). Everything lives in
`GUI/searchapp/static/searchapp/cinema.css`; pages only add page-specific rules.

## Concept

**Signal.** A calm graphite console where posters and progress are the only loud things.
The brand coral marks one thing per screen: the primary action, or what is live right now.
Dark only: posters and backdrops are the content, and the app runs next to Sonarr, Radarr and Jellyfin.

## Contract

- Classes keep the `cn-` prefix and tokens the `--cn-` prefix. Page scripts and the ARR/Library
  pages build markup with these names: restyle by changing values, not names.
- No raw hex in templates or page CSS. Use tokens.
- User-visible strings go through `searchapp/i18n` (`i18n/it.json`).

## Tokens

| Group | Token | Value | Use |
|---|---|---|---|
| Surface | `--cn-void` | `#0A0B0E` | app background |
| | `--cn-deep` | `#0F1014` | wells, inputs, sidebar |
| | `--cn-surf` | `#15171C` | cards, rows |
| | `--cn-surf-2` | `#1D2027` | hover, raised |
| | `--cn-surf-3` | `#272B34` | menus, sheets, toasts |
| Line | `--cn-edge` / `--cn-edge-2` | white 8% / 16% | dividers, control borders |
| Text | `--cn-white` | `#F2F3F5` | primary |
| | `--cn-mute` | `#A9AEB9` | secondary |
| | `--cn-faint` | `#8A8F9B` | tertiary, labels (4.5:1 on `--cn-surf-2`) |
| Brand | `--cn-hot` | `#FF5A36` | primary action, live state |
| | `--cn-on-hot` | `#1A0A05` | text on coral (white fails 4.5:1) |
| | `--cn-hot-ink` | `#FF8A6E` | coral text on dark |
| Status | `--cn-go` | `#4ADE80` | done, reachable |
| | `--cn-amber` | `#FBBF24` | warning |
| | `--cn-bad` | `#FB7185` | error, failed (never coral: coral is the brand) |
| | `--cn-cool` | `#5B6170` | idle |
| Focus | `--cn-focus` | `#8FC7FF` | 2px ring, 2px offset |

Status is never color alone: every badge carries a text label and a dot or icon.

**Type.** Inter variable (bundled, `font-display: swap`) for UI and display; system mono for data.
Scale 12 / 13 / 14 / 15 / 16 / 18 / 22 / 28 / 36, display `clamp(28px, 4vw, 44px)`.
Weights 400 body, 500 labels, 600 titles, 700 display. Inputs are 16px on phones (no iOS zoom).
Numbers that change use `tabular-nums`.

**Space.** 4px grid: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64. Page gutter `--cn-pad` = `clamp(16px, 3vw, 40px)`.

**Radius.** `--cn-radius-sm` 8, `--cn-radius` 12, `--cn-radius-lg` 18, pills 999.

**Elevation.** Cards: 1px inset edge. Raised: `--cn-e2`. Overlays (dialogs, sheets, toasts): `--cn-e3`.

**Layers.** sticky 20, nav 40, tray 50, overlay 60, toast 70, skip link 100.

**Breakpoints.** 480, 768, 1024, 1440. The shell switches at 1024.

## Shell

- **1024px and up:** fixed left sidebar. Primary navigation (Search, Downloads, Watchlist, Library)
  at the top; secondary group (Settings, Logs, language, donate, logout) at the bottom.
- **Below 1024px:** slim top bar with the brand, bottom tab bar with the four primary destinations
  plus **More**, which opens the secondary group as a bottom sheet. Safe-area insets are respected.
- Every nav item has an icon and a label. The current page carries `aria-current="page"`.
- Downloads shows a live count while something is running.

## Components

| Class | Role |
|---|---|
| `cn-cta` | primary button, one per screen. `is-ghost` secondary, `is-danger` destructive |
| `cn-mini` | small button and compact select. `is-mark` accent |
| `cn-opt` | chip / toggle (`aria-pressed`) |
| `cn-st` | status badge: `is-run`, `is-done`, `is-wait`, `is-type`, `is-warn`, `is-dead` |
| `cn-input`, `cn-area`, `cn-field`, `cn-check` | form controls; `cn-check` renders a switch |
| `cn-box`, `cn-slab` + `cn-big`, `cn-lines` + `cn-ln`, `cn-table` | cards, stat strip, rows, table |
| `cn-switch` | tabs (`aria-selected`) |
| `cn-msg`, `cn-warnbox`, `cn-empty` | inline messages and empty states |
| `cn-tile` + `cn-poster`, `cn-ep`, `cn-stab` | poster card, episode card, season tab |
| `cn-hero` | title header with backdrop |
| `cn-tray` | sticky action bar for a selection |
| `cn-ico` | icon from the sprite in `cinema_base.html` (`<use href="#i-name">`) |

Touch targets are at least 44px on coarse pointers, 36px with a mouse. Actions are never hover-only.

## Motion

| Token | Value | Use |
|---|---|---|
| `--cn-t-fast` | 120ms | press, hover, color |
| `--cn-t` | 220ms | state change, small enter |
| `--cn-t-slow` | 420ms | large enter, progress |
| `--cn-ease-out` | `cubic-bezier(.22, 1, .36, 1)` | entering |
| `--cn-ease-in` | `cubic-bezier(.55, 0, 1, .45)` | leaving (about 65% of the enter time) |
| `--cn-ease-spring` | `linear()` spring, cubic-bezier fallback | sheets, toggles, selection |

- Only `transform` and `opacity` animate. Nothing animates layout.
- Page changes use cross-document view transitions: content fades and rises, the shell stays still,
  the active nav marker slides to its new place.
- Lists and grids enter staggered by 35ms, capped at 10 items.
- Running work shows the equalizer mark (three bars) and a moving sheen on its progress bar.
- Press feedback is a 0.97 scale. Dialogs scale in; on phones they rise as bottom sheets.
- `prefers-reduced-motion: reduce` turns off view transitions, stagger, sheen and equalizer;
  what remains is a short opacity change.

## Avoid

- More than one coral button on a screen.
- Emoji or text glyphs as icons.
- Hover-only actions, placeholder-only labels, color-only status.
- Inline `style=""` for layout or color.
- Horizontal page scroll at any width from 360px.
