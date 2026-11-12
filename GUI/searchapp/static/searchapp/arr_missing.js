(function () {
    "use strict";
    const config = document.currentScript.dataset;
    const tr = text => (window.t ? window.t(text) : text);
    const bar = document.getElementById("am-bar");
    if (!bar) return;
    const count = document.getElementById("am-count");
    const msg = document.getElementById("am-msg");
    const download = document.getElementById("am-download");
    const filter = document.getElementById("am-filter");
    const leaves = () => [...document.querySelectorAll("[data-am-episode], [data-am-movie]")];
    let holdBar = false;
    const ACTIVE_STATES = ["pending", "downloading"];
    const AWAITING_IMPORT_STATES = ["completed", "import_pending"];
    const IMPORT_WATCH_MS = 120000;
    let pollTimer = null;

    async function post(url, body) {
        const response = await fetch(url, {
            method: "POST",
            signal: AbortSignal.timeout(90000),
            headers: {"Content-Type": "application/json", "X-CSRFToken": config.csrf},
            body: JSON.stringify(body),
        });
        let data = {};
        try { data = await response.json(); } catch (_) {}
        if (!response.ok || data.status === "error") throw new Error(data.message || data.error || tr("Request failed."));
        return data;
    }

    function scopeLeaves(scopeInput) {
        const container = scopeInput.closest("[data-am-scope-group]") || scopeInput.closest(".am-card");
        return [...container.querySelectorAll("[data-am-episode]")].filter(input => !input.disabled);
    }

    function syncScopes() {
        document.querySelectorAll("[data-am-scope]").forEach(scope => {
            const inputs = scopeLeaves(scope);
            const picked = inputs.filter(input => input.checked).length;
            scope.disabled = !inputs.length;
            scope.checked = !!inputs.length && picked === inputs.length;
            scope.indeterminate = picked > 0 && picked < inputs.length;
        });
    }

    function render() {
        const picked = leaves().filter(input => input.checked);
        const episodes = picked.filter(input => input.dataset.amEpisode).length;
        const movies = picked.length - episodes;
        const parts = [];
        if (episodes) parts.push(episodes === 1 ? tr("1 episode") : tr("{n} episodes").replace("{n}", episodes));
        if (movies) parts.push(movies === 1 ? tr("1 movie") : tr("{n} movies").replace("{n}", movies));
        count.textContent = parts.length ? parts.join(" · ") + " " + tr("selected") : tr("Nothing selected");
        download.disabled = !picked.length;
        const open = picked.length > 0 || holdBar;
        bar.classList.toggle("is-on", open);
        bar.inert = !open;
        document.body.classList.toggle("am-has-bar", open);
        syncScopes();
    }

    document.addEventListener("change", event => {
        const input = event.target;
        if (!(input instanceof HTMLInputElement) || !input.classList.contains("am-check")) return;
        if (input.hasAttribute("data-am-scope")) scopeLeaves(input).forEach(leaf => { leaf.checked = input.checked; });
        msg.textContent = "";
        render();
    });

    document.querySelectorAll(".am-toggle").forEach(toggle => toggle.addEventListener("click", () => {
        const body = document.getElementById(toggle.getAttribute("aria-controls"));
        const open = toggle.getAttribute("aria-expanded") !== "true";
        toggle.setAttribute("aria-expanded", String(open));
        body.hidden = !open;
    }));

    function visibleLeaves() {
        return leaves().filter(input => !input.disabled && !input.closest("[data-am-item]").hidden);
    }
    document.getElementById("am-select-all")?.addEventListener("click", () => {
        visibleLeaves().forEach(input => { input.checked = true; });
        render();
    });
    document.getElementById("am-clear")?.addEventListener("click", () => {
        leaves().forEach(input => { input.checked = false; });
        render();
    });

    let filterTimer;
    filter?.addEventListener("input", () => {
        clearTimeout(filterTimer);
        filterTimer = setTimeout(() => {
            const query = filter.value.trim().toLowerCase();
            let shown = 0;
            document.querySelectorAll("[data-am-item]").forEach(item => {
                item.hidden = !!query && !item.dataset.title.includes(query);
                if (!item.hidden) shown += 1;
            });
            document.querySelectorAll(".am-group").forEach(group => {
                group.hidden = !group.querySelector("[data-am-item]:not([hidden])");
            });
            document.getElementById("am-nomatch").hidden = shown > 0;
        }, 120);
    });

    download.addEventListener("click", async () => {
        const picked = leaves().filter(input => input.checked);
        const body = {
            episodes: picked.filter(input => input.dataset.amEpisode).map(input => Number(input.dataset.amEpisode)),
            movies: picked.filter(input => input.dataset.amMovie).map(input => Number(input.dataset.amMovie)),
        };
        download.disabled = true;
        download.setAttribute("aria-busy", "true");
        msg.className = "am-bar-msg";
        msg.textContent = tr("Sending to the download queue...");
        try {
            const result = await post(config.downloadUrl, body);
            picked.forEach(input => {
                input.checked = false;
                input.disabled = true;
                input.closest(".am-row").classList.add("is-sent");
            });
            refreshStates(picked.map(input => input.closest(".am-row").querySelector("[data-am-key]")));
            const notes = [tr("{n} queued for download.").replace("{n}", result.queued)];
            if (result.skipped) notes.push(tr("{n} already in the queue.").replace("{n}", result.skipped));
            if (result.gone) notes.push(tr("{n} no longer missing.").replace("{n}", result.gone));
            msg.classList.add("is-good");
            msg.textContent = notes.join(" ");
            holdBar = true;
            setTimeout(() => { holdBar = false; render(); }, 6000);
        } catch (error) {
            msg.classList.add("is-bad");
            msg.textContent = error.name === "TimeoutError" ? tr("Sonarr or Radarr took too long. Retry in a moment.") : error.message;
        } finally {
            download.removeAttribute("aria-busy");
            render();
        }
    });

    function activeSlots() {
        return [...document.querySelectorAll("[data-am-key]")].filter(slot =>
            ACTIVE_STATES.includes(slot.dataset.amState)
            || (AWAITING_IMPORT_STATES.includes(slot.dataset.amState) && Date.now() < Number(slot.dataset.amWatchUntil || 0)));
    }

    function applyState(slot, entry) {
        const locked = ACTIVE_STATES.includes(entry.state) || entry.state === "imported";
        if (AWAITING_IMPORT_STATES.includes(entry.state) && ACTIVE_STATES.includes(slot.dataset.amState)) {
            slot.dataset.amWatchUntil = String(Date.now() + IMPORT_WATCH_MS);
        }
        slot.dataset.amState = entry.state;
        slot.innerHTML = entry.html;
        const row = slot.closest(".am-row");
        const input = row.querySelector("[data-am-episode], [data-am-movie]");
        input.disabled = locked;
        if (locked) input.checked = false;
        row.classList.toggle("is-sent", ACTIVE_STATES.includes(entry.state));
    }

    async function refreshStates(slots) {
        clearTimeout(pollTimer);
        pollTimer = null;
        const keys = [...new Set(slots.filter(Boolean).map(slot => slot.dataset.amKey))].slice(0, 500);
        if (keys.length && !document.hidden) {
            try {
                const response = await fetch(config.statesUrl + "?keys=" + encodeURIComponent(keys.join(",")), {
                    signal: AbortSignal.timeout(15000),
                });
                const data = await response.json();
                if (response.ok && data.states) {
                    document.querySelectorAll("[data-am-key]").forEach(slot => {
                        const entry = data.states[slot.dataset.amKey];
                        if (entry) applyState(slot, entry);
                    });
                    render();
                }
            } catch (_) {}
        }
        clearTimeout(pollTimer);
        pollTimer = activeSlots().length ? setTimeout(() => refreshStates(activeSlots()), 3000) : null;
    }

    document.addEventListener("visibilitychange", () => {
        if (!document.hidden && activeSlots().length) refreshStates(activeSlots());
    });

    function chip(language) {
        const item = document.createElement("li");
        item.className = "am-chip" + (language.wanted ? " is-want" : "");
        item.textContent = language.name || language.code;
        if (language.wanted) {
            const mark = document.createElement("span");
            mark.className = "am-chip-mark";
            mark.textContent = tr("wanted");
            item.append(mark);
        }
        return item;
    }

    function sourceLink(url, provider) {
        if (!/^https?:\/\//i.test(url || "")) return null;
        const link = document.createElement("a");
        link.className = "am-src";
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = tr("Open on the provider");
        link.setAttribute("aria-label", tr("Open on the provider: {provider}").replace("{provider}", provider));
        return link;
    }

    function showReport(box, result) {
        box.replaceChildren();
        box.className = "am-result is-open";
        const line = document.createElement("p");
        line.className = "am-verdict";
        if (!result.found) {
            box.classList.add("is-bad");
            line.textContent = tr("Not found on any configured provider.");
            box.append(line);
            if (result.searched && result.searched.length) {
                const searched = document.createElement("p");
                searched.className = "am-source";
                const names = document.createElement("span");
                names.dataset.noTr = "";
                names.textContent = result.searched.join(", ");
                searched.append(tr("Searched on:") + " ", names);
                box.append(searched);
            }
            if (result.series_only) {
                line.textContent = tr("Found only as a series, while Radarr lists it as a movie.");
                const seen = document.createElement("p");
                seen.className = "am-source";
                const name = document.createElement("span");
                name.dataset.noTr = "";
                name.textContent = result.match + " · " + result.provider;
                seen.append(name);
                box.append(seen);
            }
            return;
        }
        const source = document.createElement("p");
        source.className = "am-source";
        const name = document.createElement("span");
        name.dataset.noTr = "";
        name.textContent = result.match + " · " + result.provider;
        source.append(tr("Match:") + " ", name);
        const link = sourceLink(result.url, result.provider);
        if (link) source.append(" ", link);
        if (!result.audio_supported) {
            box.classList.add("is-warn");
            line.textContent = tr("This provider cannot list audio before downloading. Your configured languages are still enforced when the download starts.");
            box.append(line, source);
            return;
        }
        const languages = result.audio_languages || [];
        const wanted = languages.filter(language => language.wanted);
        if (!languages.length) {
            box.classList.add("is-warn");
            line.textContent = tr("No labelled audio track found.");
        } else if (!result.wanted.length) {
            line.textContent = tr("Audio available:");
        } else if (wanted.length) {
            box.classList.add("is-good");
            line.textContent = tr("Has your languages. Audio available:");
        } else {
            box.classList.add("is-bad");
            line.textContent = tr("None of your languages. Audio available:");
        }
        const chips = document.createElement("ul");
        chips.className = "am-chips";
        chips.setAttribute("aria-label", tr("Audio languages"));
        languages.forEach((language, index) => {
            const item = chip(language);
            item.style.setProperty("--am-i", index);
            chips.append(item);
        });
        box.append(line);
        if (languages.length) box.append(chips);
        if (result.qualities?.length) {
            const quality = document.createElement("p");
            quality.className = "am-source";
            quality.textContent = tr("Quality:") + " " + result.qualities.join(", ");
            box.append(quality);
        }
        box.append(source);
    }

    document.addEventListener("click", async event => {
        const button = event.target.closest(".am-lang-btn");
        if (!button) return;
        const box = document.getElementById(button.getAttribute("aria-describedby"));
        const body = button.dataset.amCheckMovie
            ? {movie: Number(button.dataset.amCheckMovie)}
            : {episode: Number(button.dataset.amCheckEpisode)};
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
        const label = button.textContent;
        button.textContent = tr("Checking...");
        box.className = "am-result is-open is-loading";
        box.textContent = tr("Searching the providers and reading the tracks. This can take a few seconds.");
        try {
            showReport(box, await post(config.checkUrl, body));
        } catch (error) {
            box.className = "am-result is-open is-bad";
            box.textContent = error.name === "TimeoutError" ? tr("The provider took too long. Retry the check.") : error.message;
        } finally {
            button.disabled = false;
            button.removeAttribute("aria-busy");
            button.textContent = label;
        }
    });

    render();
    refreshStates(activeSlots());
})();
