(function () {
    "use strict";
    const config = document.currentScript.dataset;
    const tr = text => (window.t ? window.t(text) : text);
    const filter = document.getElementById("lib-filter");
    const onlyMissing = document.getElementById("lib-missing");
    const onlyItalian = document.getElementById("lib-italian");
    const kinds = [...document.querySelectorAll("[data-lib-kind]")];
    let kind = "all";
    let timer;

    const pressed = button => button?.getAttribute("aria-pressed") === "true";

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
                    && (!pressed(onlyItalian) || ["good", "warn"].includes(item.dataset.libLang));
                item.hidden = !match;
                if (match) visible += 1;
            });
            group.hidden = !visible;
            shown += visible;
        });
        document.getElementById("lib-nomatch").hidden = shown > 0;
    }

    kinds.forEach(button => button.addEventListener("click", () => {
        kind = button.dataset.libKind;
        kinds.forEach(other => other.setAttribute("aria-pressed", String(other === button)));
        apply();
    }));
    [onlyMissing, onlyItalian].forEach(toggle => toggle?.addEventListener("click", () => {
        toggle.setAttribute("aria-pressed", String(!pressed(toggle)));
        apply();
    }));
    filter?.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(apply, 120);
    });

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
            badge.replaceChildren(Object.assign(document.createElement("span"), {textContent: tr(summary ? summary.label : "Not checked")}));
            if (summary?.count) {
                badge.append(" ", Object.assign(document.createElement("span"), {className: "cn-num", textContent: summary.count}));
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
