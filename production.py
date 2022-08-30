# -*- coding: utf-8 -*-

from collections import defaultdict
from fnx_fs.fields import files
from openerp import SUPERUSER_ID
from openerp.osv import fields, osv
from openerp.tools import self_ids
# from fnx.oe import Proposed
import logging

_logger = logging.getLogger(__name__)


class fnx_pd_ingredient(osv.Model):
    """
    ingredients have a m2m with orders because a single order can be split into
    multiple steps and each ingredient should be listed with each step
    """
    _name = 'fnx.pd.ingredient' # (F329) ingredients actually used in the Production Sales Order
    _order = 'sequence'
    _rec_name = 'item_id'

    def _get_qty_needed_desc(self, cr, uid, ids, field_name, args, context=None):
        res = {}
        if not ids:
            return res
        elif isinstance(ids, (int, long)):
            ids = [ids]
        for record in self.read(cr, uid, ids, fields=['qty_needed', 'qty_desc'], context=context):
            res[record['id']] = '%.2f %s' % (record['qty_needed'], record['qty_desc'])
        return res

    _columns = {
        'name': fields.char('Name', size=19, required=True),  # 'order:item'  (12:6)  (+6 due to order_step_total)
        'sequence': fields.integer('Sequence'),
        # order_ids is M2M because a single order can be produced over several production lines
        'order_ids': fields.many2many(
            'fnx.pd.order',
            'order2ingredients_rel', 'ingredient_id', 'order_id',
            string='Order',
            ),
        'order_no': fields.related(
            'order_ids', 'order_no',
            string='Order #',
            type='char',
            ),
        'order_state': fields.related(
            'order_ids', 'state',
            string='Order State',
            type='selection',
            selection=[
                ('draft', 'New'),
                ('sequenced', 'Scheduled'),
                ('released', 'Released'),
                ('running', 'Running'),
                ('stopped', 'Stopped'),
                ('produced', 'Produced'),
                ('complete', 'Complete'),
                ('cancelled', 'Cancelled'),
                ]),
        'order_product': fields.related(
            'order_ids', 'item_id',
            string='Product',
            type='many2one',
            obj='product.product'
            ),
        'order_schedule_date': fields.related(
            'order_ids', 'schedule_date',
            string='Run date',
            type='date',
            ),
        'item_id': fields.many2one('product.product', 'Ingredient', required=True, help='raw ingredient in product table'),
        'qty_needed': fields.float('Qty Needed'),
        'qty_desc': fields.char('Qty Unit', size=8),
        'qty_needed_desc': fields.function(
            _get_qty_needed_desc,
            string='Qty Needed (with units)',
            type='char',
            store={
                'fnx.pd.ingredient': (lambda t, c, u, ids, ctx: ids, ['qty_needed', 'qty_desc'], 10),
                },
            ),
        'qty_avail': fields.related(
            'item_id', 'fis_qty_available',
            string='Qty Avail.',
            type='float',
            digits=(16,2),
            ),
        'confirmed': fields.related(
            'order_ids', 'confirmed',
            string='Reserved by',
            type='selection',
            selection=[('fis', 'FIS'), ('user', 'OpenERP')],
            ),
        }

    _sql_constraints = []


