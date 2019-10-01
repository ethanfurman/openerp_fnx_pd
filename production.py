# -*- coding: utf-8 -*-

from collections import defaultdict
from datetime import datetime
from openerp import SUPERUSER_ID
from openerp.osv import fields, osv
from openerp.tools import DEFAULT_SERVER_TIME_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT
from dbf import DateTime
from VSS.utils import float
from fnx.oe import Proposed
import logging

_logger = logging.getLogger(__name__)


class fnx_pd_ingredient(osv.Model):
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
        'item_id': fields.many2one('product.product', 'Ingredient', required=True),
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
    "production order" # (F328)  Production Sales Order
    _name = 'fnx.pd.order'
    _description = 'production order'
    _inherit = ['mail.thread']
    _order = 'order_no'
    _rec_name = 'order_no'
    _mail_flat_thread = False

    _track = {
        'state' : {
            'fnx_pd.mt_fnx_pd_draft': lambda s, c, u, r, ctx: r['state'] == 'draft',
            'fnx_pd.mt_fnx_pd_sequenced': lambda s, c, u, r, ctx: r['state'] == 'sequenced',
            'fnx_pd.mt_fnx_pd_released': lambda s, c, u, r, ctx: r['state'] == 'released',
            'fnx_pd.mt_fnx_pd_running': lambda s, c, u, r, ctx: r['state'] == 'running',
            'fnx_pd.mt_fnx_pd_stopped': lambda s, c, u, r, ctx: r['state'] == 'stopped',
            'fnx_pd.mt_fnx_pd_complete': lambda s, c, u, r, ctx: r['state'] == 'complete',
            'fnx_pd.mt_fnx_pd_cancelled': lambda s, c, u, r, ctx: r['state'] == 'cancelled',
            }
        }

    def _calc_display_time(self, cr, uid, ids, field_name, args, context=None):
        res = {}
        if not ids:
            return res
        elif isinstance(ids, (int, long)):
            ids = [ids]
        for record in self.read(cr, uid, ids, fields=['last_start_time', 'last_finish_time'], context=context):
            rec_id = record['id']
            last_start_time = record['last_start_time']
            last_finish_time = record['last_finish_time']
            res[rec_id] = False
            if last_start_time:
                text = fields.datetime.context_timestamp(
                            cr, uid,
                            datetime.strptime(last_start_time, DEFAULT_SERVER_DATETIME_FORMAT),
                            context=context,
                            ).strftime(DEFAULT_SERVER_TIME_FORMAT)
                if last_finish_time:
                    text += '\n%s' % (fields.datetime.context_timestamp(
                                cr, uid,
                                datetime.strptime(last_finish_time, DEFAULT_SERVER_DATETIME_FORMAT),
                                context=context,
                                ).strftime(DEFAULT_SERVER_TIME_FORMAT))
                res[rec_id] = text
        return res

    def _get_color(self, cr, uid, ids, field_name, args, context=None):
        res = {}
        if not ids:
            return res
        elif isinstance(ids, (int,long)):
            ids = [ids]
        for record in self.browse(cr, uid, ids, context=context):
            state = record.state
            confirmed = record.confirmed
            sequence = record.sequence
            for ingredient in record.ingredient_ids:
                if ingredient.qty_avail < ingredient.qty_needed:
                    out_of_stock = True
                    break
            else:
                out_of_stock = False
            color = 'black'
            if out_of_stock and not confirmed:
                color = 'red'
            elif (state == 'released' and confirmed) or state in ['running', 'stopped', 'complete']:
                color = 'green'
            elif state == 'draft' and confirmed:
                color = 'orange'
            elif state == 'sequenced':
                color = 'blue'
            elif state in ['cancelled']:
                color = 'gray'
            elif sequence == 0:
                color = 'purple'
            res[record.id] = color
        return res

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
        order_nos = [rec['order_no'] for rec in records]
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
            ('running', 'Running'),
            ('stopped', 'Stopped'),
            ('complete', 'Complete'),
            ('cancelled', 'Cancelled'),
            ],
            string='Status',
            sort_order='definition',
            ),
        'order_no': fields.char('Order #', size=12, required=True, track_visibility='onchange'),
        'item_id': fields.many2one('product.product', 'Item', track_visibility='onchange'),
        'ordered_qty': fields.float('Requested Qty', track_visibility='onchange', oldname='qty'),
        'line_id': fields.many2one('fis_integration.production_line', 'Production Line', track_visibility='onchange'),
        'line_id_set': fields.boolean('Line Locked', help='if True, nightly script will not update this field'),
        'confirmed': fields.selection(
            [('fis', 'FIS'), ('user', 'OpenERP')],
            string='Supplies reserved by',
            track_visibility='onchange',
            ),
        'schedule_date': fields.date('Run Date', track_visibility='onchange'),
        'schedule_date_set': fields.boolean('Date Locked', help='if True, nightly script will not update this field'),
        'sequence': fields.integer('Order of Production'),
        'start_date': fields.datetime('Production Started', oldname='started', track_visibility='onchange'),
        'finish_date': fields.datetime('Production Finished', oldname='completed', track_visibility='onchange'),
        'last_start_time': fields.datetime('Most recent start date-time'),
        'last_finish_time': fields.datetime('Most recent finish date-time'),
        'completed_fis_qty': fields.integer('Total produced (FIS)', track_visibility='onchange'),
        'display_time': fields.function(_calc_display_time, type='text', string='Time'),
        'cumulative_time': fields.float('Total Time'),
        'dept': fields.char('Department', size=10, track_visibility='onchange'),
        'special_instructions': fields.text('Special Instructions'),
        # formula info
        'formula_code': fields.char('Formula & Rev', size=64),
        'coating': fields.char('Coating', size=10, track_visibility='onchange'),
        'allergens': fields.char('Allergens', size=10, track_visibility='onchange'),
        'ingredient_ids': fields.many2many(
            'fnx.pd.ingredient',
            'order2ingredients_rel', 'order_id', 'ingredient_id',
            string='Ingredients',
            ),
        # status color
        'color': fields.function(
            _get_color,
            fnct_inv=True,
            type='char',
            size=10,
            string='Color State',
            store={
                'fnx.pd.order': (
                    lambda self, cr, uid, ids, ctx={}: ids,
                    ['state', 'confirmed', 'sequence'],
                    10,
                    ),
                },
            ),
        }

    _constraints = [
        (_unique_order_no, 'Order already exists in the system', ['order_no']),
        ]

    _defaults = {
        'state': 'draft',
        'sequence': 0,
        'display_time': '',
        'cumulative_time': 0,
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
        order_id = super(fnx_pd_order, self).create(cr, uid, values, context=context)
        return order_id

    def write(self, cr, uid, ids, values, context=None):
        'if needed: update status, change/remove order to/from producuction line'
        if isinstance(ids, (int, long)):
            ids = [ids]
        if not ids:
            return super(fnx_pd_order, self).write(cr, uid, ids, values, context=context)
        nightly = (context or {}).get('fis-updates', False)
        for record in self.browse(cr, SUPERUSER_ID, ids, context=context):
            final_record = Proposed(self, cr, values, record, context)
            vals = values.copy()

            if nightly:
                if 'line_id' in vals and final_record.line_id_set:
                    del vals['line_id']
                    final_record.line_id = record.line_id
                if 'schedule_date' in vals and final_record.schedule_date_set:
                    del vals['schedule_date']
                    final_record.schedule_date = record.schedule_date
            else:
                if vals.get('line_id') and not final_record.line_id_set:
                    vals['line_id_set'] = final_record.line_id_set = True
                if vals.get('schedule_date') and not final_record.schedule_date_set:
                    vals['schedule_date_set'] = final_record.schedule_date_set = True
            if final_record.state == 'draft':
                if final_record.confirmed or final_record.schedule_date_set:
                    vals['state'] = final_record.state = 'sequenced'
            try:
                if not super(fnx_pd_order, self).write(cr, uid, record.id, vals, context=context):
                    return False
            except Exception:
                _logger.error('failed trying to write id %s with %s', record.id, vals)
                raise
        return True

    def pd_list_recall(self, cr, uid, ids, context=None):
        vals = {'state': 'sequenced'}
        for record in self.browse(cr, uid, ids, context=context):
            if record.order_no == 'CLEAN':
                continue
            if record.confirmed == 'user':
                vals['confirmed'] = False
                for ingredient in record.ingredient_ids:
                    res = ingredient.item_id.write({'fis_qty_consumed': ingredient.item_id.fis_qty_consumed+ingredient.qty_needed})
                    if not res:
                        return False
        return self.write(cr, uid, ids, vals, context=context)

    def pd_list_release(self, cr, uid, ids, context=None):
        vals = {'state':'released'}
        for record in self.browse(cr, uid, ids, context=context):
            if record.order_no == 'CLEAN':
                continue
            if record.confirmed != 'fis':
                vals['confirmed'] = 'user'
                for ingredient in record.ingredient_ids:
                    res = ingredient.item_id.write({'fis_qty_consumed': ingredient.item_id.fis_qty_consumed-ingredient.qty_needed})
                    if not res:
                        return False
        return self.write(cr, uid, ids, vals, context=context)

    def pd_job_special_instructions_acknowledged(self, cr, uid, ids, context=None):
        return {
                'name': 'Special Instructions Acknowledged',
                'view_type': 'form',
                'view_mode': 'form',
                'view_id': self.pool.get('ir.model.data').get_object_reference(cr, uid, 'fnx_pd', 'fnx_pd_order_operator_acknowledged_form')[1],
                'res_model': 'fnx.pd.order',
                'res_id': ids[0],
                'type': 'ir.actions.act_window',
                'target': 'new',
                'context': context,
                }

    def pd_job_start(self, cr, uid, ids, context=None):
        return self.write(
                cr, uid, ids,
                {'state':'running', 'last_start_time':DateTime.now(), 'last_finish_time':False},
                context=context,
                )

    def pd_job_stop(self, cr, uid, ids, context=None):
        res = self.write(cr, uid, ids, {'state':'stopped', 'last_finish_time':DateTime.now()}, context=context)
        if not res:
            return res
        if isinstance(ids, (int, long)):
            ids = [ids]
        for record in self.read(cr, uid, ids, fields=['cumulative_time', 'last_start_time', 'last_finish_time'], context=context):
            rec_id = record['id']
            cuma = record['cumulative_time']
            start = DateTime.strptime(record['last_start_time'], DEFAULT_SERVER_DATETIME_FORMAT)
            finish = DateTime.strptime(record['last_finish_time'], DEFAULT_SERVER_DATETIME_FORMAT)
            cuma += float(finish - start)
            if not self.write(cr, uid, rec_id, {'cumulative_time': cuma}, context=context):
                return False
        return res

    def pd_state(self, cr, uid, ids, context):
        state = context.pop('new_state')
        return self.write(cr, uid, ids, {'state':state}, context=context)

class fnx_pd_product_formula(osv.Model):
    "product formula information" # (F320) Formula Master File
    _name = 'fnx.pd.product.formula'
    _order = 'formula'

    _columns = {
        'name': fields.char('Name', size=6),
        'formula': fields.char('Formula #', size=14),
        'description': fields.char('Name', size=64),
        'coating': fields.char('Coating', size=10, track_visibility='onchange'),
        'allergens': fields.char('Allergens', size=10, track_visibility='onchange'),
        'ingredient_ids': fields.one2many('fnx.pd.product.ingredient', 'formula_id', 'Ingredients'),
        }

    _sql_constraints = [
            ('uniq_formula_name', 'unique(name)', 'Formulae must be unique'),
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
    "mapping from alpha code  to multiple lines, e.g. GB -> 05, 01"
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


