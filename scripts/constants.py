#!/usr/bin/env python

from fislib.constants import Enum, IntEnum, IndexEnum

__all__ =['ProductionState', 'QAll_C', 'BadFormat', 'MissingPartner', 'FISenum', 'F328', 'process_failure_mail']

module = globals()

ProductionState = IntEnum(
    'ProductionState',
    'draft needy partial scheduled ready running complete cancelled',
    )
globals().update(ProductionState.__members__)

QAll_C = IndexEnum(
    'QAll_C',
    'HEADER EMAIL DEPT PROD_LINE TYPE ITEM_CODE ITEM_DESC ORDER_NUM CONFIRMED QTY DATE DAY COATING ALLERGENS'.split(),
    start=0,
    )
globals().update(QAll_C.__members__)


class BadFormat(Exception):
    "production order is incomplete"


class MissingPartner(Exception):
    "unable to find partner"


class FISenum(str, Enum):
    pass


class F328(FISenum):
    """
    IFPP0 - SALES ORDER PRODUCTION PENDING - HEADER
    """
    company_id              = 'An$(1,2)'        # Company Code
    order_id                = 'An$(3,6)'        # Order Number
    produced                = 'Bn$(8,1)'        # Produced (Y/N/P/X)
    order_confirmed         = 'Bn$(13,1)'       # Order Confirmed?
    prod_id                 = 'Cn$(1,8)'        # Product Number
    formula_id              = 'Cn$(19,10)'      # Formula Code
    formula_rev             = 'Cn$(29,3)'       # Formula Revision
    dept_id                 = 'Cn$(157,2)'      # Department Code
    prod_line               = 'Cn$(159,2)'      # Production Line
    prod_sched_date         = 'Fn$(1,6)'        # Production Scheduled Date
    prod_date               = 'Fn$(13,6)'       # 41: Production Date
    sched_date              = 'Fn$(19,6)'       # Scheduled Date
    units_produced          = 'Ln'              # Units Produced
    no_of_lots_produced     = 'Mn'              # No Of Lots Produced
    qty_on_order            = 'Nn'              # Qty On Order


process_failure_mail = """\
To: %s
From: FnxPD <noreply@sunridgefarms.com>
Date: %s
Subject: Failures during processing of QALL spreadsheet

The following errors were detected during nightly processing:

%s
"""

__all__ += list(ProductionState.__members__) + list(QAll_C.__members__)
