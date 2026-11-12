(function () {
    "use strict";
    const filter = document.getElementById("lib-filter");
    if (!filter) return;
    const onlyMissing = document.getElementById("lib-missing");
    const kinds = [...document.querySelectorAll("[data-lib-kind]")];
    let kind = "all";
    let timer;

    function apply() {
        const query = filter.value.trim().toLowerCase();
        const missingOnly = onlyMissing.getAttribute("aria-pressed") === "true";
        let shown = 0;
        document.querySelectorAll("[data-lib-group]").forEach(group => {
            const groupOn = kind === "all" || kind === group.dataset.libGroup;
            let visible = 0;
            group.querySelectorAll("[data-lib-item]").forEach(item => {
                const match = groupOn
                    && (!query || item.dataset.title.includes(query))
                    && (!missingOnly || Number(item.dataset.missing) > 0);
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
    onlyMissing.addEventListener("click", () => {
        onlyMissing.setAttribute("aria-pressed", String(onlyMissing.getAttribute("aria-pressed") !== "true"));
        apply();
    });
    filter.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(apply, 120);
    });
})();
