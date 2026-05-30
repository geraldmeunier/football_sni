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
