from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    ebay_order_id = fields.Char(readonly=True, copy=False, index=True)
    is_ebay_order = fields.Boolean(compute="_compute_is_ebay_order", store=True)

    def _compute_is_ebay_order(self):
        for order in self:
            order.is_ebay_order = bool(order.ebay_order_id or (order.origin or "").startswith("eBay "))
