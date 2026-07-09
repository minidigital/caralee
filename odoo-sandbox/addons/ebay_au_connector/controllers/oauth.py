import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class EbayOAuthController(http.Controller):
    @http.route("/ebay_au/oauth/callback", type="http", auth="user", website=False)
    def oauth_callback(self, code=None, state=None, error=None, **kwargs):
        if error:
            return request.render("ebay_au_connector.oauth_result", {
                "success": False,
                "message": error,
            })

        if not code or not state or not state.startswith("ebay_au_account_"):
            return request.render("ebay_au_connector.oauth_result", {
                "success": False,
                "message": "Missing authorization code or account reference.",
            })

        account_id = int(state.replace("ebay_au_account_", ""))
        account = request.env["ebay.au.account"].browse(account_id)
        if not account.exists():
            return request.render("ebay_au_connector.oauth_result", {
                "success": False,
                "message": "Unknown eBay account.",
            })

        try:
            account._apply_authorization_code(code)
            message = "eBay account connected successfully."
            success = True
        except Exception as exc:
            _logger.exception("eBay OAuth callback failed")
            account.state = "error"
            message = str(exc)
            success = False

        return request.render("ebay_au_connector.oauth_result", {
            "success": success,
            "message": message,
            "account": account,
        })
