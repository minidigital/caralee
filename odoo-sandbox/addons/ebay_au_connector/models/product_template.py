from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ebay_sync_enabled = fields.Boolean(string="Sync to eBay AU")
    ebay_account_id = fields.Many2one("ebay.au.account", string="eBay Account")
    ebay_sku = fields.Char(string="eBay SKU")
    ebay_category_id = fields.Char(string="eBay Category ID")
    ebay_condition = fields.Selection(
        [
            ("NEW", "New"),
            ("LIKE_NEW", "Like New"),
            ("USED_EXCELLENT", "Used - Excellent"),
            ("USED_VERY_GOOD", "Used - Very Good"),
            ("USED_GOOD", "Used - Good"),
            ("USED_ACCEPTABLE", "Used - Acceptable"),
        ],
        default="NEW",
    )
    ebay_brand = fields.Char()
    ebay_listing_id = fields.Many2one("ebay.au.listing", readonly=True, copy=False)
    ebay_listing_state = fields.Selection(
        related="ebay_listing_id.state",
        string="eBay Listing Status",
        readonly=True,
    )

    def action_create_ebay_listing(self):
        Listing = self.env["ebay.au.listing"]
        for product in self:
            if not product.ebay_sync_enabled:
                continue
            if not product.ebay_account_id:
                continue
            listing = product.ebay_listing_id
            if not listing:
                listing = Listing.create({
                    "account_id": product.ebay_account_id.id,
                    "product_id": product.id,
                    "sku": product.ebay_sku or product.default_code or str(product.id),
                    "price": product.list_price,
                    "quantity": int(product.qty_available) if product.type == "product" else 1,
                    "category_id": product.ebay_category_id,
                })
                product.ebay_listing_id = listing.id
            listing.action_sync_all()
        return True
