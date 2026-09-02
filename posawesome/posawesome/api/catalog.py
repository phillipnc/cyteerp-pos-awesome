"""Item catalog endpoints.

The v14 implementation issued four queries per item (barcodes, batches, serials,
stock) inside the result loop, which made a 5 000-item profile unusable. Every
lookup here is batched instead: the item list costs a fixed handful of queries no
matter how many rows come back.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate
from frappe.utils.caching import redis_cache

from erpnext.accounts.doctype.pos_profile.pos_profile import get_item_groups
from erpnext.stock.get_item_details import get_item_details

from posawesome.posawesome.api.currency import build_currency_context
from posawesome.posawesome.api.utils import (
	as_dict,
	as_list,
	check_pos_profile_access,
	get_available_batches,
	get_available_serial_nos,
	get_stock_availability,
	get_stock_availability_bulk,
)

ITEM_FIELDS = [
	"name as item_code",
	"item_name",
	"description",
	"stock_uom",
	"image",
	"is_stock_item",
	"has_variants",
	"variant_of",
	"item_group",
	"has_batch_no",
	"has_serial_no",
	"max_discount",
	"brand",
	"idx",
]


# ---------------------------------------------------------------------------
# Item list
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_items(
	pos_profile,
	price_list=None,
	item_group="",
	search_value="",
	customer=None,
	limit=None,
	invoice_currency=None,
	posting_date=None,
):
	"""Sellable items for a POS profile.

	Honours the profile's item-group restriction, optional search limiting, and the
	stock/batch/serial display switches.
	"""
	profile = as_dict(pos_profile)
	profile_name = profile.get("name")
	if not profile_name:
		frappe.throw(_("POS Profile is required"))
	check_pos_profile_access(profile_name)

	ttl = cint(profile.get("posa_server_cache_duration")) * 60

	if profile.get("posa_use_server_cache"):

		@redis_cache(ttl=ttl or 1800)
		def _cached(
			profile_name,
			price_list,
			item_group,
			search_value,
			customer,
			limit,
			invoice_currency,
			posting_date,
		):
			return _get_items(
				profile,
				price_list,
				item_group,
				search_value,
				customer,
				limit,
				invoice_currency,
				posting_date,
			)

		return _cached(
			profile_name,
			price_list,
			item_group,
			search_value,
			customer,
			limit,
			invoice_currency,
			posting_date,
		)

	return _get_items(
		profile,
		price_list,
		item_group,
		search_value,
		customer,
		limit,
		invoice_currency,
		posting_date,
	)


def _get_items(
	profile,
	price_list,
	item_group,
	search_value,
	customer,
	limit,
	invoice_currency=None,
	posting_date=None,
):
	warehouse = profile.get("warehouse")
	price_list = price_list or profile.get("selling_price_list")
	use_limit_search = cint(profile.get("pose_use_limit_search"))
	only_in_stock = cint(profile.get("posa_display_items_in_stock"))
	show_templates = cint(profile.get("posa_show_template_items"))
	hide_variants = cint(profile.get("posa_hide_variants_items"))

	page_length = cint(limit) or (cint(profile.get("posa_search_limit")) or 500 if use_limit_search else 0)

	item = frappe.qb.DocType("Item")
	query = (
		frappe.qb.from_(item)
		.select(
			item.name.as_("item_code"),
			item.item_name,
			item.description,
			item.stock_uom,
			item.image,
			item.is_stock_item,
			item.has_variants,
			item.variant_of,
			item.item_group,
			item.has_batch_no,
			item.has_serial_no,
			item.max_discount,
			item.brand,
		)
		.where(item.disabled == 0)
		.where(item.is_sales_item == 1)
		.where(item.is_fixed_asset == 0)
		.orderby(item.item_name)
	)

	allowed_groups = get_item_groups(profile.get("name"))
	if allowed_groups:
		query = query.where(item.item_group.isin(allowed_groups))

	if item_group:
		query = query.where(item.item_group == item_group)

	if not show_templates:
		query = query.where(item.has_variants == 0)
	if hide_variants:
		query = query.where(item.variant_of.isnull() | (item.variant_of == ""))

	if search_value:
		resolved = search_serial_or_batch_or_barcode_number(
			search_value, cint(profile.get("posa_search_serial_no"))
		)
		if resolved.get("item_code"):
			query = query.where(item.name == resolved["item_code"])
		else:
			pattern = f"%{search_value}%"
			query = query.where(item.name.like(pattern) | item.item_name.like(pattern))

	if page_length:
		query = query.limit(page_length)

	items_data = query.run(as_dict=True)
	if not items_data:
		return []

	return _decorate_items(
		items_data,
		profile,
		price_list,
		warehouse,
		customer,
		only_in_stock,
		invoice_currency,
		posting_date,
	)


def _decorate_items(
	items_data,
	profile,
	price_list,
	warehouse,
	customer,
	only_in_stock,
	invoice_currency=None,
	posting_date=None,
):
	"""Attach prices, barcodes, stock and (optionally) batch/serial data in bulk."""
	item_codes = [row.item_code for row in items_data]

	currency_context = build_currency_context(
		profile,
		invoice_currency=invoice_currency,
		price_list=price_list,
		posting_date=posting_date,
	)
	prices = _get_item_prices(
		item_codes,
		price_list,
		currency_context["price_list_currency"],
		customer,
	)
	rate_factor = flt(currency_context["item_rate_factor"]) or 1
	barcodes = _get_barcodes(item_codes)
	stock = get_stock_availability_bulk(item_codes, warehouse) if warehouse else {}
	uoms = _get_uoms_bulk(item_codes)

	search_batch = cint(profile.get("posa_search_batch_no"))
	search_serial = cint(profile.get("posa_search_serial_no"))
	show_templates = cint(profile.get("posa_show_template_items"))

	result = []
	for row in items_data:
		item_code = row.item_code
		qty_on_hand = flt(stock.get(item_code))

		if only_in_stock and row.is_stock_item and qty_on_hand <= 0:
			continue

		price = prices.get(item_code, {}).get(row.stock_uom) or prices.get(item_code, {}).get("__any__") or {}
		item_uoms = uoms.get(item_code, [])
		for uom in item_uoms:
			uom_price = prices.get(item_code, {}).get(uom["uom"])
			if uom_price:
				uom["rate"] = flt(uom_price.get("price_list_rate")) * rate_factor
			elif price:
				uom["rate"] = (
					flt(price.get("price_list_rate"))
					* flt(uom.get("conversion_factor") or 1)
					* rate_factor
				)

		row.update(
			{
				"rate": flt(price.get("price_list_rate")) * rate_factor,
				"currency": currency_context["invoice_currency"],
				"item_barcode": barcodes.get(item_code, []),
				"item_uoms": item_uoms,
				"actual_qty": qty_on_hand,
				"batch_no_data": (
					get_available_batches(item_code, warehouse) if search_batch and row.has_batch_no else []
				),
				"serial_no_data": (
					get_available_serial_nos(item_code, warehouse) if search_serial and row.has_serial_no else []
				),
				"attributes": (
					get_item_attributes(item_code) if show_templates and row.has_variants else ""
				),
				"item_attributes": (
					_get_variant_attributes(item_code) if show_templates and row.variant_of else ""
				),
			}
		)
		result.append(row)

	return result


def _get_item_prices(item_codes, price_list, currency, customer=None):
	"""{item_code: {uom_or___any__: price_row}} for the whole batch of items."""
	if not price_list or not item_codes:
		return {}

	today = nowdate()
	ip = frappe.qb.DocType("Item Price")
	rows = (
		frappe.qb.from_(ip)
		.select(ip.item_code, ip.price_list_rate, ip.currency, ip.uom)
		.where(ip.price_list == price_list)
		.where(ip.item_code.isin(item_codes))
		.where(ip.selling == 1)
		.where(ip.currency == currency)
		# An empty validity window means "always valid", which is how nearly every
		# plain selling price is stored. A `valid_from <= today` comparison drops
		# those rows silently and the whole catalog prices at zero.
		.where(ip.valid_from.isnull() | (ip.valid_from <= today))
		.where(ip.valid_upto.isnull() | (ip.valid_upto >= today))
		.where(ip.customer.isnull() | (ip.customer == "") | (ip.customer == customer))
		# Ascending puts the open-ended rows first, so a dated, more specific price
		# overwrites the generic one below.
		.orderby(ip.valid_from)
		.run(as_dict=True)
	)

	prices = {}
	for row in rows:
		# Later rows win, so the most specific validity window ends up in place.
		prices.setdefault(row.item_code, {})[row.uom or "__any__"] = row
	return prices


def _get_barcodes(item_codes):
	if not item_codes:
		return {}
	rows = frappe.get_all(
		"Item Barcode",
		filters={"parent": ["in", item_codes]},
		fields=["parent", "barcode", "posa_uom"],
	)
	barcodes = {}
	for row in rows:
		barcodes.setdefault(row.parent, []).append({"barcode": row.barcode, "posa_uom": row.posa_uom})
	return barcodes


def _get_variant_attributes(item_code):
	return frappe.get_all(
		"Item Variant Attribute",
		fields=["attribute", "attribute_value"],
		filters={"parent": item_code, "parentfield": "attributes"},
		order_by="idx asc",
	)


@frappe.whitelist()
def get_items_groups(pos_profile=None):
	"""Leaf item groups, restricted to the profile's allowed groups when set."""
	filters = {"is_group": 0}
	if pos_profile:
		allowed = get_item_groups(pos_profile)
		if allowed:
			filters["name"] = ["in", allowed]
	return frappe.get_all("Item Group", filters=filters, fields=["name"], order_by="name", limit_page_length=500)


