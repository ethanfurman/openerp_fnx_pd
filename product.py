from osv import osv, fields
import logging
from fis_integration.scripts import recipe

_logger = logging.getLogger(__name__)

class product_product(osv.Model):
    'add link to production orders'
    _name = 'product.product'
    _inherit = 'product.product'

    def _calc_avail_qtys(self, cr, uid, ids, field_names, args, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        res = {}
        if not field_names:
            return res
        datas = self.read(
            cr, uid, ids,
            fields=[
                'id', 'xml_id',
                'fis_qty_on_hand', 'fis_qty_produced', 'fis_qty_consumed',
                'fis_qty_purchased', 'fis_qty_sold',
                ],
            context=context)
        for row in datas:
            values = res[row['id']] = {}
            if 'fis_qty_available' in field_names:
                values['fis_qty_available'] = sum([
                        row['fis_qty_on_hand'],
                        row['fis_qty_produced'],
                        row['fis_qty_consumed'],
                        row['fis_qty_purchased'],
                        row['fis_qty_sold'],
                        ])
            if 'fis_qty_makeable' in field_names:
                values['fis_qty_makeable'] = recipe.make_on_hand(row['xml_id'])
        return res

    def _get_qty_update_ids(self, cr, uid, changed_ids, context=None):
        if isinstance(changed_ids, (int, long)):
            changed_ids = [changed_ids]
        ids = list(changed_ids)
        datas = self.read(cr, uid, changed_ids, fields=['prod_ingredient_ids'], context=context)
        for row in datas:
            ids.extend(row['prod_ingredient_ids'])
        return ids

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
        'fis_qty_makeable': fields.function(
            _calc_avail_qtys,
            type='float',
            string='Immediately Producible',
            help="How much can be made with current inventory.",
            multi='calc_available',
            store={
                'product.product': (
                    _get_qty_update_ids,
                    ['fis_qty_produced', 'fis_qty_consumed', 'fis_qty_purchased', 'fis_qty_sold'],
                    10,
                    ),
                },
            ),
        'fis_qty_available': fields.function(
            _calc_avail_qtys,
            type='float',
            string='Quantity Available Today',
            help="How much inventory is available at this moment.",
            multi='calc_available',
            store={
                'product.product': (
                    _get_qty_update_ids,
                    ['fis_qty_produced', 'fis_qty_consumed', 'fis_qty_purchased', 'fis_qty_sold'],
                    10,
                    ),
                },
            ),
        }
