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

	frappe.ready(function () {
		document.querySelectorAll(".fsni-play-button").forEach(function (button) {
			button.addEventListener("click", function (event) {
				event.preventDefault();
				event.stopPropagation();
				subscribe(button.dataset.competition);
			});
		});
	});
})();
