import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EbayAccount(models.Model):
    _name = "ebay.au.account"
    _description = "eBay Australia Account"
    _inherit = ["ebay.au.api.mixin"]
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    environment = fields.Selection(
        [
            ("sandbox", "Sandbox"),
            ("production", "Production"),
        ],
        default="sandbox",
        required=True,
    )
    marketplace_id = fields.Char(default="EBAY_AU", readonly=True)
    client_id = fields.Char(string="App ID (Client ID)", required=True)
    client_secret = fields.Char(string="Cert ID (Client Secret)", required=True)
    ru_name = fields.Char(
        string="RuName (Redirect URL name)",
        required=True,
        help="The RuName configured in your eBay developer application.",
    )
    access_token = fields.Char(copy=False)
    refresh_token = fields.Char(copy=False)
    token_expiry = fields.Datetime(copy=False)
    payment_policy_id = fields.Char(string="Payment Policy ID")
    fulfillment_policy_id = fields.Char(string="Fulfillment Policy ID")
    return_policy_id = fields.Char(string="Return Policy ID")
    merchant_location_key = fields.Char(
        default="default_location",
        help="Inventory location key used when publishing offers.",
    )
    default_category_id = fields.Char(
        string="Default eBay Category ID",
        help="Fallback eBay category for new listings.",
    )
    out_of_stock_price_bump_enabled = fields.Boolean(
        string="Increase Price When Out of Stock",
        default=True,
        help="When warehouse stock is zero, add the configured amount to the eBay listing price.",
    )
    out_of_stock_price_increase = fields.Monetary(
        string="Out of Stock Price Increase",
        default=1100.0,
        currency_field="company_currency_id",
        help="Amount added to the Odoo sales price when the product is out of stock.",
    )
    company_currency_id = fields.Many2one(
        related="company_id.currency_id",
        readonly=True,
    )
    last_order_sync = fields.Datetime(readonly=True)
    state = fields.Selection(
        [
            ("draft", "Not Connected"),
            ("connected", "Connected"),
            ("error", "Error"),
        ],
        default="draft",
        readonly=True,
    )
    listing_count = fields.Integer(compute="_compute_counts")
    order_count = fields.Integer(compute="_compute_counts")
    product_count = fields.Integer(compute="_compute_counts")

    @api.depends("name")
    def _compute_counts(self):
        Listing = self.env["ebay.au.listing"]
        Order = self.env["ebay.au.order"]
        Product = self.env["product.template"]
        for account in self:
            account.listing_count = Listing.search_count([("account_id", "=", account.id)])
            account.order_count = Order.search_count([("account_id", "=", account.id)])
            account.product_count = Product.search_count([
                ("ebay_account_id", "=", account.id),
                ("ebay_sync_enabled", "=", True),
            ])

    def action_connect_ebay(self):
        self.ensure_one()
        if not self.client_id or not self.client_secret or not self.ru_name:
            raise UserError(_("Set Client ID, Client Secret, and RuName before connecting."))
        state = f"ebay_au_account_{self.id}"
        url = self._ebay_build_authorize_url(self, state)
        return {
            "type": "ir.actions.act_url",
            "url": url,
            "target": "new",
        }

    def action_disconnect(self):
        self.write({
            "access_token": False,
            "refresh_token": False,
            "token_expiry": False,
            "state": "draft",
        })

    def action_fetch_policies(self):
        self.ensure_one()
        policies = self._ebay_request(
            self,
            "GET",
            "/sell/account/v1/fulfillment_policy",
            params={"marketplace_id": self.marketplace_id},
        )
        payment = self._ebay_request(
            self,
            "GET",
            "/sell/account/v1/payment_policy",
            params={"marketplace_id": self.marketplace_id},
        )
        returns = self._ebay_request(
            self,
            "GET",
            "/sell/account/v1/return_policy",
            params={"marketplace_id": self.marketplace_id},
        )
        fulfillment = (policies.get("fulfillmentPolicies") or [{}])[0]
        payment_policy = (payment.get("paymentPolicies") or [{}])[0]
        return_policy = (returns.get("returnPolicies") or [{}])[0]
        self.write({
            "fulfillment_policy_id": fulfillment.get("fulfillmentPolicyId"),
            "payment_policy_id": payment_policy.get("paymentPolicyId"),
            "return_policy_id": return_policy.get("returnPolicyId"),
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Policies updated"),
                "message": _("Fetched business policies from eBay."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_ensure_inventory_location(self):
        self.ensure_one()
        payload = {
            "location": {
                "address": {
                    "addressLine1": self.company_id.street or "1 Example Street",
                    "city": self.company_id.city or "Sydney",
                    "stateOrProvince": self.company_id.state_id.code or "NSW",
                    "postalCode": self.company_id.zip or "2000",
                    "country": self.company_id.country_id.code or "AU",
                },
            },
            "locationTypes": ["WAREHOUSE"],
            "merchantLocationStatus": "ENABLED",
            "name": self.company_id.name or self.name,
        }
        self._ebay_request(
            self,
            "POST",
            f"/sell/inventory/v1/location/{self.merchant_location_key}",
            payload=payload,
        )
        return True

    def action_sync_orders(self):
        for account in self:
            account._sync_orders()
        return True

    def action_sync_listing_prices(self):
        listings = self.env["ebay.au.listing"].search([
            ("account_id", "in", self.ids),
            ("offer_id", "!=", False),
        ])
        synced = listings.action_apply_stock_pricing(sync_to_ebay=True)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Listing prices updated"),
                "message": _("%s listing(s) checked for stock-based pricing.") % synced,
                "type": "success",
                "sticky": False,
            },
        }

    def action_view_listings(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("eBay Listings"),
            "res_model": "ebay.au.listing",
            "view_mode": "list,form",
            "domain": [("account_id", "=", self.id)],
        }

    def action_view_orders(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("eBay Orders"),
            "res_model": "ebay.au.order",
            "view_mode": "list,form",
            "domain": [("account_id", "=", self.id)],
        }

    def action_view_products(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("eBay Products"),
            "res_model": "product.template",
            "view_mode": "list,form",
            "domain": [
                ("ebay_account_id", "=", self.id),
                ("ebay_sync_enabled", "=", True),
            ],
        }

    def _ebay_refresh_token_if_needed(self):
        self.ensure_one()
        if (
            self.access_token
            and self.token_expiry
            and fields.Datetime.now() < self.token_expiry - timedelta(minutes=5)
        ):
            return
        if not self.refresh_token:
            return
        token_data = self._ebay_refresh_access_token(self)
        self._store_token_data(token_data)

    def _store_token_data(self, token_data):
        expires_in = int(token_data.get("expires_in", 7200))
        vals = {
            "access_token": token_data.get("access_token"),
            "token_expiry": fields.Datetime.now() + timedelta(seconds=expires_in),
            "state": "connected",
        }
        if token_data.get("refresh_token"):
            vals["refresh_token"] = token_data.get("refresh_token")
        self.write(vals)

    def _apply_authorization_code(self, code):
        self.ensure_one()
        token_data = self._ebay_exchange_code(self, code)
        self._store_token_data(token_data)
        try:
            self.action_ensure_inventory_location()
        except Exception as exc:
            _logger.warning("Could not create inventory location: %s", exc)

    def _sync_orders(self, days_back=7):
        self.ensure_one()
        params = {
            "filter": f"creationdate:[{self._ebay_since(days_back)}..]",
            "limit": 50,
        }
        payload = self._ebay_request(
            self,
            "GET",
            "/sell/fulfillment/v1/order",
            params=params,
        )
        imported = 0
        for order_payload in payload.get("orders", []):
            if self.env["ebay.au.order"].import_order(self, order_payload):
                imported += 1
        self.last_order_sync = fields.Datetime.now()
        return imported

    def _ebay_since(self, days_back):
        since = fields.Datetime.now() - timedelta(days=days_back)
        return since.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    @api.model
    def cron_sync_orders(self):
        accounts = self.search([("state", "=", "connected"), ("active", "=", True)])
        for account in accounts:
            try:
                account._sync_orders()
            except Exception as exc:
                _logger.exception("eBay order sync failed for %s: %s", account.name, exc)
                account.state = "error"
