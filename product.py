from osv import osv, fields
import logging
from fis_integration.scripts import recipe

_logger = logging.getLogger(__name__)

class product_product(osv.Model):
    'add link to production orders'
    _name = 'product.product'
    _inherit = 'product.product'

    def _calc_makeable(self, cr, uid, ids, field_name, args, context=None):
        # XXX should this use the by-order recipe method instead of the
        #     by-item recipe method?
        if isinstance(ids, (int, long)):
            ids = [ids]
        res = {}
        if field_name != 'fis_qty_makeable':
            return res
        datas = self.read(cr, uid, ids, fields=['id', 'xml_id'], context=context)
        for row in datas:
            values = res[row['id']] = {}
            values['fis_qty_makeable'] = recipe.make_on_hand(row['xml_id'])
        return res

    def _get_qty_update_ids(self, cr, uid, changed_ids, context=None):
        if isinstance(changed_ids, (int, long)):
            changed_ids = [changed_ids]
        ids = []
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
        # XXX below only tracks active order ingredients -- should we also track non-active
        #     order ingrediens?
        'prod_ingredient_ids': fields.one2many(
            'fnx.pd.ingredient',
            'item_id',
            string='Ingredient for',
            domain=[('order_state','not in',['complete','cancelled'])],
            ),
        'fis_qty_makeable': fields.function(
            _calc_makeable,
            type='float',
            string='Immediately Producible',
            help="How much can be made with current inventory.",
            store={
                'product.product': ( _get_qty_update_ids, ['fis_qty_available'], 10,),
                },
            ),
        }
