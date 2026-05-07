# Copyright (c) 2017, Frappe Technologies and Contributors
# License: MIT. See LICENSE
from unittest.mock import patch

import frappe
from frappe.core.doctype.sms_settings import sms_settings
from frappe.tests import IntegrationTestCase


class TestSMSSettings(IntegrationTestCase):
	def test_create_nested_param_supports_indexed_paths(self):
		payload = {}
		sms_settings.create_nested_param(payload, "messages[0].destinations[0].to", "20123456789")
		sms_settings.create_nested_param(payload, "messages[0].text", "Hello")

		self.assertEqual(
			payload,
			{"messages": [{"destinations": [{"to": "20123456789"}], "text": "Hello"}]},
		)

	def test_create_nested_param_supports_whitespace_in_index(self):
		payload = {}
		sms_settings.create_nested_param(payload, "messages[ 0 ].text", "Hello")
		self.assertEqual(payload, {"messages": [{"text": "Hello"}]})

	def test_create_nested_param_rejects_non_numeric_index(self):
		with self.assertRaises(frappe.ValidationError):
			sms_settings.create_nested_param({}, "messages[foo].text", "Hello")

	def test_create_nested_param_rejects_index_root_path(self):
		with self.assertRaises(frappe.ValidationError):
			sms_settings.create_nested_param({}, "[0].to", "20123456789")

	def test_create_nested_param_rejects_container_type_mismatch(self):
		payload = {"messages": {}}
		with self.assertRaises(frappe.ValidationError):
			sms_settings.create_nested_param(payload, "messages[0].text", "Hello")

	def test_send_via_gateway_supports_nested_message_and_receiver_paths(self):
		sms_doc = frappe._dict(
			{
				"message_parameter": "messages[0].text",
				"receiver_parameter": "messages[0].destinations[0].to",
				"use_post": 1,
				"sms_gateway_url": "https://example.test/sms/2/text/advanced",
				"parameters": [
					frappe._dict({"header": 1, "parameter": "Authorization", "value": "App KEY"}),
					frappe._dict({"header": 1, "parameter": "Content-Type", "value": "application/json"}),
					frappe._dict({"header": 0, "parameter": "messages[0].from", "value": "ServiceSMS"}),
				],
			}
		)

		calls = []

		def fake_send_request(gateway_url, params, headers=None, use_post=False, use_json=False):
			calls.append(
				{
					"gateway_url": gateway_url,
					"params": frappe.as_json(params),
					"headers": headers,
					"use_post": use_post,
					"use_json": use_json,
				}
			)
			return 200

		arg = {"receiver_list": ["201", "202"], "message": b"Hello", "success_msg": False}

		with (
			patch.object(sms_settings.frappe, "get_doc", return_value=sms_doc),
			patch.object(sms_settings, "send_request", side_effect=fake_send_request),
			patch.object(sms_settings, "create_sms_log"),
		):
			sms_settings.send_via_gateway(arg)

		self.assertEqual(len(calls), 2)
		first_payload = frappe.parse_json(calls[0]["params"])
		second_payload = frappe.parse_json(calls[1]["params"])

		self.assertEqual(first_payload["messages"][0]["text"], "Hello")
		self.assertEqual(first_payload["messages"][0]["from"], "ServiceSMS")
		self.assertEqual(first_payload["messages"][0]["destinations"][0]["to"], "201")
		self.assertEqual(second_payload["messages"][0]["destinations"][0]["to"], "202")
		self.assertEqual(calls[0]["headers"]["Authorization"], "App KEY")
		self.assertEqual(calls[0]["headers"]["Content-Type"], "application/json")
		self.assertTrue(calls[0]["use_json"])
		self.assertTrue(calls[1]["use_json"])

	def test_send_via_gateway_rejects_nested_paths_without_json_mode(self):
		sms_doc = frappe._dict(
			{
				"message_parameter": "messages[0].text",
				"receiver_parameter": "messages[0].destinations[0].to",
				"use_post": 1,
				"sms_gateway_url": "https://example.test/sms/2/text/advanced",
				"parameters": [
					frappe._dict({"header": 1, "parameter": "Authorization", "value": "App KEY"}),
					frappe._dict({"header": 0, "parameter": "messages[0].from", "value": "ServiceSMS"}),
				],
			}
		)

		arg = {"receiver_list": ["201"], "message": b"Hello", "success_msg": False}

		with (
			patch.object(sms_settings.frappe, "get_doc", return_value=sms_doc),
			patch.object(sms_settings, "send_request") as mock_send_request,
			self.assertRaises(frappe.ValidationError),
		):
			sms_settings.send_via_gateway(arg)

		mock_send_request.assert_not_called()
