# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import frappe
from frappe import _, msgprint, throw
from frappe.model.document import Document
from frappe.utils import nowdate


class SMSSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.core.doctype.sms_parameter.sms_parameter import SMSParameter
		from frappe.types import DF

		message_parameter: DF.Data
		parameters: DF.Table[SMSParameter]
		receiver_parameter: DF.Data
		sms_gateway_url: DF.SmallText
		use_post: DF.Check
	# end: auto-generated types

	pass


def validate_receiver_nos(receiver_list):
	validated_receiver_list = []
	for d in receiver_list:
		if not d:
			continue

		# remove invalid character
		for x in [" ", "-", "(", ")"]:
			d = d.replace(x, "")

		validated_receiver_list.append(d)

	if not validated_receiver_list:
		throw(_("Please enter valid mobile nos"))

	return validated_receiver_list


@frappe.whitelist()
def get_contact_number(contact_name: str, ref_doctype: str, ref_name: str):
	"Return mobile number of the given contact."
	number = frappe.db.sql(
		"""select mobile_no, phone from tabContact
		where name=%s
			and exists(
				select name from `tabDynamic Link` where link_doctype=%s and link_name=%s
			)
	""",
		(contact_name, ref_doctype, ref_name),
	)

	return (number and (number[0][0] or number[0][1])) or ""


@frappe.whitelist()
def send_sms(receiver_list: str | list[str], msg: str, sender_name: str = "", success_msg: bool = True):
	send_sms_hook_methods = frappe.get_hooks("send_sms")
	if send_sms_hook_methods:
		return frappe.get_attr(send_sms_hook_methods[-1])(receiver_list, msg, sender_name, success_msg)

	import json

	if isinstance(receiver_list, str):
		receiver_list = json.loads(receiver_list)
		if not isinstance(receiver_list, list):
			receiver_list = [receiver_list]

	receiver_list = validate_receiver_nos(receiver_list)

	arg = {
		"receiver_list": receiver_list,
		"message": frappe.safe_decode(msg).encode("utf-8"),
		"success_msg": success_msg,
	}

	if frappe.db.get_single_value("SMS Settings", "sms_gateway_url"):
		send_via_gateway(arg)
	else:
		msgprint(_("Please Update SMS Settings"))


def is_nested_path(path):
	return "." in (path or "") or "[" in (path or "")


def validate_nested_params_for_json_mode(sms_settings, use_json):
	if use_json:
		return

	nested_params = []
	if is_nested_path(sms_settings.message_parameter):
		nested_params.append(sms_settings.message_parameter)
	if is_nested_path(sms_settings.receiver_parameter):
		nested_params.append(sms_settings.receiver_parameter)

	for d in sms_settings.get("parameters"):
		if not d.header and is_nested_path(d.parameter):
			nested_params.append(d.parameter)

	if nested_params:
		throw(
			_(
				"Nested SMS parameter paths require JSON mode. Set header Content-Type to application/json. Offending parameters: {0}"
			).format(", ".join(sorted(set(nested_params))))
		)


