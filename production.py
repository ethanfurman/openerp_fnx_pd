# -*- coding: utf-8 -*-

from itertools import groupby
from openerp.osv import fields, osv
from openerp.tools import float_compare, DEFAULT_SERVER_DATETIME_FORMAT, detect_server_timezone
from openerp.tools.translate import _
from fnx import Date, DateTime, Time, float, get_user_timezone, all_equal
import logging

_logger = logging.getLogger(__name__)


class fnx_pd_order(osv.Model):
    _name = 'fnx.pd.order'
    _description = 'production order'
    _inherit = ['mail.thread']
    #_order = 'appointment_date asc, appointment_order asc, state desc'
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
        chat_context = context.copy()
        res_partner = self.pool.get('res.partner')
        res_users = self.pool.get('res.users')
        product_product = self.pool.get('product.product')
        chat_context['mail_create_nolog'] = True
        chat_context['mail_create_nosubscribe'] = True
        follower_ids = values.pop('follower_ids')
        product = product_product.browse(cr, uid, values['item_id'])
        product_follower_ids = [p.id for p in (product.message_follower_ids or [])]
        user_follower_ids = res_users.search(cr, uid, [('partner_id','in',follower_ids),('id','!=',1)])
        user_follower_records = res_users.browse(cr, uid, user_follower_ids)
        partner_follower_ids = [u.partner_id.id for u in user_follower_records]
        date = values.pop('date')
        new_id = super(fnx_pd_order, self).create(cr, uid, values, context=context)
        if user_follower_ids:
            self.message_post(
                    cr, uid, new_id,
                    body="order added to the system",
                    partner_ids=partner_follower_ids,
                    subtype='mt_comment',
                    context=context,
                    )
        else:
            self.message_post(cr, uid, new_id, body='order added', context=context)
        if follower_ids:
            self.message_subscribe_users(cr, uid, [new_id], user_ids=follower_ids, context=context)
        return new_id

