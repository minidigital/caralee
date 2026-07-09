import base64
import json
import logging
from urllib.parse import urlencode

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

EBAY_MARKETPLACE_AU = "EBAY_AU"
EBAY_SCOPES = " ".join([
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    "https://api.ebay.com/oauth/api_scope/sell.account",
])


class EbayApiMixin(models.AbstractModel):
    _name = "ebay.au.api.mixin"
    _description = "eBay Australia API helpers"

    @api.model
    def _ebay_hosts(self, environment):
        if environment == "production":
            return {
                "api": "https://api.ebay.com",
                "auth": "https://auth.ebay.com",
            }
        return {
            "api": "https://api.sandbox.ebay.com",
            "auth": "https://auth.sandbox.ebay.com",
        }

    def _ebay_basic_auth_header(self, client_id, client_secret):
        token = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        return f"Basic {token}"

    def _ebay_request(self, account, method, path, payload=None, params=None):
        account._ebay_refresh_token_if_needed()
        if not account.access_token:
            raise UserError(_("Connect the eBay account before calling the API."))

        hosts = self._ebay_hosts(account.environment)
        url = f"{hosts['api']}{path}"
        headers = {
            "Authorization": f"Bearer {account.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Content-Language": "en-AU",
        }
        response = requests.request(
            method,
            url,
            headers=headers,
            json=payload,
            params=params,
            timeout=60,
        )
        if response.status_code >= 400:
            message = response.text
            try:
                message = json.dumps(response.json(), indent=2)
            except Exception:
                pass
            _logger.error("eBay API error %s %s: %s", method, path, message)
            raise UserError(_("eBay API error (%(status)s): %(message)s") % {
                "status": response.status_code,
                "message": message,
            })
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def _ebay_build_authorize_url(self, account, state):
        hosts = self._ebay_hosts(account.environment)
        query = urlencode({
            "client_id": account.client_id,
            "redirect_uri": account.ru_name,
            "response_type": "code",
            "scope": EBAY_SCOPES,
            "state": state,
        })
        return f"{hosts['auth']}/oauth2/authorize?{query}"

    def _ebay_exchange_code(self, account, code):
        hosts = self._ebay_hosts(account.environment)
        response = requests.post(
            f"{hosts['api']}/identity/v1/oauth2/token",
            headers={
                "Authorization": self._ebay_basic_auth_header(
                    account.client_id, account.client_secret
                ),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": account.ru_name,
            },
            timeout=60,
        )
        if response.status_code >= 400:
            raise UserError(_("Failed to exchange eBay authorization code: %s") % response.text)
        return response.json()

    def _ebay_refresh_access_token(self, account):
        if not account.refresh_token:
            raise UserError(_("No refresh token stored for this eBay account."))
        hosts = self._ebay_hosts(account.environment)
        response = requests.post(
            f"{hosts['api']}/identity/v1/oauth2/token",
            headers={
                "Authorization": self._ebay_basic_auth_header(
                    account.client_id, account.client_secret
                ),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": account.refresh_token,
                "scope": EBAY_SCOPES,
            },
            timeout=60,
        )
        if response.status_code >= 400:
            raise UserError(_("Failed to refresh eBay token: %s") % response.text)
        return response.json()

    def _ebay_get_product_stock_qty(self, product):
        if product.type == "product":
            return int(product.qty_available)
        return 1

    def _ebay_is_out_of_stock(self, product):
        return product.type == "product" and int(product.qty_available) <= 0

    def _ebay_compute_sync_pricing(self, account, product):
        base_price = product.list_price
        quantity = self._ebay_get_product_stock_qty(product)
        ebay_price = base_price
        bump_active = False
        if self._ebay_is_out_of_stock(product) and account.out_of_stock_price_bump_enabled:
            ebay_price = base_price + account.out_of_stock_price_increase
            bump_active = True
        return {
            "base_price": base_price,
            "price": ebay_price,
            "quantity": max(quantity, 0),
            "out_of_stock_price_active": bump_active,
        }

    def _ebay_inventory_payload(self, product, account, quantity=None):
        sku = product.ebay_sku or product.default_code or str(product.id)
        description = product.description_sale or product.name
        if quantity is None:
            quantity = self._ebay_get_product_stock_qty(product)
        return {
            "availability": {
                "shipToLocationAvailability": {
                    "quantity": max(int(quantity), 0),
                },
            },
            "condition": product.ebay_condition or "NEW",
            "product": {
                "title": product.name[:80],
                "description": description or product.name,
                "aspects": {
                    "Brand": [product.ebay_brand or "Unbranded"],
                },
            },
        }, sku

    def _ebay_offer_payload(self, listing):
        product = listing.product_id
        account = listing.account_id
        return {
            "sku": listing.sku,
            "marketplaceId": EBAY_MARKETPLACE_AU,
            "format": "FIXED_PRICE",
            "availableQuantity": listing.quantity,
            "categoryId": listing.category_id or account.default_category_id,
            "listingDescription": product.description_sale or product.name,
            "listingPolicies": {
                "paymentPolicyId": account.payment_policy_id,
                "fulfillmentPolicyId": account.fulfillment_policy_id,
                "returnPolicyId": account.return_policy_id,
            },
            "merchantLocationKey": account.merchant_location_key,
            "pricingSummary": {
                "price": {
                    "currency": listing.currency_id.name,
                    "value": f"{listing.price:.2f}",
                },
            },
        }

    def _ebay_order_to_partner_vals(self, buyer):
        username = buyer.get("username") or "eBay Buyer"
        return {
            "name": username,
            "email": buyer.get("buyerRegistrationAddress", {}).get("email"),
            "customer_rank": 1,
        }

    def _ebay_order_to_sale_vals(self, account, order_payload):
        pricing = order_payload.get("pricingSummary", {})
        total = pricing.get("total", {})
        buyer = order_payload.get("buyer", {})
        partner_vals = self._ebay_order_to_partner_vals(buyer)
        partner = self.env["res.partner"].search([
            ("name", "=", partner_vals["name"]),
            ("email", "=", partner_vals.get("email")),
        ], limit=1)
        if not partner:
            partner = self.env["res.partner"].create(partner_vals)

        lines = []
        for item in order_payload.get("lineItems", []):
            sku = item.get("sku")
            product = self.env["product.product"].search([
                ("default_code", "=", sku),
            ], limit=1)
            if not product:
                product = self.env["product.product"].create({
                    "name": item.get("title") or sku or "eBay Item",
                    "default_code": sku,
                    "type": "consu",
                    "list_price": float(
                        item.get("lineItemCost", {}).get("value", 0.0)
                    ),
                })
            lines.append((0, 0, {
                "product_id": product.id,
                "product_uom_qty": int(item.get("quantity", 1)),
                "price_unit": float(item.get("lineItemCost", {}).get("value", 0.0)),
                "name": item.get("title") or product.display_name,
            }))

        currency_name = total.get("currency", "AUD")
        currency = self.env["res.currency"].search([("name", "=", currency_name)], limit=1)
        return {
            "partner_id": partner.id,
            "origin": f"eBay {order_payload.get('orderId')}",
            "client_order_ref": order_payload.get("orderId"),
            "currency_id": currency.id if currency else account.company_id.currency_id.id,
            "order_line": lines,
            "note": "Imported from eBay Australia.",
        }
