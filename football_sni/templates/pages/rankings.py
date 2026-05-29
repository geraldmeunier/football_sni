from football_sni.website import require_login


def get_context(context):
	require_login("/rankings")
	context.no_cache = 1
	context.show_sidebar = 0
	context.full_width = 1
	context.body_class = "fsni-site"
	context.title = "Rankings"