#    def create(self, cr, uid, values, context=None):
#        if context == None:
#            context = {}
#        res_partner = self.pool.get('res.partner')
#        res_users = self.pool.get('res.users')
#        if 'carrier_id' not in values or not values['carrier_id']:
#            values['carrier_id'] = res_partner.search(cr, uid, [('xml_id','=','99'),('module','=','F27')])[0]
#        if 'partner_id' not in values or not values['partner_id']:
#            raise ValueError('partner not specified')
#        context['mail_create_nolog'] = True
#        context['mail_create_nosubscribe'] = True
#        partner = res_partner.browse(cr, uid, values['partner_id'])
#        partner_follower_ids = [p.id for p in partner.message_follower_ids]
#        user_follower_ids = res_users.search(cr, uid, [('partner_id','in',partner_follower_ids),('id','!=',1)])
#        user_follower_records = res_users.browse(cr, uid, user_follower_ids)
#        partner_follower_ids = [u.partner_id.id for u in user_follower_records]
#        real_id = values.pop('real_id', None)
#        real_name = None
#        direction = DIRECTION[values['direction']].title()
#        body = '%s order created' % direction
#        follower_ids = values.pop('local_contact_ids', [])
#        follower_ids.extend(user_follower_ids)
#        if real_id:
#            values['local_contact_id'] = real_id #res_users.browse(cr, uid, real_id, context=context)
#            follower_ids.append(real_id)
#            real_name = res_users.browse(cr, uid, real_id, context=context).partner_id.name
#            body = 'Order received from %s %s' % ({'Purchase':'Purchaser', 'Sale':'Sales Rep'}[direction], real_name)
#        if 'appointment_date' in values:
#            try:
#                appt = Date.fromymd(values['appointment_date'])
#            except ValueError:
#                appt = Date.fromymd(values['appointment_date'][:-2] + '01')
#                appt = appt.replace(delta_month=1)
#                values['appointment_date'] = appt.ymd()
#        new_id = super(fnx_sr_shipping, self).create(cr, uid, values, context=context)
#        if user_follower_ids:
#            self.message_post(cr, uid, new_id, body=body, partner_ids=partner_follower_ids, subtype='mt_comment', context=context)
#        else:
#            self.message_post(cr, uid, new_id, body=body, context=context)
#        if follower_ids:
#            self.message_subscribe_users(cr, uid, [new_id], user_ids=follower_ids, context=context)
#        return new_id
#
#    def write(self, cr, uid, id, values, context=None):
#        if context is None:
#            context = {}
#        context['mail_create_nolog'] = True
#        context['mail_create_nosubscribe'] = True
#        state = None
#        follower_ids = values.pop('local_contact_ids', [])
#        login_id = values.pop('login_id', None)
#        real_name = None
#        if login_id:
#            res_users = self.pool.get('res.users')
#            partner = res_users.browse(cr, uid, login_id, context=context).partner_id
#            values['local_contact_id'] = partner.id
#            follower_ids.append(login_id)
#        if not context.pop('from_workflow', False):
#            state = values.pop('state', None)
#        result = super(fnx_sr_shipping, self).write(cr, uid, id, values, context=context)
#        if 'appointment_time' in values:
#            self.sr_schedule(cr, uid, id, context=context)
#        if state is not None:
#            wf = self.WORKFLOW[state]
#            wf(self, cr, uid, id, context=context)
#        if follower_ids:
#            self.message_subscribe_users(cr, uid, id, user_ids=follower_ids, context=context)
#        return result
#
#    def sr_draft(self, cr, uid, ids, context=None):
#        if context is None:
#            context = {}
#        context['from_workflow'] = True
#        override = context.get('manager_override')
#        values = {'state':'draft'}
#        if override:
#            values['appointment_time'] = 0.0
#            values['appt_confirmed'] = False
#            values['appt_confirmed_on'] = False
#            values['appt_scheduled_by_id'] = False
#            values['check_in'] = False
#            values['check_out'] = False
#        if self.write(cr, uid, ids, values, context=context):
#            if override:
#                context['mail_create_nosubscribe'] = True
#                self.message_post(cr, uid, ids, body="Reset to draft", context=context)
#            return True
#        return False
#
#    def sr_schedule(self, cr, uid, ids, context=None):
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
#    def sr_appointment(self, cr, uid, ids, context=None):
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
#    def sr_ready(self, cr, uid, ids, context=None):
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
#    def sr_checkin(self, cr, uid, ids, context=None):
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
#    def sr_complete(self, cr, uid, ids, context=None):
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
#        order_update = context.get('order_update')
#        values = {'state':'complete'}
#        if not order_update:
#            values['check_out'] = DateTime.now()
#            body = 'Driver checked out at %s' % values['check_out']
#        for id in ids:
#            current = self.browse(cr, uid, id, context=context)
#            if override:
#                values['check_out'] = current.check_out or False
#                body = 'Reset to Complete.'
#            if self.write(cr, uid, id, values, context=context):
#                context['mail_create_nosubscribe'] = True
#                followers = self._get_followers(cr, uid, [id], None, None, context=context)[id]['message_follower_ids']
#                if not order_update:
#                    self.message_post(cr, uid, id, body=body, context=context)
#                if current.direction == 'incoming':
#                    message = 'Complete:  received from %s.' % current.partner_id.name
#                else:
#                    message = 'Complete:  shipped to %s.' % current.partner_id.name
#                self.message_post(cr, uid, id, body=message, subtype='mt_comment', partner_ids=followers, context=context)
#        return True
#
#    def sr_cancel(self, cr, uid, ids, context=None):
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
#        return super(fnx_sr_shipping, self).search(cr, user, args=new_args, offset=offset, limit=limit, order=order, context=context, count=count)

fnx_pd_order()


class fnx_pd_schedule(osv.Model):
    _name = 'fnx.pd.schedule'
    _description = 'production schedule'
    _order = 'scheduled_date desc, scheduled_seq asc'

    def _getname(self, cr, uid, ids, field_name, field_value, arg, context=None):
        pass

    _columns= {
        'name': fields.function(_getname, method=True, store=True, string="Order / Product"),
        'order_id': fields.one2many('fnx.pd.order', 'order_no', 'Order'),
        'schedule_date': fields.date('Scheduled for'),
        'schedule_seq': fields.integer('Sequence'),
        'line_id': fields.many2one('cmms.line', 'Production Line'),
        'qty': fields.integer('Quantity'),
    }
fnx_pd_schedule()

