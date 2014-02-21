{
    'name': 'Fnx Production',
    'version': '0.1',
    'category': 'Generic Modules',
    'description': """\
            Phoenix Production Orders.

            Keeps track of production orders.
            """,
    'author': 'Emile van Sebille',
    'maintainer': 'Emile van Sebille',
    'website': 'www.openerp.com',
    'depends': [
            'base',
            'cmms',
            'crm',
            'fis_integration',
            'fnx',
        ],
    'data': [
            'security/security.xml',
            'security/ir.model.access.csv',
            'production_view.xml',
        ],
    'test': [],
    'installable': True,
    'active': False,
}
