from osv import osv, fields
import logging

_logger = logging.getLogger(__name__)

class product_product(osv.Model):
    'add link to production orders'
    _name = 'product.product'
    _inherit = 'product.product'

    _columns = {
        'prod_order_ids': fields.one2many(
            'fnx.pd.order',
            'item_id',
            string='Production Orders',
            domain=[('state','not in',['complete','cancelled'])],
            order='schedule_date, sequence',
            ),
        'prod_ingredient_ids': fields.one2many(
            'fnx.pd.ingredient',
            'item_id',
            string='Ingredient for',
            domain=[('order_state','not in',['complete','cancelled'])],
            ),
        }