def create_nested_param(data, key, value):
	if "." not in key and "[" not in key:
		data[key] = value
		return

	def parse_key_tokens(path):
		tokens = []
		for part in path.split("."):
			if not part:
				continue

			cursor = 0
			while cursor < len(part):
				if part[cursor] == "[":
					end = part.find("]", cursor)
					if end == -1:
						throw(
							_(
								"Invalid nested SMS parameter path: {0}. Missing closing ']' for an array index."
							).format(path)
						)

					index_text = part[cursor + 1 : end].strip()
					if not index_text.isdigit():
						throw(
							_(
								"Invalid nested SMS parameter path: {0}. Array index '{1}' must be a non-negative integer."
							).format(path, part[cursor + 1 : end])
						)

					tokens.append(int(index_text))
					cursor = end + 1
				else:
					next_bracket = part.find("[", cursor)
					if next_bracket == -1:
						tokens.append(part[cursor:])
						break
					tokens.append(part[cursor:next_bracket])
					cursor = next_bracket
		return tokens

	def get_container_name(container):
		if isinstance(container, dict):
			return "object"
		if isinstance(container, list):
			return "array"
		return type(container).__name__

	def throw_invalid_path(path, token, parent):
		throw(
			_(
				"Invalid nested SMS parameter path '{0}': token '{1}' expects a different container, but found {2}."
			).format(path, token, get_container_name(parent))
		)

	tokens = parse_key_tokens(key)
	if not tokens:
		throw(_("Invalid nested SMS parameter path: {0}").format(key))
	if isinstance(tokens[0], int):
		throw_invalid_path(key, tokens[0], data)

	parent = data
	for i, token in enumerate(tokens):
		is_last = i == len(tokens) - 1
		next_token = None if is_last else tokens[i + 1]

		if isinstance(token, int):
			if not isinstance(parent, list):
				throw_invalid_path(key, token, parent)
			while len(parent) <= token:
				parent.append(None)

			if is_last:
				parent[token] = value
				return

			expected_container = list if isinstance(next_token, int) else dict
			if parent[token] is None:
				parent[token] = expected_container()
			elif not isinstance(parent[token], expected_container):
				throw_invalid_path(key, next_token, parent[token])
			parent = parent[token]
			continue

		if not isinstance(parent, dict):
			throw_invalid_path(key, token, parent)
		if is_last:
			parent[token] = value
			return

		expected_container = list if isinstance(next_token, int) else dict
		if token not in parent:
			parent[token] = expected_container()
		elif not isinstance(parent[token], expected_container):
			throw_invalid_path(key, next_token, parent[token])
		parent = parent[token]


def is_json_content_type(headers):
	if not headers:
		return False

	content_type = None
	for key, value in headers.items():
		if isinstance(key, str) and key.lower() == "content-type":
			content_type = value
			break

	if not isinstance(content_type, str):
		return False

	media_type = content_type.split(";", 1)[0].strip().lower()
	return media_type == "application/json"


def send_via_gateway(arg):
	ss = frappe.get_doc("SMS Settings", "SMS Settings")
	headers = get_headers(ss)
	use_json = is_json_content_type(headers)
	validate_nested_params_for_json_mode(ss, use_json)

	message = frappe.safe_decode(arg.get("message"))
	args = {}
	create_nested_param(args, ss.message_parameter, message)
	for d in ss.get("parameters"):
		if not d.header:
			create_nested_param(args, d.parameter, d.value)

	success_list = []
	for d in arg.get("receiver_list"):
		create_nested_param(args, ss.receiver_parameter, d)
		status = send_request(ss.sms_gateway_url, args, headers, ss.use_post, use_json)

		if 200 <= status < 300:
			success_list.append(d)

	if len(success_list) > 0:
		args.update(arg)
		create_sms_log(args, success_list)
		if arg.get("success_msg"):
			frappe.msgprint(_("SMS sent successfully"))


def get_headers(sms_settings=None):
	if not sms_settings:
		sms_settings = frappe.get_doc("SMS Settings", "SMS Settings")

	headers = {"Accept": "text/plain, text/html, */*"}
	for d in sms_settings.get("parameters"):
		if d.header == 1:
			headers[d.parameter] = d.value

	return headers


def send_request(gateway_url, params, headers=None, use_post=False, use_json=False):
	import requests

	if not headers:
		headers = get_headers()
	kwargs = {"headers": headers}

	if use_json:
		kwargs["json"] = params
	elif use_post:
		kwargs["data"] = params
	else:
		kwargs["params"] = params

	if use_post:
		response = requests.post(gateway_url, **kwargs)
	else:
		response = requests.get(gateway_url, **kwargs)
	response.raise_for_status()
	return response.status_code


# Create SMS Log
# =========================================================
def create_sms_log(args, sent_to):
	sl = frappe.new_doc("SMS Log")
	sl.sent_on = nowdate()
	sl.message = args["message"].decode("utf-8")
	sl.no_of_requested_sms = len(args["receiver_list"])
	sl.requested_numbers = "\n".join(args["receiver_list"])
	sl.no_of_sent_sms = len(sent_to)
	sl.sent_to = "\n".join(sent_to)
	sl.flags.ignore_permissions = True
	sl.save()
