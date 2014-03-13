# -*- coding: utf-8 -*-

from itertools import groupby
from openerp.osv import fields, osv
from openerp.tools import float_compare, DEFAULT_SERVER_DATETIME_FORMAT, detect_server_timezone
from openerp.tools.translate import _
from fnx import Date, DateTime, Time, float, get_user_timezone, all_equal, PropertyDict, Proposed
import logging

_logger = logging.getLogger(__name__)


class fnx_pd_order(osv.Model):
    _name = 'fnx.pd.order'
    _description = 'production order'
    _inherit = ['mail.thread']
    _order = 'order_no asc'
    _rec_name = 'order_no'
    _mail_flat_thread = False
    
    _columns = {
        'order_no': fields.char('Order #', size=12, required=True),
        'item_id': fields.many2one('product.product', 'Item', required=True),
        'qty': fields.integer('Quantity'),
        'coating': fields.char('Coating', size=10),
        'allergens': fields.char('Allergens', size=10),
        'dept': fields.char('Department', size=10),
        'line': fields.char('Production Line', size=10),
        'confirmed': fields.boolean('Supplies reserved'),
        'schedule_ids': fields.one2many('fnx.pd.schedule', 'order_id', 'Schedule'),
        'state': fields.selection([
            ('draft', 'Unscheduled'),
            ('needs_schedule', 'Ready, needs Scheduled'),
            ('partial', 'Partially Scheduled'),
            ('scheduled', 'Scheduled'),
            ('ready', 'Ready'),
            ('running', 'In Progress'),
            ('complete', 'Complete'),
            ('cancelled', 'Cancelled'),
            ],
            'Status'),
        }

    _sql_constraint = [
        ('order_unique', 'unique(order_no)', 'Order already exists in the system'),
        ]

    _defaults = {
        'state': lambda *a, **kw: 'draft',
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
        if context == None:
            context = {}
        res_partner = self.pool.get('res.partner')
        res_users = self.pool.get('res.users')
        product_product = self.pool.get('product.product')
        fnx_pd_schedule = self.pool.get('fnx.pd.schedule')
        context['mail_create_nolog'] = True
        context['mail_create_nosubscribe'] = True
        follower_ids = values.pop('follower_ids')
        product = product_product.browse(cr, uid, values['item_id'])
        product_follower_ids = [p.id for p in (product.message_follower_ids or [])]
        user_follower_ids = res_users.search(cr, uid, [('partner_id','in',product_follower_ids),('id','!=',1)])
        user_follower_records = res_users.browse(cr, uid, user_follower_ids)
        product_follower_ids = [u.partner_id.id for u in user_follower_records]
        date = values.pop('date')
        new_id = super(fnx_pd_order, self).create(cr, uid, values, context=context)
        current = self.browse(cr, uid, new_id, context=context)
        # create scehdule entry
        sched_vals = {
                'name': '%s - [%s] %s' % (current.order_no, current.item_id.xml_id, current.item_id.name),
                'schedule_date': date,
                'qty': current.qty,
                'order_id': new_id,
                }
        sched_id = fnx_pd_schedule.create(cr, uid, sched_vals, context=context)
        # create comments
        if product_follower_ids:
            self.message_post(
                    cr, uid, new_id,
                    body="order added to the system",
                    partner_ids=product_follower_ids,
                    subtype='mt_comment',
                    context=context,
                    )
        else:
            self.message_post(cr, uid, new_id, body='order added', context=context)
        if follower_ids:
            self.message_subscribe_users(cr, uid, [new_id], user_ids=follower_ids, context=context)
        return new_id

    def write(self, cr, uid, id, values, context=None):
        if context is None:
            context = {}
        context['mail_create_nolog'] = True
        context['mail_create_nosubscribe'] = True
        follower_ids = values.pop('follower_ids', [])
        date = values.pop('date', None)
        state = None
        if not context.pop('from_workflow', False):
            state = values.pop('state', None)
        result = super(fnx_pd_order, self).write(cr, uid, id, values, context=context)
        if state is not None:
            wf = self.WORKFLOW[state]
            wf(self, cr, uid, id, context=context)
        if follower_ids:
            self.message_subscribe_users(cr, uid, [id], user_ids=follower_ids, context=context)
        return result

    def pd_draft(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        context['from_workflow'] = True
        override = context.get('manager_override')
        values = {'state':'draft'}
        if override:
            values['appointment_time'] = 0.0
            values['appt_confirmed'] = False
            values['appt_confirmed_on'] = False
            values['appt_scheduled_by_id'] = False
            values['check_in'] = False
            values['check_out'] = False
        if self.write(cr, uid, ids, values, context=context):
            if override:
                context['mail_create_nosubscribe'] = True
                self.message_post(cr, uid, ids, body="Reset to draft", context=context)
            return True
        return False

    def NOOP(*args,**kwargs):return False

#    def pd_schedule(self, cr, uid, ids, context=None):
#        if context is None:
#            context = {}
#        if isinstance(ids, (int, long)):
#            ids = [ids]
#        context['from_workflow'] = True
#        user_tz = get_user_timezone(self, cr, uid)[uid]
#        override = context.get('manager_override')
#        current = self.browse(cr, uid, ids, context=context)[0]
#        if current.appointment_date and current.appointment_time:
#            values = {
#                    'appt_scheduled_by_id': uid,
#                    'appt_confirmed': True,
#                    'appt_confirmed_on': DateTime.now(),
#                    }
#            if override:
#                values['state'] = 'scheduled'
#            elif current.state == 'draft':
#                values['state'] = 'scheduled'
#            elif current.state == 'appt':
#                values['state'] = 'ready'
#            dt = utc.localize(DateTime(current.appointment).datetime())
#            if user_tz:
#                dt = dt.astimezone(timezone(user_tz))
#            body = 'Scheduled for %s' % (dt.strftime('%Y-%m-%d %H:%M %Z'), )
#            if override:
#                values['check_in'] = False
#                values['check_out'] = False
#                values['appt_confirmed_on'] = current.appt_confirmed_on
#                body = 'Reset to scheduled.'
#            if self.write(cr, uid, ids, values, context=context):
#                context['mail_create_nosubscribe'] = True
#                for id in ids:
#                    self.message_post(cr, uid, id, body=body, context=context)
#                return True
#        return False
#
#    def pd_appointment(self, cr, uid, ids, context=None):
#        if context is None:
#            context = {}
#        if isinstance(ids, (int, long)):
#            ids = [ids]
#        context['from_workflow'] = True
#        override = context.get('manager_override')
#        values = {'state':'appt'}
#        body = 'Order pulled.'
#        if override:
#            values['appointment_time'] = 0.0
#            values['appt_confirmed'] = False
#            values['appt_confirmed_on'] = False
#            values['appt_scheduled_by_id'] = False
#            values['check_in'] = False
#            values['check_out'] = False
#            body = 'Appointment cancelled.'
#        if self.write(cr, uid, ids, values, context=context):
#            context['mail_create_nosubscribe'] = True
#            for id in ids:
#                self.message_post(cr, uid, id, body=body, context=context)
#            return True
#        return False
#
#    def pd_ready(self, cr, uid, ids, context=None):
#        if context is None:
#            context = {}
#        if isinstance(ids, (int, long)):
#            ids = [ids]
#        context['from_workflow'] = True
#        override = context.get('manager_override')
#        values = {'state':'ready'}
#        body = 'Order pulled.'
#        current = self.browse(cr, uid, ids, context=context)[0]
#        if not (current.appointment_date and current.appointment_time):
#            return False
#        if override:
#            values['check_in'] = False
#            values['check_out'] = False
#            body = 'Reset to Ready.'
#        if self.write(cr, uid, ids, values, context=context):
#            context['mail_create_nosubscribe'] = True
#            for id in ids:
#                self.message_post(cr, uid, id, body=body, context=context)
#            return True
#        return False
#
#    def pd_checkin(self, cr, uid, ids, context=None):
#        if context is None:
#            context = {}
#        if isinstance(ids, (int, long)):
#            ids = [ids]
#        if len(ids) > 1:
#            # check all have the same carrier
#            records = self.browse(cr, uid, ids, context=context)
#            carrier_ids = [r.carrier_id.id for r in records]
#            if not all_equal(carrier_ids):
#                raise osv.except_osv('Error', 'Not all carriers are the same, unable to process')
#        context['from_workflow'] = True
#        override = context.get('manager_override')
#        current = self.browse(cr, uid, ids, context=context)[0]
#        values = {
#                'state':'checked_in',
#                'check_in': current.check_in or DateTime.now(),
#                }
#        body = 'Driver checked in at %s' % values['check_in']
#        if override:
#            values['check_out'] = False
#            body = 'Reset to Driver checked in.'
#        if self.write(cr, uid, ids, values, context=context):
#            context['mail_create_nosubscribe'] = True
#            for id in ids:
#                self.message_post(cr, uid, id, body=body, context=context)
#            return True
#        return False
#
    def pd_complete(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        if isinstance(ids, (int, long)):
            ids = [ids]
        context['from_workflow'] = True
        override = context.get('manager_override')
        order_update = context.get('order_update')
        values = {'state':'complete'}
        if not order_update:
            values['check_out'] = DateTime.now()
            body = 'Order complete.'
        fnx_pd_schedule = self.pool.get('fnx.pd.schedule')
        for id in ids:
            current = self.browse(cr, uid, id, context=context)
            if override:
                body = 'Reset to Complete.'
            if self.write(cr, uid, id, values, context=context):
                context['mail_create_nosubscribe'] = True
        return True
#
#    def pd_cancel(self, cr, uid, ids, context=None):
#        if context is None:
#            context = {}
#        if isinstance(ids, (int, long)):
#            ids = [ids]
#        context['from_workflow'] = True
#        if self.write(cr, uid, ids, {'state':'cancelled'}, context=context):
#            context['mail_create_nosubscribe'] = True
#            for id in ids:
#                self.message_post(cr, uid, id, body='Order cancelled.', context=context)
#            return True
#        return False
#
#    def search(self, cr, user, args=None, offset=0, limit=None, order=None, context=None, count=False):
#        # 2013 08 12  (yyyy mm dd)
#        new_args = []
#        for arg in args:
#            if not isinstance(arg, list) or arg[0] != 'date' or arg[2] not in ['THIS_WEEK', 'LAST_WEEK', 'THIS_MONTH', 'LAST_MONTH']:
#                new_args.append(arg)
#                continue
#            today = Date.today()
#            period = arg[2]
#            if period == 'THIS_WEEK':
#                start = today.replace(day=RelativeDay.LAST_MONDAY)
#                stop = start.replace(delta_day=6)
#            elif period == 'LAST_WEEK':
#                start = today.replace(day=RelativeDay.LAST_MONDAY, delta_day=-7)
#                stop = start.replace(delta_day=6)
#            elif period == 'THIS_MONTH':
#                start = today.replace(day=1)
#                stop = start.replace(delta_month=1, delta_day=-1)
#            elif period == 'LAST_MONTH':
#                start = today.replace(day=1, delta_month=-1)
#                stop = start.replace(delta_month=1, delta_day=-1)
#            else:
#                raise ValueError("forgot to update something! (period is %r)" % (arg[2],))
#            op = arg[1]
#            if arg[1] in ('=', 'in'):
#                op = '&'
#                first = '>='
#                last = '<='
#            elif arg[1] in ('!=', 'not in'):
#                op = '|'
#                first = '<'
#                last = '>'
#            if op != arg[1]:
#                new_args.append(op)
#                new_args.append(['date', first, start.strftime('%Y-%m-%d')])
#                new_args.append(['date', last, stop.strftime('%Y-%m-%d')])
#            elif '<' in op:
#                new_args.append(['date', op, start.strftime('%Y-%m-%d')])
#            elif '>' in op:
#                new_args.append(['date', op, last.strftime('%Y-%m-%d')])
#            else:
#                raise ValueError('unable to process domain: %r' % arg)
#        return super(fnx_pd_order, self).search(cr, user, args=new_args, offset=offset, limit=limit, order=order, context=context, count=count)

    WORKFLOW = {
        'draft': pd_draft,
        #'scheduled': pd_schedule,
        #'appt': pd_appointment,
        #'ready': pd_ready,
        #'checked_in': pd_checkin,
        #'complete': NOOP,
        'complete': pd_complete,
        #'cancelled': pd_cancel,
        }


fnx_pd_order()


class fnx_pd_schedule(osv.Model):
    _name = 'fnx.pd.schedule'
    _description = 'production schedule'
    _order = 'schedule_date asc, schedule_seq asc'

    def _order_status(self, cr, uid, ids, field_names=None, args=None, context=None):
        if context == None:
            context = {}
        if isinstance(ids, (int, long)):
            ids = [ids]
        values = {}
        for record in self.browse(cr, uid, ids, context=context):
            values[record.id] = record.order_id.state
        return values

    _columns= {
        'name': fields.char(string="Order / Product", size=64),
        'order_id': fields.many2one('fnx.pd.order', 'Order', ondelete='cascade'),
        'schedule_date': fields.date('Scheduled for'),
        'schedule_seq': fields.integer('Sequence'),
        'line_id': fields.many2one('cmms.line', 'Production Line'),
        'qty': fields.integer('Quantity'),
        'order_status': fields.function(
            _order_status,
            type='char',
            method=True,
            store=True,
            string='Order State',
            ),
    }

    def _insert_order_in_sequence(self, cr, uid, id, proposed, context=None):
        if context is None:
            context = {}
        if isinstance(proposed.line_id, int):
            line_id = proposed.line_id
        else:
            line_id = proposed.line_id.id
        days_orders = self.browse(cr, uid,
                self.search(cr, uid, [
                    ('line_id','=',line_id),
                    ('schedule_date','=',proposed.schedule_date),
                    ('schedule_seq','=',proposed.schedule_seq),
                    ], context=context),
                context=context)
        for order in days_orders:  # either zero or one order
            self.write(cr, uid, [order.id], values={'schedule_seq':proposed.schedule_seq+1}, context=context)

    def _sum_order_quantities(self, cr, uid, current, proposed, context=None):
        if context is None:
            context = {}
        records = self.browse(cr, uid,
                self.search(cr, uid, [('order_id','=',proposed.order_id.id)], context=context),
                context=context)
        current_total = sum([rec.qty for rec in records])
        new_total = current_total - current.qty + proposed.qty
        return new_total

    def write(self, cr, uid, ids, values, context=None):
        if ids:
            if isinstance(ids, (int, long)):
                ids = [ids]
            if context is None:
                context = {}
            current = self.browse(cr, uid, ids[0], context=context)
            master = current.order_id
            new_values = Proposed(self, values)
            proposed = Proposed(self, values, current)
            if new_values.schedule_seq:
                if len(ids) > 1:
                    raise osv.except_osv('Error', 'Cannot set multiple records to the same non-zero sequence')
                # push down any other orders of the same sequence
                self._insert_order_in_sequence(cr, uid, ids[0], proposed, context)
            if new_values.qty:
                new_total = self._sum_order_quantities(cr, uid, current, proposed, context=context)
                if new_total > master.qty:
                    raise osv.except_osv('Error', 'New total if %d is more than order calls for (%d)' % (new_total, master.qty))
                # create new schedule entry to cover the difference
                new_qty = master.qty - new_total
                self.create(cr, uid, dict(
                    name=proposed.name,
                    order_id=proposed.order_id.id,
                    schedule_date=proposed.schedule_date,
                    schedule_seq=0,
                    line_id=proposed.line_id.id,
                    qty=new_qty,
                    ), context=context)
        return super(fnx_pd_schedule, self).write(cr, uid, ids, values, context)
fnx_pd_schedule()
