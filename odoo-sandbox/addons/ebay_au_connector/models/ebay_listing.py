from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EbayListing(models.Model):
    _name = "ebay.au.listing"
    _description = "eBay Australia Listing"
    _inherit = ["ebay.au.api.mixin"]
    _order = "write_date desc"

    name = fields.Char(compute="_compute_name", store=True)
    account_id = fields.Many2one(
        "ebay.au.account",
        required=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one(
        "product.template",
        required=True,
        ondelete="cascade",
    )
    sku = fields.Char(required=True)
    offer_id = fields.Char(readonly=True, copy=False)
    listing_id = fields.Char(readonly=True, copy=False)
    category_id = fields.Char(string="eBay Category ID")
    quantity = fields.Integer(default=1)
    base_price = fields.Float(
        string="Odoo Price",
        help="Normal product sales price before any out-of-stock increase.",
    )
    price = fields.Float(
        string="eBay Price",
        required=True,
        help="Price sent to eBay, including any out-of-stock increase.",
    )
    out_of_stock_price_active = fields.Boolean(
        string="Out of Stock Price Active",
        readonly=True,
        help="Indicates the configured out-of-stock price increase is currently applied.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.ref("base.AUD", raise_if_not_found=False)
        or self.env.company.currency_id,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("inventory_synced", "Inventory Synced"),
            ("offer_created", "Offer Created"),
            ("published", "Published"),
            ("error", "Error"),
        ],
        default="draft",
        readonly=True,
    )
    last_error = fields.Text(readonly=True)
    last_sync = fields.Datetime(readonly=True)

    _sql_constraints = [
        (
            "ebay_listing_sku_account_uniq",
            "unique(account_id, sku)",
            "SKU must be unique per eBay account.",
        ),
    ]

    @api.depends("product_id", "sku")
    def _compute_name(self):
        for listing in self:
            listing.name = listing.product_id.display_name or listing.sku

    @api.onchange("product_id", "account_id")
    def _onchange_product_id(self):
        if self.product_id and self.account_id:
            pricing = self._ebay_compute_sync_pricing(self.account_id, self.product_id)
            self.sku = self.product_id.ebay_sku or self.product_id.default_code or str(self.product_id.id)
            self.base_price = pricing["base_price"]
            self.price = pricing["price"]
            self.quantity = pricing["quantity"]
            self.out_of_stock_price_active = pricing["out_of_stock_price_active"]
            self.category_id = self.product_id.ebay_category_id

    def _refresh_price_from_stock(self):
        for listing in self:
            pricing = listing._ebay_compute_sync_pricing(
                listing.account_id,
                listing.product_id,
            )
            listing.write(pricing)

    def action_apply_stock_pricing(self, sync_to_ebay=False):
        updated = 0
        for listing in self:
            previous = (
                listing.price,
                listing.quantity,
                listing.out_of_stock_price_active,
            )
            listing._refresh_price_from_stock()
            changed = (
                listing.price,
                listing.quantity,
                listing.out_of_stock_price_active,
            ) != previous
            if not changed:
                continue
            updated += 1
            if sync_to_ebay and listing.offer_id:
                listing._sync_inventory()
                listing._create_offer()
        return updated

    def action_sync_inventory(self):
        for listing in self:
            listing._refresh_price_from_stock()
            listing._sync_inventory()
        return True

    def action_create_offer(self):
        for listing in self:
            listing._refresh_price_from_stock()
            listing._create_offer()
        return True

    def action_publish_offer(self):
        for listing in self:
            listing._publish_offer()
        return True

    def action_sync_all(self):
        for listing in self:
            listing._refresh_price_from_stock()
            listing._sync_inventory()
            listing._create_offer()
            listing._publish_offer()
        return True

    @api.model
    def cron_sync_stock_prices(self):
        listings = self.search([
            ("account_id.state", "=", "connected"),
            ("account_id.active", "=", True),
            ("offer_id", "!=", False),
        ])
        for listing in listings:
            try:
                listing.action_apply_stock_pricing(sync_to_ebay=True)
            except Exception as exc:
                listing.write({
                    "state": "error",
                    "last_error": str(exc),
                })

    def _sync_inventory(self):
        self.ensure_one()
        account = self.account_id
        payload, sku = self._ebay_inventory_payload(
            self.product_id,
            account,
            quantity=self.quantity,
        )
        self._ebay_request(
            account,
            "PUT",
            f"/sell/inventory/v1/inventory_item/{sku}",
            payload=payload,
        )
        self.write({
            "sku": sku,
            "state": "inventory_synced",
            "last_sync": fields.Datetime.now(),
            "last_error": False,
        })

    def _create_offer(self):
        self.ensure_one()
        account = self.account_id
        if not all([
            account.payment_policy_id,
            account.fulfillment_policy_id,
            account.return_policy_id,
        ]):
            raise UserError(_("Fetch or configure eBay business policies on the account first."))
        if not self.category_id and not account.default_category_id:
            raise UserError(_("Set an eBay category on the listing or account."))

        payload = self._ebay_offer_payload(self)
        if self.offer_id:
            result = self._ebay_request(
                account,
                "PUT",
                f"/sell/inventory/v1/offer/{self.offer_id}",
                payload=payload,
            )
        else:
            result = self._ebay_request(
                account,
                "POST",
                "/sell/inventory/v1/offer",
                payload=payload,
            )
        self.write({
            "offer_id": result.get("offerId") or self.offer_id,
            "state": "offer_created",
            "last_sync": fields.Datetime.now(),
            "last_error": False,
        })

    def _publish_offer(self):
        self.ensure_one()
        if not self.offer_id:
            raise UserError(_("Create an offer before publishing."))
        result = self._ebay_request(
            self.account_id,
            "POST",
            f"/sell/inventory/v1/offer/{self.offer_id}/publish",
        )
        self.write({
            "listing_id": result.get("listingId"),
            "state": "published",
            "last_sync": fields.Datetime.now(),
            "last_error": False,
        })
