# eBay Australia Connector

Odoo 18 module for syncing products and orders with the **EBAY_AU** marketplace.

## Setup

1. Create an application at https://developer.ebay.com/
2. Enable OAuth and create a **RuName** whose auth accepted URL points to:
   `https://<your-odoo-domain>/ebay_au/oauth/callback`
3. In Odoo, go to **eBay AU → Accounts** and create an account with:
   - App ID (Client ID)
   - Cert ID (Client Secret)
   - RuName
4. Click **Connect to eBay** and sign in with your seller account.
5. Click **Fetch Policies** to load payment, fulfillment, and return policies.
6. On products, open the **eBay AU** tab, enable sync, and click **Sync to eBay**.

## Features

- OAuth 2.0 seller authorization (sandbox or production)
- Inventory item sync via Sell Inventory API
- Offer creation and publish for EBAY_AU fixed-price listings
- Order import from Sell Fulfillment API into Odoo sales orders
- Scheduled order sync every 15 minutes

## Notes

- Seller accounts must be opted in to eBay Business Policies.
- Sandbox is selected by default; switch to Production when ready.
- Currency defaults to AUD for Australian listings.