# ---------------------------------------------------------------------------
# Per-item detail
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_item_detail(item, doc=None, warehouse=None, price_list=None):
	"""Priced, taxed detail for one item — the cart's source of truth for a line."""
	item = as_dict(item)
	item_code = item.get("item_code")
	if not item_code:
		frappe.throw(_("Item Code is required"))

	item["selling_price_list"] = price_list
	details = get_item_details(item, as_dict(doc, {}) or None, overwrite_warehouse=False)

	if warehouse and item.get("is_stock_item"):
		details["actual_qty"] = get_stock_availability(item_code, warehouse)

	has_batch_no, has_serial_no, max_discount = frappe.get_cached_value(
		"Item", item_code, ["has_batch_no", "has_serial_no", "max_discount"]
	)
	details["max_discount"] = max_discount
	details["has_batch_no"] = has_batch_no
	details["has_serial_no"] = has_serial_no
	details["batch_no_data"] = get_available_batches(item_code, warehouse) if has_batch_no and warehouse else []
	details["serial_no_data"] = (
		get_available_serial_nos(item_code, warehouse) if has_serial_no and warehouse else []
	)
	prices = _get_item_prices(
		[item_code],
		price_list,
		item.get("price_list_currency")
		or frappe.get_cached_value("Price List", price_list, "currency")
		or frappe.get_cached_value("Company", item.get("company"), "default_currency"),
		item.get("customer"),
	).get(item_code, {})
	conversion_rate = flt(item.get("conversion_rate")) or 1
	plc_conversion_rate = flt(item.get("plc_conversion_rate")) or conversion_rate
	details["item_uoms"] = _uoms_with_prices(
		item_code,
		prices,
		plc_conversion_rate / conversion_rate,
	)
	return details


