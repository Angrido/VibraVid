(function () {
    "use strict";
    const config = document.currentScript.dataset;
    const tr = text => (window.t ? window.t(text) : text);
    const filter = document.getElementById("lib-filter");
    const onlyMissing = document.getElementById("lib-missing");
    const onlyItalian = document.getElementById("lib-italian");
    const onlyBusy = document.getElementById("lib-busy");
    const sort = document.getElementById("lib-sort");
    const toggles = [onlyMissing, onlyItalian, onlyBusy];
    const kinds = [...document.querySelectorAll("[data-lib-kind]")];
    const VIEW_KEY = "vv-lib-view";
    let kind = "all";
    let timer;

    const pressed = button => button?.getAttribute("aria-pressed") === "true";
    const sorters = {
        title: (a, b) => (a.dataset.title > b.dataset.title) - (a.dataset.title < b.dataset.title),
        missing: (a, b) => Number(b.dataset.missing) - Number(a.dataset.missing),
        added: (a, b) => b.dataset.added.localeCompare(a.dataset.added),
        size: (a, b) => Number(b.dataset.size) - Number(a.dataset.size),
    };

    function sortTiles() {
        const by = sorters[sort.value] || sorters.title;
        document.querySelectorAll(".lib-grid").forEach(grid => {
            grid.append(...[...grid.children].sort((a, b) => by(a, b) || sorters.title(a, b)));
        });
    }

    function setKind(next) {
        kind = kinds.some(button => button.dataset.libKind === next) ? next : "all";
        kinds.forEach(button => button.setAttribute("aria-pressed", String(button.dataset.libKind === kind)));
    }

    function rememberView() {
        try {
            sessionStorage.setItem(VIEW_KEY, JSON.stringify({
                query: filter.value, kind, sort: sort.value, on: toggles.filter(pressed).map(toggle => toggle.id),
            }));
        } catch (_) {}
    }

    function restoreView() {
        let view = null;
        try { view = JSON.parse(sessionStorage.getItem(VIEW_KEY) || "null"); } catch (_) {}
        if (!view) return;
        filter.value = view.query || "";
        setKind(view.kind);
        toggles.forEach(toggle => toggle.setAttribute("aria-pressed", String((view.on || []).includes(toggle.id))));
        if (sorters[view.sort] && view.sort !== "title") {
            sort.value = view.sort;
            sortTiles();
        }
    }

    function apply() {
        if (!filter) return;
        const query = filter.value.trim().toLowerCase();
        let shown = 0;
        document.querySelectorAll("[data-lib-group]").forEach(group => {
            const groupOn = kind === "all" || kind === group.dataset.libGroup;
            let visible = 0;
            group.querySelectorAll("[data-lib-item]").forEach(item => {
                const match = groupOn
                    && (!query || item.dataset.title.includes(query))
                    && (!pressed(onlyMissing) || Number(item.dataset.missing) > 0)
                    && (!pressed(onlyItalian) || ["good", "warn"].includes(item.dataset.libLang))
                    && (!pressed(onlyBusy) || item.dataset.libBusy === "1");
                item.hidden = !match;
                if (match) visible += 1;
            });
            group.hidden = !visible;
            shown += visible;
        });
        document.getElementById("lib-nomatch").hidden = shown > 0;
    }

    function choose() {
        rememberView();
        apply();
    }

    kinds.forEach(button => button.addEventListener("click", () => {
        setKind(button.dataset.libKind);
        choose();
    }));
    toggles.forEach(toggle => toggle?.addEventListener("click", () => {
        toggle.setAttribute("aria-pressed", String(!pressed(toggle)));
        choose();
    }));
    filter?.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(choose, 120);
    });
    sort?.addEventListener("change", () => {
        sortTiles();
        rememberView();
    });

    async function request(url, body) {
        const options = body === undefined ? {} : {
            method: "POST",
            headers: {"Content-Type": "application/json", "X-CSRFToken": config.csrf},
            body: JSON.stringify(body),
        };
        const response = await fetch(url, {...options, signal: AbortSignal.timeout(60000)});
        let data = {};
        try { data = await response.json(); } catch (_) {}
        if (!response.ok || data.status === "error") throw new Error(data.message || tr("Request failed."));
        return data;
    }

    const activityLook = {
        downloading: ["is-run", "Downloading"], queued: ["is-warn", "Queued"], failed: ["is-dead", "Failed"],
    };
    const LIVE_IDS = ["lib-stats", "lib-series-n", "lib-movies-n"];
    let activityTimer = null;
    let activityBusy = false;

    function fillBadge(badge, label, count) {
        badge.replaceChildren(Object.assign(document.createElement("span"), {textContent: tr(label)}));
        if (count) badge.append(" ", Object.assign(document.createElement("span"), {className: "cn-num", textContent: count}));
    }

    function paintActivity(titles) {
        const landed = [];
        document.querySelectorAll("[data-lib-key]").forEach(item => {
            const counts = {...titles[item.dataset.libKey]};
            counts.failed = Math.min(counts.failed || 0, Number(item.dataset.missing));
            const state = Object.keys(activityLook).find(name => counts[name]) || "";
            const busy = state === "downloading" || state === "queued";
            if (item.dataset.libBusy === "1" && !busy) landed.push(item.dataset.libKey);
            item.dataset.libBusy = busy ? "1" : "";
            const badge = item.querySelector("[data-lib-activity]");
            const shown = state + ":" + (counts[state] || 0);
            if (badge.dataset.shown === shown) return;
            badge.dataset.shown = shown;
            badge.hidden = !state;
            if (!state) return;
            const [tone, label] = activityLook[state];
            badge.className = "cn-st " + tone;
            fillBadge(badge, label, counts[state] > 1 && counts[state]);
        });
        return landed;
    }

    function scheduleActivity() {
        activityTimer = document.querySelector('[data-lib-busy="1"]') ? setTimeout(pollActivity, 4000) : null;
    }

    async function reloadTiles(keys) {
        const response = await fetch(window.location.href, {cache: "no-store", signal: AbortSignal.timeout(60000)});
        if (!response.ok) throw new Error(response.status);
        const fresh = new DOMParser().parseFromString(await response.text(), "text/html");
        keys.forEach(key => {
            const next = fresh.querySelector(`[data-lib-key="${key}"]`);
            if (!next) return;
            const old = document.querySelector(`[data-lib-key="${key}"]`);
            const check = next.querySelector("[data-lib-check]");
            if (check) check.disabled = !!old.querySelector("[data-lib-check]")?.disabled;
            old.replaceWith(next);
        });
        LIVE_IDS.forEach(id => {
            const next = fresh.getElementById(id);
            if (next) document.getElementById(id)?.replaceWith(next);
        });
    }

    async function refreshLanded(keys, titles) {
        try {
            await reloadTiles(keys);
            paintActivity(titles);
            if (sort.value !== "title") sortTiles();
        } catch (_) {
            keys.forEach(key => { document.querySelector(`[data-lib-key="${key}"]`).dataset.libBusy = "1"; });
        }
    }

    async function pollActivity() {
        if (activityBusy || document.hidden) return;
        activityBusy = true;
        clearTimeout(activityTimer);
        try {
            const data = await request(config.activityUrl);
            const landed = paintActivity(data.titles);
            if (landed.length) await refreshLanded(landed, data.titles);
            apply();
        } catch (_) {}
        activityBusy = false;
        scheduleActivity();
    }

    if (filter) {
        restoreView();
        paintActivity(JSON.parse(document.getElementById("lib-activity").textContent));
        apply();
        scheduleActivity();
        document.addEventListener("visibilitychange", pollActivity);
        window.addEventListener("pageshow", event => { if (event.persisted) pollActivity(); });
    }

    const status = document.getElementById("lib-lang-status");
    if (!status) return;
    const checkAll = document.getElementById("lib-lang-all");
    const interval = document.getElementById("lib-lang-interval");
    const checkButtons = () => [checkAll, ...document.querySelectorAll("[data-lib-check]")];
    const toneClass = {good: "is-done", warn: "is-warn", bad: "is-dead"};
    let polling = null;

    const formatTime = seconds => new Date(seconds * 1000).toLocaleString(window.CN_LANG || undefined,
        {dateStyle: "medium", timeStyle: "short"});
    document.querySelectorAll("[data-lib-ts]").forEach(node => { node.textContent = formatTime(Number(node.dataset.libTs)); });

    function setStatus(text, tone) {
        status.textContent = text;
        status.className = "lib-langbar-status" + (tone ? " cn-msg is-" + tone : "");
    }

    function paintBadges(titles) {
        document.querySelectorAll("[data-lib-key]").forEach(item => {
            const badge = item.querySelector("[data-lib-lang-badge]");
            if (!badge) return;
            const summary = titles[item.dataset.libKey];
            item.dataset.libLang = summary ? summary.tone : "";
            badge.className = "cn-st lib-lang-st " + (toneClass[summary?.tone] || "is-wait");
            fillBadge(badge, summary ? summary.label : "Not checked", summary?.count);
            const link = item.querySelector("[data-lib-source]");
            const source = summary?.source;
            const valid = source && /^https?:\/\//i.test(source.url || "");
            link.hidden = !valid;
            if (valid) {
                link.href = source.url;
                link.setAttribute("aria-label", tr("Open on the provider: {provider}").replace("{provider}", source.provider));
            }
        });
        apply();
    }

    function setBusy(running, clicked) {
        checkButtons().forEach(button => {
            if (!button) return;
            button.disabled = running || (button === checkAll && button.dataset.empty === "1");
            button.toggleAttribute("aria-busy", running && button === clicked);
        });
    }

    function render(data) {
        paintBadges(data.titles || {});
        if (data.running) {
            setStatus(tr("Checking {done} of {total}…").replace("{done}", data.done).replace("{total}", data.total));
        } else if (data.last_checked) {
            setStatus(tr("Last check") + " " + formatTime(data.last_checked));
        }
    }

    async function poll() {
        try {
            const data = await request(config.statusUrl);
            render(data);
            if (data.running) { polling = setTimeout(poll, 2500); return; }
            polling = null;
            setBusy(false);
            setStatus(tr("Check complete.") + (data.last_checked ? " " + tr("Last check") + " " + formatTime(data.last_checked) : ""), "good");
        } catch (error) {
            polling = setTimeout(poll, 8000);
        }
    }

    async function start(body, button) {
        setBusy(true, button);
        setStatus(tr("Starting the check…"));
        try {
            render(await request(config.checkUrl, body));
            clearTimeout(polling);
            polling = setTimeout(poll, 1500);
        } catch (error) {
            setBusy(false);
            setStatus(error.message, "bad");
        }
    }

    if (checkAll) checkAll.dataset.empty = checkAll.disabled ? "1" : "";
    checkAll?.addEventListener("click", () => start({scope: "all"}, checkAll));
    document.addEventListener("click", event => {
        const button = event.target.closest("[data-lib-check]");
        if (!button) return;
        start({[button.dataset.libCheck]: Number(button.dataset.libId)}, button);
    });

    interval?.addEventListener("change", async () => {
        try {
            await request(config.intervalUrl, {hours: Number(interval.value)});
            setStatus(Number(interval.value) ? tr("Automatic check saved.") : tr("Automatic check turned off."), "good");
        } catch (error) {
            setStatus(error.message, "bad");
        }
    });

    if (status.dataset.running) {
        setBusy(true);
        polling = setTimeout(poll, 1500);
    }
})();
