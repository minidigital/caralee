import json

from odoo import api, fields, models


class EbayOrder(models.Model):
    _name = "ebay.au.order"
    _description = "eBay Australia Order"
    _inherit = ["ebay.au.api.mixin"]
    _order = "create_date desc"

    name = fields.Char(required=True, readonly=True)
    account_id = fields.Many2one(
        "ebay.au.account",
        required=True,
        ondelete="cascade",
    )
    ebay_order_id = fields.Char(required=True, readonly=True, index=True)
    sale_order_id = fields.Many2one("sale.order", readonly=True)
    buyer_username = fields.Char(readonly=True)
    total_amount = fields.Float(readonly=True)
    currency_id = fields.Many2one("res.currency", readonly=True)
    fulfillment_status = fields.Char(readonly=True)
    payment_status = fields.Char(readonly=True)
    raw_payload = fields.Text(readonly=True)
    state = fields.Selection(
        [
            ("imported", "Imported"),
            ("linked", "Linked to Sale Order"),
            ("error", "Error"),
        ],
        default="imported",
        readonly=True,
    )

    _sql_constraints = [
        (
            "ebay_order_id_account_uniq",
            "unique(account_id, ebay_order_id)",
            "This eBay order was already imported.",
        ),
    ]

    @api.model
    def import_order(self, account, order_payload):
        ebay_order_id = order_payload.get("orderId")
        if not ebay_order_id:
            return False
        existing = self.search([
            ("account_id", "=", account.id),
            ("ebay_order_id", "=", ebay_order_id),
        ], limit=1)
        if existing:
            return False

        pricing = order_payload.get("pricingSummary", {})
        total = pricing.get("total", {})
        currency_name = total.get("currency", "AUD")
        currency = self.env["res.currency"].search([("name", "=", currency_name)], limit=1)
        buyer = order_payload.get("buyer", {})

        sale_vals = self._ebay_order_to_sale_vals(account, order_payload)
        sale_order = self.env["sale.order"].create(sale_vals)
        sale_order.ebay_order_id = ebay_order_id

        self.create({
            "name": ebay_order_id,
            "account_id": account.id,
            "ebay_order_id": ebay_order_id,
            "sale_order_id": sale_order.id,
            "buyer_username": buyer.get("username"),
            "total_amount": float(total.get("value", 0.0)),
            "currency_id": currency.id if currency else account.company_id.currency_id.id,
            "fulfillment_status": order_payload.get("orderFulfillmentStatus"),
            "payment_status": order_payload.get("orderPaymentStatus"),
            "raw_payload": json.dumps(order_payload, indent=2),
            "state": "linked",
        })
        return True

    def action_open_sale_order(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "res_id": self.sale_order_id.id,
            "view_mode": "form",
        }