@frappe.whitelist()
def get_items_details(pos_profile, items_data):
	"""Stock, UOM and serial/batch data for a set of cart items, in bulk."""
	profile = as_dict(pos_profile)
	rows = as_list(items_data)
	if not rows:
		return []

	warehouse = profile.get("warehouse")
	item_codes = [row.get("item_code") for row in rows if row.get("item_code")]
	stock = get_stock_availability_bulk(item_codes, warehouse)
	uoms = _get_uoms_bulk(item_codes)
	flags = {
		row.name: row
		for row in frappe.get_all(
			"Item",
			filters={"name": ["in", item_codes]},
			fields=["name", "has_batch_no", "has_serial_no"],
		)
	}

	result = []
	for row in rows:
		item_code = row.get("item_code")
		flag = flags.get(item_code) or frappe._dict(has_batch_no=0, has_serial_no=0)
		row = dict(row)
		row.update(
			{
				"item_uoms": uoms.get(item_code, []),
				"actual_qty": flt(stock.get(item_code)),
				"has_batch_no": flag.has_batch_no,
				"has_serial_no": flag.has_serial_no,
				"batch_no_data": (
					get_available_batches(item_code, warehouse) if flag.has_batch_no and warehouse else []
				),
				"serial_no_data": (
					get_available_serial_nos(item_code, warehouse) if flag.has_serial_no and warehouse else []
				),
			}
		)
		result.append(row)
	return result


