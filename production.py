# -*- coding: utf-8 -*-

from itertools import groupby
from openerp import SUPERUSER_ID
from openerp.osv import fields, osv
from openerp.osv.osv import except_osv as ERPError
from openerp.tools import float_compare, DEFAULT_SERVER_DATETIME_FORMAT, detect_server_timezone
from openerp.tools.translate import _
from fnx import Date, DateTime, Time, float, all_equal
from fnx.oe import Proposed
import logging

_logger = logging.getLogger(__name__)

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

    _columns = {
        'state': fields.selection([
            ('draft', 'Scheduled'),
            ('sequenced', 'Sequenced'),
            ('running', 'Running'),
            ('stopped', 'Stopped'),
            ('complete', 'Complete'),
            ('cancelled', 'Cancelled'),
            ],
            string='Status'),
        'order_no': fields.char('Order #', size=12, required=True, track_visibility='onchange'),
        'item_id': fields.many2one('product.product', 'Item', track_visibility='onchange'),
        'qty': fields.integer('Quantity', track_visibility='onchange'),
        'coating': fields.char('Coating', size=10, track_visibility='onchange'),
        'allergens': fields.char('Allergens', size=10, track_visibility='onchange'),
        'dept': fields.char('Department', size=10, track_visibility='onchange'),
        'line_id': fields.many2one('fis_integration.production_line', 'Production Line', track_visibility='onchange'),
        'line_id_set': fields.boolean('User Updated', help='if True, nightly script will not update this field'),
        'confirmed': fields.boolean('Supplies Reserved', track_visibility='onchange'),
        'schedule_date': fields.date('Run Date', track_visibility='onchange'),
        'schedule_date_set': fields.boolean('User Updated', help='if True, nightly script will not update this field'),
        'sequence': fields.integer('Order of Production'),
        'start_date': fields.datetime('Production Started', oldname='started', track_visibility='onchange'),
        'finish_date': fields.datetime('Production Finished', oldname='completed', track_visibility='onchange'),
        'completed_fis_qty': fields.integer('Total produced (FIS)', track_visibility='onchange'),
        }

    _sql_constraint = [
        ('order_unique', 'unique(order_no)', 'Order already exists in the system'),
        ]

    _defaults = {
        'state': 'draft',
        'sequence': 0,
        }

    def _generate_order_by(self, order_spec, query):
        "correctly orders state field if state is in query"
        order_by = super(fnx_pd_order, self)._generate_order_by(order_spec, query)
        if order_spec and 'state ' in order_spec:
            state_column = self._columns['state']
            state_order = 'CASE '
            for i, state in enumerate(state_column.selection):
                state_order += "WHEN %s.state='%s' THEN %i " % (self._table, state[0], i)
            state_order += 'END '
            order_by = order_by.replace('"%s"."state" ' % self._table, state_order)
        return order_by

    def create(self, cr, uid, values, context=None):
        'create production order, attach to appropriate production line and item'
        follower_ids = values.pop('follower_ids', [])
        product_product = self.pool.get('product.product')
        res_users = self.pool.get('res.users')
        item = product_product.browse(cr, uid, values['item_id'])
        product_follower_ids = [p.id for p in (item.message_follower_ids or [])]
        follower_ids.extend(res_users.search(cr, uid, [('partner_id','in',product_follower_ids),('id','!=',1)]))
        values['message_follower_user_ids'] = follower_ids
        order_id = super(fnx_pd_order, self).create(cr, uid, values, context=context)
        return order_id

    def write(self, cr, uid, ids, values, context=None):
        'if needed: update status, change/remove order to/from producuction line'
        if isinstance(ids, (int, long)):
            ids = [ids]
        if not ids:
            return super(fnx_pd_order, self).write(cr, uid, ids, values, context=context)
        for record in self.browse(cr, SUPERUSER_ID, ids, context=context):
            final_record = Proposed(self, cr, values, record, context)
            vals = values.copy()
            if 'line_id' in vals and final_record.line_id_set:
                del vals['line_id']
                final_record.line_id = record.line_id
            if 'schedule_date' in vals and final_record.schedule_date_set:
                del vals['schedule_date']
                final_record.schedule_date = record.schedule_date
            if (
                ('schedule_date' in vals and uid != SUPERUSER_ID) or
                (not final_record.schedule_date_set and final_record.state not in ['draft', ])
                ):
                    vals['schedule_date_set'] = True
            if (
                ('line_id' in vals and uid != SUPERUSER_ID) or
                (not final_record.line_id_set and final_record.state not in ['draft', ])
                ):
                    vals['line_id_set'] = True
            if not super(fnx_pd_order, self).write(cr, uid, record.id, vals, context=context):
                return False
        return True

    def pd_list_recall(self, cr, uid, ids, context=None):
        return self.write(cr, uid, ids, {'state':'draft'}, context=context)

    def pd_list_release(self, cr, uid, ids, context=None):
        return self.write(cr, uid, ids, {'state':'sequenced'}, context=context)

    def pd_job_start(self, cr, uid, ids, context=None):
        return self.write(cr, uid, ids, {'state':'running'}, context=context)

    def pd_job_stop(self, cr, uid, ids, context=None):
        return self.write(cr, uid, ids, {'state':'stopped'}, context=context)

    def pd_state(self, cr, uid, ids, context):
        # fnx_pd_order = self.pool.get('fnx.pd.order')
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
            total = initial = sequenced = needy = ready = 0
            for order in (record.order_ids or []):
                state = order.state
                pulled = order.confirmed
                total += 1
                if state == 'draft' and not pulled:
                    initial += 1
                elif state == 'draft' and pulled:
                    needy += 1
                elif state == 'sequenced' and not pulled:
                    sequenced += 1
                else:
                    ready += 1
            if sequenced + ready:
                res[record.id]['order_run_total'] = '%d Orders' % (sequenced + ready)
            else:
                res[record.id]['order_run_total'] = '- 0 -'
            if total:
                total = '<span>%d Orders -- %d, ' % (total, initial)
                sequenced = '<span style="color: blue;">%d</span>, ' % sequenced
                needy = '<span style="color: red;">%d</span>, ' % needy
                ready = '<span style="color: green;">%d</span></span>' % ready
                res[record.id]['order_totals'] = total + sequenced + needy + ready
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
