{
    "name": "eBay Australia Connector",
    "version": "18.0.1.0.0",
    "category": "Sales/eCommerce",
    "summary": "Connect Odoo to eBay Australia (EBAY_AU) for listings and orders",
    "description": """
eBay Australia marketplace connector for Odoo 18.

Features:
- OAuth 2.0 connection to eBay seller accounts (sandbox or production)
- Push Odoo products to eBay inventory and publish offers on EBAY_AU
- Import eBay orders into Odoo sales orders
- Scheduled order synchronization

Requires an eBay Developer Program application with Sell API scopes.
    """,
    "author": "Caralee",
    "license": "LGPL-3",
    "depends": [
        "sale_management",
        "stock",
        "product",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/oauth_templates.xml",
        "views/ebay_account_views.xml",
        "views/ebay_listing_views.xml",
        "views/ebay_order_views.xml",
        "views/product_template_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": True,
}
