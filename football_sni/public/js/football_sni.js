(function () {
	function subscribe(competition) {
		frappe.confirm(
			__("Do you want to join this competition?"),
			function () {
				frappe.call({
					method: "football_sni.website.subscribe_to_competition",
					args: { competition: competition },
					freeze: true,
					freeze_message: __("Joining competition..."),
					callback: function (response) {
						if (!response.message) {
							return;
						}

						frappe.msgprint({
							title: __("Welcome!"),
							message: response.message.message,
							indicator: "green",
							primary_action: {
								label: __("Continue"),
								action: function () {
									window.location.href = response.message.redirect_to;
								},
							},
						});
					},
				});
			}
		);
	}


	function getPickPayload(row) {
		var pickA = row.querySelector('[data-field="pick_a"]');
		var pickB = row.querySelector('[data-field="pick_b"]');
		return {
			pick: row.dataset.pick,
			pick_a: pickA ? pickA.value : '',
			pick_b: pickB ? pickB.value : '',
		};
	}

	function getPickSignature(row) {
		var payload = getPickPayload(row);
		return [payload.pick_a, payload.pick_b].join('|');
	}

	function rememberSavedValues(row) {
		row.querySelectorAll('.fsni-pick-input').forEach(function (input) {
			input.dataset.savedValue = input.value || '';
		});
		row.dataset.savedSignature = getPickSignature(row);
	}

	function restoreSavedValues(row) {
		row.querySelectorAll('.fsni-pick-input').forEach(function (input) {
			input.value = input.dataset.savedValue || '';
		});
	}

	function refocusInput(input) {
		window.setTimeout(function () {
			input.focus();
			input.select();
		}, 0);
	}

	function validatePickInputs(row) {
		var isValid = true;
		row.querySelectorAll('.fsni-pick-input').forEach(function (input) {
			var value = input.value.trim();
			if (!isValid || value === '') {
				return;
			}

			if (!/^\d+$/.test(value)) {
				frappe.show_alert({ message: __('Picks must be integers.'), indicator: 'red' }, 5);
				restoreSavedValues(row);
				refocusInput(input);
				isValid = false;
				return;
			}

			var integerValue = parseInt(value, 10);
			if (integerValue < 0 || integerValue > 20) {
				frappe.show_alert({ message: __('Picks must be between 0 and 20.'), indicator: 'red' }, 5);
				restoreSavedValues(row);
				refocusInput(input);
				isValid = false;
			}
		});
		return isValid;
	}

	function savePick(row) {
		if (!row || row.classList.contains('is-closed')) {
			return;
		}

		if (!validatePickInputs(row)) {
			return;
		}

		var signature = getPickSignature(row);
		if (row.dataset.savedSignature === signature || row.dataset.savingSignature === signature) {
			return;
		}

		var pickA = row.querySelector('[data-field="pick_a"]');
		var pickB = row.querySelector('[data-field="pick_b"]');
		row.dataset.savingSignature = signature;
		row.classList.add('is-saving');

		frappe.call({
			method: 'football_sni.website.update_competition_pick',
			args: getPickPayload(row),
			callback: function (response) {
				row.classList.remove('is-saving');
				delete row.dataset.savingSignature;
				if (!response.message) {
					return;
				}
				if (pickA) {
					pickA.value = response.message.pick_a || '';
				}
				if (pickB) {
					pickB.value = response.message.pick_b || '';
				}
				rememberSavedValues(row);
				row.classList.add('is-saved');
				window.setTimeout(function () {
					row.classList.remove('is-saved');
				}, 900);
			},
			error: function () {
				row.classList.remove('is-saving');
				delete row.dataset.savingSignature;
			},
		});
	}

	function bindPickInputs(root) {
		(root || document).querySelectorAll('.fsni-pick-input').forEach(function (input) {
			var row = input.closest('tr[data-pick]');
			if (row && !row.dataset.savedSignature) {
				rememberSavedValues(row);
			}

			input.addEventListener('change', function () {
				savePick(input.closest('tr[data-pick]'));
			});

			input.addEventListener('blur', function () {
				savePick(input.closest('tr[data-pick]'));
			});

			input.addEventListener('keydown', function (event) {
				if (event.key === 'Enter' || event.key === 'Tab') {
					savePick(input.closest('tr[data-pick]'));
				}
			});
		});
	}

	frappe.ready(function () {
		document.querySelectorAll(".fsni-play-button").forEach(function (button) {
			button.addEventListener("click", function (event) {
				event.preventDefault();
				event.stopPropagation();
				subscribe(button.dataset.competition);
			});
		});

		bindPickInputs(document);
	});
})();