class fnx_pd_order(osv.Model):
    """
    orders have a m2m with ingredients because a single order can be split into
    multiple steps and each ingredient should be listed with each step
    """
    _name = 'fnx.pd.order' # (F328)  Production Sales Order
    _description = 'production order'
    _inherit = ['mail.thread', 'fnx_fs.fs']
    _order = 'order_no'
    _rec_name = 'order_no'
    _mail_flat_thread = False

    _fnxfs_path = 'fnx_pd/order'
    _fnxfs_path_fields = ['order_no']

    _track = {
        'state' : {
            'fnx_pd.mt_fnx_pd_draft': lambda s, c, u, r, ctx: r['state'] == 'draft',
            'fnx_pd.mt_fnx_pd_sequenced': lambda s, c, u, r, ctx: r['state'] == 'sequenced',
            'fnx_pd.mt_fnx_pd_released': lambda s, c, u, r, ctx: r['state'] == 'released',
            'fnx_pd.mt_fnx_pd_produced': lambda s, c, u, r, ctx: r['state'] == 'produced',
            'fnx_pd.mt_fnx_pd_complete': lambda s, c, u, r, ctx: r['state'] == 'complete',
            'fnx_pd.mt_fnx_pd_cancelled': lambda s, c, u, r, ctx: r['state'] == 'cancelled',
            }
        }

    def _get_color(self, cr, uid, ids, field_name, args, context=None):
        # Color Summary (`color` field)
        # -----------------------------
        # - black: produced, complete
        # - gray: cancelled
        # - blue: released (label printed)
        # - red: scheduled and missing stock, or confirmed and not scheduled
        # - dark red: draft and missing stock
        # - green: scheduled and stock available
        # - dark green: draft and stock available
        #
        # Status Summary (`state` field)
        # ------------------------------
        # - draft (New): exists in FIS; dark red = missing stock, dark green = stock available, red = confirmed (should be sequenced)
        # - sequenced (Scheduled): has a date to be produced; red = missing stock, green = stock available
        # - released (Released): label has been printed and product is being produced; blue
        # - produced (Produced): order has been completed today; black
        # - complete (Complete): order has been completed; black
        # - cancelled (Cancelled): order has been cancelled; gray

        res = {}
        if not ids:
            return res
        elif isinstance(ids, (int,long)):
            ids = [ids]
        for record in self.browse(cr, uid, ids, context=context):
            state = record.state
            confirmed = record.confirmed
            sequenced = record.state == 'sequenced'
            color = None
            if state == 'cancelled':
                color = 'gray'
            elif state in ('produced', 'complete'):
                color = 'black'
            elif state == 'released':
                color = 'blue'
            if color is not None:
                res[record.id] = color
                continue
            # only draft and sequenced orders get this far
            for ingredient in record.ingredient_ids:
                if ingredient.qty_avail < ingredient.qty_needed:
                    out_of_stock = True
                    break
            else:
                out_of_stock = False
            if out_of_stock and sequenced or confirmed and not sequenced:
                color = 'red'
            # still possible:
            # - draft, not confirmed, w/ stock
            # - draft, not confirmed, w/o stock
            # - sequenced w/ stock
            elif out_of_stock:
                # can only be a draft order
                color = 'darkred'
            elif sequenced:
                # must have stock
                color = 'green'
            else:
                # must be draft, w/ stock
                color = 'darkgreen'
            res[record.id] = color
        return res

    def _get_mark_prod_text(self, cr, uid, ids, field_name, args, context=None):
        res = {}
        if not ids:
            return res
        for record in self.browse(cr, uid, ids, context=context):
            if record.state in ('released','running','stopped'):
                res[record.id] = '%s / %s' % (record.markem, record.line_id.name)
            else:
                res[record.id] = '%s' % (record.line_id.name, )
        return res

    def _get_orders_from_ingredients(self, cr, uid, ids, context=None):
        _logger.warning('product ids: %r', ids)
        product_product = self
        product_ids = ids
        self = product_product.pool.get('fnx.pd.order')
        # get order ingredient ids that match the product ids
        pd_ingredient = self.pool.get('fnx.pd.ingredient')
        ingredient_ids = pd_ingredient.search(cr, SUPERUSER_ID, [('item_id','in',product_ids)])
        _logger.warning('ingredient ids: %r', ingredient_ids)
        # get order ids that include the order ingredients
        ids = self.search(cr, SUPERUSER_ID, [('ingredient_ids','in',ingredient_ids)])
        _logger.warning('order ids: %r', ids)
        return ids


    def _post_init(self, pool, cr):
        ids = self.search(cr, 1, [('color','=',False)])
        res = self._get_color(cr, 1, ids, 'color', None)
        same_color = {}
        for id, color in res.items():
            same_color.setdefault(color, []).append(id)
        for color, ids in same_color.items():
            self.write(cr, 1, ids, {'color': color})
        return True

    def _unique_order_no(self, cr, uid, ids, _cache={}):
        # get the order numbers of the ids given, then check if any other
        # orders also have those order numbers
        if isinstance(ids, (int, long)):
            ids = [ids]
        records = self.read(cr, uid, ids, fields=['order_no'])
        order_nos = [
                rec['order_no']
                for rec in records
                if rec['order_no'] not in ('CLEAN', )
                ]
        try:
            duplicates = self.search(cr, uid, [('order_no','in',order_nos),('id','not in',ids)])
        except Exception:
            _logger.error("failed with [('order_no','in',%r),('id','not in',%r)]" % (order_nos, ids))
            raise
        return not duplicates

    _columns = {
        'state': fields.selection([
            ('draft', 'New'),
            ('sequenced', 'Scheduled'),
            ('released', 'Released'),
            ('produced', 'Produced'),
            ('complete', 'Complete'),
            ('cancelled', 'Cancelled'),
            ],
            string='Status',
            sort_order='definition',
            ),
        'order_no': fields.char('Order #', size=12, required=True, track_visibility='onchange'),
        'item_id': fields.many2one('product.product', 'Item', track_visibility='onchange', help='item being produced'),
        'ordered_qty': fields.float('Requested Qty', track_visibility='onchange', oldname='qty'),
        'line_id': fields.many2one('fis_integration.production_line', 'Production Line', track_visibility='onchange'),
        'line_id_set': fields.boolean('Line Locked', help='if True, nightly script will not update this field'),
        'markem': fields.char('Markem line', size=32, readonly=True),
        'mark_prod_line': fields.function(
            _get_mark_prod_text,
            string='Markem / Production Line',
            size=128,
            type='char',
            store={
                'fnx.pd.order': (self_ids, ['line_id','markem','state'], 10),
                },
            ),
        'tracking_no': fields.char('Tracking #', size=32, readonly=True),
        'confirmed': fields.selection(
            [('fis', 'FIS'), ('user', 'OpenERP')],
            string='Supplies reserved by',
            track_visibility='onchange',
            ),
        'schedule_date': fields.date('Run Date', track_visibility='onchange'),
        'schedule_date_set': fields.boolean('Date Locked', help='if True, nightly script will not update this field'),
        'sequence': fields.integer('Order of Production'),
        'finish_date': fields.datetime('Production Finished', oldname='completed', track_visibility='onchange'),
        'completed_fis_qty': fields.integer('Total produced (FIS)', track_visibility='onchange'),
        'dept': fields.char('Department', size=10, track_visibility='onchange'),
        'special_instructions': fields.text('Special Instructions'),
        # formula info
        'formula_code': fields.char('Formula & Rev', size=64),
        'coating': fields.char('Coating', size=10, track_visibility='onchange'),
        'allergens': fields.char('Allergens', size=10, track_visibility='onchange'),
        'batches': fields.integer('Batches needed', track_visibility='onchange'),
        'ingredient_ids': fields.many2many(
            'fnx.pd.ingredient',
            'order2ingredients_rel', 'order_id', 'ingredient_id',
            string='Ingredients',
            ),
        'label_images': files('images', string='Markem Labels', style='images', sort='oldest'),
        # status color
        'color': fields.function(
            _get_color,
            fnct_inv=True,
            type='char',
            size=10,
            string='Color State',
            store={
                'fnx.pd.order': (self_ids, ['state','confirmed'], 10),
                'product.product': (_get_orders_from_ingredients, ['fis_qty_available'], 10),
                },
            ),
        }

    _constraints = [
        (_unique_order_no, 'Order already exists in the system', ['order_no']),
        ]

    _defaults = {
        'state': 'draft',           # also checked for in create() as script may pass False
        'sequence': 0,
        }

    def create(self, cr, uid, values, context=None):
        'create production order, attach to appropriate production line and item'
        follower_ids = values.pop('follower_ids', [])
        product_product = self.pool.get('product.product')
        res_users = self.pool.get('res.users')
        item = product_product.browse(cr, uid, values['item_id'], context=context)
        product_follower_ids = [p.id for p in (item.message_follower_ids or [])]
        follower_ids.extend(
                res_users.search(
                    cr, uid,
                    [('partner_id','in',product_follower_ids),('id','!=',1)],
                    context=context),
                )
        values['message_follower_user_ids'] = follower_ids
        values['state'] = values.get('state', 'draft')
        order_id = super(fnx_pd_order, self).create(cr, uid, values, context=context)
        return order_id

    # def write(self, cr, uid, ids, values, context=None):
    #     'if needed: update status, change/remove order to/from producuction line'
    #     if isinstance(ids, (int, long)):
    #         ids = [ids]
    #     if not ids:
    #         return super(fnx_pd_order, self).write(cr, uid, ids, values, context=context)
    #     # nightly = (context or {}).get('fis-updates', False)
    #     for record in self.browse(cr, SUPERUSER_ID, ids, context=context):
    #         final_record = Proposed(self, cr, values, record, context)
    #         vals = values.copy()
    #
    #         # if nightly:
    #         #     if 'line_id' in vals and final_record.line_id_set:
    #         #         del vals['line_id']
    #         #         final_record.line_id = record.line_id
    #         #     if 'schedule_date' in vals and final_record.schedule_date_set:
    #         #         del vals['schedule_date']
    #         #         final_record.schedule_date = record.schedule_date
    #         # else:
    #         #     if vals.get('line_id') and not final_record.line_id_set:
    #         #         vals['line_id_set'] = final_record.line_id_set = True
    #         #     if vals.get('schedule_date') and not final_record.schedule_date_set:
    #         #         vals['schedule_date_set'] = final_record.schedule_date_set = True
    #         # if final_record.state == 'draft':
    #         #     if final_record.confirmed:   # or final_record.schedule_date_set:
    #         #         vals['state'] = final_record.state = 'sequenced'
    #         try:
    #             if not super(fnx_pd_order, self).write(cr, uid, record.id, vals, context=context):
    #                 return False
    #         except Exception:
    #             _logger.error('failed trying to write id %s with %s', record.id, vals)
    #             raise
    #     return True

    def pd_state(self, cr, uid, ids, context):
        state = context.pop('new_state')
        return self.write(cr, uid, ids, {'state':state}, context=context)

    def update_colors(self, cr, uid, context=None):
        ids = self.search(cr, uid, [('id','!=',0)], context=context)
        updated_colors = self._get_color(cr, uid, ids, None, None, context=context)
        color_groups = defaultdict(list)
        for id, color in updated_colors.items():
            color_groups[color].append(id)
        for color, ids in color_groups.items():
            _logger.info('setting %d records to %r', len(ids), color)
            self.write(cr, SUPERUSER_ID, ids, {'color': color}, context=context)
        return True

