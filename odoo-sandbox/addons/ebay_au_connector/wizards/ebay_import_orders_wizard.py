from odoo import fields, models


class EbayImportOrdersWizard(models.TransientModel):
    _name = "ebay.au.import.orders.wizard"
    _description = "Import eBay Orders"

    account_id = fields.Many2one("ebay.au.account", required=True)
    days_back = fields.Integer(default=7)

    def action_import(self):
        self.ensure_one()
        imported = self.account_id._sync_orders(days_back=self.days_back)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "eBay orders imported",
                "message": f"{imported} new order(s) imported.",
                "type": "success",
                "sticky": False,
            },
        }