def _get_uoms(item_code):
	return frappe.get_all(
		"UOM Conversion Detail",
		filters={"parent": item_code},
		fields=["uom", "conversion_factor"],
		order_by="idx asc",
	)


def _uoms_with_prices(item_code, prices, rate_factor=1):
	uoms = _get_uoms(item_code)
	stock_uom = next(
		(row.uom for row in uoms if flt(row.conversion_factor) == 1),
		"",
	)
	base = prices.get("__any__") or prices.get(stock_uom)
	for row in uoms:
		price = prices.get(row.uom)
		if price:
			row["rate"] = flt(price.get("price_list_rate")) * rate_factor
		elif base:
			row["rate"] = (
				flt(base.get("price_list_rate"))
				* flt(row.conversion_factor or 1)
				* rate_factor
			)
	return uoms


def _get_uoms_bulk(item_codes):
	if not item_codes:
		return {}
	rows = frappe.get_all(
		"UOM Conversion Detail",
		filters={"parent": ["in", item_codes]},
		fields=["parent", "uom", "conversion_factor"],
		order_by="idx asc",
	)
	uoms = {}
	for row in rows:
		uoms.setdefault(row.parent, []).append({"uom": row.uom, "conversion_factor": row.conversion_factor})
	return uoms


@frappe.whitelist()
def get_serial_batch_availability(item_code, warehouse, qty=None, posting_date=None):
	"""Everything the serial/batch picker needs for one item."""
	has_batch_no, has_serial_no = frappe.get_cached_value("Item", item_code, ["has_batch_no", "has_serial_no"])
	payload = {
		"item_code": item_code,
		"has_batch_no": has_batch_no,
		"has_serial_no": has_serial_no,
		"batches": get_available_batches(item_code, warehouse, posting_date) if has_batch_no else [],
		"serial_nos": get_available_serial_nos(item_code, warehouse) if has_serial_no else [],
	}

	# Offer a default FIFO/expiry pick so the cashier can accept and move on.
	if has_batch_no and flt(qty) > 0:
		remaining = flt(qty)
		suggestion = []
		for batch in payload["batches"]:
			if remaining <= 0:
				break
			take = min(remaining, flt(batch["batch_qty"]))
			suggestion.append({"batch_no": batch["batch_no"], "qty": take})
			remaining -= take
		payload["suggested_batches"] = suggestion
		payload["shortfall"] = flt(remaining)

	return payload


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


@frappe.whitelist()
def search_serial_or_batch_or_barcode_number(search_value, search_serial_no=0):
	"""Resolve a scanned string to an item, trying barcode then serial then batch."""
	if not search_value:
		return {}

	barcode = frappe.db.get_value(
		"Item Barcode",
		{"barcode": search_value},
		["barcode", "parent as item_code", "posa_uom"],
		as_dict=True,
	)
	if barcode:
		return barcode

	if cint(search_serial_no):
		serial = frappe.db.get_value(
			"Serial No", search_value, ["name as serial_no", "item_code"], as_dict=True
		)
		if serial:
			return serial

	batch = frappe.db.get_value("Batch", search_value, ["name as batch_no", "item as item_code"], as_dict=True)
	if batch:
		return batch

	return {}