class fnx_pd_product_formula(osv.Model):
    "product formula information" # (F320) Formula Master File
    _name = 'fnx.pd.product.formula'
    _order = 'formula'
    _rec_name = 'formula'

    _columns = {
        'name': fields.char('Name', size=6),
        'formula': fields.char('Formula #', size=14),
        'description': fields.char('Name', size=64),
        'coating': fields.char('Coating', size=10, track_visibility='onchange'),
        'allergens': fields.char('Allergens', size=10, track_visibility='onchange'),
        'ingredient_ids': fields.one2many('fnx.pd.product.ingredient', 'formula_id', 'Ingredients'),
        }

    _sql_constraints = [
            ('uniq_formula_name', 'unique(formula)', 'Formulae must be unique'),
            ]

class fnx_pd_product_ingredient(osv.Model):
    "ingredient for product formula" # (F322) Formula Ingredient Detail
    _name = 'fnx.pd.product.ingredient'
    _order = 'sequence'

    def _get_qty_needed_desc(self, cr, uid, ids, field_name, args, context=None):
        res = {}
        if not ids:
            return res
        elif isinstance(ids, (int, long)):
            ids = [ids]
        for record in self.read(cr, uid, ids, fields=['qty_needed', 'qty_desc'], context=context):
            res[record['id']] = '%.2f %s' % (record['qty_needed'], record['qty_desc'])
        return res

    _columns = {
        'name': fields.char('Name', size=17),  # 'formula-rev:item'  (6-3:6)
        'sequence': fields.integer('Sequence'),
        'formula_id': fields.many2one('fnx.pd.product.formula'),
        'item_id': fields.many2one('product.product', string='Ingredient'),
        'qty_needed': fields.float('Qty Needed'),
        'qty_desc': fields.char('Qty Unit', size=8),
        'qty_needed_desc': fields.function(
            _get_qty_needed_desc,
            string='Qty Needed (with units)',
            type='char',
            store={
                'fnx.pd.product.ingredient': (lambda t, c, u, ids, ctx: ids, ['qty_needed', 'qty_desc'], 10),
                },
            ),
        'qty_avail': fields.related(
            'item_id', 'fis_qty_available',
            string='Qty Avail.',
            type='float',
            digits=(16,2),
            ),
        }

