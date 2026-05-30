# Copyright (c) 2026, Gerald Meunier and contributors
# For license information, please see license.txt

from urllib.parse import urlparse

import frappe
import requests
from frappe.model.document import Document
from frappe.utils.file_manager import save_file


class CompetitionTeam(Document):
	def validate(self):
		if self.iso:
			self.image_url = (
				"https://raw.githubusercontent.com/hampusborgos/country-flags/main/svg/"
				f"{self.iso.strip().lower()}.svg"
			)

	def after_insert(self):
		self.attach_image_from_url()

	def on_update(self):
		self.attach_image_from_url()

	def attach_image_from_url(self):
		if not self.image_url or self.image:
			return

		try:
			response = requests.get(self.image_url, timeout=15)
			response.raise_for_status()
		except requests.RequestException as exc:
			frappe.throw(f"Unable to fetch image from {self.image_url}: {exc}")

		filename = urlparse(self.image_url).path.rsplit("/", 1)[-1] or f"{self.name}.svg"
		file_doc = save_file(
			filename,
			response.content,
			self.doctype,
			self.name,
			is_private=0,
			df="image",
		)
		if file_doc.is_private:
			file_doc.db_set("is_private", 0, update_modified=False)

		self.image = file_doc.file_url
		self.db_set("image", file_doc.file_url, update_modified=False)
