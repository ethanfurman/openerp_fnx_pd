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
            'sample.mt_fnx_pd_draft': lambda s, c, u, r, ctx: r['state'] == 'draft',
            'sample.mt_fnx_pd_sequenced': lambda s, c, u, r, ctx: r['state'] == 'sequenced',
            'sample.mt_fnx_pd_running': lambda s, c, u, r, ctx: r['state'] == 'running',
            'sample.mt_fnx_pd_stopped': lambda s, c, u, r, ctx: r['state'] == 'stopped',
            'sample.mt_fnx_pd_complete': lambda s, c, u, r, ctx: r['state'] == 'complete',
            'sample.mt_fnx_pd_cancelled': lambda s, c, u, r, ctx: r['state'] == 'cancelled',
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
        'state': lambda *a: 'draft',
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
        print '-' * 75
        print 'fnx_pd_order.create:', values
        print '-' * 75
        follower_ids = values.pop('follower_ids', [])
        product_product = self.pool.get('product.product')
        res_users = self.pool.get('res.users')
        item = product_product.browse(cr, uid, values['item_id'])
        product_follower_ids = [p.id for p in (item.message_follower_ids or [])]
        follower_ids.extend(res_users.search(cr, uid, [('partner_id','in',product_follower_ids),('id','!=',1)]))
        values['message_follower_user_ids'] = follower_ids
        order_id = super(fnx_pd_order, self).create(cr, uid, values, context=context)
        # product_product.write(cr, SUPERUSER_ID, values['item_id'], {'prod_order_ids': [(4, order_id)]}, context=context)
        # if 'line_id' in values and values['line_id']:
        #     prod_lines = self.pool.get('fis_integration.production_line')
        #     prod_lines.write(cr, SUPERUSER_ID, values['line_id'], {'order_ids': [(4, order_id)]}, context=context)
        return order_id

    # def unlink(self, cr, uid, ids, context=None):
    #     'remove order from production line'
    #     prod_lines = self.pool.get('fis_integration.production_line')
    #     product_product = self.pool.get('product.product')
    #     for record in self.browse(cr, SUPERUSER_ID, ids, context=context):
    #         # prod_lines.write(cr, SUPERUSER_ID, record.line_id.id, {'order_ids': [(3, record.id)]}, context=context)
    #         product_product.write(cr, SUPERUSER_ID, record.item_id.id, {'prod_order_ids': [(3, record.id)]}, context=context)
    #     return super(fnx_pd_order, self).unlink(cr, uid, ids, context=context)

    def write(self, cr, uid, ids, values, context=None):
        'if needed: update status, change/remove order to/from producuction line'
        # if 'item_id' in values:
        #     raise ERPError('Error', 'Item cannot be changed.  Instead, remove order and create a new one.')
        if isinstance(ids, (int, long)):
            ids = [ids]
        if not ids:
            return super(fnx_pd_order, self).write(cr, uid, ids, values, context=context)
        # prod_lines = self.pool.get('fis_integration.production_line')
        # product_product = self.pool.get('product.product')
        for record in self.browse(cr, SUPERUSER_ID, ids, context=context):
            final_record = Proposed(self, cr, values, record, context)
            vals = values.copy()
            if 'line_id' in vals and final_record.line_id_set:
                del vals['line_id']
                final_record.line_id = record.line_id
            if 'schedule_date' in vals and final_record.schedule_date_set:
                del vals['schedule_date']
                final_record.schedule_data = record.schedule_data
            # if 'line_id' in vals or ('state' in vals and vals['state'] in ('complete', 'cancelled')):
            #     # remove previous line
            #     prod_lines.write(cr, SUPERUSER_ID, record.line_id.id, {'order_ids': [(3, record.id)]}, context=context)
            # if 'line_id' in vals and vals['line_id']:
            #     # add new line
            #     prod_lines.write(cr, SUPERUSER_ID, vals['line_id'], {'order_ids': [(4, record.id)]}, context=context)
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
            # if 'state' in vals and vals['state'] in ('complete', 'cancelled'):
            #     order is finished, remove from line and item
            #     if final_order.prod_line:
            #         prod_lines.write(cr, SUPERUSER_ID, final_record.line_id.id, {'order_ids': [(3, record.id)]}, context=context)
            #     product_product.write(cr, SUPERUSER_ID, final_record.item_id.id, {'prod_order_ids': [(3, record.id)]}, context=context)
        return True

    def pd_state(self, cr, uid, ids, context):
        # fnx_pd_order = self.pool.get('fnx.pd.order')
        state = context.pop('new_state')
        return self.write(cr, uid, ids, {'state':state}, context=context)

class production_line(osv.Model):
    "production line"
    _name = 'fis_integration.production_line'
    _inherit = 'fis_integration.production_line'

    _columns = {
        'order_ids': fields.one2many(
            'fnx.pd.order',
            'line_id',
            'Pending Orders',
            domain=[('state','not in',['complete','cancelled'])],
            order='schedule_date, sequence',
            ),
        }
