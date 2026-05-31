from football_sni.website import add_user_settings_context, require_user_location


def get_context(context):
	require_user_location("/rankings")
	add_user_settings_context(context)
	context.no_cache = 1
	context.show_sidebar = 0
	context.full_width = 1
	context.body_class = "fsni-site"
	context.title = "Rankings"
