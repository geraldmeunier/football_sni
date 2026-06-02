import frappe
from frappe import _
from frappe.utils import is_markdown, markdown

from football_sni.website import add_user_settings_context, require_user_location


def get_context(context):
	require_user_location("/faq")
	add_user_settings_context(context)
	context.no_cache = 1
	context.show_sidebar = 0
	context.full_width = 1
	context.body_class = "fsni-site"
	context.title = _("FAQ")
	context.categories = get_faq_categories()


def get_faq_categories():
	categories = frappe.db.sql(
		"""
		select
			category.name,
			category.category_name,
			category.category_description,
			category.route,
			category.help_articles
		from `tabHelp Category` category
		where category.published = 1
			and exists (
				select 1
				from `tabHelp Article` article
				where article.category = category.name
					and article.published = 1
			)
		order by category.help_articles desc, category.category_name asc, category.name asc
		""",
		as_dict=True,
	)

	articles_by_category = get_faq_articles_by_category()
	for category in categories:
		category.articles = articles_by_category.get(category.name, [])
	return categories


def get_faq_articles_by_category():
	articles = frappe.db.sql(
		"""
		select
			article.name,
			article.title,
			article.category,
			article.content,
			article.level,
			article.route
		from `tabHelp Article` article
		inner join `tabHelp Category` category on category.name = article.category
		where article.published = 1
			and category.published = 1
		order by category.category_name asc, article.creation asc, article.title asc
		""",
		as_dict=True,
	)

	articles_by_category = {}
	for article in articles:
		if is_markdown(article.content):
			article.content = markdown(article.content)
		articles_by_category.setdefault(article.category, []).append(article)
	return articles_by_category
