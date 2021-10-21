from osv import osv, fields
from openerp.tools import SUPERUSER_ID
from fis_integration.scripts import recipe
from fnx_fs.fields import files
import logging

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
            res[row['id']] = recipe.make_on_hand(row['xml_id'])
        return res

    def _get_qty_update_ids(self, cr, uid, changed_product_ids, context=None):
        #
        # find the formulas with the changed-qty ingredients, and return the ids
        # of the products that are built with those formulas
        #
        if isinstance(changed_product_ids, (int, long)):
            changed_product_ids = [changed_product_ids]
        fnx_pd_product_ingredient = self.pool.get('fnx.pd.product.ingredient')
        ingredients = fnx_pd_product_ingredient.read(
                cr, SUPERUSER_ID,
                [('item_id','in',changed_product_ids)],
                fields=['id','formula_id'],
                context=context
                )
        formulae_ids = [ingred['formula_id'] and ingred['formula_id'][0] for ingred in ingredients]
        product_ids = self.search(
                cr, SUPERUSER_ID,
                [('fnx_pd_formula_id','in',formulae_ids)],
                context=context
                )
        return product_ids

    def _get_formula_update_ids(product_formula, cr, uid, changed_formula_ids, context=None):
        #
        # find the products effected by the change in formula name
        #
        if isinstance(changed_formula_ids, (int, long)):
            changed_formula_ids = [changed_formula_ids]
        self = product_formula.pool.get('product.product')
        formulae_names = [
                formula['name']
                for formula in product_formula.read(
                    cr, SUPERUSER_ID,
                    changed_formula_ids,
                    fields=['id','name'],
                    context=context,
                )]
        product_ids = self.search(
                cr, SUPERUSER_ID,
                [('module','=','F135'),('xml_id','in',formulae_names)],
                context=context
                )
        return product_ids

    def _get_item_formula(self, cr, uid, ids, field_name, args, context=None):
        res = {}.fromkeys(ids)
        product_map = dict([
                (p['xml_id'], p['id'])
                for p in self.read(
                    cr, SUPERUSER_ID, ids,
                    fields=['xml_id'],
                    context=context,
                    )
                ])
        formulae_map = dict([
                (f['name'], f['id'])
                for f in self.pool.get('fnx.pd.product.formula').read(
                    cr, SUPERUSER_ID,
                    [('name','in',product_map.keys())],
                    context=context,
                    )
                ])
        for product_name, product_id in product_map.items():
            res[product_id] = formulae_map.get(product_name, False)
        return res

    # one set of fields tracks actual
    _columns = {
        # orders and order ingredients to make this product
        'prod_order_ids': fields.one2many(
            'fnx.pd.order',
            'item_id',
            string='Production Orders',
            domain=[('state','not in',['complete','cancelled'])],
            order='schedule_date, sequence',
            help="production orders to make this product",
            ),
        # XXX below only tracks active order ingredients -- should we also track non-active
        #     order ingrediens?
        'prod_ingredient_ids': fields.one2many(
            'fnx.pd.ingredient',
            'item_id',
            string='Ingredient for',
            domain=[('order_state','not in',['complete','cancelled'])],
            help="ingredients from production order formula to make this product",
            ),
        'fis_qty_makeable': fields.float(
            string='Immediately Producible',
            digits=(15,3),
            help="How much can be made with current inventory.",
            ),
        # default formula to make this product
        'fnx_pd_formula_id': fields.function(
            _get_item_formula,
            type='many2one',
            relation='fnx.pd.product.formula',
            string='Formula Link',
            store={
                'fnx.pd.product.formula': (_get_formula_update_ids, ['name'], 10,),
                },
            help="the default formula to make this item",
            ),
        'fnx_pd_formula_name': fields.related(
            'fnx_pd_formula_id', 'formula',
            string='Formula',
            type='char',
            size=14,
            help="actually the FIS ID of the product",
            ),
        'fnx_pd_formula_ingredient_ids': fields.related(
            'fnx_pd_formula_id', 'ingredient_ids',
            string='Formula Ingredients',
            type='one2many',
            relation='fnx.pd.product.ingredient',
            fields_id='formula_id',
            help="ingredients from the default formula to make this product",
            ),
        # coating and allergens are the same for both the default formula
        # and production order formulas
        'fnx_pd_formula_coating': fields.related(
            'fnx_pd_formula_id', 'coating',
            string='Coating',
            type='char',
            size=10,
            ),
        'fnx_pd_formula_allergens': fields.related(
            'fnx_pd_formula_id', 'allergens',
            string='Allergens',
            type='char',
            size=10,
            ),
        # miscelleny
        'fnx_pd_nutrition_files': files('nutrition', string='Nutrition Information'),
        }