class production_line(osv.Model):
    "production line"
    _name = 'fis_integration.production_line'
    _inherit = 'fis_integration.production_line'

    def _calc_totals(self, cr, uid, ids, field_name, args, context=None):
        res = {}
        if not ids:
            return res
        elif isinstance(ids, (int, long)):
            ids = [ids]
        for record in self.browse(cr, uid, ids, context=context):
            res[record.id] = {}
            totals = defaultdict(int)
            for order in (record.order_ids or []):
                totals[order.color] += 1
            if totals['blue'] and totals['green']:
                # sequenced and ready
                res[record.id]['order_run_total'] = '%d Orders' % (totals['blue'] + totals['green'])
            else:
                res[record.id]['order_run_total'] = '- 0 -'
            total = sum([totals[k] for k in totals if k in ('red','orange','purple','black','blue','green')])
            if total:
                # out of stock, supplies pulled / needs scheduled, new order / needs scheduled, default,
                # scheduled, ready to go
                total = '%d Orders -- ' % total
                pieces = []
                pieces.append( '<span style="color: red;font-weight: bold">%d</span>' % totals['red'] )
                pieces.append( '<span style="color: #f80;font-weight: bold">%d</span>' % totals['orange'] )
                pieces.append( '<span style="color: purple;font-weight: bold">%d</span>' % totals['purple'] )
                pieces.append( '<span style="color: black;font-weight: bold">%d</span>' % totals['black'] )
                pieces.append( '<span style="color: blue;font-weight: bold">%d</span>' % totals['blue'] )
                pieces.append( '<span style="color: green;font-weight: bold">%d</span>' % totals['green'] )
                res[record.id]['order_totals'] = '<span>%s %s</span>' % (total, ', '.join(pieces))
            else:
                res[record.id]['order_totals'] = '<span>- 0 -</span>'
        return res

    _columns = {
        'order_ids': fields.one2many(
            'fnx.pd.order',
            'line_id',
            'Pending Orders',
            domain=[('state','not in',['complete','cancelled'])],
            order='sequence, schedule_date',
            ),
        'order_totals': fields.function(
            _calc_totals,
            type='html',
            string='Totals',
            multi='totals',
            ),
        'order_run_total': fields.function(
            _calc_totals,
            type='char',
            string='Ready',
            multi='totals',
            ),
        }