@frappe.whitelist()
def scan_code(
	pos_profile,
	code,
	price_list=None,
	customer=None,
	invoice_currency=None,
	posting_date=None,
):
	"""Resolve a scan straight into a ready-to-add item row.

	Returns ``None`` when nothing matches so the client can show "no such barcode"
	without a second round trip.
	"""
	profile = as_dict(pos_profile)
	check_pos_profile_access(profile.get("name"))

	resolved = search_serial_or_batch_or_barcode_number(code, cint(profile.get("posa_search_serial_no")))
	if not resolved.get("item_code"):
		return None

	items = _get_items(
		profile,
		price_list,
		"",
		resolved["item_code"],
		customer,
		1,
		invoice_currency,
		posting_date,
	)
	if not items:
		return None

	item = items[0]
	# Carry the scan context so the cart can preselect the right UOM/serial/batch.
	item["scanned_barcode"] = resolved.get("barcode")
	item["scanned_uom"] = resolved.get("posa_uom")
	item["scanned_serial_no"] = resolved.get("serial_no")
	item["scanned_batch_no"] = resolved.get("batch_no")
	return item


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------


def _build_item_variant_cache(template_item_code):
	attributes = [
		row.attribute
		for row in frappe.get_all(
			"Item Variant Attribute", {"parent": template_item_code}, ["attribute"], order_by="idx asc"
		)
	]

	variant_rows = frappe.get_all(
		"Item Variant Attribute",
		{"variant_of": template_item_code},
		["parent", "attribute", "attribute_value"],
		order_by="name",
		as_list=True,
	)

	disabled = {row.name for row in frappe.get_all("Item", {"disabled": 1}, ["name"])}
	variant_rows = [row for row in variant_rows if row[0] not in disabled]

	attribute_value_item_map = frappe._dict()
	item_attribute_value_map = frappe._dict()
	for item_code, attribute, attribute_value in variant_rows:
		attribute_value_item_map.setdefault((attribute, attribute_value), []).append(item_code)
		item_attribute_value_map.setdefault(item_code, {})[attribute] = attribute_value

	optional_attributes = set()
	for attr_map in item_attribute_value_map.values():
		for attribute in attributes:
			if attribute not in attr_map:
				optional_attributes.add(attribute)

	cache = frappe.cache()
	cache.hset("posa_attribute_value_item_map", template_item_code, attribute_value_item_map)
	cache.hset("posa_item_attribute_value_map", template_item_code, item_attribute_value_map)
	cache.hset("posa_item_variants_data", template_item_code, variant_rows)
	cache.hset("posa_optional_attributes", template_item_code, optional_attributes)
	return optional_attributes


def _get_item_optional_attributes(item_code):
	cached = frappe.cache().hget("posa_optional_attributes", item_code)
	if cached is None:
		return _build_item_variant_cache(item_code)
	return cached


@frappe.whitelist()
def get_item_attributes(item_code):
	"""Attribute/value matrix for a template item, for the variant picker."""
	attributes = frappe.get_all(
		"Item Variant Attribute",
		fields=["attribute"],
		filters={"parenttype": "Item", "parent": item_code},
		order_by="idx asc",
	)

	optional_attributes = _get_item_optional_attributes(item_code) or set()

	for attribute in attributes:
		attribute.values = frappe.get_all(
			"Item Attribute Value",
			fields=["attribute_value", "abbr"],
			filters={"parenttype": "Item Attribute", "parent": attribute.attribute},
			order_by="idx asc",
		)
		if attribute.attribute in optional_attributes:
			attribute.optional = True

	return attributes


@frappe.whitelist()
def get_variant_items(template_item_code, pos_profile, price_list=None):
	"""Enabled variants of a template, priced and stocked like the main list."""
	profile = as_dict(pos_profile)
	variants = frappe.get_all(
		"Item",
		filters={"variant_of": template_item_code, "disabled": 0, "is_sales_item": 1},
		fields=[field for field in ITEM_FIELDS if field != "idx"],
		order_by="item_name asc",
	)
	if not variants:
		return []
	return _decorate_items(
		variants,
		profile,
		price_list or profile.get("selling_price_list"),
		profile.get("warehouse"),
		None,
		cint(profile.get("posa_display_items_in_stock")),
	)