(function () {
	if (window.location.pathname !== '/login') {
		return;
	}

	var context = null;
	var loadingTurnstile = false;
	var STYLE_ID = 'fsni-login-security-style';

	function injectStyle() {
		if (document.getElementById(STYLE_ID)) {
			return;
		}

		var style = document.createElement('style');
		style.id = STYLE_ID;
		style.textContent = '' +
			'.fsni-login-message {' +
			'align-items:flex-start;background:#fff7ed;border:1px solid #fb923c;border-left:4px solid #ea580c;' +
			'border-radius:8px;box-shadow:0 8px 20px rgba(124,45,18,.08);color:#7c2d12;display:flex;' +
			'font-size:13px;font-weight:650;gap:10px;line-height:1.45;margin:14px 0 2px;padding:12px 14px 12px 12px;text-align:left;' +
			'}' +
			'.fsni-login-message:before {' +
			'align-items:center;background:#fed7aa;border-radius:999px;color:#9a3412;content:"!";display:inline-flex;' +
			'flex:0 0 22px;font-size:15px;font-weight:800;height:22px;justify-content:center;line-height:1;margin-top:1px;width:22px;' +
			'}' +
			'.fsni-turnstile {display:flex;justify-content:center;margin:14px 0 16px;min-height:65px;}';
		document.head.appendChild(style);
	}

	function getLoginForms() {
		return Array.prototype.slice.call(
			document.querySelectorAll('.form-login, .form-signup, .form-login-with-email-link')
		);
	}

	function ensureSecurityBlock(form) {
		var actions = form.querySelector('.page-card-actions');
		if (!actions) {
			return null;
		}

		var block = form.querySelector('.fsni-login-security');
		if (!block) {
			block = document.createElement('div');
			block.className = 'fsni-login-security';
			actions.parentNode.insertBefore(block, actions);
		}

		if (context.login_message && !block.querySelector('.fsni-login-message')) {
			var message = document.createElement('div');
			message.className = 'fsni-login-message';
			message.innerHTML = context.login_message;
			block.appendChild(message);
		}

		if (context.turnstile_enabled && !block.querySelector('.fsni-turnstile')) {
			var turnstileContainer = document.createElement('div');
			turnstileContainer.className = 'fsni-turnstile';
			block.appendChild(turnstileContainer);
		}

		return block;
	}

	function renderTurnstile() {
		if (!context || !context.turnstile_enabled || !window.turnstile) {
			return;
		}

		getLoginForms().forEach(function (form) {
			var block = ensureSecurityBlock(form);
			var container = block && block.querySelector('.fsni-turnstile');
			if (!container || container.dataset.widgetId) {
				return;
			}

			container.dataset.widgetId = window.turnstile.render(container, {
				sitekey: context.turnstile_site_key,
				theme: 'light'
			});
		});
	}

	function loadTurnstile() {
		if (!context || !context.turnstile_enabled) {
			return;
		}

		if (window.turnstile) {
			renderTurnstile();
			return;
		}

		if (loadingTurnstile) {
			return;
		}

		loadingTurnstile = true;
		var script = document.createElement('script');
		script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
		script.async = true;
		script.defer = true;
		script.onload = renderTurnstile;
		document.head.appendChild(script);
	}

	function getVisibleForm() {
		var forms = getLoginForms();
		for (var i = 0; i < forms.length; i++) {
			var section = forms[i].closest('section');
			if (section && window.getComputedStyle(section).display !== 'none') {
				return forms[i];
			}
		}
		return forms[0] || null;
	}

	function getTurnstileToken() {
		var form = getVisibleForm();
		var widget = form && form.querySelector('.fsni-turnstile');
		if (!widget || !widget.dataset.widgetId || !window.turnstile) {
			return '';
		}
		return window.turnstile.getResponse(widget.dataset.widgetId);
	}

	function resetVisibleTurnstile() {
		var form = getVisibleForm();
		var widget = form && form.querySelector('.fsni-turnstile');
		if (widget && widget.dataset.widgetId && window.turnstile) {
			window.turnstile.reset(widget.dataset.widgetId);
		}
	}

	function injectSecurityBlocks() {
		if (!context) {
			return;
		}
		injectStyle();
		getLoginForms().forEach(ensureSecurityBlock);
		renderTurnstile();
	}

	function patchLoginCall() {
		if (!window.login || !window.login.call || window.login._fsni_security_patched) {
			return false;
		}

		var originalCall = window.login.call;
		window.login.call = function (args, callback, url) {
			if (context && context.turnstile_enabled && args && (
				args.cmd === 'login' ||
				args.cmd === 'frappe.core.doctype.user.user.sign_up' ||
				args.cmd === 'frappe.www.login.send_login_link'
			)) {
				args.cf_turnstile_response = getTurnstileToken();
			}

			var request = originalCall.apply(this, arguments);
			if (request && request.always) {
				request.always(resetVisibleTurnstile);
			}
			return request;
		};
		window.login._fsni_security_patched = true;
		return true;
	}

	function patchRoutes() {
		if (!window.login || !window.login.route || window.login._fsni_route_patched) {
			return false;
		}
		var originalRoute = window.login.route;
		window.login.route = function () {
			var result = originalRoute.apply(this, arguments);
			injectSecurityBlocks();
			return result;
		};
		window.login._fsni_route_patched = true;
		return true;
	}

	function bootstrap() {
		frappe.call({
			method: 'football_sni.security.get_login_security_context',
			callback: function (response) {
				context = response.message || {};
				injectSecurityBlocks();
				patchLoginCall();
				patchRoutes();
				loadTurnstile();
			}
		});
	}

	function waitForFrappeLogin() {
		if (window.frappe && window.login && window.login.call) {
			bootstrap();
			return;
		}
		window.setTimeout(waitForFrappeLogin, 50);
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', waitForFrappeLogin);
	} else {
		waitForFrappeLogin();
	}
}());

