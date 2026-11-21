(function () {
    "use strict";
    const config = document.currentScript.dataset;
    const targets = ["1080p", "720p", "480p"];
    const shared = document.querySelector("#cn-series-quality .cn-quality-picker");
    function field(form, name, value) {
        let input = form.elements.namedItem(name);
        if (!input) { input = document.createElement("input"); input.type = "hidden"; input.name = name; form.appendChild(input); }
        input.value = value;
        input.disabled = false;
    }
    function sourceForm(picker) {
        return picker.closest(".cn-tile")?.querySelector("form") ||
            document.querySelector(".cn-series-actions form");
    }
    function reportError(picker, message) {
        picker.querySelector(".cn-quality-result").textContent = message;
        const audio = window.CinemaAudio?.pickerFor(picker);
        if (audio) {
            const status = audio.querySelector(".cn-audio-result");
            status.textContent = message; status.classList.add("is-error");
            audio.querySelector("select").disabled = false;
            audio.closest("dialog").querySelector("[data-audio-download]").disabled = false;
        }
    }
    async function request(form) {
        window.CinemaAudio?.prepareForm(form);
        const data = new FormData(form);
        const season = data.get("season_number") || data.get("selected_seasons") || data.get("season") || data.get("auto_season") ||
            document.querySelector(".cn-stab.is-active")?.dataset.season;
        const seasonNumber = String(season || "").match(/\d+/)?.[0];
        const panel = [...document.querySelectorAll(".cn-spanel")].find(section => section.dataset.season === seasonNumber);
        const episode = data.get("selected_episodes") || data.get("episode") || panel?.querySelector(".cn-ep:not([hidden])")?.dataset.episode;
        return window.CN.fetchJSON(config.qualityUrl, {
            signal: AbortSignal.timeout(30000),
            method: "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": data.get("csrfmiddlewaretoken")},
            body: JSON.stringify({source_alias: data.get("source_alias"), item_payload: data.get("item_payload"),
                season, episode, audio_language: data.get("audio_language")})
        });
    }
    // The picker's own status line is often folded away (tile "Quality and tracks"), so a check
    // that blocks a download also explains itself right below the button that was pressed.
    function anchorFor(form, submitter) {
        const button = submitter || form.querySelector('[type="submit"]') ||
            (form.id && document.querySelector('[form="' + form.id + '"]')) ||
            (form.id === "cn-seasons-form" && document.getElementById("cn-seasons-btn"));
        return (button || form).closest(".cn-pick, .cn-series-actions, .cn-season-hd, form, .cn-tray") || form;
    }
    function clearNear(form) {
        form._qualityNote?.remove();
        delete form._qualityNote;
    }
    function showNear(form, submitter, message) {
        clearNear(form);
        const note = document.createElement("p");
        note.className = "cn-msg is-bad is-near";
        note.setAttribute("role", "alert");
        note.textContent = message;
        const anchor = anchorFor(form, submitter);
        if (anchor.classList.contains("cn-tray")) {
            // The tray floats over the page: say it in the tray itself.
            const text = anchor.querySelector(".cn-tray-txt");
            if (text) { text.textContent = message; text.title = message; }
            return;
        }
        anchor.insertAdjacentElement("afterend", note);
        form._qualityNote = note;
    }
    function populate(picker, available) {
        const select = picker.querySelector("select"), selected = select.value;
        select.replaceChildren(new Option("Use config", ""));
        const qualities = [...new Set([...targets, selected, ...(available || [])])].filter(q => /^\d+p$/.test(q) && parseInt(q) <= 1080 && q !== "360p");
        qualities.sort((a, b) => parseInt(b) - parseInt(a)).forEach(q => {
            const suffix = available === null ? " - check availability" : available.includes(q) ? " - available" : " - Watchlist";
            select.add(new Option(q + suffix, q));
        });
        select.value = selected;
    }
    async function load(picker, form) {
        const status = picker.querySelector(".cn-quality-result"), button = picker.querySelector("button");
        const generation = (picker._generation || 0) + 1;
        picker._generation = generation;
        picker._lastError = "";
        button.disabled = true; status.textContent = "Checking the provider...";
        try {
            const result = await request(form || sourceForm(picker));
            if (picker._generation !== generation) return null;
            window.CinemaAudio?.applyAvailable(picker, result);
            if (document.activeElement === picker.querySelector("select")) {
                picker._pendingQualities = result.qualities || [];
            } else {
                delete picker._pendingQualities;
                populate(picker, result.qualities || []);
            }
            status.textContent = (result.sample ? result.sample + ": " : "") +
                (result.qualities?.length ? "Available: " + result.qualities.join(", ") + ". " : "") +
                (result.message || "Other qualities: add to Watchlist and wait for availability.");
            return result;
        } catch (error) {
            if (picker._generation === generation) {
                picker._lastError = error.name === "TimeoutError"
                    ? "Provider check timed out. Retry, use config, or add to Watchlist."
                    : error.message || "Unable to check provider qualities.";
                reportError(picker, picker._lastError);
            }
            return null;
        } finally {
            if (picker._generation === generation) button.disabled = false;
        }
    }
    function key(form) {
        const data = new FormData(form);
        return "cn-quality:" + data.get("source_alias") + ":" + data.get("item_payload");
    }
    document.querySelectorAll(".cn-quality-picker").forEach(picker => {
        populate(picker, null);
        const form = sourceForm(picker);
        if (shared === picker && form) {
            try { picker.querySelector("select").value = sessionStorage.getItem(key(form)) || ""; } catch (_) {}
        }
        picker.querySelector("button").addEventListener("click", () => load(picker));
        picker.querySelector("select").addEventListener("change", () => {
            if (!picker._generation) load(picker);
        });
        picker.querySelector("select").addEventListener("blur", () => {
            if (picker._pendingQualities !== undefined) {
                populate(picker, picker._pendingQualities);
                delete picker._pendingQualities;
            }
        });
    });
    document.addEventListener("submit", async function (event) {
        if (event.defaultPrevented) return;
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        if (form.dataset.qualityPending) { event.preventDefault(); return; }
        const picker = form.closest(".cn-tile")?.querySelector(".cn-quality-picker") || shared;
        if (!picker) return;
        const data = new FormData(form);
        if (!data.has("item_payload")) return;
        const manual = !!picker.querySelector(".cn-manual-tracks")?.checked;
        const quality = manual ? "" : picker.querySelector("select").value;
        const audio = window.CinemaAudio?.selectionFor(form);
        field(form, "quality", quality);
        field(form, "manual_tracks", manual ? "on" : "");
        const action = new URL(form.action, location.href).pathname;
        const watchlist = action === config.watchlistUrl;
        if (watchlist) { field(form, "auto_enabled", "on"); return; }
        const download = action === config.downloadUrl || data.has("download_type");
        if (!download) {
            try { sessionStorage.setItem(key(form), quality); } catch (_) {}
            return;
        }
        clearNear(form);
        // "auto" is the default for every movie/series form and asks for nothing specific:
        // only an explicit quality or audio language needs the provider check first.
        const explicitAudio = audio && audio !== "auto" ? audio : null;
        if (manual || (!quality && !explicitAudio)) return;
        event.preventDefault();
        form.dataset.qualityPending = "1";
        const submitter = event.submitter;
        const wasDisabled = submitter?.disabled;
        // Keep the label and its icon: the spinner comes from aria-busy (cinema.css).
        if (submitter) { submitter.disabled = true; submitter.setAttribute("aria-busy", "true"); }
        let submitted = false;
        const fail = message => {
            reportError(picker, message);
            showNear(form, submitter, message);
        };
        try {
            const result = await load(picker, form);
            if (!result) {
                if (picker._lastError) showNear(form, submitter, picker._lastError);
                return;
            }
            if (quality && !result.qualities?.includes(quality)) {
                fail("Selected quality is unavailable or could not be verified for this video. Add to Watchlist to wait, or use config.");
                return;
            }
            if (explicitAudio && result.audio_supported) {
                const available = result.audio_languages || [];
                const match = window.CinemaAudio.availableForSelection(available, explicitAudio);
                if (!match) {
                    fail("The requested audio is unavailable for this video. Choose another language or inspect tracks manually.");
                    return;
                }
            }
            field(form, "quality", quality);
            HTMLFormElement.prototype.submit.call(form);
            submitted = true;
        } finally {
            if (submitter) submitter.removeAttribute("aria-busy");
            // Once submit() ran the page is navigating: a second click would queue the download twice.
            if (submitted) {
                if (submitter) submitter.dataset.qualityLocked = "1";
            } else {
                delete form.dataset.qualityPending;
                if (submitter) submitter.disabled = wasDisabled;
            }
        }
    });
    // Back/forward cache restores the page as it was left: unlock what the submit locked.
    window.addEventListener("pageshow", event => {
        if (!event.persisted) return;
        document.querySelectorAll("[data-quality-locked]").forEach(button => {
            button.disabled = false;
            delete button.dataset.qualityLocked;
        });
        document.querySelectorAll("form[data-quality-pending]").forEach(form => { delete form.dataset.qualityPending; });
    });
    document.addEventListener("cn:audio-change", function (event) {
        const picker = event.target.closest(".cn-tile")?.querySelector(".cn-quality-picker") || shared;
        if (!picker) return;
        picker._generation = (picker._generation || 0) + 1;
        picker.querySelector(".cn-quality-check").disabled = false;
        picker.querySelector(".cn-quality-result").textContent = "Audio choice updated. Check this video's tracks before downloading.";
    });
    document.querySelectorAll(".js-check-qualities").forEach(button => button.addEventListener("click", async function () {
        const form = button.closest("form"), status = form.querySelector(".cn-quality-result");
        button.disabled = true; status.textContent = "Checking...";
        try {
            const result = await request(form);
            status.textContent = (result.sample ? result.sample + ": " : "") +
                (result.qualities.length ? result.qualities.join(", ") : result.message || "No qualities reported.");
        } catch (error) { status.textContent = error.message; }
        finally { button.disabled = false; }
    }));
})();
