(function (global) {
	"use strict";
	function esc(value) {
		return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
			return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
		});
	}

	function duotone(text) {
		var hue = 0, s = String(text || "?");
		for (var i = 0; i < s.length; i++) hue += s.charCodeAt(i);
		hue = hue % 360;
		return ["hsl(" + hue + " 34% 26%)", "hsl(" + hue + " 40% 10%)"];
	}

	function titleize(text) {
		return String(text == null ? "" : text)
			.replace(/[-_]+/g, " ")
			.replace(/\s+/g, " ")
			.trim()
			.split(" ")
			.map(function (w) {
				var lower = w === w.toLowerCase() && w !== w.toUpperCase();
				return lower ? w.charAt(0).toUpperCase() + w.slice(1) : w;
			})
			.join(" ");
	}

	function pct(value) {
		var n = parseFloat(value);
		return isFinite(n) ? Math.max(0, Math.min(100, n)) : 0;
	}

	function paint(node, key) {
		var tone = duotone(key);
		node.style.setProperty("--cn-p1", tone[0]);
		node.style.setProperty("--cn-p2", tone[1]);
	}

	function tr(text) { return typeof global.t === "function" ? global.t(text) : text; }

	function toLogin() {
		global.location.assign("/login/?next=" + encodeURIComponent(global.location.pathname + global.location.search));
	}

	// JSON requests for page scripts. An expired session answers 401 (we ask for JSON, so the
	// middleware never redirects): go to the login page instead of treating the reply as data.
	// Rejects on a non-2xx status or a body that is not JSON; error.status / error.data carry the details.
	function fetchJSON(url, options) {
		options = options || {};
		var headers = new Headers(options.headers || {});
		if (!headers.has("Accept")) headers.set("Accept", "application/json");
		var request = {};
		Object.keys(options).forEach(function (key) { request[key] = options[key]; });
		request.headers = headers;
		return fetch(url, request).then(function (response) {
			var type = response.headers.get("Content-Type") || "";
			var landed = response.redirected && /^\/login\/?$/.test(new URL(response.url).pathname);
			if (response.status === 401 || landed) {
				toLogin();
				throw Object.assign(new Error(tr("Your session has expired. Sign in again.")), { status: 401 });
			}
			if (type.indexOf("json") === -1) {
				throw Object.assign(new Error(tr("Unexpected reply from the server (HTTP {status}).").replace("{status}", response.status)),
					{ status: response.status });
			}
			return response.json().then(function (data) {
				if (!response.ok) {
					var text = data && (data.message || data.error);
					throw Object.assign(new Error(text || tr("Request failed (HTTP {status}).").replace("{status}", response.status)),
						{ status: response.status, data: data });
				}
				return data;
			});
		});
	}

	// Confirmation sheet for destructive actions: resolves true only on the danger button.
	// Focus starts on Cancel (the safe choice) and returns to the opener when it closes.
	function confirmAction(options) {
		return new Promise(function (resolve) {
			var opener = document.activeElement;
			var dialog = document.createElement("dialog");
			dialog.className = "cn-dialog";
			var id = "cn-confirm-" + Date.now();
			dialog.setAttribute("aria-labelledby", id);
			var title = document.createElement("h2");
			title.id = id;
			title.textContent = tr(options.title);
			dialog.appendChild(title);
			if (options.text) {
				var text = document.createElement("p");
				text.className = "cn-note";
				text.textContent = tr(options.text);
				dialog.appendChild(text);
			}
			if (options.detail) {
				var detail = document.createElement("p");
				detail.className = "cn-cap";
				detail.textContent = options.detail;
				dialog.appendChild(detail);
			}
			var actions = document.createElement("div");
			actions.className = "cn-dialog-actions";
			var cancel = document.createElement("button");
			cancel.type = "button";
			cancel.className = "cn-cta is-ghost";
			cancel.textContent = tr("Cancel");
			var ok = document.createElement("button");
			ok.type = "button";
			ok.className = "cn-cta is-danger";
			ok.textContent = tr(options.confirm);
			actions.append(cancel, ok);
			dialog.appendChild(actions);
			var result = false;
			cancel.addEventListener("click", function () { dialog.close(); });
			ok.addEventListener("click", function () { result = true; dialog.close(); });
			closeOnBackdrop(dialog);
			dialog.addEventListener("close", function () {
				dialog.remove();
				if (opener && opener.isConnected && typeof opener.focus === "function") opener.focus({ preventScroll: true });
				resolve(result);
			});
			document.body.appendChild(dialog);
			dialog.showModal();
			cancel.focus();
		});
	}

	// Close a modal only for clicks on the backdrop: a click on the dialog's own padding
	// also targets the <dialog>, so compare against its box instead of event.target.
	function closeOnBackdrop(dialog) {
		dialog.addEventListener("click", function (event) {
			if (event.target !== dialog || (event.clientX === 0 && event.clientY === 0)) return;
			var box = dialog.getBoundingClientRect();
			var inside = event.clientX >= box.left && event.clientX <= box.right &&
				event.clientY >= box.top && event.clientY <= box.bottom;
			if (!inside) dialog.close();
		});
	}

	// Self-scheduling poll: never overlaps (a tick waits for the previous request), pauses
	// while the tab is hidden and resumes when it is shown. next() returns the delay in ms,
	// or 0 to stop until start() is called again.
	function poll(task, next) {
		var timer = 0, busy = false, stopped = true, again = false;
		function schedule(ms) {
			clearTimeout(timer);
			timer = ms > 0 ? setTimeout(tick, ms) : 0;
			stopped = !(ms > 0);
		}
		function tick() {
			clearTimeout(timer);
			if (busy) { again = true; return; }
			if (document.hidden) return;
			busy = true;
			Promise.resolve().then(task).catch(function () {}).then(function () {
				busy = false;
				if (again) { again = false; tick(); return; }
				schedule(next());
			});
		}
		document.addEventListener("visibilitychange", function () {
			if (!document.hidden && !stopped && !busy) tick();
		});
		return {
			start: function () { stopped = false; tick(); },
			later: function (ms) { stopped = false; schedule(ms); }
		};
	}

	global.CN = {
		esc: esc, duotone: duotone, titleize: titleize, pct: pct, paint: paint,
		fetchJSON: fetchJSON, confirm: confirmAction, closeOnBackdrop: closeOnBackdrop, poll: poll
	};
})(window);
