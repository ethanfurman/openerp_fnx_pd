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
    _order = 'order_no desc'
    _rec_name = 'order_no'
    _mail_flat_thread = False

    def _get_total_produced(self, cr, uid, ids, field_name, arg, context=None):
        res = {}
        if isinstance(ids, (int, long)):
            ids = [ids]
        for current in self.browse(cr, uid, ids, context=context):
            productive_runs = [run for run in current.schedule_ids if run.state in ('complete', 'closed')]
            produced = sum([run.qty for run in productive_runs])
            res[current.id] = produced
        return res
    
    _columns = {
        'order_no': fields.char('Order #', size=12, required=True),
        'item_id': fields.many2one('product.product', 'Item', required=True),
        'qty': fields.integer('Quantity'),
        'coating': fields.char('Coating', size=10),
        'allergens': fields.char('Allergens', size=10),
        'dept': fields.char('Department', size=10),
        'line_id': fields.many2one('fis_integration.production_line', 'Production Line'),
        'confirmed': fields.boolean('Supplies reserved'),
        'schedule_ids': fields.one2many('fnx.pd.schedule', 'order_id', 'Schedule'),
        'state': fields.selection([
            ('draft', 'Draft'),
            ('needs_schedule', 'Needs Scheduled'),
            ('scheduled', 'Scheduled'),
            ('ready', 'Ready'),
            ('running', 'In Progress'),
            ('complete', 'Complete'),
            ('closed', 'Complete'),
            ('cancelled', 'Cancelled'),
            ],
            'Status'),
        'completed_date': fields.date('Finished on'),
        'completed_qty': fields.function(
            _get_total_produced,
            type="integer",
            string='Total produced',
            method=True,
            ),
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
        if context == None:
            context = {}
        res_partner = self.pool.get('res.partner')
        res_users = self.pool.get('res.users')
        product_product = self.pool.get('product.product')
        fnx_pd_schedule = self.pool.get('fnx.pd.schedule')
        context['mail_create_nolog'] = True
        context['mail_create_nosubscribe'] = True
        follower_ids = values.pop('follower_ids')
        line_id = values['line_id']
        item_id = values['item_id']
        product = product_product.browse(cr, uid, values['item_id'])
        product_follower_ids = [p.id for p in (product.message_follower_ids or [])]
        user_follower_ids = res_users.search(cr, uid, [('partner_id','in',product_follower_ids),('id','!=',1)])
        user_follower_records = res_users.browse(cr, uid, user_follower_ids)
        product_follower_ids = [u.partner_id.id for u in user_follower_records]
        date = values.pop('date')
        new_id = super(fnx_pd_order, self).create(cr, uid, values, context=context)
        current = self.browse(cr, uid, new_id, context=context)
        # create schedule entry
        sched_vals = {
                'name': '%s - [%s] %s' % (current.order_no, current.item_id.xml_id, current.item_id.name),
                'schedule_date': date,
                'qty': current.qty,
                'order_id': new_id,
                'line_id': line_id,
                'item_id': item_id,
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

    def write(self, cr, uid, ids, values, context=None):
        if context is None:
            context = {}
        if isinstance(ids, (int, long)):
            ids = [ids]
        context['mail_create_nolog'] = True
        context['mail_create_nosubscribe'] = True
        follower_ids = values.pop('follower_ids', [])
        date = values.pop('date', None)
        state = None
        if not context.pop('from_workflow', False):
            state = values.pop('state', None)
        # write data to record
        result = super(fnx_pd_order, self).write(cr, uid, ids, values, context=context)
        # check schedule to see if new date is later than existing dates
        if date:
            fnx_pd_schedule = self.pool.get('fnx.pd.schedule')
            for id in ids:
                current = self.browse(cr, uid, id, context=context)
                current_scheduled = [sched.schedule_date for sched in current.schedule_ids]
                try:
                    if not current_scheduled:
                        # create schedule entry
                        sched_vals = {
                                'name': '%s - [%s] %s' % (current.order_no, current.item_id.xml_id, current.item_id.name),
                                'schedule_date': date,
                                'qty': current.qty,
                                'order_id': current.id,
                                'line_id': values['line_id'],
                                'item_id': values['item_id'],
                                }
                        sched_id = fnx_pd_schedule.create(cr, uid, sched_vals, context=context)
                        if current.confirmed:
                            state = 'needs_schedule'
                        else:
                            state = 'draft'
                    elif date > min(current_scheduled):
                        schedule_ids = [sched.id for sched in current.schedule_ids]
                        fnx_pd_schedule.write(cr, uid, schedule_ids,
                                {'schedule_date': date, 'schedule_seq':0}, context=context)
                        if current.confirmed:
                            state = 'needs_schedule'
                        else:
                            state = 'draft'
                except ValueError:
                    print current_scheduled
                    raise
        if state is not None:
            wf = self.WORKFLOW[state]
            wf(self, cr, uid, ids, context=context)
        elif 'state' not in values:
            self.pd_update_state(cr, uid, ids, context=context)
        if follower_ids:
            self.message_subscribe_users(cr, uid, ids, user_ids=follower_ids, context=context)
        return result

    def pd_draft(self, cr, uid, ids, context=None):
        "called when an order is first created, or if current FIS date is later than current schedule date"
        if context is None:
            context = {}
            if isinstance(ids, (int, long)):
                ids = [ids]
        context['from_workflow'] = True
        override = context.get('manager_override')
        values = {'state':'draft'}
        if self.write(cr, uid, ids, values, context=context):
            if override:
                fnx_pd_schedule = self.pool.get('fnx.pd.schedule')
                for id in ids:
                    current = self.browse(cr, uid, id, context=context)
                    schedule_ids = [sched.id for sched in current.schedule_ids]
                    fnx_pd_schedule.write(cr, uid, schedule_ids, {'state':'dormant'}, context=context)
            return True
        return False

    def pd_needs_schedule(self, cr, uid, ids, context=None):
        "supplies have been pulled (from FIS), not yet scheduled; or no supplies and not fully scheduled"
        if context is None:
            context = {}
        if isinstance(ids, (int, long)):
            ids = [ids]
        context['from_workflow'] = True
        override = context.get('manager_override')
        values = {'state':'needs_schedule'}
        body = 'Order pulled, needs to be scheduled.'
        if override:
            pass
        if self.write(cr, uid, ids, values, context=context):
            context['mail_create_nosubscribe'] = True
            for id in ids:
                self.message_post(cr, uid, id, body=body, context=context)
            return True
        return False

    def pd_schedule(self, cr, uid, ids, context=None):
        "order has complete schedules, but supplies have not been pulled (from fnx.pd.schedule)"
        if context is None:
            context = {}
        if isinstance(ids, (int, long)):
            ids = [ids]
        context['from_workflow'] = True
        override = context.get('manager_override')
        current = self.browse(cr, uid, ids, context=context)[0]
        if current.confirmed:  # supplies have been pulled?
            values = {'state': 'ready'}
        else:
            values = {'state': 'scheduled'}
        if override:
            pass
        if self.write(cr, uid, ids, values, context=context):
            #context['mail_create_nosubscribe'] = True
            #for id in ids:
            #    self.message_post(cr, uid, id, body=body, context=context)
            return True
        return False

    def pd_ready(self, cr, uid, ids, context=None):
        "only called by manager override"
        if context is None:
            context = {}
        if isinstance(ids, (int, long)):
            ids = [ids]
        context['from_workflow'] = True
        override = context.get('manager_override')
        state = 'ready'
        body = 'Ready'
        current = self.browse(cr, uid, ids, context=context)[0]
        # TODO check that supplies are confirmed and order is scheduled
        for id in ids:
            if not current.confirmed:
                state = 'scheduled'
            if not (all(sched.schedule_seq for sched in current.schedule_ids) \
              and sum(sched.qty for sched in current.schedule_ids) == current.qty):
                state = 'needs_schedule'
        if override:
            body = 'Reset to Ready.'
            pass
        if self.write(cr, uid, ids, {'state': state}, context=context):
            return True
        return False

    def pd_running(self, cr, uid, ids, context=None):
        "only called by manager override"
        if isinstance(ids, (int, long)):
            ids = [ids]
        context['from_workflow'] = True
        for id in ids:
            current = self.browse(cr, uid, ids, context=context)[0]
            if any(sched.state == 'running' for sched in current.schedule_ids):
                if not self.write(cr, uid, ids, {'state':'running'}, context=context):
                    return False
        return True

    def pd_complete(self, cr, uid, ids, context=None):
        "only called by manager override"
        if context is None:
            context = {}
        context['from_workflow'] = True
        return self.write(cr, uid, ids, {'state':'complete'}, context=context)

    def pd_cancel(self, cr, uid, ids, context=None):
        "only called by manager override"
        if context is None:
            context = {}
        if isinstance(ids, (int, long)):
            ids = [ids]
        context['from_workflow'] = True
        if self.write(cr, uid, ids, {'state':'cancelled'}, context=context):
            context['mail_create_nosubscribe'] = True
            self.message_post(cr, uid, ids, body='Order cancelled.', context=context)
            return True
        return False

    def pd_update_state(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        dropped = context.get('dropped')
        if isinstance(ids, (int, long)):
            ids = [ids]
        context['from_workflow'] = True
        context['mail_create_nosubscribe'] = True
        for current in self.browse(cr, uid, ids, context=context):
            values = {}
            if dropped or all(sched.state == 'complete' for sched in current.schedule_ids):
                values['completed_date'] = Date.today()
                if current.completed_qty == 0:
                    state = 'cancelled'
                    sched_state = 'cancelled' # only needed if dropped
                else:
                    state = 'complete'
                    sched_state = 'closed' # only needed if dropped
                if dropped:
                    # mark all schedules as 'closed' or 'cancelled'
                    # if current state is not 'complete', change qty to 0
                    #fnx_pd_schedule = self.pool.get('fnx.pd.schedule')
                    ctx = context.copy()
                    ctx['from_pd_update_state'] = True
                    for schedule in current.schedule_ids:
                        if schedule.state == 'complete':
                            qty = schedule.qty
                        else:
                            qty = 0
                        schedule.write({'state':sched_state, 'qty':qty}, context=ctx)
            elif any(sched.state == 'running' for sched in current.schedule_ids):
                state = 'running'
            elif all(sched.schedule_seq for sched in current.schedule_ids) \
              and sum(sched.qty for sched in current.schedule_ids) >= current.qty:
                if current.confirmed:
                    state = 'ready'
                else:
                    state = 'scheduled'
            elif any(sched.schedule_seq for sched in current.schedule_ids) or current.confirmed:
                state = 'needs_schedule'
            else:
                state = 'draft'
            values['state'] = state
            line_xml_ids = [(sched.line_id.xml_id, sched.line_id.id) for sched in current.schedule_ids]
            if line_xml_ids:
                values['line_id'] = min(line_xml_ids)[1]
            if not current.write(values, context=context):
                return False
        return True

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
        'needs_schedule': pd_needs_schedule,
        'scheduled': pd_schedule,
        'ready': pd_ready,
        'running': pd_running,
        'complete': pd_complete,
        'cancelled': pd_cancel,
        }


fnx_pd_order()


class fnx_pd_schedule(osv.Model):

    def _generate_order_by(self, order_spec, query):
        "correctly orders state field if state is in query"
        order_by = super(fnx_pd_schedule, self)._generate_order_by(order_spec, query)
        if order_spec and 'state ' in order_spec:
            state_column = self._columns['state']
            state_order = 'CASE '
            for i, state in enumerate(state_column.selection):
                state_order += "WHEN %s.state='%s' THEN %i " % (self._table, state[0], i)
            state_order += 'END '
            order_by = order_by.replace('"%s"."state" ' % self._table, state_order)
        return order_by

    def _get_schedule_ids_for_order(fnx_pd_order, cr, uid, ids, context=None):
        if not isinstance(ids, (int, long)):
            [ids] = ids
        return [s.id for s in fnx_pd_order.browse(cr, uid, ids, context=context).schedule_ids]

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

    def _order_status(self, cr, uid, ids, field_names=None, args=None, context=None):
        if context == None:
            context = {}
        if isinstance(ids, (int, long)):
            ids = [ids]
        fnx_pd_order = self.pool.get('fnx.pd.order')
        states = dict([(v, n) for (v, n) in fnx_pd_order._columns['state'].selection])
        values = {}
        for record in self.browse(cr, uid, ids, context=context):
            values[record.id] = states[record.order_id.state]
        return values

    def _sum_order_quantities(self, cr, uid, current, proposed, context=None):
        if context is None:
            context = {}
        records = self.browse(cr, uid,
                self.search(cr, uid, [('order_id','=',proposed.order_id.id)], context=context),
                context=context)
        current_total = sum([rec.qty for rec in records])
        new_total = current_total - current.qty + proposed.qty
        return new_total

    _name = 'fnx.pd.schedule'
    _description = 'production schedule'
    _order = 'schedule_date asc, schedule_seq asc'

    _columns= {
        'name': fields.char(string="Order / Product", size=64),
        'order_id': fields.many2one('fnx.pd.order', 'Order', ondelete='cascade'),
        'schedule_date': fields.date('Scheduled for'),
        'schedule_seq': fields.integer('Sequence'),
        'line_id': fields.many2one('fis_integration.production_line', 'Production Line', domain="[('name','!=','Open')]"),
        'qty': fields.integer('Quantity'),
        'state': fields.selection([
            ('dormant',''),
            ('running','Running'),
            ('complete','Done'),
            ('cancelled', 'Cancelled'),
            ('closed', 'Closed'),   # controlling order has been completed
            ],
            'Status',
            ),
        'order_status': fields.function(
            _order_status,
            type='char',
            method=True,
            store={
                'fnx.pd.order': (_get_schedule_ids_for_order, ['state'], 20),
                },
            string='Order State',
            ),
        'item_id': fields.many2one('product.product', 'Item', required=True),
        }

    _defaults = {
        'state': 'dormant',
        }

    def pd_run(self, cr, uid, ids, context=None):
        fnx_pd_order = self.pool.get('fnx.pd.order')
        if isinstance(ids, (int, long)):
            ids = [ids]
        for id in ids:
            if self.write(cr, uid, ids, {'state':'running'}, context=context):
                current = self.browse(cr, uid, id, context=context)
                fnx_pd_order.pd_update_state(cr, uid, [current.order_id.id], context=context)
            else:
                return False
        return True

    def pd_complete(self, cr, uid, ids, context=None):
        fnx_pd_order = self.pool.get('fnx.pd.order')
        if isinstance(ids, (int, long)):
            ids = [ids]
        for id in ids:
            if self.write(cr, uid, ids, {'state':'complete'}, context=context):
                current = self.browse(cr, uid, id, context=context)
                fnx_pd_order.pd_update_state(cr, uid, [current.order_id.id], context=context)
            else:
                return False
        return True

    def write(self, cr, uid, ids, values, context=None):
        if context is None:
            context = {}
        if ids and not context.get('from_pd_update_state'):
            if isinstance(ids, (int, long)):
                ids = [ids]
            if context is None:
                context = {}
            fnx_pd_order = self.pool.get('fnx.pd.order')
            current = self.browse(cr, uid, ids[0], context=context)
            master = current.order_id
            new_values = Proposed(self, values)
            proposed = Proposed(self, values, current)
            if isinstance(proposed.order_id, (int, long)):
                order_id = proposed.order_id
            else:
                order_id = proposed.order_id.id
            if new_values.schedule_seq:
                if len(ids) > 1:
                    raise osv.except_osv('Error', 'Cannot set multiple records to the same non-zero sequence')
                # push down any other orders of the same sequence
                self._insert_order_in_sequence(cr, uid, ids[0], proposed, context)
            if new_values.qty:
                new_total = self._sum_order_quantities(cr, uid, current, proposed, context=context)
                new_qty = master.qty - new_total
            fnx_pd_order.pd_update_state(cr, uid, [order_id], context=context)
        return super(fnx_pd_schedule, self).write(cr, uid, ids, values, context)
fnx_pd_schedule()

class production_line(osv.Model):
    "production line"
    _name = 'fis_integration.production_line'
    _inherit = 'fis_integration.production_line'

    _columns = {
        'schedule_ids': fields.one2many(
            'fnx.pd.schedule',
            'line_id',
            'Scheduled Runs',
            ),
        }
production_line()
