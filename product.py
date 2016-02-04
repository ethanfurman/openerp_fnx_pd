from osv import osv, fields
import logging

_logger = logging.getLogger(__name__)

class product_product(osv.Model):
    'Adds Available column and shipped_as columns'
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
        }

product_product()