class production_line_map(osv.Model):
    "mapping from alpha code to multiple lines, e.g. GB -> 05, 01"
    _name = "fnx.pd.multiline"
    _rec_name = 'key'

    def _calc_name(self, cr, uid, ids, field_name, args, context=None):
        res = {}
        if not ids:
            return res
        if isinstance(ids, (int, long)):
            ids = [ids]
        for multiline in self.browse(cr, uid, ids, context=context):
            names = []
            for line in multiline.line_ids:
                names.append(line.line_id.desc)
            res[multiline.id] = u' \u21e8 '.join(names)
        return res


    _columns = {
        'name': fields.function(
            _calc_name,
            string='Line Configuration',
            type='char',
            size=128,
            store={
                'fnx.pd.multiline': (lambda t, c, u, ids, ctx: ids, ['line_ids'], 10),
                },
            ),
        'key': fields.char('FIS ID', size=2, required=True),
        'line_ids': fields.one2many('fnx.pd.multiline.entry', 'map_id', string='Line'),
        }


class production_line_map_entry(osv.Model):
    "production line map entry"
    _name = 'fnx.pd.multiline.entry'

    _columns = {
        'map_id': fields.many2one('fnx.pd.multiline', 'Multiline Bundle', ondelete='cascade'),
        'line_id': fields.many2one('fis_integration.production_line', string='Line', ondelete='restrict'),
        'sequence': fields.integer('Sequence', help='allows drag-n-drop ordering; actual value is irrelevent'),
        'name': fields.related('line_id', 'name', string='Name', type='char', size=40),
        }


class pd_order_clean(osv.TransientModel):
    _name = 'fnx.pd.order.clean'

    _columns = {
        'order_no': fields.char('Order #', size=12, required=True, track_visibility='onchange'),
        'item_id': fields.many2one('product.product', 'Item', track_visibility='onchange'),
        'line_id': fields.many2one('fis_integration.production_line', 'Production Line', track_visibility='onchange'),
        }

    _defaults = {
        'order_no': 'CLEAN',
        }

    def create_cleaning(self, cr, uid, ids, context=None):
        # context contains 'active_id', 'active_ids', and 'active_model'
        #
        # we need to create the order in fnx.pd.order, then add that newly
        # created order to the appropriate line
        #
        if isinstance(ids, (int, long)):
            ids = [ids]
        production_order = self.pool.get('fnx.pd.order')
        production_line = self.pool.get('fis_integration.production_line')
        for data in self.read(cr, uid, ids, context=context):
            item_id = data['item_id'][0]
            line_id = data['line_id'][0]
            order_id = production_order.create(
                    cr, uid,
                    dict(order_no='CLEAN', item_id=item_id, line_id=line_id, context=context),
                    )
            if not production_line.write(cr, uid, [line_id], {'order_ids': [[4, order_id,]]}, context=context):
                return False
        return {'type': 'ir.actions.client', 'tag': 'reload'}


