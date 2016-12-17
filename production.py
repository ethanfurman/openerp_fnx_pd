# -*- coding: utf-8 -*-

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
    _name = 'fnx.pd.ingredient'
    _order = 'item_id'
    _rec_name = 'item_id'

    _columns = {
        'order_id': fields.many2one('fnx.pd.order', 'Order', ondelete='cascade'),
        'item_id': fields.many2one('product.product', 'Ingredent'),
        'qty_needed': fields.float('Qty Needed'),
        'qty_desc': fields.char('Qty Unit', size=8),
        'qty_avail': fields.related(
            'item_id',
            'qty_available',
            type='float',
            string='Qty Avail.',
            ),
        'confirmed': fields.related(
            'order_id',
            'confirmed',
            type='selection',
            string='Pulled',
            ),
        }


class fnx_pd_order(osv.Model):
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
        for record in self.read(cr, uid, ids, fields=['state', 'confirmed', 'sequence'], context=context):
            rec_id = record['id']
            state = record['state']
            confirmed = record['confirmed']
            sequence = record['sequence']
            color = 'black'
            if (state == 'sequenced' and confirmed) or state in ['running', 'stopped', 'complete']:
                color = 'green'
            elif state == 'draft' and confirmed:
                color = 'red'
            elif state == 'sequenced':
                color = 'blue'
            elif state in ['cancelled']:
                color = 'gray'
            elif sequence == 0:
                color = 'purple'
            res[rec_id] = color
        return res

    _columns = {
        'state': fields.selection([
            ('draft', 'Scheduled'),
            ('sequenced', 'Sequenced'),
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
        'line_id_set': fields.boolean('User Updated', help='if True, nightly script will not update this field'),
        'confirmed': fields.selection(
            [('fis', 'FIS'), ('user', 'OpenERP')],
            string='Supplies Reserved',
            track_visibility='onchange',
            ),
        'schedule_date': fields.date('Run Date', track_visibility='onchange'),
        'schedule_date_set': fields.boolean('User Updated', help='if True, nightly script will not update this field'),
        'sequence': fields.integer('Order of Production'),
        'start_date': fields.datetime('Production Started', oldname='started', track_visibility='onchange'),
        'finish_date': fields.datetime('Production Finished', oldname='completed', track_visibility='onchange'),
        'last_start_time': fields.datetime('Most recent start date-time'),
        'last_finish_time': fields.datetime('Most recent finish date-time'),
        'completed_fis_qty': fields.integer('Total produced (FIS)', track_visibility='onchange'),
        'display_time': fields.function(_calc_display_time, type='text', string='Time'),
        'cumulative_time': fields.float('Total Time'),
        'dept': fields.char('Department', size=10, track_visibility='onchange'),
        # formula info
        'formula_code': fields.char('Formula & Rev', size=64),
        'coating': fields.char('Coating', size=10, track_visibility='onchange'),
        'allergens': fields.char('Allergens', size=10, track_visibility='onchange'),
        'ingredient_ids': fields.one2many('fnx.pd.ingredient', 'order_id', 'Ingredents'),
        # status color
        'color': fields.function(
            _get_color,
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

    _sql_constraint = [
        ('order_unique', 'unique(order_no)', 'Order already exists in the system'),
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
        nightly = (context or {}).get('script', False)
        for record in self.browse(cr, SUPERUSER_ID, ids, context=context):
            final_record = Proposed(self, cr, values, record, context)
            vals = values.copy()
            if nightly and 'line_id' in vals and final_record.line_id_set:
                del vals['line_id']
                final_record.line_id = record.line_id
            if nightly and 'schedule_date' in vals and final_record.schedule_date_set:
                del vals['schedule_date']
                final_record.schedule_date = record.schedule_date
            if not final_record.line_id_set and final_record.state != 'draft':
                    vals['line_id_set'] = True
            if not nightly and 'line_id' in vals and not final_record.line_id_set:
                vals['line_id_set'] = True
            if not nightly and 'schedule_date' in vals and not final_record.schedule_date_set:
                vals['schedule_date_set'] = True
            if not super(fnx_pd_order, self).write(cr, uid, record.id, vals, context=context):
                return False
        return True

    def pd_list_recall(self, cr, uid, ids, context=None):
        vals = {'state': 'draft'}
        for record in self.browse(cr, uid, ids, context=context):
            if record.confirmed == 'user':
                vals['confirmed'] = False
                for ingredient in record.ingredient_ids:
                    res = ingredient.item_id.write({'qty_available': ingredient.item_id.qty_available+ingredient.qty_needed})
                    if not res:
                        return False
        return self.write(cr, uid, ids, vals, context=context)

    def pd_list_release(self, cr, uid, ids, context=None):
        vals = {'state':'sequenced'}
        for record in self.browse(cr, uid, ids, context=context):
            if record.confirmed != 'fis':
                vals['confirmed'] = 'user'
                for ingredient in record.ingredient_ids:
                    res = ingredient.item_id.write({'qty_available': ingredient.item_id.qty_available-ingredient.qty_needed})
                    if not res:
                        return False
        return self.write(cr, uid, ids, vals, context=context)

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
            total = initial = sequenced = needy = ready = fresh = 0
            for order in (record.order_ids or []):
                state = order.state
                pulled = order.confirmed
                total += 1
                if state == ('sequenced' and pulled) or state in ('running','stopped'):
                    # green (released to floor, supplies pulled  OR  running/stopped)
                    ready += 1
                elif state == 'draft' and pulled:
                    # red (needs sequenced and released to floor)
                    needy += 1
                elif state == 'sequenced':
                    # blue (released to floor, supplies not pulled)
                    sequenced += 1
                elif order.sequence == 0:
                    # purple (just created, needs sequencing)
                    fresh += 1
                elif state == 'draft' and not pulled:
                    # black (just hangin' out)
                    initial += 1
                else:
                    _logger.error(
                            "unable to sort order %s {'state':%r, 'confirmed':%r, 'sequence':%r}",
                            state, pulled, order.sequence,
                            )
            if sequenced + ready:
                res[record.id]['order_run_total'] = '%d Orders' % (sequenced + ready)
            else:
                res[record.id]['order_run_total'] = '- 0 -'
            if total:
                total = '<span>%d Orders -- ' % total
                needy = '<span style="color: red;">%d</span>, ' % needy
                fresh = '<span style="color: purple;">%d</span>, ' % fresh
                initial = '<span style="color: black;">%d</span>, ' % initial
                sequenced = '<span style="color: blue;">%d</span>, ' % sequenced
                ready = '<span style="color: green;">%d</span></span>' % ready
                res[record.id]['order_totals'] = total + needy + fresh + initial + sequenced + ready
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
